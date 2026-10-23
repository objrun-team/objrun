# Shared complete saved-candidate inventory and reconciliation

Successor to COMMON-SAVED-CANDIDATE-RELEASE-HANDOFF; original published inputs remain unchanged.

New root disposition body retains the existing protocol and adds:

- `candidateInventoryPins`: exact unique set of every candidateArtifactPin detected in original history grade records.
- `priorPreservedCandidates`: each `{runId,candidateArtifactPin,capsulePin,partialGradePin,closureProofPin,mainDatabasePin,mainTaskId,factsPin}`.

The primary and every prior item must join its actual ordered cash/native history, pinned partial grade's actual candidateArtifactPin, actual original main DB and closure. All candidates and capsules must exactly equal the manifest unresolved inventory. Every original candidate remains present. Missing or extra inventory, wrong run, modified artifact, an original result or unresolved/executed submit is rejected.

Prior root facts must retain true candidate presence, complete preservation, formal result unrecoverable, exact pins/main identity and actual assistant submit count. The unrecoverable grade classification may be either an actual original validator rejection, or the truthful infrastructure-aborted classification `originalGradeValid:false`, `originalGraderResultAbsent:true`, `originalTestsReached:false`. No validator rejection is invented. A historical assistant submit is only permitted if the existing actual history consumer independently verifies its original tool response was unexecuted and resolves every such submit; root facts must keep its count and `originalSubmitExecuted:false`. The primary aa37 path still requires actual submit zero.

`candidateEvidencePins` remains the primary eight artifact pins; prior evidence/facts are additionally manifest-bound. The successor root entry still signs the complete manifest and its exact disposition envelope pin. No previous input/signature/lock is replaced.

## One-shot root admin

`reconcile-saved-candidate.ts` has only read-only check or explicit apply modes. It loads the new manifest, revalidates the signed disposition and all original history, verifies the selected common HOST content and attestation are manifest-bound and built from the exact new helper/builder, and requires the exact old queue subject/manifest/stage unknown with no other unclosed attempt for this task. The real old driver's OS FILETIME must be absent (PID reuse with a different known FILETIME is allowed without touching that process).

It then invokes the real new HOST original-recovery path, including actual original actor absence/current parent gates. The result must remain retryable, native/financial closed and candidate-present true; the strict shared helper revalidates it. Full actual-host result and checked evidence are saved with WX.

Apply uses one BEGIN IMMEDIATE transaction, rechecks identical rows, changes only the subject attempt and stage unknown→retryable and task quarantine→0, and appends an event containing all prior rows/result/evidence. It does not modify old result, manifest/run/context, lock/cash files, inventory, jobs, admission or broker. Valid tasks and any raced state are rejected. An event-write failure rolls back all updates. New attempt still needs the standard plan/root signature/enqueue; this tool does not spawn.

Command (root supplies final successor manifest and a new output directory):

```powershell
& $bun --smol scripts/bench-runner/reconcile-saved-candidate.ts --mode check --database <existing-queue.sqlite> --manifest <final-manifest.json> --host scripts/bench-runner/release/399afcb2e1fa638f9a355cd18e97518d8694ac06d5808bc79dabc8b20d194c81/runner.js --host-attestation scripts/bench-runner/release/399afcb2e1fa638f9a355cd18e97518d8694ac06d5808bc79dabc8b20d194c81/release-7ae8d68cde017c67f615923b4801d43c1c1ab695c765f2506fa9783707776f94.json --admission <existing-admission-control.json> --python D:/ProgramData/anaconda3/python.exe --output <new-root-check-directory>
```

For root-approved actual apply use `--mode apply` with a different fresh output directory. Apply repeats all actual checks; it does not trust a previous check JSON as authority. No production check/apply, signature or attempt was performed by this delivery.
