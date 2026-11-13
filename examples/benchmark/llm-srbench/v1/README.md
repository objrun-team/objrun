# LLM-SRBench release four-arm runner

Pinned data: `pkuHaowei/llm-srbench@f4101e201952bb35cab8332b6dcf337b6df02aa8`, 240 equations and 960 records across four arms. Server directory: `/mnt/aliyunsb/pingxingwang/tgengin-bench/llm-srbench-20261019-v1`.

The arms are single-shot structure generation, real ObjRun, at most five independent samples, and binary feedback in the same ObjRun wrapper. The shared fitter uses SciPy least_squares, three fixed initializations, at most 1000 function evaluations each, and at most 2048 fixed training points; feedback uses the complete training set. Candidates are expression JSON with parameters numbered p0, p1, etc.; evaluate only after final parameters are frozen.

Model: OpenRouter `deepseek/deepseek-v4.1-flash`, DigitalOcean only, high reasoning, temperature=0, max_tokens=16384, no provider fallback or seed. Single-shot budget is $0.025 per task; other arms $0.10, with at most $78 for formal solving. Charge every call and bounded retry. Retain upper-bound reservations for unknown requests without automatically generating again.

Run free controls before freezing source and protocol. The canary uses the first two tasks by ID in each subset: 40 records across four arms. Continue based on execution, cost, information-isolation, and trajectory checks, not pass rate. Pilot and formal runs use the same frozen package; accepted records count directly toward the full set.

All training verdicts come from training arrays. Freeze every candidate and all three cost checkpoints before batch ID/OOD evaluation; no test-based early stopping or selection. Report NMSE, Acc0.1, project success rate at NMSE≤0.01, paired intervals, duplication, truncation/anomalies, and all actual/unknown costs. The GPT-4o SA judge was not run.

Release-package reference formulas require state-function expansion and parameter-notation normalization, and some numerical references cannot directly reproduce the arrays. Records are in `outputs/controls/reference-metadata-audit.json`; neither raw arrays nor the 240-task scope changes. The grader never reads these strings. Preserve both original references and normalization-check results.

This run’s engine is copied from the current project working tree with per-file hashes. Only the copy adds binary-verdict projection and stdout/stderr persistence; original core code remains unchanged. Python uses a separate runtime entry referencing previously frozen scientific dependencies; the Bun SDK uses frozen dependencies, with versions and file hashes saved alongside results. Candidates are allowlisted expressions; execution subprocesses have no network or API keys, run as UID65534, and private grading data uses directory mode 0700.

Local entry point: `F:/git/TgEngin-handoff-2026-10-07/TgEngin/examples/benchmark/llm-srbench/v1/local_ops.py`, run with `D:/ProgramData/anaconda3/python.exe`.

| Action | Purpose |
| --- | --- |
| `stage` | Prepare the independent package and release data only before source freezing |
| `refresh` | Refresh source only before paid execution |
| `controls` | Model-free protocol, numerical, isolation, and real-engine controls |
| `launch` | Read the authorized key from the existing project .env and pass it through SSH stdin into the controller, without writing a key file |
| `pull` | Sync compact status; after termination, export/download/verify/extract the complete archive and run offline audits |

Local results: `F:/git/TgEngin-handoff-2026-10-07/TgEngin/runs/llm-srbench-release240-20261019`. `retrieval.json` records server/local SHA256, actual task count, and offline-audit results. Successful archive download does not imply successful completion of every experiment.

Resume only through the same frozen entry point. Do not rerun existing result.json entries or extend existing requests’ bounded attempt chains. Interrupted native cells do not restart automatically. Preserve unknown paid dispatches and distinguish anomalies from wrong model answers. Do not refresh the package during formal execution or change the protocol based on ID/OOD.
