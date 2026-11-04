"""Score immutable cumulative candidates against the pinned SciCode-Verified release."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
HOME = ROOT / ".phase1-data/scicode-verified"
VENDOR = HOME / "vendor/scicode-verified"
DATASET = VENDOR / "scicode_verified/problems_test.jsonl"
TARGETS = HOME / "test_data_cleaned.h5"
MANIFEST = json.loads((VENDOR / "scicode_verified/manifest.json").read_text(encoding="utf-8"))
if hashlib.md5(DATASET.read_bytes()).hexdigest() != MANIFEST["problems_test_jsonl_md5"]:
    raise RuntimeError("SciCode-Verified problem manifest mismatch")
PROBLEMS = {str(p["problem_id"]): p for p in map(json.loads, DATASET.read_text(encoding="utf-8").splitlines())}
# Fixed before model generation. Class/helper-dependent problems remain an explicit follow-up.
PILOT_IDS = ["5", "8", "9", "11", "12", "14", "15", "16", "17", "18"]

def score(problem_id: str, step_index: int, code: str, image="objrun-scicode:phase1", seconds=90):
    problem = PROBLEMS[problem_id]
    request = {"code": code, "problem": {"required_dependencies": problem["required_dependencies"]}, "step": problem["sub_steps"][step_index], "seconds": seconds}
    command = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--user", "0:0", "--cap-drop", "ALL", "--cap-add", "SETUID", "--cap-add", "SETGID", "--cap-add", "KILL", "--security-opt", "no-new-privileges", "--memory", "2g", "--cpus", "2", "--pids-limit", "128", "--tmpfs", "/tmp:rw,nosuid,size=512m"]
    for name in ["grade.py", "worker.py", "codec.py"]:
        command += ["--mount", f"type=bind,source={HERE / name},target=/worker/{name},readonly"]
    compare = ROOT / ".phase1-data/scicode/vendor/SciCode/src/scicode/compare"
    command += ["--mount", f"type=bind,source={VENDOR / 'eval_clean/vendor'},target=/root/vendor,readonly", "--mount", f"type=bind,source={compare},target=/root/scicode-extra/scicode/compare,readonly", "--mount", f"type=bind,source={TARGETS},target=/root/oracle/test_data_cleaned.h5,readonly", "-e", "OPENBLAS_NUM_THREADS=1", "-e", "OMP_NUM_THREADS=1", image, "python", "-I", "/worker/grade.py"]
    try:
        result = subprocess.run(command, input=json.dumps(request), capture_output=True, text=True, timeout=seconds + 30)
    except subprocess.TimeoutExpired:
        return {"passed": False, "valid": False, "errorType": "GraderTimeout"}
    if result.returncode:
        return {"passed": False, "valid": False, "errorType": "GraderProcessError", "diagnostic": result.stderr[-1000:]}
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        return {"passed": False, "valid": False, "errorType": "GraderProtocolError"}

def selfcheck(ids):
    records = []
    for problem_id in ids:
        problem = PROBLEMS[problem_id]
        cumulative = problem["required_dependencies"]
        for index, step in enumerate(problem["sub_steps"]):
            reference = step.get("ground_truth_code")
            if problem_id == "5" and index == 0:
                reference = (HERE / "fixtures/lanczos.py").read_text(encoding="utf-8")
            if not reference:
                records.append({"problem": problem_id, "step": step["step_number"], "kind": "reference_unavailable", "passed": False, "valid": False})
                continue
            cumulative += "\n\n" + reference
            result = score(problem_id, index, cumulative)
            record = {"problem": problem_id, "step": step["step_number"], "kind": "reference", **result}
            records.append(record)
            print(json.dumps(record), flush=True)
    if "5" in ids:
        for label, code in [("wrong", "import numpy as np\ndef lanczos(A,b,m): return np.zeros((len(b),m+1))"), ("syntax_error", "def broken("), ("read_hidden_targets", "open('/root/oracle/test_data_cleaned.h5','rb').read()"), ("read_reference_fixture", "open('/worker/fixtures/lanczos.py').read()"), ("exit_without_tests", "import os\nos._exit(0)")]:
            result = score("5", 0, code)
            record = {"problem": "5", "kind": label, **result, "checkPassed": bool(result.get("valid")) and not result.get("passed")}
            records.append(record)
            print(json.dumps(record), flush=True)
    output = ROOT / ".scratch/phase1/scicode-selfcheck.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    passed = all(r.get("valid") and r.get("passed") if r["kind"] == "reference" else r.get("checkPassed", False) for r in records)
    output.write_text(json.dumps({"variant": "SciCode-Verified v2", "ids": ids, "records": records, "allPassed": passed}, indent=2) + "\n", encoding="utf-8")
    return passed

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--selfcheck", nargs="*", default=None)
    args = parser.parse_args()
    if args.selfcheck is not None:
        raise SystemExit(0 if selfcheck(args.selfcheck or PILOT_IDS) else 1)
