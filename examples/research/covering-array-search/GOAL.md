# Frozen covering-array experiment

Find a complete CA(N;3,24,2) with N < 21. N is the number of rows,
k=24 columns, v=2 symbols {0,1}; EVERY set of three distinct columns
must contain ALL eight ordered triples at least once. No wildcards,
unknown cells, approximate coverage, or sampled checking can pass G.
Write one row per line, 24 whitespace-separated binary integers, no header.

The explicit reference CA(21;3,24,2) is the first 24 columns of the
CA(21;3,25,2) from Dwyer's CA_Database / Torres-Jimenez construction,
archived by ca-tools. Both reference arrays have been exhaustively checked.
The available live table (ca-tools commit 392d8c9e89e114d9754ca48d92031be3914e4218,
retrieved 2026-10-30) and CAs November-2024 snapshot both give N=21 here.
This is an improvement-of-reference experiment. A smaller valid array is
NOT automatically a current world record and does NOT prove optimality.
Hiess & Kampel arXiv:2510.17596 prove CAN(3,k,2)=18 for k=17..20,
and CAN(4,18,2)=36; these cases are excluded. No optimality proof for
the selected (3,24,2) was found in the checked sources.

Only the absolute five-hour campaign deadline limits the formal search.
There is no experimental cost, output-token, call, iteration or restart cap.
OpenRouter's native service/context limits still apply and are logged.
The only allowed model is OpenRouter deepseek/deepseek-v4.1-flash.

You are running inside the real ObjRun engine. Use its tools to inspect the
reference, generate programs, execute them, read real outputs, call verify,
and revise programs/search strategy based on actual missing triples. Do not
finish with a plan. Start with a deliberately row-deleted reference candidate,
ask verify for its actual defects, then use that evidence to choose repair.
Available: Python, NumPy, SciPy, Numba, SymPy, OR-Tools, python-sat, g++.
Only /work is writable; /reference is read-only; there is no network.

Suggested starting routes: delete each possible row from different 24-column
projections of CA_21_3_25_2.txt; repair with incremental missing-tuple counts,
tabu search, annealing and diverse seeds. Or extend CA_20_3_23_2.txt with a
24th column and jointly repair. Structured constructions, SAT/CP-SAT, mixed
multi-cell moves and unbiased restarts are also allowed. These suggestions
come from the experiment preparer, not from the solver model. You decide
which to implement and revise based on measured progress.

Persist every program revision and its seed/configuration in /work/history/.
Append decisions to /work/decisions.jsonl: observation, chosen strategy,
reason, code filename/hash, seed, result. Maintain /work/progress.json with
target N, actual iterations, missing count, seed, checkpoints, timestamps.
Never invent progress. Distinguish your planning decisions from numerical
search steps done by the algorithm. Model sampling seed is not guaranteed
by the provider; log algorithm seeds explicitly.

For long computation use run_command background=true, checkpoint regularly,
and use job_status. Keep useful computation running while analyzing feedback.
Use considerate CPU concurrency (the host has other experiments); this is an
isolation precaution, not a campaign search budget. Preserve complete
candidate arrays atomically in /work/candidate.txt and /work/candidates/.
The host independently checks changed candidate.txt files. Other candidate
files can be checked using verify with answer='{"path":"candidates/name.txt"}'.
The verifier returns missing-triple counts/witnesses. Only zero missing triples
with valid dimensions/alphabet and independent agreement is a valid CA.

When valid below the current frozen threshold, call submit with the JSON path
descriptor. The host saves immutable array bytes and both verification reports
BEFORE publishing a new goal below the verified N. Continue in the SAME
original deadline; success and failure do not reset time. A run that fails to
find an improvement is not a non-existence proof.
