# Computer-assisted existence certificate

The fixed problem is F(X)=sum(i,j)(xi·xj)^4−36 on 24 unit vectors in R^6.
The author reference, transposed from Zenodo version 2, is normalized separately
and exactly for the comparison; no variable weights are introduced.

The candidate near the supplied coordinates has energy
0.123748845780637877497603007553786270370673609822803.
The feasible author's reference has energy about 5.872576472834084e−12.
All inequalities below were evaluated with outward-rounded Arb ball arithmetic.

Let a be the exact dyadic base stored in certificate.witness.json, and let R be
the 144 by 15 matrix whose columns are the common elementary infinitesimal
rotations applied to a. The variables y=(x,lambda,mu) have dimensions 144+24+15.
Use the polynomial system

    grad E(x) − N(x) lambda + R mu = 0,
    (1 − xi·xi)/2 = 0   (i=1,...,24),
    R^T(x−a) = 0.

Here E=F+36 and N has each xi in its own disjoint six-row block. Its symmetric
Jacobian has upper-left block H_L=Hess E−diag(lambda_i I6), upper-right blocks
−N and R, and their transposes below.

The exact dyadic center c, approximate inverse C and congruence matrix Q are
saved as integer pairs [m,e], denoting exactly m*2^e. Thus witnesses do not rely
on interpreting a rounded decimal as exact. The box radius is r=2^−180 in every
one of the 183 coordinates. The creator used 180 decimal digits; a separate
verifier, with a different block construction of the Hessian, used 220 digits.
The independent verifier found the conservative bounds

    ||I − C J(box)||_infinity < 1.310e−49,
    ||C f(c)||_infinity < 3.176e−179,
    ||C f(c)|| + ||I−CJ(box)|| r < 8.548e−104 < r.

Therefore y -> y−C f(y) maps the box strictly into itself and is a contraction.
C is nonsingular: ||I−CJ(c)||<1 implies CJ(c), and hence C, is nonsingular.
Banach's fixed-point theorem supplies a unique zero of the polynomial system
inside this box. This establishes existence, not just a small residual.

For Rot(x), the rotation-generator matrix at x, the verifier independently
certifies invertibility of R^T Rot(x) throughout the box by a Neumann bound
smaller than 6.940e−54. At the KKT zero, dotting stationarity with Rot(x)
annihilates both grad E (rotation invariance) and N lambda (tangency of rotations).
Thus Rot(x)^T R mu=0 implies mu=0. The zero is a true constrained stationary
point of the original problem, with all 24 norms exactly one.

To establish positivity on the entire tangent slice, form

    A = H_L + 100 N N^T + 100 R R^T.

The verifier certifies Q nonsingular via ||I−Q^TQ||_infinity < 1.819e−14.
Every diagonal of Q^T A Q exceeds the sum of absolute off-diagonal entries,
with a rigorously positive minimum margin greater than 0.06681270600967.
Symmetry and Gershgorin therefore imply A is positive definite on R^144.
For every nonzero u with N^T u=0 and R^T u=0, u^T H_L u=u^T A u>0.
These are all 105 slice directions. Invertibility of R^T Rot(x) proves that
the slice is transverse to the 15-dimensional common-rotation orbit. The
second-derivative test on this smooth slice yields a strict local minimum
modulo rotations, and hence a local minimum on the FULL product (S^5)^24.
The common rotations make it non-strict as a minimum in raw coordinates.
No eigenvalue threshold was used to remove extra directions in this proof.

Finally, the box evaluation encloses the stationary energy in

    [0.123748845780637877497603007553786270370673609822803 +/- 5.67e−52],

while an interval evaluation of the explicitly normalized author's rows is
below 5.873e−12. This strict comparison proves non-globality without any claim
that the reference is an exact zero-energy design or a global optimizer.

Numerical cross-checks are separate: checker.py verifies all 120 tangent
dimensions, removes only the rank-15 geometric rotation span, reports a minimum
quotient eigenvalue approximately 0.07710913323, and tests soft and random
geodesic perturbations. These checks alone would not establish existence.

Attribution and scope: random restarts and model decisions ran through the real
ObjRun engine using only deepseek/deepseek-v4.1-flash. The host prepared the
search support and independent numerical checker; the host also constructed
this interval certificate and its separate verifier. Model-written refinement
and analysis artifacts are recorded separately. The result is not evidence of
a causal framework advantage, a classification of the landscape, or a claim
of novelty relative to all existing literature. It is a reproducible
computer-assisted proof, conditional on the documented arithmetic/software and
the explicit mathematical argument above; it is not a Lean/Coq formalization.

Reproduce with the run's controller-env Python:

    python verify_certificate.py certificate.witness.json author-reference.json --output replay.json

Every proof-package file is covered by manifest.json. The original numerical
checker and GOAL.md remain covered by the earlier frozen-g.json.
