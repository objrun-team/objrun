# Round 2: resolve the Lennard-Jones global-minimum separation conjecture

Fixed model: OpenRouter deepseek/deepseek-v4.1-flash, real ObjRun engine.
Only budget is five hours from this round's FIRST paid dispatch, including any
paid preflight. There is no cost/token/iteration campaign cap. No paid preflight
was made. Do not reset/extend the absolute deadline or purchase compute.

Frozen definitions: every integer N>=2, N distinct points in R3,
V(r)=r^-12-r^-6, E=sum_{i<j}V(r_ij), ALL global energy minimizers,
r_min=min_{i<j}r_ij. This is finite N with unbounded N, not an infinite lattice.

PRIMARY SUCCESS (one of these, independently checked):
A. Prove r_min>=1 for all such configurations (the paper body Eq12).
B. Exhibit r_min<1 in a finite N configuration AND a rigorous GLOBAL optimality
   proof for that exact configuration, excluding every competitor in R3.
A stronger all-N proof r_min>1 also counts but must be stated separately.
Failure to establish the strict version does not invalidate a valid >=1 proof.

Improving a lower bound below1 is SECONDARY ONLY and must not terminate this
round successfully. Local minima, stationary points, virial identities, beating
database energies, finite collections of N, or numerical optimum estimates are
NOT primary success. Keep all counterexamples to candidate lemmas and failed
approaches, explaining exactly what quantifier or condition failed.

PRIOR ROUND: host/model independently certified
r_min >= (347/500)*2^(1/6) ~.778988661526704849. This did NOT resolve either
conjecture. Prior frozen literature baseline was the unrounded implication of
Yuhjtman's proof, c_ref~.768420525585496046 (published display .767764).
Read /reference/prior-round/proof/PROOF.md, /reference/PROOF_FAMILY.md,
/reference/LITERATURE.md, and arXiv2511.15008 Sections2.3/2.5 (HTML and text).
Prior exact checkers and source PDFs/text are retained read-only. Their
ball_average_v1 certificate family only proves bounds below1; do not waste this
entire round tuning that family as if it solved the primary conjecture.

Research directions (not assumptions):
- Use genuinely global optimality: single/multiple-particle movement or deletion
  plus reinsertion comparisons; finite cluster energy subadditivity; supporting
  hyperplanes; removal of close pairs; scaling or local stress constraints.
- Combine geometric exclusion/packing and distance distributions, explicitly
  respecting 3D realizability. Every relaxation direction must be justified.
- Assess stronger necessary conditions (gradient/Hessian plus global move).
  A conjectured inequality for all stationary configurations is usually too
  strong: produce a failure example before relying on it.
- If building interval certificates, cover complete domains including arbitrary
  N and tails. Exact polynomial checks certify ONLY their stated inequalities;
  they do not certify the logical reduction or global minimality by themselves.
- An analytic reduction to a finite certificate is valuable, but only a full
  justified reduction plus replay can resolve the conjecture.
- If one route has a demonstrated obstruction, document it and change route;
  do not repeatedly re-run equivalent scalar optimizations.

Every20-30 minutes of useful work, save RESEARCH_LOG.md with approaches,
proved lemmas, unproved steps, failures, next action, and results. Use background
jobs with checkpoints for long computations; use the foreground command itself,
not nohup/& (private PID namespace exits otherwise). Seeds must be saved;
deterministic search should be explicitly recorded. /work is writable;
/reference read-only; local numpy/scipy/sympy/mpmath and g++ available.

SUBMISSION SCHEMA candidate.json:
{
 "claim_type":"proof_ge_1|proof_gt_1|counterexample|improved_bound|partial_lemma|obstruction",
 "statement":"exact quantified claim, including units and scope",
 "method":"manual" or "ball_average_v1",
 "proof_path":"PROOF.md",
 "files":["supporting-code.py","certificate.json","coordinates.json"],
 "unproved_steps":[],
 "seed":"... or deterministic",
 "...":"for ball_average_v1 also include its original a,b,cutoff,particle_minus_energy"
}
Submit/verify {"path":"candidate.json"}. The protected host checker snapshots
all files and fails closed: a schema-complete claim is NOT a verified theorem.
For arbitrary new proofs the host independently reviews the mathematics and
implements/replays the required certificates outside your writable directory.
You cannot self-issue a primary success receipt. Continue productive independent
work while awaiting review, until the host validates primary success or deadline.
Do not execute model-generated verification code on the host directly.

Primary success stops immediately (no need to wait15 minutes or use five hours).
After deadline no new requests or research computation, only host verification
of saved evidence, report, cost reconciliation and owned-process cleanup.

Units: in Yuhjtman's Phi(s)=s^-12-2s^-6, r=2^(1/6)s and E_user=E_Phi/4;
the target r=1 means s=2^(-1/6), not s=1. Standard Cambridge4V uses same r,
energy /4. Do not assume published data is globally certified. Distinguish host
proof/checker contributions from your discoveries and programs. No publication.
