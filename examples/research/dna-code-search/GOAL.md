# Short DNA code construction: n=10, d=4, GC=5

Run the scientific search autonomously using the configured OpenRouter DeepSeek
V4.1 Flash model and the actual ObjRun propose/execute/verify/revise loop. The
only campaign resource budget is five hours elapsed time, starting at launch.
There is no money, token, request-count, search-count, iteration or CPU quota.

## Primary frozen construction profile

Produce an explicit set of DISTINCT uppercase DNA strings, each of length 10:

1. Each word has exactly five G or C bases.
2. Hamming distance is at least four between every pair of DISTINCT words.
3. No word contains two length-three substrings where one is the reverse
   complement of the other. Include overlapping substring pairs, exactly as
   the author's CheckFSS algorithm. Longer such stems are thereby excluded.
4. The whole set is closed under reversal and Watson-Crick complement
   (A<->T, C<->G), and hence also reverse complement.
5. The initial success threshold is STRICTLY MORE THAN 676 words.

These are the properties of the reproducible Table 4 construction, not a
claim to satisfy the stronger literal all-pairs R/RC inequalities in the paper.
The human explicitly selected this interpretation after the discrepancy was
explained. Never weaken these frozen properties or claim a strict R/RC record.
After success the controller may publish a new task with a higher threshold,
within the SAME original five-hour deadline, to continue improving the result.

## Sources and baseline

Wang, Liu and Chen, arXiv:2409.06519, Table 4 and Algorithms 2/4.
Source data: https://doi.org/10.5281/zenodo.13369169
The original GF(4) [10,6,4] generator was independently enumerated. Filtering
to GC=5 gives 1008 words; adding CheckFSS gives 676. The latter is independently
checked by two implementations. Both published sets contain x and reverse(x),
so their literal all-pairs reverse distance is zero. For example AAAAACCCCC and
CCCCCAAAAA occur together. The experiment will report this audit separately.

The reference codewords and original Magma programs are available read-only
under /reference. You do not need Magma: Python numpy/scipy/numba/sympy/ortools
and g++/make are installed. /work is writable and persistent across calls.
The container has no credentials and no external network. The sources supplied
are sufficient for this constructive search; the host checker is outside it.

## Execution and evidence

Use the run_command tool for shell commands in the container. It supports
background jobs; job_status retrieves their logs without interrupting them.
For a long search, run in the background, write atomic checkpoints, and inspect
progress. All processes end at the same campaign deadline. Do not confuse a
numerical/statistical heuristic with the final integer checker.

Keep source code, random seeds and the best candidate in /work. Write the best
known set to candidate.txt (one word per line), using an atomic file replace.
Write progress.json for human monitoring, with observed size, search method,
seed, elapsed time and current bottleneck. This progress is self-reported;
only the separate verify tool establishes validity.

Call verify with answer equal to the JSON string {"path":"candidate.txt"}.
The checker reads a snapshot of the file and reports its hash and concrete
constraint failures. You may verify partial candidates as often as useful.
After an accepted verification, submit the same JSON string. Keep the artifact
unchanged until submission has been checked again. A text claim of success,
runtime estimate or code that could generate a set is not a witness.

Potential approaches include extending/replacing orbits in the baseline,
other GF(4) code/coset constructions, greedy construction with local exchanges,
and independent-set optimization over reversal/complement orbits. The whole
GC=5 pool has 258048 words before FSS filtering. Avoid a naive all-pairs dense
graph if it costs too much; implicit neighborhoods and compiled loops may help.
These are suggestions, not mandated methods. Use the entire available time
productively and revise the algorithm based on actual results. Preserve even
negative or partial results with exact labels. Do not claim a current world
record: the comparison target is the frozen, reproduced 2024 construction.
