from pathlib import Path
from fractions import Fraction as F
import json,sys,hashlib
import sympy as s
from check import *
ROOT=Path(__file__).resolve().parents[3]
RUN=Path((ROOT/'data/lj-bound-search/latest-run.txt').read_text().strip())
base=RUN/'baseline'
cal={'method':'ball_average_v1','a':'0.6','b':'0.7','cutoff':'0.64','particle_minus_energy':0,'calibration':True}
report=verify(cal,base/'original-average-certificate.json')
assert report['valid']
assert integral(F(54,100)).hi<F(2695,100)
assert integral(F(64,100)).hi<F(2405,100)
assert 2*F(65,100)**6+F(2695,100)*F(65,100)**9<1
assert 2*F(684,1000)**6+F(2405,100)*F(684,1000)**9<1
ref,K=reference_interval();cr=ref*SCALE
data={'published_scaled':'171/250','published_exact':'(171/250) * 2^(1/6)','published_decimal':dec((I(F(171,250))*SCALE).lo),'c_ref_definition':'2^(1/6) times unique positive root a of 2*a^6+K*a^9=1; K=24*integral_{16/25}^infinity theta(r)*r^2 dr','c_ref_interval':[str(cr.lo),str(cr.hi)],'c_ref_decimal_interval':[dec(cr.lo),dec(cr.hi)],'a_ref_interval':[str(ref.lo),str(ref.hi)],'K_interval':[str(K.lo),str(K.hi)],'K_decimal_interval':[dec(K.lo),dec(K.hi)],'note':'Stronger unrounded implication of existing Yuhjtman proof is frozen to avoid counting rounding as novelty. This is host baseline work, not model discovery.','average_check':report,'units':{'r':'2^(1/6)*s','E_user':'E_Yuhjtman/4','Cambridge_standard_4V':'r unchanged, energy/4'}}
(base/'reference.json').write_text(json.dumps(data,indent=2))
# Exact small-N configurations, no optimizer or virial-only inference.
ell=2**s.Rational(1,6)
points=[s.Matrix([0,0,0]),s.Matrix([ell,0,0]),s.Matrix([ell/2,s.sqrt(3)*ell/2,0]),s.Matrix([ell/2,s.sqrt(3)*ell/6,s.sqrt(s.Rational(2,3))*ell])]
calibrations=[]
for N in (2,3,4):
    ds=[s.simplify((points[i]-points[j]).dot(points[i]-points[j])) for i in range(N) for j in range(i)]
    E=s.simplify(sum(d**-6-d**-3 for d in ds))
    assert E==-s.Rational(N*(N-1),8)
    assert all(s.simplify(d-ell**2)==0 for d in ds)
    calibrations.append({'N':N,'coordinates_exact':[[str(c) for c in p] for p in points[:N]],'coordinates_decimal':[[str(s.N(c,55)) for c in p] for p in points[:N]],'r_min_exact':'2^(1/6)','energy_exact':str(E),'global_proof':'V(r)=(r^-6-1/2)^2-1/4 >= -1/4; all pairs attain this lower bound in R3 for N<=4.'})
(base/'small-N-calibration.json').write_text(json.dumps(calibrations,indent=2))
print(json.dumps({'baseline_pass':True,'c_ref':data['c_ref_decimal_interval'],'original_average_cover_leaves':report['cover_leaves'],'small_N':[2,3,4]}))
