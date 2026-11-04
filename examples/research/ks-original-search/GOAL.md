# Frozen original real three-dimensional Kochen-Specker construction search

Use the actual ObjRun engine and only OpenRouter deepseek/deepseek-v4.1-flash.
Primary success is an exact original KS set in R^3 with at most 30 DISTINCT rays,
strictly below the verified 31-ray construction baseline frozen before search.
The 2026 literature review found no smaller verified construction under this
definition. Never reduce the target during the run. Existing or new 31-ray sets
and exclusion of a finite pool are partial outcomes, never primary success.

For every ray x_i is binary. For EVERY exactly orthogonal pair, x_i+x_j<=1.
For EVERY three mutually orthogonal rays, x_i+x_j+x_k=1. This full constraint
system must be UNSAT. All nonzero real multiples represent the same ray;
zero vectors, proportional duplicates, numerical near-orthogonality, abstract
graphs without exact three-dimensional embeddings, extended KS systems and
other dimensions are not accepted. Count every auxiliary ray.

Candidate JSON: {"field_d":2,"vectors":[[1,0,0],[["1/2","1/3"],1,0],...]}
Each coordinate is an exact integer or rational a/b string, or a pair [a,b]
meaning a+b*sqrt(field_d). field_d is a positive nonsquare integer, default 2.
Do not use JSON floats, decimal approximations or symbolic expression strings.
Optional declared_edges are zero-based pairs; each will be checked exactly.
Rational and real quadratic coordinates are supported by the frozen checker.
This is an accepted certificate format and a search strategy, not a claim that
all real embeddings live in these fields. If you find a different exact field,
save its complete certificate as an unaccepted lead; never claim success.

Save immutable candidates under /work/candidates/*.json using atomic rename;
also save the latest promising full candidate at /work/candidate.json. Submit
JSON {"path":"candidates/name.json"}. The host reconstructs all geometry and
the CNF, emits a complete DPLL split/unit UNSAT proof, then a separately coded
SymPy geometry and bitmask SAT implementation reconstructs and replays it.
The protected checker and manifest cannot be edited from the search namespace.
The 31-ray baseline and 40 positive/negative/mutation tests were passed first.

Read /reference/RESEARCH.md, /reference/ck31.json and /reference/baseline-audit.json.
The 49-ray {0,+-1,+-2} pool has a published restricted optimality result at 31;
use it for calibration only. Search beyond it: larger integer/quadratic pools,
exact rotations/unions of KS fragments, cross-product completion, deletion and
replacement, SAT-guided MUS/OCUS, graphs with exact embedding, local changes.
The host seed support code is optional; improve or replace it. A failed finite
pool search never proves a universal lower bound. Do not reproduce tens of TiB
proofs. Use local CPU, preferably at most two CPU workers concurrently to avoid
disturbing other experiments. No purchase, no network in solver namespace.

The sole campaign budget is five hours measured from the FIRST paid API dispatch,
including any paid preflight (none planned). /work/campaign-clock.json records
the immutable start and deadline. There is no fee, token or iteration budget.
Keep random seeds, exact coordinates, code, progress and local solver statistics.
Record actual compute iterations in /work/progress.json, not just plans.
Use background=true for long jobs; keep the program in the foreground of its
bash command, since each command has its own PID namespace. Stop files allow
cooperative termination. Save progress at least every minute. Never busy-poll
job_status; use time to test distinct strategies or reason about actual results.

The host immediately stops when a below-baseline candidate passes full independent
final checks, without waiting for a monitor tick. Otherwise stop all searching
at the original deadline. After it, only final checks of saved evidence are
allowed. Never restart or extend the clock. Never publish results or show keys.
Model proposes/implements algorithms; host supplies infrastructure/checkers;
existing SAT/scientific packages perform computation. Keep attribution separate.
