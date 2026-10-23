"""Publish only the Terminal-Bench handoff status from actual local receipts."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3

from docker_owned import ROOT, sha


def main():
    status_path = ROOT / "docs/repair-2026-10-08/parallel-bench-handoff-2026-10-09/terminal-bench-status.json"
    status = json.loads(status_path.read_bytes())
    preparation = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1"
    controls, unfinished = [], []
    for folder in sorted((preparation / "cold-snapshots").iterdir()):
        if not folder.is_dir():
            continue
        target = folder / "control.json"
        if target.exists():
            record = json.loads(target.read_bytes())
            controls.append({"taskId": record["taskId"], "control": record.get("control", "empty"),
                             "path": str(target), "sha256": sha(target),
                             "validated": record["validated"], "allClosed": record["allOwnedContainersClosed"],
                             "fatal": record["fatal"], "modelCalls": record["modelCalls"]})
        else:
            unfinished.append(str(folder))
    cash = sorted((preparation / "cash-observations").glob("*/balance.json"), key=lambda path: path.stat().st_mtime)
    now = datetime.now(timezone.utc)
    status.update({"updatedAtUtc": now.isoformat(), "updatedAtAsiaShanghai": now.astimezone(timezone(timedelta(hours=8))).isoformat(),
                   "phase": "paired_paid_lifecycle_preparation",
                   "actualSnapshotControls": controls,
                   "unfinishedSnapshotControls": unfinished,
                   "validatedEmptySnapshotTaskIds": sorted({r["taskId"] for r in controls if r["validated"] and r["control"] == "empty"}),
                   "validatedPositiveSnapshotTaskIds": sorted({r["taskId"] for r in controls if r["validated"] and r["control"] == "positive"}),
                   "validatedWrongSnapshotTaskIds": sorted({r["taskId"] for r in controls if r["validated"] and r["control"] == "wrong"}),
                   "snapshotSourcePins": [{"path": str(path), "sha256": sha(path)} for path in sorted(Path(__file__).parent.glob("*.py"))],
                   "allOwnedSnapshotControlsClosed": not unfinished and all(r["allClosed"] for r in controls),
                   "privateGraderControlsComplete": all(len({r["taskId"] for r in controls if r["validated"] and r["control"] == kind}) == 12 for kind in ("empty", "positive", "wrong")), "executionProtocolFrozen": False,
                   "freshCashAdmissionComplete": False, "freshResourceAdmissionComplete": False,
                   "sharedPaidLockAcquired": status.get("sharedPaidLockAcquired", False), "newProjectLlmRequests": status.get("newProjectLlmRequests", 0),
                   "next": "Finish independent financial close certificate and fresh owned absence; freeze paid entry, refresh cash/cross-family admission, then run twelve real paired U/F tasks within 9 CNY and package/review"})
    directive = preparation / "user-resource-directive.json"
    if directive.exists():
        status["userResourceDirective"] = {"path": str(directive), "sha256": sha(directive), "data": json.loads(directive.read_bytes())}
    status["newPaidBudgetCny"] = "9"
    status["operationalHeadroomCny"] = "0"
    status["retainedUnknownCarryCny"] = "8.39218"
    status["paidRealTaskRuns"] = status.get("paidRealTaskRuns", 0)
    status["latestCoreColdAudit"] = str(preparation / "paired-cold/repair-2026-10-09T10-35-00-679Z/independent-audit.json")
    status["hardStorageQuotaSupported"] = False
    status["hardStorageQuotaProbe"] = str(preparation / "storage-probes/c61a0504a9714ac298c45f6070fdd8cf/probe.json")
    if cash:
        balance = json.loads(cash[-1].read_bytes())
        status["latestReadOnlyCashObservation"] = {"path": str(cash[-1]), "sha256": sha(cash[-1]), "data": balance}
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": str(status_path), "empty": len(status["validatedEmptySnapshotTaskIds"]),
                      "positive": len(status["validatedPositiveSnapshotTaskIds"]),
                      "wrong": len(status["validatedWrongSnapshotTaskIds"]),
                      "unfinished": len(unfinished), "modelCalls": 0}))


if __name__ == "__main__":
    main()
