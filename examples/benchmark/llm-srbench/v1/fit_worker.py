"""Expression-only numerical worker. No arbitrary Python, imports or attributes."""
import ast,json,os,resource,signal,sys,time
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
import numpy as np
from scipy.optimize import least_squares
from scipy.special import erf

class CandidateError(Exception): pass
def maxfn(*args):
    out=args[0]
    for a in args[1:]:out=np.maximum(out,a)
    return out
def minfn(*args):
    out=args[0]
    for a in args[1:]:out=np.minimum(out,a)
    return out
FUN={k:getattr(np,k) for k in ['exp','log','log10','sin','cos','tan','sinh','cosh','tanh','sqrt','abs','sign','arcsin','arccos','arctan','arcsinh','arccosh','arctanh']}
FUN.update({'Abs':np.abs,'asin':np.arcsin,'acos':np.arccos,'atan':np.arctan,'asinh':np.arcsinh,'acosh':np.arccosh,'atanh':np.arctanh,'Max':maxfn,'Min':minfn,'maximum':np.maximum,'minimum':np.minimum,'erf':erf,'coth':lambda x:1/np.tanh(x),'sech':lambda x:1/np.cosh(x)})
def expression(text,dimensions):
    if not isinstance(text,str) or len(text)>8192:raise CandidateError('InvalidExpression')
    text=text.replace('^','**');node=ast.parse(text,mode='eval')
    names=set(FUN)|{'pi','E'}|{'x'+str(i) for i in range(dimensions)}|{'p'+str(i) for i in range(16)}
    allowed=(ast.Expression,ast.BinOp,ast.UnaryOp,ast.Call,ast.Name,ast.Load,ast.Constant,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow,ast.USub,ast.UAdd)
    for n in ast.walk(node):
        if not isinstance(n,allowed):raise CandidateError('ForbiddenExpressionSyntax')
        if isinstance(n,ast.Name) and n.id not in names:raise CandidateError('UnknownSymbol')
        if isinstance(n,ast.Constant) and (type(n.value) not in (int,float) or not np.isfinite(n.value) or abs(n.value)>1e100):raise CandidateError('InvalidConstant')
        if isinstance(n,ast.Call) and (not isinstance(n.func,ast.Name) or n.func.id not in FUN or n.keywords or len(n.args)>8):raise CandidateError('ForbiddenFunction')
    params=sorted({n.id for n in ast.walk(node) if isinstance(n,ast.Name) and n.id.startswith('p') and n.id[1:].isdigit()},key=lambda n:int(n[1:]))
    if params and params!=['p'+str(i) for i in range(len(params))]:raise CandidateError('NonContiguousParameters')
    code=compile(node,'<equation>','eval')
    def predict(X,p):
        env={**FUN,'pi':np.pi,'E':np.e,**{'x'+str(i):X[:,i] for i in range(dimensions)},**dict(zip(params,p))}
        with np.errstate(all='ignore'):v=eval(code,{'__builtins__':{}},env)
        a=np.asarray(v,dtype=float)
        if a.ndim==0:a=np.full(len(X),float(a))
        if a.shape!=(len(X),):raise CandidateError('PredictionShape')
        return a
    return predict,params,len(list(ast.walk(node)))
def metrics(pred,y):
    y=np.asarray(y,dtype=float).reshape(-1);pred=np.asarray(pred,dtype=float)
    if pred.shape!=y.shape:return {'valid':True,'passed':False,'errorType':'PredictionShape','finiteCoverage':0.0}
    finite=np.isfinite(pred);coverage=float(finite.mean())
    if not finite.all():return {'valid':True,'passed':False,'errorType':'NonFinitePrediction','finiteCoverage':coverage,'nmse':None,'acc01':False}
    with np.errstate(all='ignore'):
        sse=float(np.sum((pred-y)**2));sst=float(np.sum((y-y.mean())**2));nmse=sse/sst if sst else (0.0 if sse==0 else float('inf'))
        rel=np.where(y!=0,np.abs((pred-y)/y),np.where(pred==0,0.0,np.inf));maximum=float(np.max(rel))
    return {'valid':True,'passed':bool(np.isfinite(nmse) and nmse<=.01),'nmse':nmse if np.isfinite(nmse) else None,'acc01':bool(maximum<=.1),'maxRelativeError':maximum if np.isfinite(maximum) else None,'finiteCoverage':coverage,'points':len(y),'zeroVarianceTarget':sst==0}
def main(q):
    data={'X':np.asarray(q['X'],float),'y':np.asarray(q['y'],float)} if 'X' in q else np.load(q['data'],allow_pickle=False);X=data['X'];y=data['y'].reshape(-1)
    predict,params,nodes=expression(q['expression'],X.shape[1]);begin=time.process_time()
    if q.get('mode')=='predict':return {**metrics(predict(X,q.get('parameters',[])),y),'cpuSeconds':time.process_time()-begin}
    if not np.isfinite(X).all() or not np.isfinite(y).all():raise RuntimeError('NonFiniteDataset')
    chosen=np.linspace(0,len(X)-1,min(2048,len(X)),dtype=int);xf=X[chosen];yf=y[chosen];scale=max(float(np.std(yf)),1e-12)
    initials=q.get('initial',[])
    if initials and (not isinstance(initials,list) or len(initials)!=len(params) or not all(type(a) in (int,float) and np.isfinite(a) and abs(a)<=1e10 for a in initials)):raise CandidateError('InvalidInitialParameters')
    best=np.asarray(initials if initials else [1.0]*len(params),dtype=float);loss=float('inf');fitlog=[]
    if params:
        starts=[best,np.full(len(params),.1),np.full(len(params),-1.0)]
        def residual(p):
            a=predict(xf,p);r=(a-yf)/scale
            return np.nan_to_num(r,nan=1e12,posinf=1e12,neginf=-1e12).clip(-1e12,1e12)
        for start in starts:
            try:
                f=least_squares(residual,start,max_nfev=1000);v=float(np.mean(residual(f.x)**2));fitlog.append({'nfev':int(f.nfev),'objective':v,'status':int(f.status)})
                if np.isfinite(v) and v<loss:best=f.x;loss=v
            except (ValueError,FloatingPointError,OverflowError) as e:fitlog.append({'errorType':type(e).__name__})
    pred=predict(X,best)
    return {**metrics(pred,y),'parameters':best.tolist(),'expression':q['expression'],'complexityAstNodes':nodes,'fitRows':len(chosen),'fitIndices':chosen.tolist(),'fitLog':fitlog,'cpuSeconds':time.process_time()-begin}
if __name__=='__main__':
    q=json.load(sys.stdin)
    signal.signal(signal.SIGXCPU,lambda *_: (_ for _ in ()).throw(CandidateError('CandidateCPUTimeout')))
    resource.setrlimit(resource.RLIMIT_CPU,(q.get('cpuSeconds',30),q.get('cpuSeconds',30)+2))
    resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,4*1024**3));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    os.setgroups([]);os.setgid(65534);os.setuid(65534)
    try:r=main(q)
    except (CandidateError,SyntaxError,ValueError,TypeError,ZeroDivisionError,OverflowError,RecursionError) as e:r={'valid':True,'passed':False,'errorType':str(e) if isinstance(e,CandidateError) else type(e).__name__}
    except Exception as e:r={'valid':False,'passed':False,'errorType':type(e).__name__}
    print(json.dumps(r,allow_nan=False),flush=True)
