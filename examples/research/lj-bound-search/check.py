"""Host-authored, exact-rational verifier for a documented ball-average proof family.
No candidate code is executed. All accepted leaves cover the entire parameter square.
"""
from fractions import Fraction as F
from pathlib import Path
import json,sys,hashlib,math
import sympy as S

def root_interval(q,n,digits=45):
    q=F(q); scale=10**digits; lo=0;hi=2*scale
    while F(hi,scale)**n<q:hi*=2
    while hi-lo>1:
        mid=(hi+lo)//2
        if F(mid,scale)**n<=q:lo=mid
        else:hi=mid
    return F(lo,scale),F(hi,scale)

class I:
    def __init__(self,a,b=None):self.lo=F(a);self.hi=F(a if b is None else b)
    def __add__(self,o):
        o=iv(o);return I(self.lo+o.lo,self.hi+o.hi)
    __radd__=__add__
    def __neg__(self):return I(-self.hi,-self.lo)
    def __sub__(self,o):return self+-iv(o)
    def __rsub__(self,o):return iv(o)+-self
    def __mul__(self,o):
        o=iv(o);v=[a*b for a in (self.lo,self.hi) for b in (o.lo,o.hi)];return I(min(v),max(v))
    __rmul__=__mul__
    def __truediv__(self,o):
        o=iv(o);assert o.lo*o.hi>0;return self*I(1/o.hi,1/o.lo)
    def __rtruediv__(self,o):return iv(o)/self
    def __pow__(self,n):
        if n<0:return I(1)/(self**(-n))
        if n==0:return I(1)
        if self.lo>=0:return I(self.lo**n,self.hi**n)
        if self.hi<=0:return I(self.lo**n,self.hi**n) if n%2 else I(self.hi**n,self.lo**n)
        return I(min(self.lo**n,self.hi**n) if n%2 else 0,max(self.lo**n,self.hi**n))
def iv(x):return x if isinstance(x,I) else I(x)

T=I(*root_interval(F(11,5),6)); A=F(360,121)*T; B=F(25,11)
SCALE=I(*root_interval(F(2),6))
def integral(L):
    # Exact antiderivatives on [L,T] and [T,infinity]. No numerical tail cutoff.
    L=F(L)
    return 24*(A*(T**2-L**2)/2-B*(T**3-L**3)/3+F(2,3)/T**3-F(1,9)/T**9)

def reference_interval():
    K=integral(F(16,25));lo=F(684,1000);hi=F(7,10)
    for _ in range(180):
        m=(lo+hi)/2;v=2*m**6+K*m**9-1
        if v.hi<0:lo=m
        elif v.lo>0:hi=m
        else:break
    return I(lo,hi),K

def dec(x):
    from decimal import Decimal,localcontext
    with localcontext() as c:
        c.prec=55;return str(Decimal(x.numerator)/Decimal(x.denominator))

def polynomial(a,b,L):
    x,y=S.symbols('x y');c=S.Rational(a)/2+(S.Rational(b)-S.Rational(a))*x/2
    r=S.Rational(89,100)+y*(S.Rational(L)+c-S.Rational(89,100));w=S.symbols('w')
    alpha=lambda w:-w**3/3+r*w*w+(c*c-r*r)*w
    beta=lambda w:-w**4/4+2*r*w**3/3+(c*c-r*r)*w*w/2
    J=S.Rational(A.lo)*(alpha(r+c)-alpha(S.Rational(L)))-S.Rational(B)*(beta(r+c)-beta(S.Rational(L)))
    p=S.Poly(3*r**11*J-4*c**3*(2*r**6-1),x,y)
    terms={tuple(k):F(v) for k,v in p.terms()};n,m=p.degree(x),p.degree(y)
    out=[]
    for i in range(n+1):
        row=[]
        for j in range(m+1):
            row.append(sum(v*F(math.comb(i,k),math.comb(n,k))*F(math.comb(j,l),math.comb(m,l)) for (k,l),v in terms.items() if k<=i and l<=j))
        out.append(row)
    return out,terms

def split_line(line):
    levels=[line]
    while len(levels[-1])>1:levels.append([(a+b)/2 for a,b in zip(levels[-1],levels[-1][1:])])
    return [r[0] for r in levels],[r[-1] for r in reversed(levels)]
def split_grid(g,axis):
    if axis==1:
        rows=[split_line(r) for r in g];return [v[0] for v in rows],[v[1] for v in rows]
    a,b=split_grid([list(t) for t in zip(*g)],1)
    return [list(t) for t in zip(*a)],[list(t) for t in zip(*b)]
def evaluate(terms,x,y):return sum(v*x**i*y**j for (i,j),v in terms.items())

def cover(g,terms):
    stack=[('',g,F(0),F(1),F(0),F(1))];leaves=[];minimum=None
    while stack:
        path,b,x0,x1,y0,y1=stack.pop();low=min(map(min,b))
        if low>=0:
            leaves.append({'path':path,'lower':str(low)});minimum=low if minimum is None else min(minimum,low);continue
        xm=(x0+x1)/2;ym=(y0+y1)/2
        if evaluate(terms,xm,ym)<0:
            raise ValueError('Ball-average inequality fails at exact normalized point '+str((xm,ym)))
        axis=len(path)%2;left,right=split_grid(b,axis)
        if axis==0:
            stack.extend([(path+'1',right,xm,x1,y0,y1),(path+'0',left,x0,xm,y0,y1)])
        else:
            stack.extend([(path+'1',right,x0,x1,ym,y1),(path+'0',left,x0,x1,y0,ym)])
    return leaves,minimum

def verify(obj,certificate=None):
    if obj.get('method')!='ball_average_v1':
        return {'valid':False,'requires_host_proof_review':True,'reason':'Unsupported proof method; provide complete proof, code, certificate. No automatic success.'}
    a=F(obj.get('a','0.684'));b=F(obj['b']);L=F(obj['cutoff']);level=int(obj.get('particle_minus_energy',0))
    assert F(3,5)<=a<=b<F(4,5),'proof range'
    assert level in (0,1),'only established relocation levels 0 or 1'
    assert 0<L<T.lo and L+b< F(149,100),'positive harmonic integrand extent'
    assert L>=F(89,100)-a/2 and L<=F(89,100)+a/2,'cap geometry'
    assert L+a/2>=F(89,100),'nonempty transition interval'
    if obj.get('calibration'):
        assert a==F(3,5) and b==F(7,10) and L==F(16,25) and level==0
    else:assert a==F(171,250),'coverage starts from published proven bound'
    K=integral(L);assert K.lo>0
    g,terms=polynomial(a,b,L);leaves,margin=cover(g,terms)
    v=2*b**6+K*b**9-1-level*b**12
    # f(a) strictly increasing on (0,b]: f'=12a^5+9Ka^8-12 level a^11>0 because b<1.
    valid=v.hi<0
    ref,_=reference_interval()
    improved=valid and b>ref.hi
    if obj.get('calibration'):valid=True;improved=False
    result={'valid':valid,'improved':improved,'method':'ball_average_v1','b_scaled_exact':str(b),'c_new_expression':str(b)+' * 2^(1/6)','c_new_interval':[str((I(b)*SCALE).lo),str((I(b)*SCALE).hi)],'c_new_decimal':dec((I(b)*SCALE).lo),'cutoff':str(L),'particle_minus_energy':level,'K_interval':[str(K.lo),str(K.hi)],'contradiction_upper':str(v.hi),'cover_leaves':len(leaves),'minimum_bernstein_coefficient':str(margin),'all_N':True,'original_conjecture_solved':False,'calibration_only':bool(obj.get('calibration'))}
    if certificate:
        Path(certificate).write_text(json.dumps({'candidate':obj,'report':result,'cover':leaves,'polynomial_terms':[[i,j,str(v)] for (i,j),v in sorted(terms.items())]},indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    try:res=verify(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig')),sys.argv[2] if len(sys.argv)>2 else None)
    except Exception as e:res={'valid':False,'reason':str(e)}
    print(json.dumps(res))
