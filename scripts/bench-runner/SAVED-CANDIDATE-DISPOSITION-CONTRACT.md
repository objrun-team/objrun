# Shared saved-candidate disposition release

This successor leaves all original source/releases and attempt records unchanged. It does not sign, launch, reconcile/apply, grade, restore a candidate, acquire resources, or change admission.

## Contract

The manifest declares `adapterConfig.unresolvedOriginalCandidatePins` (the real candidate and capsule remain present) and:

```json
{"savedCandidateDisposition":{"protocol":"bench-saved-candidate-disposition-contract-v1","envelopePin":"Pin","candidateEvidencePins":["the eight artifact Pins below"]}}
```

`envelopePin` points to `{protocol:"bench-root-signed-saved-candidate-disposition-v1", disposition:BODY, signature:BASE64}`. The original Ed25519 authority signs the UTF-8 bytes of `JSON.stringify(BODY)`, with `crypto.sign(null, bytes, originalPrivateKey)`. No new key or unsigned rootReviewed flag is accepted.

BODY fields:

- `protocol:"bench-saved-candidate-disposition-v1"`, `taskId`, `bench`, `attemptId`, `runId`, `expiresAtUtc`.
- `predecessorManifestPin`, `authorityPin`, `oldAttemptLockPin`, `canonicalLockPins`.
- `mainDatabasePin`, `mainTaskId`, exact ordered `cashClosePins`, `aggregateBudgetPin`.
- `fees:{knownUsd,unknownUsd,calls}` (must equal full actual cash/journal replay).
- `originalContract:{taskCapUsd,solveSeconds,gradeSeconds,providerSeconds}` (same original limits; the consumer additionally compares every original CPU/memory/model/provider/reasoning/tool limit).
- `factsPin`: immutable root-reviewed factual audit, not executable authority. It must retain true candidate presence, submit count zero, original main claimed/result null, original validator valid false and exact identity/artifacts.
- The eight artifact fields: `candidateArtifactPin`, `capsulePin`, `partialGradePin`, `originalPid1FramePin`, `rawCtrfPin`, `originalContractPin`, `closureProofPin`, `frameRecoveryProofPin`. Every hash/path/size must match the factual audit and manifest pin graph.
- `decisions:{originalFormalResultUnrecoverable:true,originalCandidateCompletelyPreserved:true,allowNewAttempt:true,promoteOriginalValid:false,regradeOriginal:false,restoreCandidateIntoFreshWorkspace:false}`.

The root-signed new entry must also contain `rootReview.savedCandidateDispositionPin` equal to the envelope pin. Its existing rootRuntimeBinding signs the complete successor manifest. The disposition signs the actual predecessor manifest, original signed entry/lock and unchanged successor contract/fee evidence; the successor root entry signs the manifest containing the disposition. This avoids a self-referential manifest/envelope hash.

## Enforcement

The original history consumer still replays all actual cash/journals, native ledgers/stream closes, original task DBs and canonical identities. Explicit candidateCustodyPins and a partial-grade candidateArtifactPin now require declared candidate inventory before any no-candidate route can apply. An original valid result or submitted candidate remains forbidden by this narrow route.

The same old manifest authority must verify both the old runtime entry and the new disposition. Actual old attempt/nonce/manifest and original canonical envelope signatures are checked. A changed candidate, pin, cap, deadline, missing closure, or unsigned facts fails closed.

Host recover reports `candidateOrSubmissionPresent:true`, `noOriginalCandidateOrGrade:false`, canonical identity preserved, original null identity false. Before recording retryable recovery, the actual configured fresh-history/current-parent guard and actual actor absence checks still run. The queue only accepts a true-candidate retryable result by re-reading its unique manifest-bound recovery receipt and independently revalidating the disposition/history; no arbitrary boolean is added. Execute and native-stage entry revalidate it again, and formal driver preflight rechecks the new root entry/disposition join before resources. Existing fresh106, owned pool, before-journal/forward and original limits remain unchanged.

This does not insert a saved candidate into a new initial workspace. Any future initial-state transfer requires a separate original-contract-compatible authority.

## Python launcher pre-resource correction

The new builder calls frozen `preparePythonModuleBinding` and pure `bindLauncherPythonArgs(prepared.launcherContents, contract)` inside driver preflight, before `api.resource`. Thus both actual argv and unique spawn anchors are rejected before acquisition. Frozen python-module-binding.ts is unchanged; the later installation still performs its original strict checks.

## Validation and remaining production data

Local tests use isolated generated Ed keys, local SQLite/cash journals with no provider transport, and fake current-parent source bound only to the test manifest. They exercise the actual common HOST recover branch and durable SQLite originalRecovery route. They do not establish production qualification or sign the real candidate facts.

Production remains blocked until root approves the exact six-cash history, signs the disposition with the original authority, and signs a new entry/manifest carrying that envelope and all historical locks. Existing root factual review alone cannot authorize retry. No attempt was created or applied by this delivery.
