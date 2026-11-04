# Frozen experiment: degree-7 fully symmetric positive interior prism cubature

Find fewer nodes than the reproduced 36-node Diallo–Worku construction.
The domain is D = {(x,y,z): x>-1, y>-1, x+y<0, -1<z<1}.
The weight function is exactly 1 (Lebesgue measure); volume is 4, not 1.
Exactness target: EVERY polynomial of TOTAL degree at most 7.
Full symmetry means ALL permutations of triangle barycentric coordinates
(-(x+y)/2,(x+1)/2,(y+1)/2), independently combined with z -> -z,
with identical weight at transformed nodes (S3 x C2). This is the author's
affine triangle symmetry, not merely x/y interchange.

Initial task: N <= 35 distinct nodes. A 35-node rule is ALREADY known (Witherden–
Vincent and Jaśkowiec–Sukumar data). It beats this specific 36-node paper
construction, not the checked prior best. N <= 34 would improve on the checked
references, but is not automatically a world record. No proof of minimality
or exhaustive state-of-the-art search has been made.

Pinkse 2609.26840 / PositiveWeightQuadratureSolvers.jl concerns Gaussian measure
on R^d and uniform [0,1]^d, sometimes with LESS symmetry. These are not prism
comparators. Its numerical solver ideas are useful, its counts are not the
same constrained problem. Do not relax domain, degree, weight or symmetry.

## Fixed numerical acceptance G

Submit a JSON file {"domain":"prism","degree":7,"nodes":[["x","y","z","w"], ...]}.
All four entries MUST be decimal strings, preferably with >=70 significant digits.
G runs on the host, outside your writable filesystem. It checks:

* All 120 Cartesian monomials x^a y^b z^c, a+b+c<=7, at 100 decimal digits;
  maximum absolute moment error <= 1e-40.
* Strictly positive weights; strictly interior nodes; no duplicate nodes
  (maximum-coordinate separation must exceed 1e-35).
* All 12 weighted S3 x C2 transformations, with bijective matching to 1e-40.
* An independent stdlib Decimal implementation at 110 digits checks all 120
  monomials in u=(x+1)/2, v=(y+1)/2, z, and symmetry generators independently.
* Current node threshold, fixed separately for each task before its execution.

Passing only establishes a high-precision NUMERICAL construction. An exact
formula would require an additional rigorous proof or certificate, absent here.
All thresholds, tolerances, domains and degrees are immutable during a task.
After saving a success, the controller publishes N strictly below the new best
and keeps the SAME absolute five-hour deadline.

## Available material and arithmetic

/reference/diallo-prism-q7-n36.json and the author's compact/expanded originals
are the reproduced starting rule. The prior 35-node coordinates are deliberately
not supplied as search initialization. Do not claim novelty at N=35.
You must write and improve the actual search program, choose orbit structures,
initializations and seeds, and invoke mature numerical solvers (SciPy, mpmath).
No search program is prewritten for you. NumPy, SciPy, mpmath, SymPy, g++, bash
are available. Python is the isolated environment's python on PATH.

A useful full moment identity in simplex coordinates is:
integral_D u^a v^b z^c = 0 for odd c, otherwise
8*a!*b! / ((a+b+2)!*(c+1)). Cartesian moments follow by binomial expansion.
You may optimize any equivalent reduced invariant/orthogonal basis, but G tests
the full bases. Use double precision for discovery and arbitrary precision for
polishing; a small binary64 residual alone does NOT pass G.

## Execution and trace

Use run_command (bash, background=true for long work), job_status, verify and
submit through the real ObjRun loop. /work persists; /reference is read-only;
no network or credentials are exposed. Each process has the campaign deadline.
There are no campaign cost, output-token, request-count, round or search limits.
Native service context/output limits still apply. Reasoning is configured high.

Save every promising candidate, source version and seed in /work. Use atomic
replace for candidate.json and progress.json. The latter should contain method,
orbit structure, seed, restart/evaluation counts, best residual and bottleneck.
Maintain decisions.jsonl: record your decisions separately from solver name,
solver tolerances, evaluation counts, elapsed solve time and solver outcomes.
Never overwrite a discovered better candidate with an inferior one.

Call verify with answer='{"path":"candidate.json"}'. If it passes, immediately
call submit with the EXACT same descriptor; the controller saves evidence before
starting the harder target. Do not merely report success in prose. Continue
scientific work until the original deadline, even after the first success.
Use the prior work files after recovery; never reset the five-hour clock.
