"""Official live-service empty/oracle/negative checks; no LLM or image pulls."""
import argparse
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "examples/benchmark/terminal-bench"
SPEC = importlib.util.spec_from_file_location("tb_private_verifier", BENCH / "isolated_verifier.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
CORPUS = ROOT / ".phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks"

SPY = r"""
import json,os,time
from pathlib import Path
out=Path('/tmp/spy-observations.json')
seen={'privateFiles':False,'privateSecrets':False}
while True:
    for p in [Path('/tests/test_outputs.py'),Path('/stage/tests/test_outputs.py'),Path('/logs/verifier/test-stdout.txt'),*Path('/proc').glob('[0-9]*/root/tests/test_outputs.py')]:
        try:
            if p.is_file(): seen['privateFiles']=True
        except OSError: pass
    for p in [Path('/tests/hidden-marker.txt'),Path('/stage/tests/hidden-marker.txt'),Path('/logs/verifier/test-stdout.txt'),*Path('/proc').glob('[0-9]*/root/tests/hidden-marker.txt')]:
        try:
            if 'PRIVATE-GRADER-' in p.read_text(): seen['privateFiles']=True
        except (OSError,UnicodeError): pass
    for p in Path('/proc').glob('[0-9]*/environ'):
        try:
            b=p.read_bytes()
            if b'OBJRUN_STATE_TOKEN=' in b or b'TGENGIN_GRADER_TOKEN=' in b: seen['privateSecrets']=True
        except OSError: pass
    out.write_text(json.dumps(seen))
    time.sleep(.03)
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--empty-only", action="store_true", help="strengthen the observer probe without repeating oracle/live-service preflight")
    parser.add_argument("--observer-only", action="store_true", help="report confidentiality independently if official dependency installation fails; never validate that score")
    args = parser.parse_args()
    tid = VERIFIER.TASK_ID
    directory = CORPUS / tid
    definition = tomllib.loads((directory / "task.toml").read_text(encoding="utf-8"))
    task = {"id": tid, "dir": str(directory), "cpus": str(definition["environment"]["cpus"]),
            "memory_mb": definition["environment"]["memory_mb"], "workdir": "/app", "verify_seconds": int(definition["verifier"]["timeout_sec"])}
    name = "objrun-tb-service-probe-" + uuid.uuid4().hex[:12]
    output = ROOT / "docs/repair-2026-10-08/tb-live-isolation"
    output.mkdir(parents=True, exist_ok=True)
    run = output / ("probe-" + uuid.uuid4().hex[:10])
    run.mkdir()
    report = {"taskId": tid, "imageId": VERIFIER.IMAGE_ID, "sourceHashes": VERIFIER.SOURCE_HASHES, "protocol": VERIFIER.PROTOCOL,
              "llmRequests": 0, "imagePulls": False, "privateFilesNeverCopiedToCandidate": True, "phases": {},
              "validationScope": "observer_independent_of_grading_validity" if args.observer_only else ("empty_and_observer" if args.empty_only else "empty_oracle_live_negative_and_observer"),
              "observerDetectsAnyTestOrStdoutFile": True}
    def save():
        (run / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    try:
        VERIFIER.checked("run", "--pull", "never", "-d", "--name", name, "--network", "bridge", "--cpus", task["cpus"],
                         "--memory", str(task["memory_mb"]) + "m", "--memory-swap", str(task["memory_mb"]) + "m",
                         "-w", "/app", VERIFIER.IMAGE_ID, "sleep", "infinity")
        # A detached watcher is part of the untrusted solving state.
        VERIFIER.checked("exec", "-d", name, "python3", "-c", SPY)
        for phase in (("empty",) if args.empty_only or args.observer_only else ("empty", "oracle", "service-stopped")):
            if phase == "oracle":
                VERIFIER.checked("cp", str(directory / "solution") + "/.", name + ":/solution")
                execution = VERIFIER.docker("exec", "-e", "DEBIAN_FRONTEND=noninteractive", name, "bash", "/solution/solve.sh", timeout=int(definition["agent"]["timeout_sec"]))
                (run / "oracle-execution.txt").write_text(execution.stdout + execution.stderr, encoding="utf-8")
                report["oracleExecutionCode"] = execution.returncode
                if execution.returncode:
                    raise RuntimeError("official oracle execution failed")
            elif phase == "service-stopped":
                VERIFIER.checked("exec", name, "nginx", "-s", "stop")
            got = VERIFIER.run_verifier(task, name, run)
            tests = got.pop("_tests", [])
            got["officialTests"] = len(tests)
            got["passedTests"] = sum(test.get("status") == "passed" for test in tests)
            report["phases"][phase] = got
            save()
            print(json.dumps({"phase": phase, **got}), flush=True)
            if got.get("crashed") or got.get("ran") is not True:
                if args.observer_only:
                    report["officialGradingValid"] = False
                    break
                raise RuntimeError("the private official test set did not complete")
            assert got["reward"] == (1 if phase == "oracle" else 0), "live-service positive/negative verdict mismatch"
        spy = VERIFIER.checked("exec", name, "cat", "/tmp/spy-observations.json")
        report["maliciousObserver"] = json.loads(spy.stdout)
        assert report["maliciousObserver"] == {"privateFiles": False, "privateSecrets": False}
        # A public synthetic file, written only after the grading phase, proves
        # that "false" was not caused by a detector that cannot notice stdout.
        VERIFIER.checked("exec", name, "sh", "-c", "mkdir -p /logs/verifier; printf '%s' 'PUBLIC-DETECTOR-CONTROL' > /logs/verifier/test-stdout.txt")
        for _ in range(20):
            control = json.loads(VERIFIER.checked("exec", name, "cat", "/tmp/spy-observations.json").stdout)
            if control["privateFiles"]:
                break
            time.sleep(.05)
        assert control["privateFiles"] is True
        report["observerPositiveControl"] = {"publicSyntheticStdoutDetected": True, "afterGrading": True}
        report["observerValidated"] = True
        report.setdefault("officialGradingValid", True)
        report["validated"] = report["officialGradingValid"]
        save()
        print(json.dumps({"validated": report["validated"], "observerValidated": True, "officialGradingValid": report["officialGradingValid"], "report": str(run / "report.json")}), flush=True)
    except Exception as error:
        report["validated"] = False
        report["failure"] = type(error).__name__ + ": " + str(error)
        save()
        raise
    finally:
        VERIFIER.docker("rm", "-f", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
