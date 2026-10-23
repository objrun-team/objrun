"""Lightweight current corrected results and delivery status, no audits."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
master = ROOT / "docs/repair-2026-10-09/tb12-fast-runs-v3/repair-2026-10-09T13-07-27-428Z"
target = ROOT / "docs/repair-2026-10-08/parallel-bench-handoff-2026-10-09/terminal-bench-status.json"
status = json.loads(target.read_bytes())
def read(path):
    return json.loads(path.read_bytes()) if path.exists() else {}
manifest = read(master / "manifest.json")
homes = [ROOT / "docs/repair-2026-10-09/tb12-runs-v1" / (manifest["runId"] + "-1")]
repair = read(master / "process-lane-0.json")
if repair:
    homes.append(Path(repair["output"]))
records = []
requests = 0
for home in homes:
    requests += read(home / "provider-route-receipts.json").get("modelCalls", 0)
    for path in home.glob("task-*.json"):
        value = read(path)
        if value.get("acceptance", {}).get("valid"):
            records.append(value)
delivery = read(master / "latest-delivery.json")
diagnostic_requests = read(ROOT / "docs/repair-2026-10-09/tb12-runs-v1" / (manifest["runId"] + "-0") / "provider-route-receipts.json").get("modelCalls", 0)
status.update({"phase": "corrected_parallel_real_trial_initial_zip_delivered", "correctedTrialMaster": str(master),
               "correctedTrialCompletedValidRuns": len(records), "correctedTrialModelRequests": requests,
               "newProjectLlmRequests": requests + diagnostic_requests + 531, "initialQualifiedRecords": 17,
               "excludedInfrastructureDiagnosticRequests": diagnostic_requests,
               "old17RecordsIncludedInCorrectedComparison": False, "observedArmScores": {arm: sum(value["acceptance"]["passed"] for value in records if value["arm"] == arm) for arm in ("U", "F")},
               "concurrency": 2, "parallelIsolation": "separate process lanes", "fixedHumanApiCap": None,
               "old9CnyLimitSuperseded": True, "initialDelivery": delivery,
               "fullIndependentCertification": "pending", "actualCorrectedTaskBudgetPreserved": True,
               "next": "Finish fixed twelve paired U/F, update full actual ZIP; certification gaps remain explicitly pending"})
if len(records) == 24:
    status["phase"] = "fixed_24_completed_full_zip_delivered" if delivery.get("partial") is False else "fixed_24_completed_full_zip_packaging"
    status["allFixed12PairedRunsCompleted"] = True
    status["ownBenchLockReleased"] = (master / "bench-lock-release.json").exists()
    status["next"] = "Deliver fixed 24 actual result ZIP; extra independent certification remains pending, no further model runs"
now = datetime.now(timezone.utc)
status["updatedAtUtc"] = now.isoformat()
status["updatedAtAsiaShanghai"] = now.astimezone(timezone(timedelta(hours=8))).isoformat()
target.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"completed": len(records), "modelRequests": requests, "zip": delivery.get("archive"), "score": status["observedArmScores"]}))
