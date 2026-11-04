# Five-stage third-order Williamson 2N search

Use the existing ObjRun engine and exactly OpenRouter deepseek/deepseek-v4.1-flash.
You are the algorithm designer: propose, implement and revise CPU numerical searches.
Do not merely describe a plan. There is one unextendable five-hour deadline from
the first paid request, no monetary/token/iteration campaign budget. Numerical
loops belong in programs; do useful CPU work between infrequent model decisions.

Read /reference/baseline.json and baseline-audit.json first. The paper's Table 8
Butcher a51 is inconsistent; the authoritative baseline here is reconstructed
exactly from the published low-storage recurrence, independently checked by NodePy.
Never optimize against the erroneous printed tableau.

Preserve exactly five RHS stages and the recurrence
delta_i = alpha_i delta_(i-1) + h f(t+c_i h,y_(i-1));
y_i = y_(i-1) + beta_i delta_i, alpha_1=0.
Reconstruct c=A*1 from the recurrence. No extra solution-sized registers/stages.
Fix EVERY coefficient of the reference stability polynomial, degree zero to five.
Satisfy all rooted-tree order conditions through order 3, including b*c^2=1/3.
Minimize the order-four error-vector Euclidean norm in the NodePy convention:
(b*c^3-1/4)/6, (b*A*c^2-1/12)/2, b*(c*(A*c))-1/8,
b*A*A*c-1/24. The order of components does not affect the norm.

The frozen host verifier uses independent forward recurrence and backward
conversion implementations at 100,160,180 digits. Each order/polynomial residual
must be <=1e-50. Improvement must exceed max(1e-25,100*numerical uncertainty).
Double-precision candidates need high-precision polishing before acceptance.
If possible, find rational or algebraic representations and rigorous certificates.
Any algebraic certificate must identify a particular real solution and prove
the complete constraints, not merely give equations with an approximate root.
Study internal error amplification and coefficient conditioning as secondary
diagnostics. They do not replace the frozen primary objective. Do not claim every
ODE improves. A separate frozen nonlinear ODE set is withheld from optimization.

Candidate schema: {"schema":"williamson-2n-v1","stages":5,
"alpha":["0","...","...","...","..."],"beta":["...","...","...","...","..."]}.
Every coefficient is a finite decimal or fraction STRING. Save high precision.
Use atomic temporary-file rename for /work/candidate.json. Keep every best,
seeds, executable source and append-only numerical trajectory in /work.
Write /work/progress.json with starts, evaluations, objectives, residuals,
running algorithm, seed, and latest checkpoint time. Long jobs: background=true.
Submit {"path":"candidate.json"} to the engine's verify/submit mechanism.
The host also independently audits changed candidate.json every minute.
The checker itself is outside your writable filesystem. It reconstructs the
Butcher tableau ONLY from saved alpha,beta, never trusts supplied metrics.

References: DOI 10.1007/s10543-026-01139-3, RK-Opt and NodePy. Their pinned
sources are supplied read-only. Improving this illustrative example does not
establish a new literature best or establish that ObjRun beats other frameworks.
Do not optimize the held-out ODE suite; it is evaluated only after search.
If the theoretical error-norm floor is reached, use the remaining time to
seek exact representations, certify the floor and improve conditioning/internal
amplification on that optimal manifold. Do not waste API calls repeatedly polling.
