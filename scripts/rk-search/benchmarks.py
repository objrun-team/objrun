"""Frozen held-out nonlinear ODE suite, inaccessible to the search model."""
import json,sys
from pathlib import Path
import numpy as np
import mpmath as mp
def problems():
    return [
      ('logistic',lambda t,y:2*y*(1-y),np.array([.1]),3.,lambda t:np.array([1/(1+9*np.exp(-2*t))])),
      ('cubic_decay',lambda t,y:-y**3/2,np.array([1.]),10.,lambda t:np.array([1/np.sqrt(1+t)])),
      ('nonautonomous_riccati',lambda t,y:2*t*y*y,np.array([.5]),1.,lambda t:np.array([1/(2-t*t)])),
      ('coupled_nonlinear',lambda t,y:np.array([-y[0]**2,-2*y[0]*y[1]]),np.array([1.,1.]),3.,lambda t:np.array([1/(1+t),1/(1+t)**2])),
    ]
def coefficients(raw):
    cv=lambda s:float(mp.mpf(s.split('/')[0])/(mp.mpf(s.split('/')[1]) if '/' in s else 1))
    a=np.array([cv(x) for x in raw['alpha']]);B=np.array([cv(x) for x in raw['beta']]);y=np.zeros(5);q=y.copy();A=[]
    for i in range(5):A.append(y.copy());q=a[i]*q;q[i]+=1;y+=B[i]*q
    return a,B,np.array(A),y
def run_suite(raw):
    a,B,A,b=coefficients(raw);c=A.sum(axis=1);out=[]
    for name,f,y0,T,exact in problems():
        for steps in [40,80,160,320,640]:
            h=T/steps;y=y0.copy();peak=0.
            with np.errstate(over='ignore',invalid='ignore'):
                for n in range(steps):
                    d=np.zeros_like(y)
                    for i in range(5):d=a[i]*d+h*f(n*h+c[i]*h,y);y=y+B[i]*d
                    peak=max(peak,float(np.max(np.abs(y-exact((n+1)*h)))))
            err=float(np.max(np.abs(y-exact(T))))
            out.append({'problem':name,'steps':steps,'rhs_calls':5*steps,'terminal_max_error':err if np.isfinite(err) else None,'trajectory_max_error':peak if np.isfinite(peak) else None,'finite':bool(np.all(np.isfinite(y)))})
    return out
def diagnostics(raw,refpoly):
    a,B,A,b=coefficients(raw);c=A.sum(axis=1)
    # Transfer of additive residuals inserted after each 2N stage update,
    # in BOTH solution and increment registers, through the implemented recurrence.
    xx,yy=np.meshgrid(np.linspace(-12,2,561),np.linspace(-8,8,641));z=(xx+1j*yy).ravel()
    R=np.polynomial.polynomial.polyval(z,np.array([float(mp.mpf(s.split('/')[0])/(mp.mpf(s.split('/')[1]) if '/' in s else 1)) for s in refpoly]))
    z=z[np.abs(R)<=1+1e-12];q0=np.ones_like(z);q1=np.zeros_like(z);q=[]
    for i in range(4,-1,-1):
        q.extend([np.abs(q0),np.abs(q1)])
        q0,q1=q0*(1+B[i]*z)+q1*z,q0*B[i]*a[i]+q1*a[i]
    stack=np.array(q)
    u,v=1.,0.;zero_gain=[]
    for i in range(4,-1,-1):
        zero_gain.extend([abs(u),abs(v)]);u,v=u,u*B[i]*a[i]+v*a[i]
    def constraints(x):
        aa=np.r_[0,x[:4]];bb=x[4:];Y=np.zeros(5,dtype=x.dtype);Q=Y.copy();rows=[]
        for i in range(5):rows.append(Y.copy());Q=aa[i]*Q;Q[i]+=1;Y+=bb[i]*Q
        M=np.array(rows);C=M.sum(axis=1)
        return np.array([Y.sum(),Y@C,Y@(C*C),Y@M@C,Y@M@M@C,Y@M@M@M@C])
    x=np.r_[a[1:],B];J=np.column_stack([np.imag(constraints(x.astype(complex)+1e-28j*np.eye(9)[j]))/1e-28 for j in range(9)]);s=np.linalg.svd(J,compute_uv=False)
    return {'coefficient_max_abs':float(max(np.max(abs(a)),np.max(abs(B)))),'butcher_max_abs':float(max(np.max(abs(A)),np.max(abs(b)),np.max(abs(c)))),'c':c.tolist(),'weight_cancellation':float(sum(abs(b))/abs(sum(b))),'constraint_jacobian_singular_values':s.tolist(),'constraint_jacobian_condition':float(s[0]/s[-1]),'internal_amplification':{'definition':'post-stage additive perturbations in both Williamson y and delta registers; delta has solution units','sample_rectangle':[-12,2,-8,8],'grid_shape':[641,561],'stable_sample_count':len(z),'sampled_max_single_residual_gain':float(stack.max()),'sampled_max_sum_residual_gain':float(stack.sum(axis=0).max()),'at_z0_single_residual_gain':max(zero_gain),'certificate':'sampled diagnostic, not a certified supremum'}}
if __name__=='__main__':
    raw=json.loads(Path(sys.argv[1]).read_text()); ref=json.loads(Path(sys.argv[2]).read_text())
    result={'held_out':True,'not_used_for_optimization':True,'rhs_budget_per_step':5,'reference':'analytic exact solutions evaluated in float64; roundoff near 1e-14 limits comparisons','odes':run_suite(raw),'diagnostics':diagnostics(raw,ref['stability_ascending'])}
    print(json.dumps(result,indent=2))
