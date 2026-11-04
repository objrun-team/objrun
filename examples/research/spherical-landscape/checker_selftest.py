import json,tempfile
from pathlib import Path
import numpy as np
from scipy.linalg import norm,expm
from checker import evaluate,spaces,energy

def run():
    rng=np.random.default_rng(891732);x=rng.normal(size=(24,6));x/=norm(x,axis=1)[:,None]
    f,g,h=evaluate(x);t,q,r,s=spaces(x)
    checks=[]
    for k in range(12):
        d=(t@rng.normal(size=120)).reshape(24,6);d/=norm(d);speeds=norm(d,axis=1)
        def geo(z):return x*np.cos(z*speeds)[:,None]+d*(z*np.sinc(z*speeds/np.pi))[:,None]
        a=1e-4;fp=energy(geo(a));fm=energy(geo(-a));f0=energy(x)
        gd=float(np.sum(g*d));hd=float(d.ravel()@h@d.ravel())
        graderr=abs((fp-fm)/(2*a)-gd);hesserr=abs((fp+fm-2*f0)/a**2-hd)
        assert graderr<1e-6 and hesserr<2e-5,(graderr,hesserr)
        checks.append({'gradient_error':graderr,'hessian_error':hesserr})
    a=rng.normal(size=(6,6));a=a-a.T;rot=expm(.17*a)
    err=abs(energy(x@rot)-energy(x));assert err<1e-10
    assert t.shape==(144,120) and q.shape==(120,105) and r.shape==(120,15)
    assert norm(t.T@t-np.eye(120))<1e-12
    assert norm(q.T@r)<1e-12
    # Exact easy validation: four repeated coordinate bases gives F=96-36=60.
    b=np.vstack([np.eye(6)]*4);fb,gb,hb=evaluate(b)
    assert abs(fb-60)<1e-12 and norm(gb)<1e-12
    return {'passed':True,'seed':891732,'finite_difference_checks':checks,'orthogonal_invariance_error':err,'dimensions':[144,120,15,105],'coordinate_basis_energy':fb}
if __name__=='__main__':print(json.dumps(run(),indent=2))
