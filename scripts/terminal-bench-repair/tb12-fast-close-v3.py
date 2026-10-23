"""Minimal join and exact-owner lock release for the two corrected processes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def read(path):
    return json.loads(path.read_bytes())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", required=True)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    master = Path(args.master).resolve()
    assert master.is_relative_to(ROOT / "docs/repair-2026-10-09/tb12-fast-runs-v3")
    manifest = read(master / "manifest.json")
    homes = [ROOT / "docs/repair-2026-10-09/tb12-runs-v1" / (manifest["runId"] + "-1"),
             Path(read(master / "process-lane-0.json")["output"])]
    closures = []
    pairs = set()
    for home in homes:
        summary = read(home / "summary.json")
        assert summary["operationalComplete"] and summary["fatal"] is None
        assert summary["standClose"] and summary["financialClose"]
        cash = read(Path(summary["financialClose"]["cashClose"]["path"]))
        assert cash["releasePermitted"] is True
        for path in home.glob("task-*.json"):
            record = read(path)
            assert record["acceptance"]["valid"]
            pair = (record["officialId"], record["arm"])
            assert pair not in pairs
            pairs.add(pair)
        closures.append({"home": str(home), "summary": str(home / "summary.json"),
                         "standClose": summary["standClose"], "financialClose": summary["financialClose"]})
    assert pairs == {(task, arm) for task in manifest["taskIds"] for arm in ("U", "F")}
    lock = ROOT / ".phase1-data/tb12-owned-fast-v3.lock.json"
    owned = read(lock)
    assert owned["runId"] == manifest["runId"] and owned["ownerNonce"] == "3bf9f1843d5461a1cd7b104f378e9747d72aded27119c48a"
    receipt = {"runId": manifest["runId"], "owned": owned, "completedValidRuns": 24,
               "allCorrectedLaneClosuresObserved": True, "laneClosures": closures,
               "fullIndependentCertification": "pending", "atUtc": datetime.now(timezone.utc).isoformat()}
    flag = master / "all-process-lanes-closed.json"
    if args.release:
        prior = read(flag)
        assert prior["owned"] == owned and prior["completedValidRuns"] == 24
        lock.unlink()  # The read-handle holder must have observed the join flag and exited.
        receipt["exactOwnBenchLockRemoved"] = True
        destination = master / "bench-lock-release.json"
    else:
        destination = flag
    destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(destination), "completedValidRuns": 24, "released": args.release}))

if __name__ == "__main__":
    main()
