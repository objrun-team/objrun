"""Frozen host checker; never imports optimizer code or supplied Butcher arrays."""
import argparse,hashlib,json,math,re
from collections import Counter
from pathlib import Path
import mpmath as mp
from independent_check import check as independent
HERE=Path(__file__).resolve().parent
def number(x):
    if not isinstance(x,str) or not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?:/[+-]?\d+)?',x):raise ValueError('Each coefficient must be a finite decimal or rational STRING')
    p=x.split('/');v=mp.mpf(p[0])/(mp.mpf(p[1]) if len(p)==2 else 1)
    if not mp.isfinite(v):raise ValueError('Nonfinite coefficient')
    return v
def tree_order(t):return 1+sum(tree_order(c) for c in t)
def density(t):return tree_order(t)*math.prod(density(c) for c in t)
def symmetry(t):return math.prod(math.factorial(n) for n in Counter(t).values())*math.prod(symmetry(c) for c in t)
TREES={1:[()],2:[((),)],3:[((),()),(((),),)],4:[((),(),()),(((),()),),((),((),)),((((),),),)]}
def calculate(raw,digits):
    with mp.workdps(digits):
        if raw.get('schema')!='williamson-2n-v1' or raw.get('stages')!=5:raise ValueError('Exactly five-stage Williamson 2N schema required')
        a=list(map(number,raw['alpha'])); B=list(map(number,raw['beta']))
        if len(a)!=5 or len(B)!=5 or a[0]!=0:raise ValueError('Need five alpha, five beta, alpha[0]=0')
        A=mp.matrix(5);q=mp.matrix(1,5);y=mp.matrix(1,5)
        for i in range(5):
            for j in range(5):A[i,j]=y[j]
            q=a[i]*q;q[i]+=1;y+=B[i]*q
        b=y.T;c=A*mp.matrix([1]*5)
        def elementary(t):
            v=mp.matrix([1]*5)
            for child in t:
                factor=A*elementary(child)
                for i in range(5):v[i]*=factor[i]
            return v
        errors={n:[((b.T*elementary(t))[0]-mp.mpf(1)/density(t))/symmetry(t) for t in ts] for n,ts in TREES.items()}
        poly=[mp.mpf(1)]+[(b.T*(A**k)*mp.matrix([1]*5))[0] for k in range(5)]
        fmt=lambda x:mp.nstr(x,digits-10)
        return {'precision_digits':digits,'A':[[fmt(A[i,j]) for j in range(5)] for i in range(5)],'b':[fmt(x) for x in b],'c':[fmt(x) for x in c],'tree_errors':{str(n):[fmt(x) for x in v] for n,v in errors.items()},'stability_ascending':[fmt(x) for x in poly],'error_norm':fmt(mp.sqrt(mp.fsum(x*x for x in errors[4])))}
def evaluate(path,threshold=None):
    raw=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    baseline=json.loads((HERE/'reference/baseline-audit.json').read_text())
    frozen=json.loads((HERE/'frozen-criteria.json').read_text())
    hi=calculate(raw,180);lo=calculate(raw,100)
    dec=independent(raw,baseline['stability_ascending'])
    mp.mp.dps=180
    norm=mp.mpf(hi['error_norm']);tol=mp.mpf(frozen['constraint_tolerance'])
    # Compare all tree residuals, unnormalized conventional order conditions,
    # full polynomial coefficients, and independently reconstructed tableau.
    oc=max(abs(mp.mpf(x)) for n in ['1','2','3'] for x in hi['tree_errors'][n])
    sr=max(abs(mp.mpf(x)-number(y)) for x,y in zip(hi['stability_ascending'],baseline['stability_ascending']))
    cross=max([abs(norm-mp.mpf(dec['error_norm']))]+[abs(mp.mpf(x)-mp.mpf(y)) for row,row2 in zip(hi['A'],dec['A']) for x,y in zip(row,row2)])
    uncertainty=max(abs(norm-mp.mpf(lo['error_norm'])),abs(norm-mp.mpf(dec['error_norm'])),mp.mpf('1e-90'))
    threshold=mp.mpf(str(threshold)) if threshold is not None else mp.mpf(baseline['principal_error_norm'])
    valid=max(oc,sr,mp.mpf(dec['max_constraint_residual']))<=tol and cross<mp.mpf('1e-80')
    margin=max(mp.mpf(frozen['minimum_absolute_improvement']),100*uncertainty)
    return {'valid':bool(valid),'improved':bool(valid and threshold-norm>margin),'size':float(norm),'error_norm':str(norm),'baseline_error_norm':baseline['principal_error_norm'],'max_order_tree_residual':str(oc),'max_stability_residual':str(sr),'max_constraint_residual':str(max(oc,sr,mp.mpf(dec['max_constraint_residual']))),'cross_implementation_difference':str(cross),'numerical_uncertainty_estimate':str(uncertainty),'required_improvement_margin':str(margin),'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'high_precision':hi,'independent':dec,'claim':'High-precision numerical construction; exact constraints require a separate symbolic certificate.'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('candidate');p.add_argument('--threshold');p.add_argument('--independent',action='store_true');args=p.parse_args()
    try:result=evaluate(args.candidate,args.threshold)
    except Exception as e:result={'valid':False,'improved':False,'error':str(e)}
    print(json.dumps(result,indent=2))
