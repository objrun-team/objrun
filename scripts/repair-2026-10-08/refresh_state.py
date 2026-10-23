"""Refresh continuation metadata from artifacts; do not mutate any running experiment."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/repair-2026-10-08"
file = DOCS / "run-state.json"
state = json.loads(file.read_text(encoding="utf-8-sig"))
# Preserve the separately reviewed prospective entry. Legacy evidence below
# remains authoritative for the failed campaign, not for a new runtime.
prospective = ({key: state[key] for key in ("nextExecutionFile", "nextEntryChecks",
    "remainingConditions", "budgetPolicy") if key in state}
    if state.get("scientificV2Preparation") else {})
campaign = DOCS / "campaigns" / state["activeCampaign"]
summary = json.loads((campaign / "summary.json").read_text(encoding="utf-8"))
ledger = json.loads((campaign / "api-ledger.json").read_text(encoding="utf-8"))
restoration_status = state.get("externalRestoration", {}).get("workflowStatus", "Public dependency restoration in progress; no candidate verdict yet.")
state.update({
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "plannedTaskRuns": summary["plannedTaskRuns"],
    "recordedTaskRuns": summary["recordedTaskRuns"],
    "campaignCompleted": summary["completed"],
    "recordedUsageUpperBoundUsd": ledger["recordedUsageUpperBoundUsd"],
    "providerReceiptCount": len(ledger["calls"]),
    "providerFaultCount": sum(bool(call.get("fault")) for call in ledger["calls"]),
    "fatal": ledger.get("fatal") or summary.get("fatal"),
    "nextExecutionFile": "scripts/repair-2026-10-08/campaign-next.ts",
    "nextEntryChecks": "Final future-entry freeze delivered: 34 tests / 241 assertions passed, actual local four-worker mock peak 4; atomic paid lock, I/O contract, ChemIQ provenance and TB authenticated gateway seal/drain accepted. See tb-next-runner-preparation.md and tb-next-runner-source.json. No next paid process starts before current campaign settlement.",
    "chemiqControls": {"positivePassed": 782, "planned": 816, "mappingFixRecovered": 30,
                       "missingPositiveReferenceNames": 34, "wrongAndFormatControlsPassed": 816,
                       "profile": "local OPSIN 2.8 / raw-input-length / no REST fallback"},
    "remainingConditions": [
        "SKB87 target remains; other86 task images unavailable. Old snapshot judge defaults formally disabled. JPG corrected image9289277 has22 public original-path/SHA proof; olda188 revoked for nested COPY. Fresh fixed-interpreter empty/oracle/wrong controls0/1/0 accepted. Final real-Docker zero-LLM U/F mock skb-jpg-2026-10-08T11-29-26-467Z naturally exited0, both valid0 with source/dependency/privacy/fee/cleanup closed; independent stored-evidence audit48/48 complete. CHECKS6 means explicit verify, actual six physical grades separately enumerated. Full historical HostConfig/rawTAR missing limits retained. This is preparation, not a model score; paid pilot waits for shared lock settlement.",
        "miniF2F3 identity/prefix/time matched; official Lean4.15 ZIP427590493B acquired with measuredSHA, offline Bootstrap completed and5826 official cache keys exported. Narrow fixed Batteries link compatibility reviewed. Actual workflow: " + restoration_status + " Fast independent unpack protocol required because immutable old core repeatedly scans the full bind tree. Fixed cache/public controls remain, no candidate verdict yet.",
        "Historical DeepSWE112 code/grader/image identity unknown; timestamps support 53 early successes, 58 later tasks and one retained early failure, not a certified 53/59 version split.",
        "TB nginx v2-preseed final source-hash gate passed empty0/8 and oracle8/8; 73.55MiB public dependency cache. Final cold U/F mock 2/2 valid, each 0/8 expected; 19 local mock completions, zero real LLM/cost. Twelve candidate-origin missing/forged-token probes returned401. Authenticated six-tool gateway seal/drain completed with outstanding0; actual late-tool budget-failure regression passed. Only nginx supported; other88 unsupported. Preserve earlier invalid UV and valid oracle0 failed setup controls.",
        "GPQA full closed and independently audited1386 tasks/3204 API receipts with0errors; U163/F195/Rany186 of198. ChemIQ10 U/F20 tasks/1243 receipts have separate deferred runtime closing, U3/F3; TB nginx U/F2 tasks/27 receipts/8of8 each audited49of49. Combined science1220 naturally failed task-state500/OOM at254 saved records; four unfinished receipts/reserve retained, no unified full score. Native statement/status repair has5 meaningful regressions/61 assertions and real bounded pressure evidence, original500 not reproduced. Future entry must freeze the new source and/status; no selective answer retries.",
    ],
    "optionalDiagnostics": "CMT extra parser probe and supplemental provenance delegation stopped by tool content review (possible cybersecurity risk); no probe executed and no extra data-error claim. See optional-diagnostics.md.",
    "executionQueue": "docs/repair-2026-10-08/execution-queue.json",
    "budgetPolicy": "Only one paid process. Original failed science remains at frozen4 workers/cumulativeUSD80 with four unresolved original receipts. Future separate entry needs an explicit conservative-liability admission policy and current original-currency balance/price guard; original pending and old guard are not rewritten. Each future operator guard is fixed before generation using actual known costs plus unknown liabilities and declared storage. Operator guards are not user spending caps, and protocol cost estimates are not invoices.",
    "concurrencySteering": "Completed frozen GPQA stayed at 2 workers. Current and future scientific batches prefer 4 workers and a round-robin cross-benchmark queue in one shared-cost process after resource preflight; explicit schedule/concurrency frozen before generation. TB stays one live candidate/one grader.",
})
state.update(prospective)
file.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: state[key] for key in ["activeCampaign", "recordedTaskRuns", "plannedTaskRuns",
    "campaignCompleted", "providerFaultCount", "recordedUsageUpperBoundUsd", "fatal"]}, ensure_ascii=False))
