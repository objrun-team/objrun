# Bench runner

This entry owns task admission and durable lifecycle state for Terminal-Bench and SkillsBench. It does not replace the original broker, financial ledger, resource pool, native custody database or task locks.

Run `bun scripts/bench-runner/cli.ts <command> --db <queue.sqlite> ...`. Every mutating command records local durable events. Paths, task differences, reviewed sources and original constraints belong in JSON manifests, not in task-specific runner copies.

## Intake and recovery

`drain --admission <control.json>` closes new tasks and subsequent stages. It does not pause the broker, cancel a child process, interrupt provider requests, or prevent existing grading and cleanup.

`import --inventory <inventory.json>` imports the global taskId inventory. Valid pass, wrong and budget exhaustion are permanent. Unknown history is quarantined. Missing files never establish that a task was never started. A candidate, submission or original grade must be recovered before a new paid solve.

`recover-state` quarantines attempts whose intent or running state survived a scheduler restart. It does not respawn them. A planned attempt has not started and retains its original attempt ID while awaiting its signature. Inspect exact process incarnation, native custody, lane and finance before reconciliation.

## Execution

1. `check --manifest <task.json>` validates configuration and evidence without acquiring resources or launching a task.
2. `plan --manifest <task.json> --admission <control.json>` creates a durable attempt and concrete JSON binding request. It creates no native actor, lane or model request.
3. Review and sign the concrete data using the existing root authority. The template, original expenses, contract, source pins, attempt ID and output are verified together. Never create a historical lock or nonce that did not exist.
4. `resume --admission <control.json> --approval <scoped-root-review.json>` enables only the reviewed scope. During the first official validation, the scope contains one unfinished task.
5. `run-one --attempt <planned-id> --manifest <task.json> --admission <control.json>` executes that same durable attempt. Alternatively, `enqueue` and `dispatch` drain the preparation/formal queues. Unsigned tasks remain blocked. The broker remains the sole resource authority.

The adapter can reuse a verified successful stage without spawning it again. Bundled legacy campaigns may run solve, grade and cleanup internally; their original per-stage clocks remain unchanged. A separate outer custody deadline does not extend those clocks. If custody is unresolved at that deadline, the attempt is quarantined rather than killed or automatically restarted.

## Evidence and completion

Original candidate identity, generation validity, original grading acceptance, journal/cash closure and native closure determine a valid result. A derived policy cannot turn an original invalid generation into a valid one. Driver exit code alone establishes none of these facts.

Each result archives original proof bytes before the queue advances. After exact financial and native closure, `retention.ts` publishes a permanent result record compatible with the existing global progress deduplicator. Google Docs synchronization remains a separate revision-protected, numbers-only operation.

Worker spawn, a requested model call, a lease or a historical hold is not an actual solver. Count only a joined worker/engine/main task/run/database health/live lane with exact process incarnations. Preparation uses actual taskId/argv/plan/source/lease evidence and is counted separately.

## Local verification

`bun test scripts/bench-runner` uses temporary fixtures and fake local drivers. It must not execute a completed Bench, model request, original grader, reference/oracle, Docker mutation or real task admission. The first unfinished real task is the official execution, not an extra test run.
