# Lennard-Jones uniform separation research, fixed ObjRun model

Use only OpenRouter deepseek/deepseek-v4.1-flash through the real ObjRun engine.
Only budget: five hours from first paid dispatch, including prechecks if any.
No paid precheck has occurred. Never reset deadline, purchase compute or publish.

Frozen mathematical problem: N>=2 distinct points in R3; V(r)=r^-12-r^-6;
E=sum_{i<j}V(r_ij); ALL global minimizers; r_min=min_{i<j}r_ij.
Original conjecture is r_min>=1 (body Eq12 in arXiv2511.15008); the abstract's
strict r_min>1 must be reported separately. Read reference paper Sections 2.3,2.5.

Main success: prove an all-N/all-global-minimizers uniform lower bound above
the frozen c_ref in /reference/baseline/reference.json; or prove r_min>=1;
or exhibit r_min<1 with a rigorous global optimality certificate. The printed
.767764041... is .684*2^(1/6). To exclude mere unrounding of known work, the
HOST has frozen the stronger exact implication of the existing proof:
c_ref=2^(1/6) times root of 2a^6+K_old*a^9=1,
K_old=24 integral_.64^infinity theta(w)w^2 dw. c_ref~.768420525585496.
Do not treat reproducing this as a new result.

Read /reference/PROOF_FAMILY.md and /reference/checker/check.py. Host has built
and frozen an exact rational checker for one sufficient family of ball-average
bounds, reconstructing Yuhjtman's subharmonic method. You choose/search improved
parameters or invent another argument. The host family is host contribution;
your searches, selected parameters, explanations and code are model contribution.
Potential improvements: reduce overestimated ball integrals, vary cutoff, exploit
the >=1 relocation comparison already in Vinko/Schachinger, eliminate coarse
constants. Analyze the actual slack, perform useful CPU computations, and save
all successful AND failed attempts. Write a complete PROOF.md and candidate.json.
You may explore geometry, deletion/movement, distance distributions, exact or
interval optimization. Numeric values may suggest but cannot certify results.

Supported candidate:
{"method":"ball_average_v1","a":"0.684","b":"RATIONAL OR DECIMAL",
 "cutoff":"RATIONAL OR DECIMAL","particle_minus_energy":0 or 1,
 "proof_path":"PROOF.md","search_code":"search.py","seed":251115008}

The checker certifies the entire continuum and infinite tail exactly; it is
not a numerical optimization oracle. You can run its read-only copy:
python /reference/checker/check.py candidate.json certificate.json
Then independently test:
python /reference/checker/replay.py certificate.json
The actual host grading repeats both outside your writable directory. Do not
set calibration=true for research; that mode cannot pass the improvement gate.
Submit JSON {"path":"candidate.json"} through ObjRun submit/verify.
Save complete proof and code BEFORE submission. A complete independent success
ends the run immediately, so do not wait for next monitor or aim unnecessarily at 1.
Other methods may be submitted as method=manual with complete proof/certificate;
they require host review and cannot get automatic success.

Local numpy/scipy/mpmath/sympy Python and g++ are available, /work writable,
/reference read-only, network isolated. CPU only; seeds must be recorded.
Do not infer global minimality from a stationary point, local minimum, virial
identity or an improvement over a database. Finite-N evidence is not all-N.
Do not assume arbitrary distance ratios are realizable in R3. Explicitly state
the direction of every relaxation. Check units when reusing data: r=2^(1/6)s,
E=Phi/4 for Phi=s^-12-2s^-6. Standard Cambridge 4*(r^-12-r^-6) has the same
length unit and energy must be divided by four. No database data is preloaded.

Baseline calibrations N=2,3,4 are exact regular simplices and are in
/reference/baseline/small-N-calibration.json. Full original average proof was
reproduced by the host with exact rational Bernstein coefficients. Sources and
access limitations are documented in /reference/LITERATURE.md.

If progress fails, record precise obstacles and failed inequalities. Never
lower the goal to a finite-N/local numerical result. If you improve the bound
below 1, say explicitly: improved uniform bound; original conjecture unresolved.
At deadline no new search or model requests; only host closeout of saved evidence.
