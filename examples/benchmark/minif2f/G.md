# G for miniF2F (Lean 4)

| Field | Content |
| --- | --- |
| **Source** | Paper: [arXiv:2109.00110](https://arxiv.org/abs/2109.00110) (Zheng, Han, Polu 2021; original MIT license). Two ungated Lean 4 sources: **244 test** = HF [AI-MO/minif2f_test](https://huggingface.co/datasets/AI-MO/minif2f_test) @ `5def318348521dfc34875045a9ecddf729a2b49f` (Apache-2.0, corrections by the Kimina team, [Kimina-Prover Preview](https://github.com/MoonshotAI/Kimina-Prover-Preview) @ `7abd61a5`, [arXiv:2504.11354](https://arxiv.org/abs/2504.11354)); **244 valid** = `datasets/minif2f.jsonl` from [DeepSeek-Prover-V1.5](https://github.com/deepseek-ai/DeepSeek-Prover-V1.5) @ `2c4ba911` (AI-MO did not publish valid; DeepSeek is the base version corrected by AI-MO). Total: 488, with globally unique names. Pinned Lean/Mathlib: `leanprover/lean4:v4.15.0`, Mathlib tag `v4.15.0` = `9837ca9d65d9de6fad1ef4381750ca688774e608`, REPL [leanprover-community/repl](https://github.com/leanprover-community/repl) tag `v4.15.0` = `21966799`. Rationale: these are the versions in `lean-toolchain` / `lake-manifest.json` for Kimina's 226 public proofs, which the self-test relies on. |
| **cand** | Complete Lean 4 file text: the official header (`import Mathlib` … `open … Rat`, optional) + the exact official `theorem <name> … := by` + an indented tactic proof body. A ```lean fence is allowed. The grading service takes only the portion after `:= by` for compilation. |
| **structure** | `stated → compiles → sound`, root `sound`. `stated`: the prefix, after removing comments and normalizing whitespace, equals the official header+declaration, and every subsequent nonempty line is indented (`stand.py:split_cand`, a Lean-specific precondition). `compiles`: `not kimina_client.models.is_error(resp)` (no REPL message with `severity=error`). `sound`: `not has_sorry(resp)` ∧ `#print axioms <name>` ⊆ {`propext`,`Classical.choice`,`Quot.sound`} (plus `Lean.ofReduceBool` by default). No fourth `kernel_ok` cell: error-free elaboration already passes the kernel. Bypassing it requires axioms (caught by `sound`) or a top-level `set_option debug.skipKernelTC` (blocked by `stated`). |
| **h_r** | Lean 4 compiler + Mathlib, deterministic. Result-reading functions are official: `is_error` / `has_sorry` / `is_valid` from `kimina-lean-server/client/kimina_client/models.py` ("Valid means no error and no sorry"). Assembly follows `header + formal_statement + completion` in DeepSeek-Prover-V1.5 `prover/lean/verifier.py:verify_lean4_file` (`complete = pass and not sorries`). **No LLM grading**, and none of the 488 questions are discarded. The axiom check is an additional check beyond Kimina, which does not perform it; `native_decide` is accepted by default to match leaderboard conventions. |
| **boundary** | There is no reference answer to hide: the proof is the answer, checked by compilation. Kimina's 226 public proofs reside in grader-side `golden/` for self-tests only; `/problems` does not serve them. However, they are **public on GitHub** (`minif2f_test_solved*.zip`), so disable solver-side `web_search` and set `noSearch` to "Kimina-Prover-Preview minif2f_test_solved". Grading needs neither containers nor networking after installation, but requires a machine that can run Lean (Sherlock compute node; each REPL uses ~3 GB RAM). |
| **budget** | **c=12, K=8, T=60 min**. One grading call is one compilation (5–60 s, timeout 300 s). c is slightly higher than cmt's 10 because Lean naturally involves compiling, inspecting goals, and revising. Twelve checks allow five or six iterations, not a sweep through a 20–30-item hammer list. K=8 matches cmt/deepswe. T=60 min: Kimina samples whole proofs without feedback; the comparison here is with one person receiving feedback, with an hour comparable to the time for one IMO problem. |
| **level** | 0: bit only. 1: failing cell + unclosed goals (`⊢` lines from `unsolved goals` errors and `sorries`, ≤8) + axiom list. 2: adds each error's `line/col` relative to the `theorem` line and its first line. 3: adds raw Lean errors (≤40 messages × 4,000 characters). Everything comes from REPL JSON; the grading service generates no explanations. |
| **m** | **∞** (proof text). N=(K+1)(c+1)+1=118; questions with m ≤ N: **0 / 488 = 0%**. The "hammer prior" still needs disclosure: among Kimina's 197 public test proofs, **45 (23%) are single-line tactics**. At least 45/244 = 18% of test questions can be solved by one `norm_num`/`nlinarith`/`omega`/`interval_cases … <;> omega`. This is a cheap point in the solution space, rather than a small answer space; c=12 limits this tactic. |
| **Known pitfalls** | See below. |

## Structure

```
stated ──→ compiles ──→ sound          sink = sound; checks = 12
```

- Compilation always receives **official header + official declaration + candidate proof body + `#print axioms <name>`** (one REPL command; `env: 0` is the environment after running the header). Altering the declaration is **impossible by construction**. `stated` exposes a readable 0 when the submitted prefix differs, rather than silently compiling a different problem.
- When `compiles` returns 0, `sound` does not run its check. The kernel evaluates in topological order; downstream nodes return `{value:false}` immediately when `feed[0].value !== true`, as in deepswe.
- Each candidate for a problem is compiled once, cached by sha256. All three cells read the same result.

## h_r provenance

| Check | Official code | Location |
| --- | --- | --- |
| Any errors? | `is_error(response)`: `any(m["severity"] == "error" for m in messages)` | `client/kimina_client/models.py` |
| Any sorry? | `has_sorry(response)`: `len(sorries) > 0` | Same file |
| Assembly protocol | `header + formal_statement + completion` → REPL `{"cmd": …}` | DeepSeek-Prover-V1.5 `prover/lean/verifier.py` |
| Axioms | Lean `#print axioms` (`src/Lean/Elab/Print.lean`: `'{name}' depends on axioms: […]`) | Lean core; we only regex-parse that line |

The only **custom** checks are the two in `stated`: string equality after comment/whitespace normalization, and indentation of every nonempty line after `:= by`. The former makes the DeepSeek protocol explicit; the latter follows Lean 4 syntax, where tactic blocks accept only indented lines.

## Answer space and enumeration

| Item | Value |
| --- | --- |
| m | ∞ |
| N = (K+1)(c+1)+1 | 118 |
| Questions with m ≤ N | 0 / 488 (0%) |
| Single-line proofs (197 public Kimina proofs) | 45 (23%) |
| Public proofs using `native_decide` | 11 / 197 |

## Known pitfalls

| Pitfall | Details |
| --- | --- |
| **AI-MO and DeepSeek test declarations differ** | A line-by-line diff finds **19 differences**: 14 corrections listed on the card, plus five unlisted ones (`mathd_algebra_158` adds a cast; `amc12a_2021_p18` changes `/.`→`/`; `algebra_ineq_nto1onlt2m1on` changes `<`→`≤`; two `∏` expressions add parentheses). Scores must identify the AI-MO version; they are not strictly comparable with DeepSeek-Prover test scores. |
| **valid has not been corrected** | All 244 questions follow DeepSeek. The number of unprovable statements is unknown (19 test statements were corrected, so valid likely has a single-digit count too). Treat valid scores as development results only. |
| **Data contamination** | Test proofs are public (Kimina zip and various HF `*minif2f*sols*` datasets); valid is often used for RL training. Report only test on the leaderboard; disable solver networking. |
| **`maxHeartbeats 0`** | The header disables Lean's heartbeat cap, so a single `nlinarith` can run indefinitely. The only limits are a 300 s wall timeout and 8 GB `RLIMIT_AS`. Timeout scores 0 with note `timed out`. |
| **`native_decide`** | Allows `Lean.ofReduceBool`, trusting the compiler. Leaderboards accept it, so it is accepted by default. `TGENGIN_MF2F_STRICT_AXIOMS=1` rejects it, causing 11 public Kimina proofs to score 0. |
| **Golden proofs predate revisions** | Six declarations in Kimina's 2025-04/07 zip differ from AI-MO's 2025-07 version (`mathd_algebra_314`, `aime_1995_p7`, `amc12a_2019_p12`, `amc12a_2021_p22`, `amc12b_2002_p4`, plus one). Self-tests skip them. |
| **REPL v4.15.0 has no `gc`** | Resident REPL memory grows without shrinking; replace it after `MAX_USES=16`. Official Kimina Docker uses `FrederickPu/repl@lean415compat` with added `gc`; we use the official tag for traceability. |
| **Kimina Lean Server cannot be installed on Sherlock** | It imports `prisma`, requiring node and newer glibc, incompatible with CentOS 7 glibc 2.17. The default backend therefore launches its own REPL and vendors only `models.py` (pure Python: pydantic/pygments/colorama/tabulate). |
| **Disk** | Mathlib .olean files require 5–6 GB, plus 1 GB for the toolchain; the 15 GB `$HOME` allocation is insufficient. Actual files live in `$SCRATCH`, which purges files unchanged for 90 days. Rerun setup.sh after a purge. |
| **Dependencies** | elan/Lean v4.15.0, Mathlib v4.15.0, REPL v4.15.0, jq, unzip, Python ≥3.10 (`str | None` syntax), and four pure Python packages. No docker/sympy/rdkit. |
| **Licenses** | miniF2F MIT; AI-MO data Apache-2.0; Kimina Lean Server MIT; REPL Apache-2.0; Mathlib Apache-2.0; DeepSeek-Prover-V1.5 repository MIT, including its data file. |

## Final decisions (2026-09-25)

| Decision | Main-run record | Control arm (separate record; do not pool results) |
|---|---|---|
| Gates | Three: `stated → compiles → sound`; `why` distinguishes an altered statement from a failed proof. | None |
| checks | 12 (`TGENGIN_MF2F_CHECKS` default) | c=4: measure the drop when the hammer list cannot be exhausted. |
| Axioms | Allow `Lean.ofReduceBool` by default, matching Kimina / Seed leaderboard conventions. | `TGENGIN_MF2F_STRICT_AXIOMS=1`, matching AlphaProof's final check. |
| Dataset | Run the 244 corrected AI-MO test questions first. | Run the 244 valid questions after test passes. |
| Stratified reporting | Report questions solved by a single-line tactic as a separate stratum (the Lean form of Prop enumeration). | |

`objective.ts` stays unchanged; environment variables and records capture all these choices.

## Not yet verified

None of the code has been run on the login node. Rereading identified these explicitly **unverified** points:

1. **Whether Lean v4.15.0's Linux binaries run on CentOS 7 / glibc 2.17**. Otherwise, use apptainer (`ml system apptainer`) with Kimina's image. That image uses v4.26.0, which may reject some public Kimina proofs, requiring new version pins and reduced self-test coverage.
2. **Whether `lake exe cache get` still has cached artifacts for the old v4.15.0 tag**. Without them, a full Mathlib `lake build` takes hours and tens of GB of RAM.
3. **REPL v4.15.0 output framing**: assumes JSON followed by a blank line, following Kimina `_read_response`. JSON strings in `pretty` output should not contain raw blank lines (`\n` is escaped).
4. **`#print axioms` returns as a REPL message with `severity: "info"`**, formatted as `'<name>' depends on axioms: [a, b, c]`. The text was confirmed at v4.15.0 `Print.lean` lines 158/160; the message channel has not been run.
5. **REPL `env: 0`** is indeed the environment returned by the header command. The README numbers the first environment 0; Kimina also hardcodes `env = 0`.
6. **`#print axioms <name>` can still find a declaration after an elaboration error**. Lean's error recovery generally adds it to the environment with `sorryAx`. If it cannot be found, `axioms=None` → `sound=0`, and the note contains `axioms: null`; this cannot produce a false 1.
7. **`split_cand` accepts all 226 golden proofs**. Equivalent literal comparisons with awk on the login node gave 220 matches and six differences; Python normalization has not been run.
8. **Kimina backend line offsets**: `_apply_header_offset` shifts only import lines; we then subtract the entire header length. The signs have not been tested.
9. **datasets-server rows API returns the latest revision**. The `/api/datasets` SHA assertion pins the version; the script stops if HF changes the SHA.
10. **pydantic manylinux wheels work on glibc 2.17 in a venv created by `ml python/3.12.1`**. pydantic-core 2.x provides manylinux2014 wheels, so this should work.
11. **Whether 8 GB `RLIMIT_AS` is enough for `import Mathlib`**. Kimina defaults to 8G, making the same assumption.
12. `selftest` defaults to `golden_ids()[:5]`, the first five filenames in sorted order. Their compilation times have not been inspected; some may be slow.

### Status after actual runs on 2026-09-25

- 1: Lean binaries **run** on glibc 2.17, but the toolchain clang does not, so REPL linking fails. Running in apptainer (bookworm) passes.
- 2: `lake exe cache get` still has v4.15.0 artifacts: passed, with 15 s unpacking.
- 3/4/5: REPL framing, `#print axioms` info messages, and header env=0: five self-test questions passed with the expected shape.
- 6: All five sorry controls returned `compiles=1, sound=0`.
- 7: Full self-test of 225 golden proofs: job `minif2f-selftest-all` running.
- 10/12: venv wheels and elan-init arguments passed inside the container.
- 11: With 8G RLIMIT_AS, the first `import Mathlib` took 19.7 s without OOM.

### One change after the full self-test on 2026-09-25: `stated` accepts helper lemmas

Of 225 golden proofs, 211 passed and 14 failed. Eight failures **declare a `lemma` before proving the main theorem**, matching Kimina's output format and Seed-Prover's overall approach.
Three use statements later revised by AI-MO (`amc12a_2019_p12` adds positivity assumptions, `amc12b_2002_p4` changes rational-number notation, and `mathd_algebra_314` adds `: ℝ`).
Two differ only in headers such as `open Real Set`. One (`amc12a_2002_p13`) has the same statement, but the golden proof itself does not compile; its first error remains to be investigated.

Previously, `stated` required **only** the official declaration plus an indented proof body, rejecting the first two categories and making TgEngin systematically incomparable with Kimina / Seed.
The candidate is now split into top-level commands, accepting only four kinds: `import Mathlib|Aesop` (discarded), `set_option maxHeartbeats N` (discarded), `open …` (retained), and helper `lemma`/`theorem` declarations (retained, but may not use the official theorem's name).
The final command must be the exact official declaration + `:= by` + an indented proof body. All other top-level commands (`def`, `axiom`, other `set_option`, `namespace`, `macro`, etc.) are rejected.
Compilation receives the official header + candidate opens/lemmas + official declaration + proof body + `#print axioms`.
Helper-lemma `sorry` or axioms cannot escape: if the main theorem uses them, `#print axioms` exposes them; even unused sorry makes `sorries` nonempty. Either way, `sound` returns 0.

### Final status on 2026-09-25: 220 of 225 golden proofs passed

| Failure | Count | Cause | Handling |
|---|---|---|---|
| amc12a_2019_p12, amc12b_2002_p4, mathd_algebra_314 | 3 | AI-MO revised the declarations; golden proofs use old statements. | `stated=0` is correct; the note says the statement differs from the official one. |
| aime_1995_p7 | 1 | The golden proof has its own `open Real Set` header. Replacing it with the official header, which also opens `Nat` and `Rat`, makes `sqrt` ambiguous between three meanings and compilation fails. | Keep the fixed header (DeepSeek-V1.5 / Goedel protocol). This golden proof is invalid under this protocol. Record a protocol difference; do not change the grading service. |
| amc12_2000_p1 | 1 | Scored 1 after 123 s in the first round; the REPL process died in the second (`repl closed stdout`). | Intermittent grader failure: on `repl died`, judge retries once with a new process; REPL memory cap increased from 8 to 12 GB. |

Thus the actual golden pass rate under this protocol is 221/222 after excluding three outdated declarations. The sole remaining failure is a header-protocol difference.
