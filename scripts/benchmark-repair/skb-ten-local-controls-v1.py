"""Archive SkillsBench-only local controls; never starts Docker or a provider."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / "docs/repair-2026-10-08/skillsbench-ten-takeover-v1"
BUN = "C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe"
PYTHON = "D:/ProgramData/anaconda3/python.exe"


def save(path, raw):
    with path.open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    if path.read_bytes() != raw:
        raise RuntimeError("Control evidence readback failed")
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("core", "python"))
    a = p.parse_args()
    command = [BUN, "test", "test/skb-ten-core-v2.test.ts"] if a.mode == "core" else [
        PYTHON, "-B", "-X", "utf8", "test/skb-ten-private-v2_test.py"]
    directory = HOME / "local-control-runs" / (a.mode + "-" + uuid.uuid4().hex)
    directory.mkdir(parents=True, exist_ok=False)
    source_directory = directory / "source-snapshots"; source_directory.mkdir()
    names = ["skb-artifact-journal-core-v2.ts", "skb-artifact-journal-contract-v2.ts", "skb-artifact-journal-campaign-v2.ts",
             "skb-artifact-storage-v2.ts", "skb-artifact-native-service-v2.ts", "skb_artifact_task_v2.py",
             "skb_artifact_private_eval_v2.py", "skb_artifact_capture_v2.py", "skb_artifact_transport_v2.py",
             "skb_artifact_storage_v2.py", "skb_artifact_ram_plan_v2.py", "campaign-journal.ts", "scientific-journal-proxy.ts",
             "paid-resource-proof-v2.ts", "paid-resource-admission-v2.ts", "cny-cash-shadow-v2.ts", "campaign-contract.ts",
             "skb_artifact_ram_executor_v2.py", "skb_artifact_build_storage_v1.py", "skb_artifact_build_audit_v2.py",
             "skb_artifact_native_identity_v2.py", "skb_artifact_solver_plan_v2.py", "skb_artifact_solver_v2.py",
             "skb_artifact_ready_v2.py", "skb_artifact_grade_audit_v2.py"]
    names=sorted(set(names)|{q.name for q in (ROOT/'scripts/benchmark-repair').glob('skb*') if q.suffix in ('.ts','.py','.json')}|
                 {q.name for q in (ROOT/'scripts/benchmark-repair').glob('audit-skb-artifact*') if q.is_file()})
    source_snapshots = []
    for source in [ROOT / command[-1], *(ROOT / "scripts/benchmark-repair" / name for name in names)]:
        if source.exists():
            raw = source.read_bytes()
            snapshot = save(source_directory / source.name, raw)
            source_snapshots.append({"originalPath": str(source), "snapshotPin": snapshot})
    started = datetime.now(timezone.utc).isoformat()
    child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timed_out = False
    try:
        out, err = child.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        timed_out = True
        child.kill()
        out, err = child.communicate(timeout=10)
    if len(out) + len(err) > 8*1024**2:
        raise RuntimeError("Local control output unexpectedly exceeds8MiB")
    result = {"protocol": "skillsbench-ten-local-control-run-v1", "sourcePin": save(directory / "driver-source.py", Path(__file__).read_bytes()),
              "command": command, "cwd": str(ROOT), "childPid": child.pid, "startedAtUtc": started,
              "completedAtUtc": datetime.now(timezone.utc).isoformat(), "exitCode": child.returncode,
              "directChildClosed": True, "timedOut": timed_out,
              "sourceSnapshots": source_snapshots,
              "stdoutPin": save(directory / "stdout.txt", out), "stderrPin": save(directory / "stderr.txt", err),
              "modelCalls": 0, "DockerCommands": 0, "DOrEWrites": 0, "paidLockAcquired": False,
              "scope": "Local source/control evidence only; no actual benchmark trials or environment proof"}
    receipt = save(directory / "run.json", (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"runPin": receipt, "exitCode": child.returncode, "stdoutPin": result["stdoutPin"], "stderrPin": result["stderrPin"]}))
    if child.returncode:
        print(err.decode("utf-8", errors="replace")[-12000:])
    raise SystemExit(child.returncode or 0)


if __name__ == "__main__":
    main()
