# Universal Bench runner contract

Only this new source tree is mutable during construction. Existing frozen runtime, broker, evidence, budgets and task locks remain untouched. New admissions remain closed until inventory reconciliation and zero-model checks pass. The user authorizes one unfinished real task as the official end-to-end validation, followed by automatic resumption; never replay a completed Bench to test the runner.

One CLI and durable SQLite queue drive both Terminal-Bench and SkillsBench. Task-specific data belongs in versioned JSON manifests. Existing qualified task runtimes may be reused as immutable drivers; no per-attempt or per-task root runner clones. Runtime process IDs, tokens, run directories, nonces and canonical plan paths are generated or bound at execution time, never source constants. No shell command strings.

Core modules own admission, manifests, durable state transitions, attempt/stage IDs, permanent deduplication, process custody and restart reconciliation. Adapters own original Bench protocol interpretation and stage result extraction. Inventory owns existing task/stage provenance and classification. These must use one shared schema, not independent queues or resource pools.

Stage order: prepare, qualify, solve, grade, cleanup, reconcile, archive. Each stage can reuse verified prior success. A candidate/submit/grade recovery always precedes a new paid solve. Valid includes pass, wrong and budget exhaustion and is permanent. Historical unknown state is quarantined. A crash between intent and PID receipt is unresolved until exact process/ledger reconciliation; never automatically respawn it. Recovery requires closed finance/native evidence and uses a new attempt while preserving all old costs and locks.

The intake switch affects only new stages/tasks; it never cancels an executing stage or provider request. Preparation and formal solve have separate queues. Shared resources use only the original live broker and pool. Resource availability, worker spawn and a requested model call are not actual solver counts. Count actual worker/engine/main/run/DB-health/live-lane evidence. Do not invent parallelism or release old financial holds.

Keep original per-task CPU/memory, solve/grader/tool/provider time limits, model/provider/reasoning, USD caps and prior known/unknown reservations. No budget reset, timeout expansion, oracle repeat or hidden source mutation. Shared free-disk floor remains 5GiB; no per-container disk quota or write-amount kill. Driver-owned leases must be independently verified, not nested under another pool.

All outputs are durable local artifacts. Archive original results/cash/native proof before registry updates. Google Docs synchronization remains the separate numbers-only operation with revision protection and complete native before/after comparison.

Implementation ownership: root owns shared types and integration; broker_audit owns core queue/admission/manifest/runner/CLI/tests; sb_first owns adapters/runtime contracts/tests; tb_first owns global inventory/import/task manifests and inventory tests. Coordinate schema changes through root. No model, grade, oracle, Docker mutation or Bench launch while building.
