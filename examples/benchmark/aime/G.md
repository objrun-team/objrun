# G for AIME 2024–2025

Slug: `aime`. The four contests (2024 I/II and 2025 I/II) contain 60 problems, each with an integer answer from 0 to 999.
Grading extracts an integer from the submission and checks equality with the official answer.

| Field | Contents |
| --- | --- |
| **Source** | MAA's AIME contests (no paper). Statements and answers come from three public Hugging Face datasets pinned by commit:<br>· 2024: `AI-MO/aimo-validation-aime` @ `13f9e12f`, Apache-2.0, parquet; select the 30 rows whose URLs contain `2024_AIME` from 90 problems spanning 2022–2024. Statements come from the AoPS wiki; answers retain the official three-digit notation, such as `"025"`.<br>· 2025: `math-ai/aime25` @ `563bb840`, Apache-2.0, 30 jsonl rows with clean integer `answer` values.<br>· Cross-check: `opencompass/AIME2025` @ `a6ad95f6`, MIT, 15 problems each for I and II. After removing nondigits, all 30 answers must match math-ai problem by problem, asserted in setup.sh.<br>All are ungated and accessible with `curl`. Grader: `math-verify==0.9.0` (PyPI, Apache-2.0; official Hugging Face repository `huggingface/Math-Verify`). |
| **cand** | Text ending in `\boxed{N}`. The service considers only the last 20000 characters and prefers the final `\boxed{}` (math_verify default, `boxed_match_priority=0`), falling back to a LaTeX environment or bare expression when none is present. |
| **structure** | `parsed ──→ correct`, sink = `correct`.<br>`parsed`: the SymPy objects returned by `math_verify.parse(said)` (`src/math_verify/parser.py`) contain an integer N with 0 ≤ N ≤ 999.<br>`correct`: `math_verify.verify(gold, got)` (`src/math_verify/grader.py`) reports equality; an upstream 0 immediately yields 0.<br>These are the two stages of the official rule—an integer answer in the three-digit range, then equality—the same minimal structure used for CMT/DeepSWE. |
| **h_r** | Official rule: integer equality (MAA provides no grading code). The engineering implementation uses Math-Verify's `parse` + `verify`, also used for AIME by OpenCompass `MATHVerifyEvaluator`, lighteval, and Open-R1. **Fully deterministic; no LLM grading; all 60 problems retained.** Alternative: MathArena (`eth-sri/matharena`, MIT; `extract_boxed_answer`, `parse_answer`, and `check_answers` in `src/matharena/parser.py`), the closest AIME counterpart to an official leaderboard grader. It requires a commit-pinned clone rather than a pip package, so this example uses version-pinnable math-verify. Both should agree on integer answers. |
| **boundary** | `aime.jsonl` includes `answer` and resides only in `~/.cache/tgengin-aime/`, read by stand.py; `/problems` removes `answer`. **This is not isolation**, as in CMT: a solver sharing the host can read it with `cat`. Actual enforcement requires a solver `place` sandbox. Grading needs neither containers nor networking and takes milliseconds. |
| **budget** | c=10, K=8, T=30 min/problem (`solveSeconds=1800`). Grading takes milliseconds, so c is about experimental meaning, not cost (see m). Human contests allow 3 hours for 15 problems, or 12 min/problem; 30 minutes with tools is generous. CMT's 60 minutes and DeepSWE's 120 minutes serve research and engineering tasks; AIME needs less time. |
| **level** | 0: Boolean only. 1: add the failure stage (`parse` or `value`) and extracted integer. 2: add whether the official answer is higher or lower (**a leakage experiment**, below). No level 3: an error magnitude or matching digits would disclose the answer. |
| **m** | m = 1000. N = (K+1)(c+1)+1 = 100 < 1000, so **nominal enumeration reachability is 0/60**. The answer prior is nonuniform: 16 of 60 answers are below 100 (27%), and 39 are below 300 (65%). Enumerating 0..99 in ascending order can solve 16/60 without reasoning in N=100 calls. See below. |
| **Pitfalls** | Training-data contamination; a prior favoring small answers; `python_exec` turning counting into brute force; OpenCompass II-5 recorded as `336^\circ`; paraphrased math-ai statements; math_verify timeouts only working in the main thread. |

---

## 1. Source selection

The candidate sources cover 2025, but only one suitable 2024 source provides both an explicit `answer` column and a clear license:

| Dataset | Year | License | Format | `answer` | Decision |
| --- | --- | --- | --- | --- | --- |
| `math-ai/aime24` | 2024 | Apache-2.0 | parquet | **Absent**; embedded in `solution` inside `\boxed{}` | Not used: requires custom answer extraction |
| `HuggingFaceH4/aime_2024` | 2024 | **Unspecified** | parquet | Present | Not used: missing license; itself an AI-MO subset |
| `AI-MO/aimo-validation-aime` | 2022–2024 | Apache-2.0 | parquet | Official three-digit strings | **Used**: the 30 problems from 2024 |
| `math-ai/aime25` | 2025 | Apache-2.0 | jsonl | Integer | **Used** |
| `opencompass/AIME2025` | 2025 | MIT | jsonl | Present, but II-5 is `"336^\circ"` | Cross-check only |
| `MathArena/aime_2025` | 2025 | CC BY-NC-SA | parquet | Integer | Not used: noncommercial restriction |

Problem IDs are `aime-<year>-<I|II>-<number>`. For 2024, extract the ID from the URL: AI-MO sorts URL strings as `Problem_1, Problem_10, Problem_11…`, so row order is unsuitable. For 2025, use math-ai row order (0–14 = I, 15–29 = II). Setup cross-checks every answer against OpenCompass's I/II files and fails an assertion if the order is wrong.

## 2. h_r: why math-verify instead of a custom `int(re.search(...))`

Integer equality is simple; extraction is not. Answers can appear as `\boxed{070}`, `\boxed{70.}`, `\boxed{70^\circ}`, `\boxed{\text{70}}`, `$70$`, "the answer is **70**", or `x = 35 \cdot 2 = 70`. A model may write seven boxed values while reasoning, with only the last being its answer. Every custom extraction decision reduces comparability with other results.

`parse` (`parser.py`) prioritizes the last `\boxed{}`, then LaTeX environments, then bare expressions, converting through ANTLR to SymPy.
`verify` (`grader.py`) tries string matching, numerical comparison within tolerance, then symbolic simplification. Integer-to-integer comparison is numerical equality.

The wrapper adds only a **domain check** between them: the first integer among the parsed SymPy objects (`is_Integer`, or `is_Number` and equal to its `int` conversion) must lie in 0–999. This comes from AIME's rules. The asymmetry of `verify`—accepting an equality chain such as `a+b=70` against a numerical gold answer—is harmless because AIME grades only the final number.

Unsupported grading cases: **none**. All 60 answers are integers; no LLM grader is used.

## 3. m and integer guessing with feedback

### Nominally outside exhaustive enumeration

m = 1000 and N = (8+1)(10+1)+1 = 100. Under a uniform prior, a correctness-only query eliminates one number. N blind guesses succeed with probability N/m = 10%. No problem is exhaustively enumerable under m ≤ N.

### Can correctness feedback support binary search? No

Binary search requires **ordering** feedback: higher or lower. A Boolean verdict gives equality, not one bit of ordering information. Under a uniform prior, an equality test has response entropy H(1/1000) ≈ 0.011 bit, or approximately 1.1 bit over 100 tests. A comparison gives up to 1 bit; 10 comparisons provide log2(1000) ≈ 10 bits, enough to identify any value.

| Feedback | Maximum eliminated per query | Queries to locate one of 1000 values | Blind-guess success with c=10 |
| --- | --- | --- | --- |
| Correct/incorrect only (levels 0/1) | 1 value | ~1000 | 1.1% |
| Higher/lower (level 2) | Half | 10 | **100%** |

Level 2 therefore makes G a guaranteed ten-query oracle rather than merely giving slightly richer feedback. c=10 is sufficient. This level exists to measure leakage and is not used for the formal experiment.

### What makes feedback stronger than pure enumeration?

**Candidates come from the model's posterior**, rather than uniformly from 0..999. On an AIME problem, a model often derives two or three competing numbers because it missed a case, applied mod 1000 differently, or counted half the cases. c checks turn pass@1 into pass@(c+1) over its own leading candidates. In the literature, the AIME gap between pass@1 and pass@k / cons@64 is often around 20–30 percentage points, much larger than the 1.1% blind-guess gain. `why` adds only the distinction between `parse` and `value` failure, helping formatting rather than solving the problem.

### A nonuniform prior makes actual reachability nonzero

The 60 official answers are distributed as follows:

| Range | 2024 | 2025 | Total |
| --- | --- | --- | --- |
| 0–99 | 7 | 9 | **16 (27%)** |
| 100–299 | 11 | 12 | 23 |
| 300–999 | 12 | 9 | 21 |

A solver that performs no reasoning and spends all N=100 guesses on 0..99 solves 16/60. **The nominal reachable fraction is 0%, but prior-weighted reachability is 27%.** This follows from AIME's preference for small answers rather than a defect in G, but the author of G must quantify the possible contribution to scores.

The relevant control is the budget:

| c | K | N | Problems with official answer < N | Prior-weighted reachability |
| --- | --- | --- | --- | --- |
| 10 | 8 | 100 | 16 | 27% |
| 10 | 2 | 34 | 5 (16, 19, 23, 25, 33) | 8% |
| 3 | 4 | 21 | 2 (16, 19) | 3% |

**Recommended formal setting: c=10, K=2**, or compare K=8 against K=2. Results can also separately flag tasks whose submitted numerical candidates increase monotonically as possible enumeration.

## 4. Boundary

- Answers remain on the grading-service side; `/problems` omits `answer`, and the engine seals G in its sealed store.
- **A shared host is not isolation.** The solver can use `cat ~/.cache/tgengin-aime/aime.jsonl`. As with CMT, this is a deliberately limited boundary; full enforcement requires a `place` sandbox.
- Grading requires no container or network. math_verify runs locally in milliseconds; `expectMs=5000` is sufficient.
- Disable `web_search`: AoPS contains all solutions. Listing phrases such as `"AIME 2025 I problem 3 solution"` in `noSearch` is insufficient.
- Define a `python_exec` policy. Keeping it allows brute-force solutions to counting and number-theory problems, making scores incomparable with tool-free MathArena results. Disabling it measures the model's unaided solving ability. Run and report both conditions separately if needed.

## 5. Level

| Level | `note` | Leakage |
| --- | --- | --- |
| 0 | Empty | None |
| 1 | `{stage: parse\|value, read: N, detail}` | None: `read` echoes the submitted number |
| 2 | Add `gold_is: higher\|lower` | Complete: ten binary-search queries suffice |
| 3 | Not implemented | Error magnitude or matching digits can reveal the answer in 1–3 calls |

## 6. Budget

| Control | Value | Rationale |
| --- | --- | --- |
| c | 10 (`TGENGIN_AIME_CHECKS`) | Millisecond grading makes cost negligible; sufficient for 2–3 candidates, not exhaustive enumeration |
| K | 8 (2 recommended for formal runs; see m) | 8 raises N to 100, with 27% prior-weighted reachability |
| T | 30 min | Human contests allow 12 min/problem; 30 minutes with tools is generous |
| `maxBranches` | 4 | Same as DeepSWE |

## 7. Known pitfalls

1. **Contamination:** the 2024 contest (2024-02) appears in recent training corpora; the 2025 contest (2025-02) may also appear in models with cutoffs after mid-2025. AoPS has full solutions and GitHub has many jsonl copies. Disable `web_search` and inspect the 2024/2025 gap as a contamination signal. For fresh problems, consider MathArena's 2026 contests (CC BY-NC-SA; their HF location was not checked here). These tasks measure **whether the engine helps a model correctly use what it already knows**, rather than its capability ceiling.
2. Small-answer priors can contribute enumeration successes unless accounted for above.
3. `math-ai/aime25` paraphrases statements (I-2 differs from the official wording; OpenCompass is closer). They are mathematically equivalent but not verbatim. Use OpenCompass as the primary source and normalize `^\circ` if exact wording is required.
4. OpenCompass II-5 stores `"336^\circ"`; direct `int()` conversion fails, motivating its use only for cross-checking.
5. math_verify's `parsing_timeout` / `timeout_seconds` use `signal.alarm`, which **cannot be used in worker threads**. The service passes `None` and limits submissions with `TAIL=20000`. Extreme inputs may still make ANTLR slow.
6. Dependencies: `math-verify[antlr4_13_2]==0.9.0` (SymPy, latex2sympy2_extended, ANTLR runtime) and `pyarrow` for reading parquet. On Sherlock, use `ml python/3.12.1`, a venv under `$HOME/.cache` (~150 MB), and a pip cache under `$SCRATCH`.
7. Disputed problems: AoPS errata were not checked. No withdrawn problem is known among these 60, but this has not been verified.
8. `task.id` must include `aime-<year>-<I|II>-<number>`; the run-name prefix is arbitrary.

## Unverified assumptions at the time this adapter was written

The code had not run on this machine because Python execution was forbidden on the login node. A source review left the following unverified:

- The `parse/verify` signatures in `math-verify==0.9.0` match the **main branch** reviewed. Its `utils.timeout` explicitly avoids alarms for `None`, and the error message recommends `parsing_timeout=None` in threads; the 0.9.0 tag was not reviewed separately.
- Whether `math_verify.__version__` exists (guarded with `getattr`).
- Whether `parse()` returns `Integer(70)` for `\boxed{070}`, a Float satisfying `e == int(e)` for `\boxed{70.0}`, and `Integer(1000)` for `\boxed{1000}`, rejected by the domain check.
- Whether `verify(gold, got)` can return True despite `integer_of(got) != gold` because another element in `got` matches gold. The self-test covers only gold, gold+1, no integer, and out-of-range cases.
- The result type from `ExprExtractionConfig()` for bare numerical gold strings such as `"70"` and `"25"` (expected: Integer).
- Whether `ml python/3.12.1` works in a noninteractive `set -eu` shell on a Sherlock compute node. Recorded experience suggests it sometimes does not; fallback python3 is 3.6, which the script's version assertion rejects. Availability of a manylinux2014 pyarrow wheel for CentOS 7 / glibc 2.17 / Python 3.12 is also unverified.
- The 30 selected 2024 rows and string-valued answers in AI-MO's parquet were inspected through datasets-server on main at the pinned commit, not by reading the parquet directly.
- math-ai row order is I 1–15 followed by II 1–15; setup asserts alignment with OpenCompass's two files, but that assertion had not run.
- Engine `input.result` shapes (`{body}` or string) and `feed[0].value` usage were copied from DeepSWE, not checked against the current engine version.
- Thread safety of math_verify's `parse_latex_cached` LRU cache under `ThreadingHTTPServer`.
- Sorting `/problems` by (year, contest, number) depends on string order `"I" < "II"`; the 2024 problem number is indeed an integer extracted from the URL.
