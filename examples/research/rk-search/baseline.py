"""Reproduce Table 8 from its original two-register recurrence, exactly."""
import sys,json,hashlib,types
from pathlib import Path
import sympy as S
import numpy as np
ROOT=Path(__file__).resolve().parents[3]
PREP=ROOT/'data/rk-search/preparation'
# Load the unmodified numerical modules without the optional plotting imports
# in NodePy's package initializer (host matplotlib has an unrelated ABI issue).
pkg=types.ModuleType('nodepy');pkg.__path__=[str(PREP/'nodepy/nodepy')]
sys.modules['nodepy']=pkg
import nodepy.runge_kutta_method as rk
import nodepy.rooted_trees as rt
R=S.Rational
alpha=list(map(R,['0','-9/16','-62032/41503','5929/9234','-45/98']))
beta=list(map(R,['1/4','36/49','847/3078','3/14','7/43']))
A=S.zeros(5); q=S.zeros(1,5); y=S.zeros(1,5)
for i in range(5):
    A[i,:]=y
    q=alpha[i]*q; q[i]+=1
    y+=beta[i]*q
b=y.T;c=A*S.ones(5,1)
printed=S.Matrix([[0,0,0,0,0],[R(1,4),0,0,0,0],[-R(8,49),R(36,49),0,0,0],[R(163,2394),R(3484,10773),R(847,3078),0,0],[R(12053,11172),R(2960,25137),R(847,2052),R(3,14),0]])
pb=S.Matrix(list(map(R,['37/258','220/1161','847/2322','6/43','7/43'])))
pc=S.Matrix(list(map(R,['0','1/4','4/7','2/3','13/14'])))
method=rk.ExplicitRungeKuttaMethod(np.array(A.tolist(),dtype=object),np.array(list(b),dtype=object))
errors=method.error_coeffs(4); order=method.order(mode='exact')
stability=[S.Integer(1)]+[(b.T*A**k*S.ones(5,1))[0] for k in range(5)]
assert order==3 and b==pb and c==pc
candidate={'schema':'williamson-2n-v1','stages':5,'alpha':list(map(str,alpha)),'beta':list(map(str,beta)),'source':'Bazavov 2026 Table 8 low-storage recurrence'}
norm=S.sqrt(sum(v*v for v in errors))
audit={'source_url':'https://link.springer.com/article/10.1007/s10543-026-01139-3/tables/8','alpha':candidate['alpha'],'beta':candidate['beta'],'A':[[str(v) for v in row] for row in A.tolist()],'b':list(map(str,b)),'c':list(map(str,c)),'printed_A':[[str(v) for v in row] for row in printed.tolist()],'printed_c':list(map(str,pc)),'printed_row_sums':list(map(str,printed*S.ones(5,1))),'discrepancies':[{'row':i+1,'column':j+1,'printed':str(printed[i,j]),'reconstructed':str(A[i,j])} for i in range(5) for j in range(5) if A[i,j]!=printed[i,j]],'order_exact':order,'order_residuals':list(map(str,[sum(b)-1,(b.T*c)[0]-R(1,2),(b.T*c.applyfunc(lambda x:x*x))[0]-R(1,3),(b.T*A*c)[0]-R(1,6)])),'stability_ascending':list(map(str,stability)),'nodepy_trees':[str(t) for t in rt.list_trees(4)],'nodepy_error_coefficients':list(map(str,errors)),'principal_error_norm_exact':str(norm),'principal_error_norm':str(norm.evalf(100)),'linear_tree_lower_bound':str(abs(stability[4]-R(1,24))),'source_sha256':{n:hashlib.sha256((PREP/n).read_bytes()).hexdigest() for n in ['paper.html','table8.html']}}
for name,obj in [('baseline.json',candidate),('baseline-audit.json',audit)]: (PREP/name).write_text(json.dumps(obj,indent=2))
print(json.dumps(audit,indent=2))
