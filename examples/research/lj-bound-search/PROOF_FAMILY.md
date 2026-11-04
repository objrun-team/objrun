# Frozen host proof template, not a discovered new bound

Scope: every finite N>=2 and every global minimizer of sum_{i<j} V(r_ij)
on distinct points in R^3, with V(r)=r^-12-r^-6. Write r=2^(1/6)s;
then V(r)=(s^-12-2s^-6)/4. Let h(s)=-s^-12+2s^-6.
All parameters below are in the s units. No geometric realization is inferred
from free distance variables; we start with an actual configuration in R^3.

## Literature basis and reference

Yuhjtman arXiv:1501.05248v2, Propositions 2.3, 2.4, 3.1 and Corollary 3.3,
gives a>0.684. Let tau=(11/5)^(1/6), A=(360/121)tau, B=25/11,
t(w)=A/w-B, and theta(w)=t(w) for w<=tau, h(w) otherwise.
The matching value, first derivative, second derivative at tau are exact.
The polynomial w^12(t(w)-h(w)) has signs -,+,-,+, hence at most three
positive roots by Descartes' rule; tau is already a triple root. It is positive
near zero. Thus theta>=h everywhere, and theta>=t everywhere. theta is positive.
The radial Laplacian is zero below tau and 12(-11w^-14+5w^-8)>=0 above it.
Consequently its average on any ball avoiding the origin is >=theta at the
center, by the subharmonic mean inequality in dimension three.

For separation a<=0.7, keep only contributors with s>=0.89 (h<0 below this,
since (89/100)^6<1/2), place disjoint open balls of radius a/2 around them.
Their union lies outside radius 0.54. Integrating theta gives mu(a)<26.95/a^3.
The exact inequalities 2*(.65)^6+26.95*(.65)^9<1 and monotonicity exclude
a<=.65 by moving a positive-energy particle sufficiently far away.
For .6<=a<=.7 the published cutoff .64 gives mu(a)<24.05/a^3. The baseline
checker re-proves its ball-average inequality on the entire two-dimensional
domain, not just selected values; a<=.684 is then excluded. If a>.7 the
claimed .684 bound is already true. This handles the range restriction.

We freeze the stronger UNROUNDED existing implication as c_ref, not the
printed .767764: K_old=24 integral_{.64}^infinity theta(w)w^2 dw and
c_ref=2^(1/6)*a_ref, where a_ref is the unique positive root of
2*a_ref^6+K_old*a_ref^9=1. The root is below .7. The same published argument
excludes a<a_ref, so r_min>=c_ref. Numerical display ~.768420525585496;
exact enclosing rationals are in baseline/reference.json.

## Parameterized proof obligation

Set a0=.684. A proposed b and cutoff L must obey
a0<=b<.8, 0<L<tau, L+b<1.49,
.89-a0/2<=L<=.89+a0/2, and L+a0/2>=.89.
For all a in [a0,b], put c=a/2. Positive-contributor centers with r>=L+c
have balls wholly outside L, so theta*1_{w>L} has average >=h(r).
The remaining centers have .89<=r<=L+c. Their radii w in [L,r+c] lie in
the spherical cap, because r-c<=L and L<=r+c. Also r>c and r+c<=L+b<1.49.
Here t(w)>0, verified from A/B>1.49. The spherical cap area is
pi*w/r * (c^2-(w-r)^2). Its radial integral gives the lower bound

J(r,c,L)=integral_L^(r+c) (A-B*w)*(c^2-(w-r)^2) dw
avg(theta*1_{w>L}) >= 3*J/(4*c^3*r).

Replacing A by a certified rational lower bound lowers J: its coefficient
is the integral of a nonnegative cap factor. It suffices to prove the polynomial

P(r,c)=3*r^11*J_lower(r,c,L)-4*c^3*(2*r^6-1) >= 0.

Substitute c=a0/2+(b-a0)x/2 and r=.89+y*(L+c-.89), (x,y) in [0,1]^2.
This covers the entire closed triangular/trapezoidal domain, including all
edges. The checker derives all polynomial coefficients exactly over Q. It
recursively bisects the square and accepts only when every tensor Bernstein
coefficient on each leaf is nonnegative. Bernstein basis functions are
nonnegative and sum to one, so this certifies P>=0. Leaf paths form a full
binary partition; the second implementation checks coverage and reconstructs
each leaf from the original polynomial using a separate power-to-Bernstein
calculation. No numerical minimizer or sampling value enters acceptance.

Summing the ball averages is bounded above by the integral over all |z|>L,
because the balls have disjoint interiors and the integrand is nonnegative.
This is an UPPER bound on the attractive minus-energy of any actual separated
set; enlarging the integration domain only weakens the bound. Thus mu(a)<=K/a^3,
where the whole infinite tail is integrated analytically:

K=24*[A*(tau^2-L^2)/2-B*(tau^3-L^3)/3+2/(3*tau^3)-1/(9*tau^9)].

All radical enclosures are obtained by integer bisection and checked by sixth
powers; rational interval arithmetic provides K_upper. There is no unbounded
numerical tail, omitted shell, thermodynamic limit or N-dependent remainder.

## Global optimality and contradiction

For a closest pair at distance a<=b<.8, h(a)<0. Keeping this one term and
discarding other negative terms bounds the minus-energy of its endpoint by
h(a)+K/a^3. The remaining positive contributors are pairwise a-separated.

Global optimality implies its minus-energy is >=0 by relocation to infinity.
The stronger >=1 also holds: among the other N-1 points choose an exposed
point z and a supporting unit outward vector u. Place the moved point at z+u.
Its distance to z is 1; for every other point w,
|z+u-w|^2=1+2u.(z-w)+|z-w|^2>=1, so its minus-energy is >=h(1)=1.
All configurations are finite and the move preserves distinctness. Global
minimality compares the energy before and after this single-particle move;
all pair terms not involving that particle cancel. For N=2 equality is allowed.
For N>2 the remaining terms are positive, but the weak bound suffices.

Choose q=0 or 1 for these two established comparisons. A certificate needs
2*b^6+K_upper*b^9-1-q*b^12<0. This expression is strictly increasing in
a on (0,b], since its derivative is 12a^5(1-q*a^6)+9K_upper*a^8>0.
It follows h(a)+K/a^3<q for all a0<=a<=b, a contradiction. The previously
proved a>a0 covers the lower complement; a>b needs no exclusion. Hence
r_min>2^(1/6)b, and in particular >=2^(1/6)b, for ALL N>=2 and ALL global
minimizers. Improvement is accepted only if b>a_ref_upper from the frozen
unrounded baseline, not merely b>.684. Values allowed by this template are
below 1 in user units, so neither the >=1 nor the >1 conjecture is solved.

## Provenance and other methods

The host supplied this verifier/proof family by translating existing
subharmonic-ball and relocation arguments into exact certificate obligations.
The fixed ObjRun model must perform the parameter search, explain any chosen
improvement, and save its code and proof. This host template is disclosed as
host contribution. Other methods, including a proof at 1 or a globally optimal
counterexample, require separate host mathematical review and an independently
implemented replay; the frozen automatic checker fails closed on them.

Small N calibration: V(r)=(r^-6-1/2)^2-1/4. The dimer, equilateral triangle,
and regular tetrahedron of side 2^(1/6) attain -binom(N,2)/4, the termwise
global lower bound. This proves global optimality for N=2,3,4 without numerical
search. Virial identity, local minima, database records, and finite-N tests
alone are never global or all-N proof certificates.
