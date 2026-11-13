# G for nine benchmarks — overview (2026-09-25)

Already run: cmt and deepswe. Newly written, never run on any machine: the other seven. Each directory’s G.md ends with an unverified-items list.
Each directory contains `G.md` (five-field record), `objective.ts`, `stand.py` (wraps the official grader without reimplementing decisions), `setup.sh` (idempotent; run on an sdev compute node), and `README.md`.
Shallow clones of official sources are at `/scratch/users/ehz0002/tmp/bench-src/` (skillsbench 1.1G, chembench 1.6G; removable after inspection).

| slug | Tasks | cand | Nodes (→ root) | Official h_r source | level | m | Suggested c/K/T | Enumeration reachability | Grading requirements |
|---|---|---|---|---|---|---|---|---|---|
| cmt (run) | 50 | \boxed text | parsed → equiv | cmtbench LaTeX→SymPy | 0 | Mixed options/integers/∞ | 10/8/60min | 15/50 = 30% | python |
| deepswe (run) | 112 | commit | applies → resolved | Official hidden tests | 0–3 | ∞ | 6/8/120min | 0 | docker, no network |
| gpqa | 198 | Letter A–D | parsed → correct | idavidrein/gpqa run_baseline.py | 0–2 | 4 | **1/0**/15min | 100% when K≥1 | python |
| aime | 60 | \boxed integer | parsed → correct | math-verify 0.9.0 | 0–2 (2=comparison, 10 binary-search steps) | 1000 | 10/2/30min | Nominally 0; small-answer bias lets sequential 0..99 enumeration reach 27% | python |
| chembench | 2785 | [ANSWER] letter set/number | parsed → correct | lamalab chembench prompter._calculate_metrics | 0–3 | Single-choice n, multiple-choice 2^n−1, numerical ∞ | 1/2/10min | 82% of choice tasks, 75% overall | python |
| chemiq | 816 | Integer/SMILES/IUPAC/mapping | parsed → correct | oxpig/ChemIQ answer_verifier (RDKit+OPSIN) | 0–3 | Counting 6–25, others ∞ | 3/8/15min | 226/816 = 28% | rdkit module + outbound network (OPSIN) |
| terminal-bench 2.1 | 89 | Live container | ran → passed | harbor tests/test.sh pytest | 0–3 (3 leaks answers on 11 tasks) | ∞ | 4/6/official timeout | 0 | docker + network; grading inside the solver container (shared) |
| skillsbench 1.1 | 87 | Files in container | verified → passed | verifier/test.sh pytest | 0–3 (3 leaks answers) | ∞ | 6/8/official timeout | 0 | docker + network |
| minif2f | 488 | Lean proof body | stated → compiles → sound | Lean 4.15 + Mathlib, REPL | 0–3 | ∞ | 12/8/60min | 0; one hammer solves 23% of tasks | Lean (compute node) |

## Conclusions from the table

1. **Three grader types, three boundary strengths**: pure functions (gpqa/aime/chembench/chemiq/cmt/minif2f; answers remain in the grading process) > separate containers (deepswe) > shared containers (terminal-bench and skillsbench; hidden tests are visible to the solver during grading, containers have network access, and reference solutions are public on GitHub).
2. **Four benchmarks in the homepage figure primarily measure enumeration**: gpqa 100%, chembench 75%, chemiq 28%, cmt 30%; aime is nominally 0 but has a small-answer prior. Only deepswe, terminal-bench, skillsbench, and minif2f scores are unaffected by Prop enum.
3. **Level 3 gives away answers in three places**: 11 terminal-bench tasks, skillsbench assertions containing expected values, and chembench numerical relative errors. These support upper-bound experiments only.
4. **None requires LLM grading**. Chembench’s LLM fallback parser is disabled; regex parsing failures then score 0 without excluding tasks.
5. **Services runnable on Sherlock**: gpqa, aime, chembench, chemiq, and minif2f (sdev nodes). The three Docker services require the WSL host.
6. Newly found data issues: 30 chemiq tasks may be unsolvable under the official 200-character limit; 12 chembench numerical tasks with target ≤ 0 always score 0; Kimina’s minif2f version changes 19 declarations from DeepSeek’s, not 8; terminal-bench upstream is at 4.0 and scores are incomparable with 2.1; skillsbench’s v1.1 tag was re-stamped, leaving three inconsistent commit hashes.
