"""Independent polynomial construction and per-leaf rational Bernstein replay.
Does not import the live checker, trust supplied polynomial terms or run candidate code.
"""
from fractions import Fraction as Q
from pathlib import Path
import json,sys,math
import sympy as s

def check_tree(paths):
    assert len(set(paths))==len(paths)
    def visit(prefix):
        if prefix in paths:
            assert not any(p.startswith(prefix) and p!=prefix for p in paths)
            return
        assert any(p.startswith(prefix+'0') for p in paths) and any(p.startswith(prefix+'1') for p in paths)
        visit(prefix+'0');visit(prefix+'1')
    visit('')

def main(path):
    cert=json.loads(Path(path).read_text());o=cert['candidate']
    a=Q(o['a']);b=Q(o['b']);cut=Q(o['cutoff']);level=o.get('particle_minus_energy',0)
    assert a==Q(171,250) and a<=b<Q(4,5) and level in (0,1)
    scale=10**45;lo=scale;hi=2*scale
    while hi-lo>1:
        mid=(lo+hi)//2
        if 5*mid**6<=11*scale**6:lo=mid
        else:hi=mid
    tau_lo=Q(lo,scale);tau_hi=Q(hi,scale)
    assert 0<cut<tau_lo and cut+b<Q(149,100)
    assert Q(89,100)-a/2<=cut<=Q(89,100)+a/2 and cut+a/2>=Q(89,100)
    x,y,w=s.symbols('x y w');radius=s.Rational(a)/2+x*s.Rational(b-a)/2
    center=s.Rational(89,100)+y*(s.Rational(cut)+radius-s.Rational(89,100))
    AA=s.Rational(360,121)*s.Rational(tau_lo)
    integrand=(AA-s.Rational(25,11)*w)*(radius**2-(w-center)**2)
    primitive=s.integrate(integrand,w)
    J=primitive.subs(w,center+radius)-primitive.subs(w,s.Rational(cut))
    poly=s.Poly(s.expand(3*center**11*J-4*radius**3*(2*center**6-1)),x,y)
    terms={ij:Q(v) for ij,v in poly.terms()};n=poly.degree(x);m=poly.degree(y)
    assert terms=={(i,j):Q(v) for i,j,v in cert['polynomial_terms']}
    paths={l['path'] for l in cert['cover']};assert len(paths)==len(cert['cover']);check_tree(paths)
    minimum=None
    for leaf in cert['cover']:
        x0,x1,y0,y1=Q(0),Q(1),Q(0),Q(1)
        for depth,bit in enumerate(leaf['path']):
            assert bit in '01'
            if depth%2==0:
                mid=(x0+x1)/2
                if bit=='0':x1=mid
                else:x0=mid
            else:
                mid=(y0+y1)/2
                if bit=='0':y1=mid
                else:y0=mid
        # Recompute local power coefficients from global monomials, rather than subdivision.
        local={}
        for (i,j),v in terms.items():
            for k in range(i+1):
                for l in range(j+1):
                    key=(k,l)
                    local[key]=local.get(key,Q(0))+v*math.comb(i,k)*x0**(i-k)*(x1-x0)**k*math.comb(j,l)*y0**(j-l)*(y1-y0)**l
        bound=min(sum(v*Q(math.comb(i,k),math.comb(n,k))*Q(math.comb(j,l),math.comb(m,l)) for (k,l),v in local.items() if k<=i and l<=j) for i in range(n+1) for j in range(m+1))
        assert bound>=0 and bound==Q(leaf['lower'])
        minimum=bound if minimum is None else min(minimum,bound)
    # Rational outward bounding of full integral, constructed separately.
    ku=24*(Q(360,121)*tau_hi*(tau_hi**2-cut**2)/2-Q(25,33)*(tau_lo**3-cut**3)+Q(2,3)/tau_lo**3-Q(1,9)/tau_hi**9)
    assert 2*b**6+ku*b**9-1-level*b**12<0
    # Compare to the unrounded original root without trusting any decimal approximation.
    old_cut=Q(16,25)
    kl=24*(Q(360,121)*tau_lo*(tau_lo**2-old_cut**2)/2-Q(25,33)*(tau_hi**3-old_cut**3)+Q(2,3)/tau_hi**3-Q(1,9)/tau_lo**9)
    assert 2*b**6+kl*b**9-1>0,'does not exceed original unrounded implication'
    return {'independent_replay_passed':True,'all_N':True,'b_scaled_exact':str(b),'c_new_expression':str(b)+' * 2^(1/6)','cover_leaves':len(paths),'minimum_coefficient':str(minimum),'tail':'exact antiderivative to infinity','global_optimality_use':'relocation of one particle; analytic proof reviewed separately','conjecture_ge_1':'not solved','strict_conjecture_gt_1':'not solved'}

if __name__=='__main__':
    try:result=main(sys.argv[1])
    except Exception as e:result={'independent_replay_passed':False,'reason':str(e)}
    print(json.dumps(result))
