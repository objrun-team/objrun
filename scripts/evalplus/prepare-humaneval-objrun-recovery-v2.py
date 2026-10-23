"""V2: prepare one post-full infrastructure recovery pass for the frozen Bench runner.

No model calls, scoring changes, or edits to the runner/core. Failed request trees
stay below calls/ so the existing recursive cost ledger still counts every call.
Successful cached responses and all valid result files remain in place.
"""
import argparse
import datetime
import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "docs/evalplus-20261012"
OUT = BASE / "humaneval/objrun-adapter-v1/full"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def within(path, root):
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise RuntimeError("RecoveryPathOutsideOwnResultRoot: " + str(path))
    return path


def transient(receipt):
    if not receipt or receipt.get("fault") == "ExplicitRateLimit":
        return False
    status = receipt.get("httpStatus")
    return (status == 0 and receipt.get("unknownCost") is True) or status in (408, 500, 502, 503, 504) or (
        status == 200 and re.search(r"timed? out|timeout|socket.*closed|connection.*closed|network connection lost|connection reset", str(receipt.get("fault", "")), re.I)
    )


def process_is_owned(row, engines):
    name = str(row.get("Name", "")).lower()
    command = row.get("CommandLine")
    if name and name != "bun.exe":
        return False
    if command and re.search(r"run-humaneval-objrun-adapter\.ts", command):
        return True
    matches = [engine for engine in engines if engine["pid"] == row.get("ProcessId")]
    if not matches:
        return False
    if not command or not row.get("CreationUtc") or not name:
        return True  # Ambiguous actual Bun identity must not permit a restart.
    born = datetime.datetime.fromisoformat(row["CreationUtc"].replace("Z", "+00:00"))
    for engine in matches:
        recorded = datetime.datetime.fromisoformat(engine["atUtc"].replace("Z", "+00:00"))
        # This evidence is saved after machine() returns. A newer process with
        # the old numeric PID is unrelated, even if it is another Bun engine.
        if born > recorded:
            continue
        if str(ROOT / "app/src/main.ts").replace("/", "\\").lower() in command.replace("/", "\\").lower():
            return True
    return False


def process_snapshot(out):
    ids = set()
    engines = []
    for p in [out / "status.json", out / "launch.json", out / "runner-lock.json", *out.glob("tasks/objrun/*/engine-process.json")]:
        if p.exists():
            record = read(p)
            if record.get("pid"):
                ids.add(int(record["pid"]))
                if p.name == "engine-process.json":
                    engines.append(record)
    literal = ",".join(str(pid) for pid in sorted(ids)) or "0"
    command = "@(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in @(" + literal + ") -or ($_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run-humaneval-objrun-adapter\\.ts') } | Select-Object ProcessId,Name,@{Name='CreationUtc';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}},CommandLine) | ConvertTo-Json -Compress"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not result.stdout.strip():
        return {"live": [], "ignoredReusedProcesses": []}
    value = json.loads(result.stdout)
    rows = value if isinstance(value, list) else [value]
    return {"live": [r for r in rows if process_is_owned(r, engines)],
            "ignoredReusedProcesses": [r for r in rows if not process_is_owned(r, engines)]}


def make_plan(out, expected, live):
    rows = [(p, read(p)) for p in sorted((out / "results/objrun").glob("*.json"))]
    actual = [row.get("officialId") for _, row in rows]
    pending = [str(p.parent) for p in (out / "calls").rglob("dispatch.json") if not (p.parent / "receipt.json").exists()]
    guards = []
    if live:
        guards.append("OwnedRunnerOrEngineStillLive")
    if pending:
        guards.append("DispatchWithoutReceiptRequiresEvidenceReconciliation")
    if sorted(actual) != sorted(expected) or len(set(actual)) != len(expected):
        guards.append("WaitForEntireFixedTaskList")
    plan = {"atUtc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "resultRoot": str(out),
            "guards": guards, "liveProcesses": live, "pendingRequests": pending,
            "completed": len(rows), "valid": sum(bool(r.get("grade", {}).get("valid")) for _, r in rows),
            "targets": [], "blockedTasks": []}
    for path, row in rows:
        if row.get("grade", {}).get("valid"):
            continue
        tid = row["officialId"]
        if not re.fullmatch(r"HumanEval/\d+", tid) or path.name != tid.replace("/", "-") + ".json":
            raise RuntimeError("UnexpectedResultIdentity: " + str(path))
        target = {"officialId": tid, "resultPath": str(path)}
        if "answer" in row:
            if row.get("candidateHow") != "submitted":
                plan["blockedTasks"].append({"officialId": tid, "reason": "CandidateIsNotNativeSubmittedNeedsDiagnosis"})
                continue
            target["action"] = "regrade_existing_candidate"
            plan["targets"].append(target)
            continue
        if row.get("interfaceFailure"):
            calls = out / "calls/objrun" / tid.replace("/", "-") / "schema-v3"
            failed = []
            for group in sorted(calls.glob("*/attempt-*")):
                original = read(group / "receipt.json") if (group / "receipt.json").exists() else None
                retry = group / "authorized-interface-retry-1/receipt.json"
                terminal = read(retry) if retry.exists() else original
                # Retain groups whose retry succeeded. Only invalidate transient
                # failures (or an explicitly rejected, exhausted rate limit).
                if transient(terminal) or (terminal and terminal.get("fault") == "ExplicitRateLimit"):
                    failed.append(str(group))
            if failed:
                target.update(action="retry_interface_task", failedRequestGroups=failed)
                plan["targets"].append(target)
            else:
                plan["blockedTasks"].append({"officialId": tid, "reason": "NoDurableTransientFailureToRetry", "error": row.get("error")})
        else:
            # Setup/engine errors need a diagnosis before restarting a task; a
            # solver error or missing submit must never become a retry target.
            plan["blockedTasks"].append({"officialId": tid, "reason": "EnvironmentOrRunnerFailureNeedsDiagnosis", "error": row.get("error")})
    return plan


def apply_plan(out, plan):
    if plan["guards"]:
        raise RuntimeError("RecoveryNotAtSafeBoundary: " + ", ".join(plan["guards"]))
    round_number = 1
    while (out / "recovery" / ("validity-pass-%04d.json" % round_number)).exists():
        round_number += 1
    label = "validity-pass-%04d" % round_number
    record = {**plan, "round": round_number, "state": "preparing", "moves": [],
              "runnerCodeChanged": False, "coreModified": False, "scoringChanged": False,
              "authorizedBy": "2026-10-12 user: retry abnormal tasks after full run until all tasks valid"}
    record_path = within(out / "recovery" / (label + ".json"), out)
    if not plan["targets"]:
        return {**record, "state": "no_action", "launchRequired": False}
    moves = []
    for target in plan["targets"]:
        if target["action"] == "regrade_existing_candidate":
            if read(Path(target["resultPath"])).get("interfaceRetryExhausted"):
                raise RuntimeError("CandidateRegradeBlockedByUnexpectedInterfaceState: " + target["officialId"])
            continue
        short = target["officialId"].replace("/", "-")
        task = out / "tasks/objrun" / short
        calls = out / "calls/objrun" / short
        history = task / "retained-recovery" / label
        # Preserve the native database and evidence, then use the same pinned
        # runner with the successful responses still in its cache namespace.
        for name in ("engine", "engine-process.json", "trace.json", "submit-response-attempts.json", "candidate.json"):
            source = task / name
            if source.exists():
                moves.append((source, history / name))
        for source in target["failedRequestGroups"]:
            source = Path(source)
            moves.append((source, calls / "retained-recovery" / label / source.relative_to(calls)))
        moves.append((Path(target["resultPath"]), history / "result.json"))
    for source, destination in moves:
        within(source, out)
        within(destination, out)
        if not source.exists() or destination.exists():
            raise RuntimeError("RecoveryMovePreconditionChanged: " + str(source))
        record["moves"].append({"source": str(source), "destination": str(destination)})
    save(record_path, record)
    for source, destination in moves:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
    record.update(state="ready_for_same_frozen_runner", launchRequired=True)
    save(record_path, record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Prepare one recovery pass after all runner/engine PIDs exit.")
    args = parser.parse_args()
    for pin in (BASE / "source-pins.json", BASE / "humaneval/objrun-adapter-v1-source-pins.json", BASE / "humaneval/objrun-validity-recovery-source-pins.json", BASE / "humaneval/objrun-validity-recovery-v2-source-pins.json"):
        for item in read(pin)["files"]:
            if hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError("FrozenSourceChanged: " + item["path"])
    processes = process_snapshot(OUT)
    plan = make_plan(OUT, read(BASE / "humaneval/task-ids.json"), processes["live"])
    plan.update(recoveryAdapterVersion="validity-recovery-v2", ignoredReusedProcesses=processes["ignoredReusedProcesses"])
    result = apply_plan(OUT, plan) if args.apply else {**plan, "dryRun": True}
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
