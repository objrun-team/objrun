# G for ChemBench

| Field | Content |
| --- | --- |
| Source | Paper: arXiv 2404.01475 (Nature Chemistry 2025). Code: https://github.com/lamalab-org/chembench pinned to `45f8bad062fe552810c52be3a328d5da8597ed30` (2025-09-11, v0.3.0). HF dataset `jablonkagroup/ChemBench` pinned to `6e1d25748952393f44e35b8e85bbe567246a6430` (2026-04-22), **not gated**, MIT. **2,785 questions** (the paper says 2,786; the repository has 2,788 reports): 2,542 choice questions (2,148 single-answer, 394 multiple-answer) + 243 numerical questions. Nine topics: analytical 152, chemical_preference 1,000, general 149, inorganic 92, materials 83, organic 429, physical 165, technical 40, toxicity_and_safety 675. |
| cand | **A text string**. The official format places the final answer inside `[ANSWER]…[/ANSWER]`: comma-separated uppercase letters for choice questions (`[ANSWER]A,C[/ANSWER]`); a number for numerical questions (`[ANSWER]5.8e-3[/ANSWER]`, decimal point, no units). The grading service runs the official parser on the entire submission, so it may contain reasoning followed by the tags, or just the tags. |
| structure | `parsed ──→ correct`, sink = `correct`. `parsed`: the official parser extracted an answer (`prompter.prepare_mcq_answer` + `utils.run_regex(create_multiple_choice_regex)` / `prompter.prepare_general_answer`, with `llm_extractor=None`). `correct`: `metrics["all_correct"] == 1`, as computed by `prompter.BasePrompter._calculate_metrics`. These are the two stages of the official `_process_single_result`, exposed separately: a minimal structure like cmt/deepswe. |
| h_r | **Choice questions**: `metrics.classification_scores` computes `hamming = (missing + extra selections) / number of correct choices`; `all_correct = hamming == 0`. The selected letter set must **exactly equal** the set with score 1 in `target_scores` (`prompter.py`, `_calculate_metrics`). **Numerical questions**: `metrics.mae = abs(found − target)`; `all_correct = mae < tolerance`; `tolerance = task._relative_tolerance`. This field is absent from the HF dataset, so it always defaults to `0.01 * float(target)`. Despite being called relative, the implementation requires **absolute error strictly less than 1% of the target value**; reproduced unchanged. Both checks are deterministic. **Two official model-dependent features are excluded**: (1) LLM fallback extraction when regex parsing fails (paper A.8 / Table A7: used for 0–2.4% of responses from format-compliant models, 24% for GPT-4o ReAct). Here `llm_extractor=None`, so parse failures score 0. **No questions are discarded on this basis: the discarded-question count is 0**; only this leniency is removed. (2) Keyword + BERT refusal detection (`refusal.py`, requires torch/transformers) is excluded. Refusals generally cannot be parsed and still score 0. The difference concerns official false positives: responses containing answer tags that are classified as refusals score 0 officially but are graded here. This favors the solver by <1%. |
| boundary | Answers are in `~/.cache/tgengin-chembench/chembench.jsonl`, read **only by stand.py**. `/problems` serves statements assembled with official templates, without `target`/`target_scores`. Choice texts are necessarily included as part of the question. Grading requires neither containers nor networking: pure Python (numpy / pint / fastcore / loguru / typing_extensions), at millisecond scale. As with cmt, this is **not isolation**: a solver with bash access on the same machine can cat the question bank. |
| budget | **c=1, K=2, T=10 min**. c=1: grading takes milliseconds, so cost is irrelevant; however, 40% of choice questions have only two options, and each query eliminates one, so extra queries amount to enumeration. K=2: restarting after marking a node dead is also an enumeration step. T=10 min: questions involve single-step knowledge or one calculation; the official setup uses one question/response. Ten minutes is sufficient for an agent with tools (RDKit, PubChem). Compare cmt c=10,K=8,T=60 and deepswe c=6,K=8,T=120: this benchmark is constrained by its small answer space, not slow grading. |
| level | 0: bool only. 1: adds whether failure occurred at parse or grade, and what the official parser extracted from the submission (echoes the solver's own answer, without revealing GT); a parse failure explains the format. 2: adds `options_expected / options_given / wrong_count` for choice questions; `direction` for numerical questions (too high / too low, enabling bisection). 3: adds `wrong_letters` for choice questions; `relative_error` for numerical questions (**equivalent to giving away the answer**: one query suffices to recover the target). Levels change note detail only, not G's shape. |
| Answer space m | Single-answer: m = number of options n. Multiple-answer: m = 2ⁿ − 1 (the statement says only letter(s), without disclosing how many to choose). Numerical: m = ∞ (at level ≥2, direction enables bisection; level 3 reveals the answer, making m nominal). Enumeration coverage is below. |

## Answer space and enumeration coverage

N = (K+1)(c+1)+1. Distribution of choice questions by (number of options n, number of correct options k), across 2,542 questions:

| n \ m | Single-answer m=n | Multiple-answer m=2ⁿ−1 |
| --- | --- | --- |
| 2 | 1013 | – |
| 3 | 69 | 13 (m=7) |
| 4 | 898 | 123 (m=15) |
| 5 | 89 | 18 (m=31) |
| 6 | 3 | 5 (m=63) |
| 7 | 1 | 5 (m=127) |
| 9 | 74 | 229 (m=511) |
| 10 / 16 | 1 | 1 (m=65535) |

| Budget | N | Choice questions reachable by enumeration (m ≤ N) | Share of choice questions | Share of all 2,785 |
| --- | --- | --- | --- | --- |
| c=1, K=1 (minimum) | 5 | 2069 | 81.4% | 74.3% |
| **c=1, K=2 (recommended)** | 7 | 2086 | 82.1% | 74.9% |
| c=10, K=8 (cmt budget) | 100 | 2307 | 90.8% | 82.8% |

Conclusion: **budgets cannot save ChemBench's choice questions**. Even with c=1,K=1, four fifths are within enumeration range. Preventing enumeration requires nonleaking notes (level 0/1) plus minimal tree retries. The remaining 243 numerical questions and 235 large-space multiple-answer questions (multiple choices out of 9, or 7 out of 16) are the portion that requires reasoning.
All 1,000 chemical_preference questions (36%) are binary choices; the paper itself says models perform no better than random on this topic. Recommendation: exclude them with `topics=` when dispatching a batch and report them separately. The official overall score includes them, so include them when comparing with the paper's table.

## Known pitfalls

- **12 numerical questions cannot score 1**: target ≤ 0 (three zeros, nine negatives), so the official tolerance `0.01 * target ≤ 0` makes `mae < tolerance` always false. This is a property of the official criterion and is not changed. The grading service marks them `SKIP`, omits them from `/problems`, and counts them as 0 in reports (0.43%).
- **Tolerance depends on the data source**: early versions read local JSON with a per-task `tolerance` field (examples such as 0.2 remain in `contribute_questions.md`). The HF version drops it, yielding 1% for every question. Pinning HF pins 1%; the paper does not clarify whether this matches its runs.
- **Multiple `[ANSWER]` blocks are merged**: `prepare_mcq_answer` uses `sorted(set(findall))`. Writing `[ANSWER]B[/ANSWER]` during CoT and later correcting it to `[ANSWER]C[/ANSWER]` is graded as {B, C}. Use exactly one tag pair.
- **Numerical questions use the first number inside the tags**. Units lead to a pint Quantity, then `float()` failure, nan, and score 0. Omit units.
- **The number-word fallback has no word boundaries**: `NUM_WORDS_REGEX` reads "one" in "second one" as 1, so bare text may be interpreted as answering 1. The bare-text self-test deliberately avoids number words.
- **Official `prepare_mcq_answer` can return None** (no tags, commas, or spaces, and not a single letter). The following official `re.findall(pattern, None)` would raise TypeError, but the official runner always has the LLM fallback and never reaches this case. The grading service treats None as a parse failure. This is the sole deviation from the official implementation.
- **One question has a 0.5 in `target_scores`** (`GHS_pictograms`): only 1 counts as correct; selecting a 0.5 option is an extra selection, as in the official grader.
- **The 394 multiple-answer questions** say only "letter(s)", without the correct count. Level 2 reveals `options_expected`; that is the leakage at that level.
- **Data contamination**: the question bank has been public on HF since 2024 (with a canary GUID). Sources include textbooks and ICHO exams; the paper acknowledges this.
- **Dependencies**: no rdkit (SMILES appears only in question text) or torch. `chembench.types` needs `typing_extensions`; `utils` needs `pint` + `fastcore`. `pyarrow` is used only during setup's parquet conversion.
- **CentOS 7 / glibc 2.17**: the manylinux2014 wheels for numpy 2.x and pyarrow ≥15 should theoretically install; if they do not, downgrade numpy to 1.26.

## Not yet verified

This machine is a login node; none of the code has been run. It was reread line by line after writing. The following remain explicitly unverified:

1. All of `stand.py`: whether bypassing `__init__.py` with a namespace package and stubbing five heavy modules permits `from chembench import prompter` (its top-level imports reference only those class names, so it should); and borrowing methods with `class Judge: is_mcq = BasePrompter.is_mcq`.
2. Whether `prepare_mcq_answer(..., example=ex, llm_extractor=None)` returns the expected `"['A,C']"` string, then `run_regex(..., return_first=False)` produces `['A','C']`. This follows official `tests/test_regex.py::test_mcq_label_parsing` but has not been run.
3. Numerical golden answers: target in `[ANSWER]{target}[/ANSWER]` is the original HF string (e.g. `1.5e-05`), which `NUM_REGEX` should accept; `wrong_of` multiplies by 1.5, which should fall outside 1%.
4. `setup.sh`: `git clone --no-checkout --filter=blob:none` + `sparse-checkout set src` + `checkout <sha>` (the login node's git 2.45.1 supports it; GitHub supports partial clone); HF paths `resolve/<revision-sha>/<topic>/train-00000-of-00001.parquet` (confirmed in the `main` tree, not fetched by SHA); wheel installation on glibc 2.17; the `/share/software/user/open/python/3.12.1/bin/python3` + `LD_LIBRARY_PATH` workaround (recorded in memory; the login node does report missing libpython without LD_LIBRARY_PATH).
5. parquet → jsonl cleaning follows `TaskRegistry.from_huggingface`. Each question has exactly one example (jq found zero multi-example questions among 2,785 rows downloaded from datasets-server).
6. The `feed` shape `[{from,out,value}]` was copied from deepswe and has not been run against the kernel.
7. Paper Table A3 numbers were extracted from PDF text; row alignment has not been checked individually.
