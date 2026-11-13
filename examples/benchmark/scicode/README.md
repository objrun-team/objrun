# SciCode integration: original version and Verified preparation pilot

Official source: https://github.com/scicode-bench/SciCode . Pinned commit: `e3158ea011d4235245a547460d3688d7ccbf9900`.

The goal is to integrate original SciCode: generate each full problem step by step, carrying forward this model run’s earlier generated code, and report both substep and whole-problem scores. Do not present the first substep as a complete problem or insert reference solutions into prior model context.

Original numerical targets `test_data.h5` are provided through the Google Drive folder in the official README, 1,049,345,865 bytes. Public download currently hits a quota limit; the original version has not been piloted. Verified targets are available, 1,108,078,257 bytes, with the official MD5 checked; source and SHA256 are in the run manifest.

SciCode-Verified is a separate corrected version: https://github.com/flyingwagner/scicode-verified , pinned to `ddab4a92f8d80a7113ab946628e994b52354d838`. This run uses v2, with_background=true, and preselected problems 5, 8, 9, 11, 12, 14, 15, 16, 17, 18, carrying actual delivered model code forward at each step. All 10 whole problems and 39 substeps are complete; independent final grading passed 5/10, with 10/10 valid. Results: docs/phase1/report.md. The 287 substeps and the two versions were not counted as separate benchmarks.

## Environment

`Dockerfile` pins Python and scientific-library versions. Candidates execute in disposable grading containers with network disabled, CPU/memory/process limits, and cleaned environment variables. Mount only the current candidate and data required by grading. The solver receives no access to these containers, test data, or grading side.

Existing image IDs, extra dependency versions, and file digests are in docs/phase1/environment.json. With a local cache, start `stand.py --port 17921` and pilot with `bun scripts/phase1/pilot-scicode.ts 10`; save each round’s source snapshot before the model request. Check available space before downloading original data or rebuilding images.

The current preparation environment is Python3.12/NumPy1.26.4/SciPy1.14.1, with a 90-second grading timeout. It does not reproduce the specified multi-environment OR or 1800-second configuration. Each substep gets 300 seconds/c=2 separately; this is not the budget for a whole problem. All 39 substeps in the selected 10 problems passed independently written correct-implementation controls based on public statements; all 39 incorrect-return controls and 10 syntax-error controls passed too. Separate controls cover hidden targets, reference files, no-test exits, and scientific-object transport. Full evidence is in scicode-expanded-controls.json, scicode-negative-controls.json, and scicode-selfcheck.json, covering only these 10 problems. This is explicitly a version-specific pilot, not completed acceptance of original SciCode or its full specification.

## Controls and candidate identity

Control scripts neither generate model answers nor download data:

```powershell
python scripts/phase1/scicode_expanded_controls.py
python scripts/phase1/scicode_expanded_controls.py --negative
python scripts/phase1/accept_scicode.py
```

The Brownian-motion control preserves trajectory ordering and RNG state while expanding the linear recurrence in bounded batches. The Numerov control delegates the same banded recurrence to existing BLAS. Pre-optimization implementations and their 90-second timeout verdicts remain preserved, with 3 RNG-state/result-equivalence checks and 5 analytical/recurrence checks respectively. These independent correct controls were never mixed into prior model-generated code.

Original acceptance of delivered model candidates remains in whole-problems.json. Independent reevaluation writes whole-problems-reaccepted.json, retaining digests of each original answer, extracted code, and accumulated whole-problem code. report.py requires all controls to pass, digests to match frozen candidates, and original verdicts to remain unchanged. Subsequent pilot-scicode.ts runs perform final acceptance only after all model generation finishes.

The grading service caches only structurally complete, valid Boolean verdicts. Grading faults, invalid verdicts, and exceptions return HTTP503 without caching or exposing hidden error bodies to the solver. Real HTTP regression checks validate interface behavior and do not replace official controls.
