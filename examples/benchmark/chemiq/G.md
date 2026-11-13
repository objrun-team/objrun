# G for ChemIQ

| Field | Contents |
| --- | --- |
| **Source** | [arXiv 2505.07735](https://arxiv.org/abs/2505.07735): Runcie, Deane, Imrie, "Assessing the Chemical Intelligence of Large Language Models", JCIM 2026, 66(1):216–227, DOI 10.1021/acs.jcim.5c02145. Repository: [oxpig/ChemIQ](https://github.com/oxpig/ChemIQ), BSD-3, pinned to `63826f64990802e87f1b11b9192606a20838d522` (2026-03-26). The **816 problems** are in `questions/chemiq.jsonl` in the repository, not on HF, and are ungated. `additional_smiles_to_iupac.jsonl` contains 260 error-analysis problems outside the 816 and is not included. |
| **cand** | A single-line short answer matching `answer_format`: integer (226), float (20), list of atom-mapping tuples `[(0, 2), (1, 3), …]` (184), IUPAC name (200), or SMILES (186). The official parser recognizes `\boxed{}`, `\text{}`, the last line, and the last number; for SMILES, it takes the last word on the last line. **The official verifier rejects answers longer than 200 characters or containing a newline.** |
| **structure** | `parsed ──→ correct`, sink = `correct`. `parsed`: official `utils/parser.py::AnswerParser.parse(uuid, raw)` does not return `False`. `correct`: official `utils/answer_verifier.py::AnswerVerifier.check_answer(uuid, parsed)["is_correct"]`. These are two consecutive operations in `analysis.ipynb`, exposed separately; an upstream 0 immediately yields 0 at the root. |
| **h_r** | `check_answer` dispatches by `verification_method` to five deterministic checks: `exact_match` (`str(a)==str(gt)`, 226 problems); `range` (`low<=float(a)<=high`, 20 noisy SAR problems); `list_of_tuples` (set equality, 184); `canonical_smi_match` (RDKit `MolFromSmiles` → `RemoveStereochemistry` → canonical SMILES equality, 186); and `opsin` (convert an IUPAC name to SMILES through the OPSIN web service, then compare with RDKit, 200). **No LLM grading; no problems omitted.** The 200 OPSIN problems depend on EBI's external service: deterministic, but network-dependent with a two-second timeout. |
| **boundary** | Answers occur in each jsonl row's `answer`, `meta_data.*`, top-level `smiles` for NMR, and `answer_range` / `system` for SAR. Only stand.py reads the corpus; `/problems` allows only `uuid`, `question_category`, `sub_category`, `answer_format`, and `prompt`. No container is required, but **the grader needs outbound network access** for OPSIN. This is not isolation: the public repository lets a network-enabled solver clone the answers, as in CMT. |
| **budget** | c=3, K=8, T=15 min; rationale below. |
| **level** | 0–3, described below. |
| **m** | Depends on task type. With N=(K+1)(c+1)+1=37, enumeration reaches 226/816 = 27.7%; see the table. |

## Why c=3, K=8, T=15 min

- Problems require single-sentence short answers. The official setup is one tool-free response; o3-mini takes tens of seconds to several minutes per problem. T=15 min is already more than ten times the official setting and accommodates tasks such as NMR elucidation that require repeated structure construction.
- c=3 rather than CMT's 10: 226 integer problems have answer spaces of 6–25 values, and c=10 encourages scanning 1–27. Three checks permit an answer, validation, note-based revision, and another check.
- K=8 follows CMT/DeepSWE.

## Level: information in note

A passing verdict adds no feedback. After failure, `--level` controls:

| Level | Feedback | Source |
| --- | --- | --- |
| 0 | 0/1 only | — |
| 1 | Failure stage: `parse` (extraction failure and a format reminder), `verify`, `opsin` (service timeout), `task`, or `collect` | Official parser return values |
| 2 | Adds candidate validity: whether OPSIN recognizes the IUPAC name, RDKit parses the SMILES, and how many mapping pairs were supplied | Candidate-only checks using official `_canonicalize_smiles` |
| 3 | Adds extracted original text, OPSIN-converted SMILES, and the candidate's canonical SMILES | Candidate only |

No level returns ground truth or an error magnitude; numerical proximity feedback on integer problems would permit binary search.

## Answer space m by task type

| Task type | Count | Grading | m | Basis | Enumerable with N=37 |
| --- | --- | --- | --- | --- | --- |
| counting_carbon | 50 | exact_match | 25 | Answers 3–27, two problems per value, uniform | Yes |
| counting_ring | 48 | exact_match | 6 | Answers 1–6, eight problems per value | Yes |
| shortest_path | 108 | exact_match | 18 | Answers 3–20, six problems per value | Yes |
| sar/integer | 20 | exact_match | ≈260 | Answers 322–576, derivable from the supplied data | No |
| sar/noise | 20 | range | ≈20 (effective) | Interval widths 13.6–27 across a score range of ≈270; roughly 20 stepped guesses | Yes |
| atom_mapping | 184 | list_of_tuples | ≥ 7! | Permutations of 7–25 atoms | No |
| smiles_to_iupac | 200 | opsin | ∞ | Open-ended strings | No |
| reaction | 90 | canonical_smi | ∞ | Open-ended SMILES | No |
| nmr_elucidation | 96 | canonical_smi | ∞ | Open-ended SMILES | No |

Enumeration reaches 50+48+108+20 = **226 / 816 = 27.7%**. These categories have inherently small answer spaces; even at c=1 and N=19, ring counting and shortest-path problems remain reachable. Report categories separately and mark these 226 problems. Reasoning models in the paper already approach perfect carbon/ring-counting scores, limiting discrimination in these categories.

## Known pitfalls

1. **Possibly 30 problems are unsatisfiable under the official verifier**: atom_mapping with 23/24/25 atoms, ten each. `check_answer` rejects `len(str(model_answer)) > 200`, while the parser supplies a Python list whose `str()` includes spaces. A 25-atom ground-truth answer is 230 characters, a 23-atom answer 210, and a 22-atom answer exactly 200. **This was inferred arithmetically, not executed.** A dedicated self-test probe checks it. If confirmed, count those 30 as failures and label them, consistent with the paper's curve dropping to zero with increasing n_atoms.
2. **OPSIN is external.** `opsin.ch.cam.ac.uk` redirects with 301 to `www.ebi.ac.uk/opsin/ws/`, which requests follows. One round trip from a Sherlock login node took about 1.0 s. The official `@timeout(2)` includes network time. If it fires inside `requests.get`, `_get_opsin` catches the exception and **caches False**, permanently failing that name. stand.py detects this through a pre-call cache check and elapsed time ≥1.9 s, removes the cache entry, and retries up to three times without changing the grading rule.
3. `@timeout` uses `signal.alarm` and therefore requires the main thread. The service uses a **single-threaded HTTPServer**, grading one request at a time.
4. The official verifier reads/writes `utils/opsin_cache.json` using a relative path. stand.py changes cwd to the vendor root on startup. Grading writes to that checkout and may make Git report it as dirty; this is harmless.
5. If the parser extracts integer 0, `check_answer(uuid, 0)` fails its `if not model_answer` check. No corpus answer is 0, so this does not affect the dataset.
6. **Contamination:** the repository has been public since 2025-05, including all answers and complete responses from six models (`model_responses/`, 1M lines). Problems are algorithmically generated from ZINC; the 50 2D NMR problems were added in 2025-07.
7. Official `smiles_to_iupac` grading inserts the IUPAC name directly into a URL without encoding. Names containing `#`, `%`, or `/` can be truncated or return 404, causing failure.
8. Dependencies: rdkit, numpy, requests. New PyPI RDKit wheels do not support Sherlock's glibc 2.17, so use cluster module `chemistry/py-rdkit/2024.3.2_py312`. The official conda environment does not pin RDKit; canonicalization may drift across versions, although these simple drug-like molecules reduce the risk.
9. Half of the prompt SMILES are randomized (`*_random` subcategories). A solver with RDKit can compute carbon/ring counts, shortest paths, atom mappings, and canonicalization. Tool access is an experimental variable, not a grading concern.

## Unverified assumptions at the time this adapter was written

The code had not run on this machine because Python execution was forbidden on the login node. Source review left these items unverified:

- `from utils.answer_verifier import AnswerVerifier`: `utils/` has no `__init__.py` and relies on namespace packages. The official notebook uses this import from the repository root.
- `VERIFIER.question_dict` keys are UUIDs. The parser also inserts debugging keys such as `"integer"`, but the verifier does not; confirmed by reading source, not execution.
- The OPSIN `golden_of` self-test scans `_opsin_cache` for a name matching ground truth. The author's model runs populated over 3900 entries, but the first zinc_canonical / zinc_random problem may have no match and may be skipped.
- The 200-character issue in pitfall 1 is an arithmetic prediction; the probe must confirm it.
- The ≥1.9 s timeout threshold may be too high: `signal.alarm(2)` has whole-second resolution and can fire after 1.x–2.0 s. Lower it to 1.5 if retries never occur.
- OPSIN connectivity from an **sdev compute node** was not checked; only a login-node request (1.0 s) was tested. Setup step 3 measures it again.
- `ml math devel chemistry python/3.12.1 py-numpy/1.26.3_py312 py-rdkit/2024.3.2_py312`: `ml spider` requires the `chemistry` prefix for RDKit, but binary compatibility with numpy 1.26.3 was not verified. Recorded experience says that NumPy module works with the relevant SciPy/pandas modules.
- Whether cluster Python 3.12.1 provides ensurepip for `python3 -m venv --system-site-packages`; CMT's WSL environment did not and used uv instead.
- Engine `input.result` handling (`result.body` or a bare value) follows CMT/DeepSWE and was not checked against the current engine version.
- Port 7903 does not conflict with the CMT (7901) or DeepSWE (7902) services.
- Noninteractive setup uses `source $LMOD_PKG/init/bash` to obtain `ml`. On the login node, `LMOD_PKG=/share/software/user/open/lmod/lmod` exists. `bash -n` passed, but the script had not run.
