"""Reject spurious PSLQ certificates with exact finite-field arithmetic.

This auxiliary audit does not replace or alter the frozen numerical checker.
Passing this necessary test is NOT a real-root or existence certificate.
"""
import json,hashlib,sys
from pathlib import Path
import sympy as s
p=Path(sys.argv[1]);cert=json.loads(p.read_text());t=s.symbols('t');prime=1000000007
P=s.Poly.from_list(list(reversed(cert['minpoly'])),t,modulus=prime)
assert P.degree()==len(cert['minpoly'])-1
def cv(v):
    q=s.Rational(v);den=int(q.q)%prime
    assert den!=0
    return int(q.p)%prime*pow(den,-1,prime)%prime
polys=[s.Poly.from_list([cv(v) for v in reversed(row)],t,modulus=prime)%P for row in cert['coord_polys']]
assert len(polys)==9
zero=s.Poly(0,t,modulus=prime);one=s.Poly(1,t,modulus=prime)
alpha=[zero]+polys[:4];beta=polys[4:];y=[zero]*5;q=[zero]*5
for i in range(5):
    q=[(alpha[i]*x)%P for x in q];q[i]+=one
    y=[(v+beta[i]*w)%P for v,w in zip(y,q)]
res=(sum(y,zero)-one)%P;g=s.gcd(P,res)
print(json.dumps({'certificate_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'prime':prime,'minpoly_degree':P.degree(),'first_order_residual_mod_prime':str(res.as_expr()),'gcd_degree':g.degree(),'status':'rejected' if g.degree()==0 else 'not_rejected_by_this_necessary_test','explanation':'An invertible-denominator, degree-preserving modular gcd of 1 rules out a common algebraic root satisfying even sum(b)=1. A non-rejection does not certify all order conditions or isolate a real root.'},indent=2))
