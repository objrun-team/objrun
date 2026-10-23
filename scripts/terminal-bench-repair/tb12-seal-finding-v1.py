"""Record the initial seal-timing qualification from actual completed traces."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
home = ROOT / "docs/repair-2026-10-09/tb12-runs-v1/repair-2026-10-09T11-20-29-976Z"
notes, input_pins = [], []
for path in sorted(home.glob("task-*.json")):
    value = json.loads(path.read_bytes())
    if value["arm"] != "F":
        continue
    denied = []
    for row in value["trace"]:
        if row["kind"] != "tool":
            continue
        body = json.loads(row["body"])
        if body.get("name") in {"bash", "read", "write", "edit", "glob", "grep"} and "/place returned 409" in str(body.get("value")) and row["at"] < value["deadlineUnixMs"] - 10000:
            denied.append({"unit": row["unit"], "seq": row["seq"], "at": row["at"], "tool": body["name"], "value": body["value"]})
    if denied:
        notes.append({"taskId": value["officialId"], "arm": "F", "preDeadlineClosedToolCount": len(denied), "rawDeniedRows": denied})
    input_pins.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
assert notes
target = home / "independent/seal-finding.json"
target.write_text(json.dumps({"protocol": "tb12-initial-seal-qualification-v1", "runId": home.name,
                              "fairPairedComparisonQualified": False, "finding": "Host sealed on the first submit trace marker, including markers whose calls did not run; F then received 409 while its deadline remained live.",
                              "correction": "Revision 2 keeps runtime grading serialized and snapshots atomic, allows repair after failed F units, and permanently seals only after actual terminal state with no pending provider transfer.",
                              "initialCompletedRecords": 17, "actualRealRequests": 531, "knownNewNanoCny": "1862330240",
                              "allInitialExpensesConsumeTheSame9CnyBudget": True,
                              "evidence": notes, "inputPins": input_pins, "modelCallsByReviewer": 0}, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"finding": str(target), "affectedCompletedFTasks": len(notes), "modelCalls": 0}))
