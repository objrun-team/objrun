# OlympiadBench integration

Implementation: `examples/benchmark/olympiadbench/experiments/`. `prepare.py` builds a private run bundle from pinned data and a verified FrontierScience engine copy. `ops.py deploy` deploys to novaeve and performs null-model acceptance checks. Once accepted, `ops.py launch` starts an 8-task canary in both groups, automatically continuing with the remaining tasks after it passes. The canary is included in the 236 tasks and is not generated again.

The baseline and objrun groups both use the official DeepSeek deepseek-flash with thinking enabled/high/16384. The bundle’s experiment.json, source-pins.json, and dependencies.json define the actual configuration and versions. A local dynamic-port bridge connects the real engine; the rule-based grader runs in a separate restricted Python subprocess. Only the transport controller holds the real key.

`grade.py` wraps the official grader. `runtime.py::Judge` provides a private grading queue with identity hashes and concurrent-request deduplication; `native.ts` exposes G’s present/correct HTTP handles. After writes stop, `report.py` audits candidates, grading, budgets, requests, and source code, producing SUMMARY.json, AUDIT.json, FINAL_RESULTS.csv, and REPORT.md.

`ops.py pull` retrieves compact status. After completion, `ops.py retrieve` creates a full archive on the NAS, transfers it back, and verifies matching SHA256 values at both ends. It includes all results, raw responses, request receipts, costs, logs, SQLite databases, source code, and private dependencies.

If deployment, launch, started, or dispatch records already exist, check status first; never blindly repeat an entry point. Do not regenerate valid outputs. Preserve anomalies and unknown costs, with at most three bounded retries. Estimate run costs using official token rates; separately mark actual per-request billing as unavailable.
