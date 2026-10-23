"""Read-only handoff verification and SkillsBench-only status observations."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/repair-2026-10-08"
STATUS = DOCS / "parallel-bench-handoff-2026-10-09/skillsbench-status.json"
HOME = DOCS / "skillsbench-ten-takeover-v1"
FIXED = {
    "skillsbench-ten-artifact-readonly-preflight/selection-v1/ten-task-list.json": "f4b8781fc636d67af17265bfffe41d9ff76195f4e9539d6cd37b5db6b29ee021",
    "skillsbench-ten-artifact-readonly-preflight/selection-v1/public-metadata.json": "6cab5bd04910a9a8e1cb5285c0d6ccd905a7e5b172af9b6373c3f711d61466ee",
    "skillsbench-ten-artifact-readonly-preflight/selection-v1/private-depot-and-adapter-plan.json": "6d32f483019f71eac076d7d1fb3c789c2ef23f4e7692a16eb0ebda9af35000a2",
    "skillsbench-ten-artifact-readonly-preflight/selection-v1/delivery.json": "f156a56bb551b53966a226591941e2fc207b6ccc9367d79d8bfb6a5e64fa8b9f",
    "skillsbench-ten-generic-draft-handoff-v1/handoff.json": "7156139d22d88a1e783f0f28de97eb45870b3faa4420d3690b25bf643a52f428",
    "skillsbench-ten-generic-draft-stop-2026-10-09T07-54-32Z/handoff.json": "f4a16bec60b0f6f26e8a4b150378420099dff01b08a7194a965ab48da76f84f9",
}


def pin(path):
    p = Path(path)
    a = p.lstat()
    if not stat.S_ISREG(a.st_mode) or getattr(a, "st_file_attributes", 0) & 0x400:
        raise RuntimeError("Ordinary regular handoff source required")
    with p.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    b = p.lstat()
    if (a.st_ino, a.st_size, a.st_mtime_ns) != (b.st_ino, b.st_size, b.st_mtime_ns):
        raise RuntimeError("Handoff source changed while reading")
    return {"path": str(p), "bytes": a.st_size, "sha256": digest}


def durable(path, value, replace=False):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    dest = p.with_name(p.name + ".next") if replace else p
    with dest.open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    if dest.read_bytes() != raw:
        raise RuntimeError("Status readback mismatch")
    if replace:
        os.replace(dest, p)
    return pin(p)


def observe():
    pins = []
    for name, sha in FIXED.items():
        actual = pin(DOCS / name)
        if actual["sha256"] != sha:
            raise RuntimeError("Frozen handoff identity changed: " + name)
        pins.append(actual)
    counts = {"draftSources": 0, "draftSnapshots": 0, "protectedSources": 0, "originalTaskFiles": 0}
    source_pins = []
    for name in ("skillsbench-ten-generic-draft-handoff-v1/handoff.json", "skillsbench-ten-generic-draft-stop-2026-10-09T07-54-32Z/handoff.json"):
        data = json.loads((DOCS / name).read_bytes())
        for row in data.get("sourceRows", []) + data.get("draftSourceAndSnapshotPins", []):
            for key, count in (("sourcePin", "draftSources"), ("snapshotPin", "draftSnapshots")):
                expected = row[key]
                if pin(expected["path"]) != expected:
                    raise RuntimeError("Stopped draft identity changed: " + expected["path"])
                source_pins.append(expected)
                counts[count] += 1
        for expected in data.get("protectedJpgSourcesUnchanged", []):
            if pin(expected["path"]) != expected:
                raise RuntimeError("Protected JPG source changed")
            source_pins.append(expected)
            counts["protectedSources"] += 1
    metadata = json.loads((DOCS / "skillsbench-ten-artifact-readonly-preflight/selection-v1/public-metadata.json").read_bytes())
    for row in metadata["tasks"]:
        expected = row["taskSourcePin"]
        if pin(expected["path"]) != expected:
            raise RuntimeError("Original task.md changed")
        counts["originalTaskFiles"] += 1
        for scope in ("environmentSource", "verifierSource", "oracleSourceMetadata"):
            tree = row[scope]
            for item in tree["files"]:
                actual = pin(Path(tree["root"]) / item["path"])
                if actual["bytes"] != item["bytes"] or actual["sha256"] != item["sha256"]:
                    raise RuntimeError("Original task source/fixture changed")
                counts["originalTaskFiles"] += 1
    lock_path = ROOT / ".phase1-data/owned-paid-campaign.lock.json"
    free = {x: shutil.disk_usage(x + ":/").free for x in ("C", "D", "F")}
    receipt = {
        "protocol": "skillsbench-ten-takeover-readonly-v1",
        "observedAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourcePin": pin(__file__), "handoffPins": pins, "stoppedAndProtectedSourcePins": source_pins,
        "verifiedCounts": counts, "allCheckedPinsMatch": True,
        "volumeFreeBytes": free, "CMinimumFreeBytes": 1024**3,
        "resourceAdmitted": free["C"] >= 1024**3 and free["D"] >= 6*1024**3 and free["F"] >= 12*1024**3,
        "paidLockObservation": {"exists": lock_path.exists(), "pin": pin(lock_path) if lock_path.exists() else None},
        "modelCalls": 0, "DockerOperations": 0, "DOrEWrites": 0,
        "paidReady": False, "realDistinctTasksCompleted": 0,
    }
    suffix = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    receipt_pin = durable(HOME / ("takeover-" + suffix + ".json"), receipt)
    state = {
        "protocol": "skillsbench-independent-chat-status-v1", "updatedAtUtc": receipt["observedAtUtc"],
        "phase": "implementing-ten-task-runtime", "selectedDistinctTasks": 10, "plannedTaskRuns": 20,
        "completedRealDistinctTasks": 0, "completedRealTaskRuns": 0, "realModelCalls": 0,
        "takeoverReceiptPin": receipt_pin, "frozenHandoffsVerified": True,
        "volumeFreeBytes": free, "CResourceGatePassed": free["C"] >= 1024**3,
        "paidLockExistsAtObservation": lock_path.exists(), "paidReady": False,
        "remaining": ["new ABI and route receipt controls", "nine actual solver builds", "sealed private runtime and ten full collections", "ten empty/oracle/wrong controls and owned closure", "source-bound cash/resource/lock admission", "ten same-task U/F real trials", "complete package and independent review"],
        "full87Authorized": False, "historical85_1Certified": False,
    }
    durable(STATUS, state, replace=STATUS.exists())
    print(json.dumps({"receiptPin": receipt_pin, "verifiedCounts": counts, "volumeFreeBytes": free, "resourceAdmitted": receipt["resourceAdmitted"], "paidLockExists": lock_path.exists(), "realModelCalls": 0}))


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    observe()
