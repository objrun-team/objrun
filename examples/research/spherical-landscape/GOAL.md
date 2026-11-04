# Fixed experiment: spherical (2,2), real d=6, n=24

Find a non-global local minimum of F=sum_ij <vi,vj>^4-36 on (S^5)^24.
All 576 ordered pairs, including diagonal, are included. No weights, no change
of dimension or number of vectors. Paper §2 gives c=3/(6*8)=1/16.
Example 5.2 motivates this experiment but does not prove the desired result.

Use only OpenRouter deepseek/deepseek-v4.1-flash. The sole campaign budget is
five hours from the FIRST paid dispatch, including any model preflight. It is
absolute, persistent, and cannot be reset or extended. No fee, token, iteration,
or branch budget is imposed. Numerical convergence criteria are allowed.

The author reference is reproduced from Zenodo 8126277, real_equal_norm,
t=2,d=6,n=24. Read /reference/reproduction.json and author-reference.json.
The host checker is independent of search code and inaccessible to model writes.
Coordinates use JSON {"vectors": [[6 numbers], ... 24 rows]} (transpose of V).
Save every candidate, seed and trajectory under /work/candidates. Atomic writes.
Submit JSON {"path":"candidates/filename.json"} to request independent validation.

Frozen numerical criteria: unit error <=1e-12; Riemannian gradient Frobenius
norm <=1e-9; complete 120-dimensional constraint tangent Hessian; quotient only
the actual span of common skew-symmetric rotations (normally rank 15), NEVER
remove eigenvectors just because eigenvalues are small. Strict numerical evidence
requires minimum quotient eigenvalue >1e-6 and F-reference_F >1e-8. A quotient
eigenvalue <-1e-7 rejects a minimum. |lambda|<=1e-7 is a nonrotational near-zero
mode requiring higher-order investigation. Intermediate cases are unresolved.
Check +/- negative, near-zero, five softest and 32 seeded random quotient
directions at geodesic step sizes 1e-4,1e-3,1e-2,.1; reject reliable descent.
Also re-optimize perturbed starts to detect premature termination; record outcomes.

Refine the most promising non-global candidate using >=80 decimal digits, and
check residual stability at a higher precision. If a positive quotient gap exists,
attempt interval Newton/Krawczyk or exact reconstruction. A float Hessian and
failed perturbation searches are numerical evidence only, NEVER a proof.
If extra zero modes remain, use higher-order reduced analysis; leave unresolved
if incomplete. A rigorous proof must establish stationary-point existence and
positive transverse curvature, and exhibit a strictly lower energy configuration.
Do not infer nonexistence from unsuccessful restarts. Do not claim framework
superiority, publish, access secrets, change the checker, or touch other runs.

Use local CPU, one BLAS thread per job; begin with the supplied solver and then
make substantive model-guided decisions about starts, structures, refinement and
certification. Repeated numerical work belongs in programs, not repeated model
calls. /work is persistent, /reference is read-only, network is disabled for tools.
All tool descendants terminate at the original deadline. Continue investigating
even after a numerical candidate passes; improve evidence rather than stopping.
