"""Independent exact-rational isolation audit, without importing solver code.

Ignore the supplied polynomial strings, Jacobian bounds and inclusion flags.
Rebuild the original 2N recurrence and all nine equations. Differentiate with
interval forward AD, rather than the solver's expanded symbolic polynomials.
Prove a strict invariant box and contraction for T(x)=x-C*F(x). No floats enter
any decision. This supplements, and does not modify, the frozen checker.
"""
import json,sys,hashlib
from fractions import Fraction as Q
from pathlib import Path
sys.set_int_max_str_digits(0)

class Interval:
    __slots__=('lo','hi')
    def __init__(self,lo,hi=None):
        self.lo=Q(lo);self.hi=Q(lo if hi is None else hi)
        if self.lo>self.hi:raise ValueError('Reversed interval')
    def __add__(self,other):
        other=interval(other);return Interval(self.lo+other.lo,self.hi+other.hi)
    __radd__=__add__
    def __neg__(self):return Interval(-self.hi,-self.lo)
    def __sub__(self,other):return self+-interval(other)
    def __rsub__(self,other):return interval(other)+-self
    def __mul__(self,other):
        other=interval(other)
        products=[a*b for a in (self.lo,self.hi) for b in (other.lo,other.hi)]
        return Interval(min(products),max(products))
    __rmul__=__mul__
    def magnitude(self):return max(abs(self.lo),abs(self.hi))
def interval(x):return x if isinstance(x,Interval) else Interval(x)

class Dual:
    __slots__=('v','d')
    def __init__(self,value,derivative=None):
        self.v=interval(value);self.d=[interval(x) for x in (derivative or [0]*9)]
    def __add__(self,other):
        other=dual(other);return Dual(self.v+other.v,[a+b for a,b in zip(self.d,other.d)])
    __radd__=__add__
    def __neg__(self):return Dual(-self.v,[-v for v in self.d])
    def __sub__(self,other):return self+-dual(other)
    def __rsub__(self,other):return dual(other)+-self
    def __mul__(self,other):
        other=dual(other)
        return Dual(self.v*other.v,[a*other.v+self.v*b for a,b in zip(self.d,other.d)])
    __rmul__=__mul__
def dual(x):return x if isinstance(x,Dual) else Dual(x)

def system(x,r4,r5):
    alpha=[0]+list(x[:4]);beta=list(x[4:]);delta=[0]*5;y=[0]*5;A=[]
    for i in range(5):
        A.append(y[:]);delta=[alpha[i]*v for v in delta];delta[i]+=1
        y=[u+beta[i]*v for u,v in zip(y,delta)]
    b=y;c=[sum(row) for row in A]
    dot=lambda u,v:sum(a*b for a,b in zip(u,v))
    mat=lambda v:[dot(row,v) for row in A]
    ac=mat(c);a2c=mat(ac);a3c=mat(a2c)
    c2=[v*v for v in c];c3=[u*v for u,v in zip(c2,c)]
    return [sum(b)-1,dot(b,c)-Q(1,2),dot(b,c2)-Q(1,3),dot(b,ac)-Q(1,6),
            dot(b,a2c)-r4,dot(b,a3c)-r5,dot(b,c3)-Q(1,4),
            dot(b,mat(c2))-Q(1,12),dot(b,[u*v for u,v in zip(c,ac)])-Q(1,8)]

def audit(certificate,candidate,baseline):
    cert=json.loads(certificate.read_text());raw=json.loads(candidate.read_text())
    ref=json.loads(baseline.read_text());r4,r5=map(Q,ref['stability_ascending'][4:])
    assert cert['variables']==['a2','a3','a4','a5','b1','b2','b3','b4','b5']
    X=[Interval(a,b) for a,b in cert['isolation']['box']]
    m=[Q(v) for v in cert['isolation']['midpoint']]
    assert len(X)==len(m)==9 and all(x.lo<c<x.hi for x,c in zip(X,m))
    # A rational preconditioner can be arbitrary: the contraction test below
    # certifies its adequacy. Round to keep this implementation independent of
    # the producer's huge exact inverse arithmetic and to reduce expression size.
    scale=10**40
    C=[[Q((Q(v).numerator*scale)//Q(v).denominator,scale) for v in row] for row in cert['isolation']['Y']]
    assert len(C)==9 and all(len(row)==9 for row in C)
    ad=system([Dual(x,[int(i==j) for j in range(9)]) for i,x in enumerate(X)],r4,r5)
    J=[v.d for v in ad]
    M=[[Interval(int(i==j))-sum(C[i][k]*J[k][j] for k in range(9)) for j in range(9)] for i in range(9)]
    contraction=max(sum(v.magnitude() for v in row) for row in M)
    fm=system(m,r4,r5);correction=[sum(C[i][j]*fm[j] for j in range(9)) for i in range(9)]
    K=[Interval(m[i]-correction[i])+sum(M[i][j]*(X[j]-m[j]) for j in range(9)) for i in range(9)]
    slack=[min(k.lo-x.lo,x.hi-k.hi) for k,x in zip(K,X)]
    included=all(v>0 for v in slack)
    valid=included and contraction<1
    assert raw['schema']=='williamson-2n-v1' and raw['stages']==5 and Q(raw['alpha'][0])==0
    saved=list(map(Q,raw['alpha'][1:]+raw['beta']))
    saved_inside=all(x.lo<v<x.hi for x,v in zip(X,saved))
    fs=system(saved,r4,r5)
    saved_correction=max(abs(sum(C[i][j]*fs[j] for j in range(9))) for i in range(9))
    distance=saved_correction/(1-contraction) if valid and saved_inside else None
    floor=abs(r4-Q(1,24))
    proof={
      'valid_exact_isolation':bool(valid),'saved_candidate_inside_isolating_box':saved_inside,
      'certificate_sha256':hashlib.sha256(certificate.read_bytes()).hexdigest(),
      'candidate_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),
      'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'arithmetic':'fractions.Fraction endpoints; all inequalities exact; interval forward automatic differentiation of original recurrence',
      'equations':['sum(b)=1','b*c=1/2','b*c^2=1/3','b*A*c=1/6','b*A^2*c=1901/68628','b*A^3*c=121/68628','b*c^3=1/4','b*A*c^2=1/12','b*(c*(A*c))=1/8'],
      'contraction_bound_exact':str(contraction),'contraction_bound_float_for_display':float(contraction),
      'minimum_strict_inclusion_slack_exact':str(min(slack)),
      'minimum_strict_inclusion_slack_float_for_display':float(min(slack)),
      'saved_coefficient_root_distance_bound_exact':str(distance) if distance is not None else None,
      'saved_coefficient_root_distance_bound_float_for_display':float(distance) if distance is not None else None,
      'saved_exact_constraint_residual_float_for_display':float(max(map(abs,fs))),
      'attained_error_norm_exact':str(floor) if valid else None,
      'optimality_scope':'All real five-stage Williamson 2N schemes with all third-order conditions and this exact complete stability polynomial. This is not a literature priority or broader method ranking claim.',
      'theorem':'K subset interior(X) encloses T(X); ||I-C*J(X)||_inf<1 makes T a contraction. Banach gives one fixed point in X. The derivative bound implies C*J(m) nonsingular, hence C nonsingular; fixed points are exactly F=0. Nonsingular rational polynomial system plus rational isolating box defines an exact real algebraic solution. Fixed r4 forces tau_chain=r4-1/24; other order-four components vanish at this solution, attaining the norm lower bound.',
      'isolating_box':[[str(v.lo),str(v.hi)] for v in X],
      'rational_midpoint':list(map(str,m)),'rational_preconditioner':[[str(v) for v in row] for row in C],
      'independent_K_image':[[str(v.lo),str(v.hi)] for v in K],
    }
    return proof

if __name__=='__main__':
    result=audit(*(Path(x) for x in sys.argv[1:4]));output=Path(sys.argv[4]);output.write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if not k.endswith('_exact') and k not in ['isolating_box','rational_midpoint','rational_preconditioner','independent_K_image']},indent=2))
