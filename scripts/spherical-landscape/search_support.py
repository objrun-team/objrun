"""CPU search implementation. The independent checker does not import this."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import json,time,argparse
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy.linalg import null_space,block_diag,eigh

def normalize(x):return x/np.linalg.norm(x,axis=1)[:,None]
def fg(x):
    s=x@x.T;g=8*(s**3)@x
    return np.sum(s**4)-36,g-(g*x).sum(axis=1)[:,None]*x
def chart(x):
    t=block_diag(*[null_space(v[None,:]) for v in x])
    rot=[]
    for a in range(6):
        for b in range(a):
            z=np.zeros((6,6));z[a,b]=1;z[b,a]=-1;rot.append((x@z).ravel())
    return t@null_space(np.array(rot)@t)
def hessian(x,b):
    s=x@x.T;eg=8*(s**3)@x;lam=(x*eg).sum(axis=1)
    out=[]
    for k in range(b.shape[1]):
        u=b[:,k].reshape(24,6);ds=u@x.T+x@u.T
        hu=24*(s*s*ds)@x+8*(s**3)@u-lam[:,None]*u
        out.append(b.T@hu.ravel())
    h=np.array(out).T
    return (h+h.T)/2
def optimize(x,deadline=float('inf'),trace=None):
    history=[];x=normalize(x)
    def fun(y):
        if time.time()>=deadline:raise TimeoutError('absolute campaign deadline')
        y=y.reshape(24,6);n=np.linalg.norm(y,axis=1);v=y/n[:,None];f,g=fg(v)
        return f,(g/n[:,None]).ravel()
    def callback(y):
        f,g=fg(normalize(y.reshape(24,6)));history.append([time.time(),float(f),float(np.linalg.norm(g)),'lbfgs'])
    sol=minimize(fun,x.ravel(),jac=True,method='L-BFGS-B',callback=callback,
                 options={'gtol':1e-11,'ftol':1e-15,'maxiter':2147483647,'maxfun':2147483647,'maxls':100,'maxcor':30})
    x=normalize(sol.x.reshape(24,6));reason=str(sol.message)
    while time.time()<deadline:
        f,g=fg(x);gn=np.linalg.norm(g);history.append([time.time(),float(f),float(gn),'newton'])
        if gn<2e-12:reason='gradient_converged';break
        b=chart(x);h=hessian(x,b);ev,u=eigh(h);qg=b.T@g.ravel()
        # Positive subspace pseudoinverse only for step construction, never verification.
        step=-(u@((u.T@qg)/np.maximum(ev,1e-5)))
        if np.linalg.norm(step)>.3:step*=.3/np.linalg.norm(step)
        dx=(b@step).reshape(24,6);alpha=1.;accepted=False
        while alpha>1e-10:
            y=normalize(x+alpha*dx);fy,gy=fg(y)
            if fy < f-1e-4*alpha*abs(qg@step) or (fy<=f+2e-13 and np.linalg.norm(gy)<.8*gn):
                x=y;accepted=True;break
            alpha*=.5
        if not accepted:reason='line_search_stalled';break
    else:raise TimeoutError('absolute campaign deadline')
    if trace:Path(trace).write_text(json.dumps(history))
    return x,{'status':reason,'energy':float(fg(x)[0]),'gradient_norm':float(np.linalg.norm(fg(x)[1])),'iterations':len(history)}
def atomic(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(obj));tmp.replace(path)
def campaign(reference,end,seed=20261030,offset=0):
    ref=np.array(json.loads(Path(reference).read_text())['vectors'],float);rng=np.random.default_rng(seed)
    Path('candidates').mkdir(exist_ok=True);k=offset
    while time.time()<end:
        s=int(rng.integers(0,2**53));r=np.random.default_rng(s);typ=k%6
        if typ<3:x=r.normal(size=(24,6));kind='random'
        elif typ==3:x=ref+10**r.uniform(-2,-.1)*r.normal(size=(24,6));kind='reference_perturb'
        elif typ==4:
            x=np.vstack([np.eye(6)]*4)+.15*r.normal(size=(24,6));kind='orthobases_perturb'
        else:
            x=np.zeros((24,6))
            for i in range(24):x[i,r.choice(6,2,replace=False)]=r.choice([-1.,1.],2)
            x+=.1*r.normal(size=(24,6));kind='sparse_two_support_perturb'
        name=f'candidates/s{seed}-{k:06d}'
        atomic(name+'.initial.json',{'vectors':normalize(x).tolist(),'seed':s,'kind':kind})
        try:y,info=optimize(x,end,name+'.trace.json')
        except TimeoutError:break
        b=chart(y);vals=eigh(hessian(y,b),eigvals_only=True)
        out={'vectors':y.tolist(),'seed':s,'kind':kind,'search_info':info,'search_min_eigenvalue':float(vals[0]),'search_zero_count':int(np.sum(abs(vals)<1e-7))}
        atomic(name+'.json',out)
        atomic('candidate.json',out)
        with open('search-log.jsonl','a') as f:f.write(json.dumps({'candidate':name+'.json',**{k:v for k,v in out.items() if k!='vectors'},'time':time.time()})+'\n')
        atomic('progress.json',{'completed':k+1,'last_candidate':name+'.json','time':time.time(),'energy':info['energy'],'gradient_norm':info['gradient_norm'],'min_eigenvalue':float(vals[0])})
        print(json.dumps({'k':k,'energy':info['energy'],'grad':info['gradient_norm'],'eig':float(vals[0])}),flush=True)
        k+=1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--reference',default='/reference/author-reference.json');p.add_argument('--deadline',type=float,required=True);p.add_argument('--seed',type=int,default=20261030);p.add_argument('--offset',type=int,default=0);a=p.parse_args();campaign(a.reference,a.deadline,a.seed,a.offset)
