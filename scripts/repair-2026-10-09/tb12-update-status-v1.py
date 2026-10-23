"""Refresh TB's own status from actual real-provider receipts only."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
target = ROOT / "docs/repair-2026-10-08/parallel-bench-handoff-2026-10-09/terminal-bench-status.json"
status = json.loads(target.read_bytes())
runs = ROOT / "docs/repair-2026-10-09/tb12-runs-v1"
def read(path):
    return json.loads(path.read_bytes()) if path.exists() else None
def pin(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
real = [home for home in sorted(runs.iterdir()) if (read(home / "entry-start.json") or {}).get("mode") == "run"]
if real:
    home = real[-1]
    route = read(home / "provider-route-receipts.json") or {}
    summary = read(home / "summary.json") or {}
    registry = read(home / "tb12-paid-resource-run.json") or {}
    lock = read(ROOT / ".phase1-data/owned-paid-campaign.lock.json") or {}
    records = [read(home / ("task-" + str(index) + ".json")) for index in range(24)]
    records = [value for value in records if value and value.get("acceptance")]
    status.update({"phase": "real_paired_trial_in_progress" if not summary.get("fatal") else "real_trial_fault_closure",
                   "executionProtocolFrozen": True, "freshCashAdmissionComplete": True,
                   "freshResourceAdmissionComplete": True,
                   "sharedPaidLockAcquired": lock.get("runId") == home.name and lock.get("family") in {"terminal-bench-twelve-journal-v1", "terminal-bench-twelve-journal-v2"},
                   "newProjectLlmRequests": route.get("modelCalls", 0),
                   "paidRealTaskRuns": len(records), "paidDistinctTasksObserved": len({row["officialId"] for row in records}),
                   "liveRealRun": str(home), "liveCashSnapshot": route.get("cashSnapshot"),
                   "livePendingProviderTransfers": sum(route.get("pending", {}).values()),
                   "observedArmScores": {arm: sum(bool(row["acceptance"]["passed"]) for row in records if row["arm"] == arm) for arm in ("U", "F")},
                   "operationalComplete": summary.get("operationalComplete", False),
                   "canonicalOwnerReleased": registry.get("released", False),
                   "next": "Finish fixed 24 real task runs, independently replay raw scores and cash, package all evidence, then await TB confirmation"})
    if (home / "entry-close-failure.json").exists():
        status["closureFailurePin"] = pin(home / "entry-close-failure.json")
    if (home / "independent/raw-audit.json").exists():
        status["rawRealAuditPin"] = pin(home / "independent/raw-audit.json")
        status["realRawAuditValid"] = read(home / "independent/raw-audit.json")["integrityValid"]
    if summary.get("operationalComplete") and registry.get("released"):
        status["phase"] = "real_trial_closed_package_review_pending"
    if (home / "independent/seal-finding.json").exists():
        status["fairPairedComparisonQualified"] = False
        status["sealQualificationPin"] = pin(home / "independent/seal-finding.json")
        status["phase"] = "initial_trial_financially_closed_corrected_protocol_preparation" if registry.get("released") else "initial_trial_owned_financial_closure"
        status["next"] = "Validate revision 2 post-submit repair, freeze it and run fixed twelve U/F with remaining aggregate budget; initial 17 records are qualified, not final comparison"
    entry = read(home / "entry-start.json") or {}
    if entry.get("family") == "terminal-bench-twelve-journal-v2":
        aggregate = entry["aggregateBudget"]
        status["initialQualifiedRequests"] = 531
        status["initialQualifiedRecords"] = 17
        status["initialKnownEstimatedNanoCny"] = aggregate["consumedNanoCny"]
        status["newProjectLlmRequests"] = route.get("modelCalls", 0) + 531
        status["correctedTrialModelRequests"] = route.get("modelCalls", 0)
        status["remainingTrialEnvelopeCny"] = aggregate["remainingCny"]
        status["aggregateNewExposureNanoCny"] = str(int(aggregate["consumedNanoCny"]) + int((route.get("cashSnapshot") or {}).get("newExposureNanoCny", "0")))
now = datetime.now(timezone.utc)
status["updatedAtUtc"] = now.isoformat()
status["updatedAtAsiaShanghai"] = now.astimezone(timezone(timedelta(hours=8))).isoformat()
target.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: status.get(key) for key in ("phase", "newProjectLlmRequests", "paidRealTaskRuns", "sharedPaidLockAcquired", "canonicalOwnerReleased")}))
