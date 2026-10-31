"""Independent host checker. No imports from search code; rows are 24 vectors.
All 120 product-sphere tangent dimensions are retained, then only the image of
the 15 skew-symmetric ambient generators is quotiented. No spectral pruning.
"""
import os
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['OMP_NUM_THREADS']='1'
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import scipy.linalg as la
import mpmath as mp

def evaluate(x):
    # Pairwise loops deliberately differ from the search's matrix contractions.
    f=-36.; grad=np.zeros((24,6)); h=np.zeros((144,144))
    for i in range(24):
        a=x[i]; s=slice(i*6,i*6+6); r=float(a@a)
        f+=r**4; grad[i]+=8*r**3*a
        h[s,s]+=48*r*r*np.outer(a,a)+8*r**3*np.eye(6)
        for j in range(i):
            b=x[j]; t=slice(j*6,j*6+6); g=float(a@b)
            f+=2*g**4; grad[i]+=8*g**3*b; grad[j]+=8*g**3*a
            h[s,s]+=24*g*g*np.outer(b,b); h[t,t]+=24*g*g*np.outer(a,a)
            c=24*g*g*np.outer(b,a)+8*g**3*np.eye(6)
            h[s,t]+=c; h[t,s]+=c.T
    lam=np.sum(x*grad,axis=1)
    rg=grad-lam[:,None]*x
    for i in range(24):h[6*i:6*i+6,6*i:6*i+6]-=lam[i]*np.eye(6)
    return f,rg,h

def spaces(x):
    blocks=[la.null_space(a.reshape(1,6)) for a in x]
    t=la.block_diag(*blocks)
    rotations=[]
    for a in range(6):
        for b in range(a):
            v=np.zeros_like(x);v[:,a]=x[:,b];v[:,b]=-x[:,a];rotations.append(v.ravel())
    r=t.T@np.array(rotations).T
    u,s,_=la.svd(r,full_matrices=True)
    rank=int(np.sum(s>1e-10))
    return t,u[:,rank:],u[:,:rank],s

def mp_values(raw,dps=80):
    mp.mp.dps=dps
    x=[[mp.mpf(str(a)) for a in row] for row in raw]
    norms=[mp.sqrt(mp.fsum(a*a for a in row)) for row in x]
    x=[[a/n for a in row] for row,n in zip(x,norms)]
    gram=[[mp.fsum(a*b for a,b in zip(v,w)) for w in x] for v in x]
    f=mp.fsum(g**4 for row in gram for g in row)-36
    grad=[[8*mp.fsum(gram[i][j]**3*x[j][k] for j in range(24)) for k in range(6)] for i in range(24)]
    rg=[]
    for v,g in zip(x,grad):
        lam=mp.fsum(a*b for a,b in zip(v,g));rg += [b-lam*a for a,b in zip(v,g)]
    return {'digits':dps,'normalized_energy':mp.nstr(f,dps),'normalized_gradient_norm':mp.nstr(mp.sqrt(mp.fsum(a*a for a in rg)),dps),'input_norm_error':mp.nstr(max(abs(n-1) for n in norms),dps)}

def energy(x):
    return math.fsum(float(np.dot(a,b))**4 for a in x for b in x)-36

def check(path,output=None,baseline=None,perturb=True):
    raw=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    rows=raw.get('vectors',raw.get('X')) if isinstance(raw,dict) else raw
    x0=np.array(rows,dtype=float)
    if x0.shape!=(24,6) or not np.isfinite(x0).all():raise ValueError('Require finite 24 x 6 real coordinates')
    normerr=float(np.max(abs(la.norm(x0,axis=1)-1)))
    x=x0/la.norm(x0,axis=1)[:,None]
    f,g,h=evaluate(x);t,q,r,s=spaces(x)
    ht=t.T@h@t;hq=q.T@ht@q
    vals,vecs=la.eigh(hq); full=la.eigvalsh(ht)
    hp=mp_values(rows)
    report={'input_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'shape':[24,6],
      'unit_error':normerr,'energy':energy(x),'loop_energy':f,'gradient_norm':float(la.norm(g)),
      'tangent_dimension':120,'rotation_rank':r.shape[1],'rotation_singular_values':s.tolist(),
      'quotient_dimension':q.shape[1],'full_tangent_spectrum':full.tolist(),'quotient_spectrum':vals.tolist(),
      'rotation_hessian_residual':float(la.norm(ht@r,2)),
      'negative_count':int(np.sum(vals < -1e-7)),'near_zero_count':int(np.sum(abs(vals)<=1e-7)),
      'high_precision':hp,'perturbation_seed':20261030,'gram':(x@x.T).tolist()}
    perturbations=[]
    if perturb:
        rng=np.random.default_rng(20261030)
        indices=sorted(set(range(min(5,len(vals))))|set(np.where(vals<=1e-7)[0].tolist()))
        ds=[('eigen',int(k),vecs[:,k]) for k in indices]
        ds += [('random',k,rng.normal(size=q.shape[1])) for k in range(32)]
        f0=energy(x)
        for kind,k,v in ds:
            v=v/la.norm(v);d=(t@q@v).reshape(24,6); speeds=la.norm(d,axis=1)
            for step in [1e-4,1e-3,1e-2,.1]:
                for sign in [-1,1]:
                    y=x*np.cos(step*speeds)[:,None]+d*(sign*np.sinc(step*speeds/np.pi)*step)[:,None]
                    delta=energy(y)-f0
                    perturbations.append([kind,k,sign*step,delta])
        report['perturbation_min_delta']=min(p[3] for p in perturbations)
        report['perturbations']=perturbations
    ref=None
    if baseline:
        rr=json.loads(Path(baseline).read_text());ref=float(rr['high_precision']['normalized_energy'])
    report['reference_energy']=ref
    report['strict_numerical_candidate']=bool(normerr<=1e-12 and report['gradient_norm']<=1e-9 and vals[0]>1e-6 and ref is not None and report['energy']-ref>1e-8 and (not perturb or report['perturbation_min_delta']>=-1e-10))
    if report['strict_numerical_candidate']:level='numerical_strict_local_minimum_modulo_rotations'
    elif vals[0]<-1e-7:level='negative_curvature_reject'
    elif report['gradient_norm']>1e-9:level='nonstationary_or_insufficient_refinement'
    elif report['near_zero_count']:level='degenerate_requires_higher_order_analysis'
    else:level='floating_point_stationary_configuration'
    report['evidence_level']=level
    report['proved_local_minimum']=False
    if output:
        out=Path(output);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,indent=2));np.savez(out.with_suffix('.npz'),vectors=x,gram=x@x.T,tangent_basis=t,quotient_basis=t@q,rotation_basis=t@r,hessian_tangent=ht,hessian_quotient=hq,eigenvectors=vecs,spectrum=vals)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('candidate');p.add_argument('--output');p.add_argument('--baseline');p.add_argument('--no-perturb',action='store_true');a=p.parse_args()
    try:
        r=check(a.candidate,a.output,a.baseline,not a.no_perturb)
        print(json.dumps({k:v for k,v in r.items() if k not in ['gram','perturbations','full_tangent_spectrum','quotient_spectrum']}))
    except Exception as e:print(json.dumps({'valid':False,'error':str(e)}));raise
