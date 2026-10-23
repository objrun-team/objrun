"""Exercise Windows writer detection with our harmless, hidden child processes.

Fixtures only wait: no E writes, downloads, compiler, candidate or model calls.
All child handles are stopped and waited by the parent before exporting proof.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["red", "green"])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = root / "scripts/benchmark-repair/minif2f_public_cache.py"
    spec = importlib.util.spec_from_file_location("actual_public_cache", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = root / ".phase1-data/minif2f-writer-probe-fixture" / args.mode
    fixture.mkdir(parents=True, exist_ok=False)
    for name in ["minif2f_restore.py", "minif2f_public_cache.py"]:
        (fixture / name).write_text("import time\ntime.sleep(90)\n", encoding="utf-8")
    (fixture / "minif2f_runtime.ps1").write_text(
        "param([string]$Stage)\nStart-Sleep -Seconds 90\n", encoding="utf-8")
    commands = [
        ("python_cache_download", [sys.executable, str(fixture / "minif2f_restore.py"), "cache-download"], True),
        ("python_acquire", [sys.executable, str(fixture / "minif2f_public_cache.py"), "acquire"], True),
        ("powershell_workspace", ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
                                  str(fixture / "minif2f_runtime.ps1"), "-Stage", "Workspace"], True),
        ("read_only_gate", [sys.executable, str(fixture / "minif2f_public_cache.py"), "gate"], False),
    ]
    children = []
    baseline = module.writer_probe()
    proof = None
    try:
        for label, command, write_stage in commands:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            children.append((label, child, write_stage))
        time.sleep(1)
        if any(child.poll() is not None for _, child, _ in children):
            raise RuntimeError("a harmless fixture exited before actual CIM observation")
        try:
            proof = module.writer_probe()
        except RuntimeError as error:
            prefix = "another observed writer overlaps the owned root: "
            if not str(error).startswith(prefix):
                raise
            proof = json.loads(str(error)[len(prefix):])
        hits = {row["pid"] for row in proof["host_conflicts"]}
        expected = {child.pid for _, child, write_stage in children if write_stage}
        gate_pids = {child.pid for _, child, write_stage in children if not write_stage}
        if args.mode == "red" and hits & expected:
            raise RuntimeError("old implementation did not reproduce the expected missed writers")
        if args.mode == "green" and not expected <= hits:
            raise RuntimeError("corrected detection missed an actual live write-stage fixture")
        if gate_pids & hits:
            raise RuntimeError("read-only Gate fixture was incorrectly classified as a writer")
        report = {"mode": args.mode, "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "observedAt": datetime.now(timezone.utc).isoformat(), "baseline": baseline,
                  "actualCimProof": proof, "fixtures": [
                      {"label": label, "pid": child.pid, "writeStage": write_stage,
                       "detected": child.pid in hits, "aliveAtObservation": True}
                      for label, child, write_stage in children],
                  "regressionPassed": True, "eWrite": False, "download": False,
                  "candidateRun": False, "llmCalled": False}
    finally:
        for _, child, _ in children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
        if any(child.poll() is None for _, child, _ in children):
            raise RuntimeError("our harmless child cleanup did not close")
    report["ownedChildrenAllExited"] = True
    output = root / "docs/repair-2026-10-08/minif2f-writer-probe" / (args.mode + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise RuntimeError("preserve previous regression evidence; no overwrite")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"mode": args.mode, "passed": True, "expectedWriters": len(expected),
                      "actualWritersDetected": len(hits & expected), "readOnlyGateFalsePositive": False,
                      "ownedChildrenAllExited": True, "eWrite": False, "llmCalled": False}))


if __name__ == "__main__":
    main()
