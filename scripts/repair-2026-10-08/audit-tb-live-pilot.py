"""Read-only audit of a closed nginx pilot; never runs a model, grader, or container.

SQLite evidence is copied with its WAL/SHM before opening, even for reads. The
optional Docker checks use exact names derived from this run and inspect only.
This script does not certify generic TB isolation or a full benchmark score.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import tomllib
import zipfile

DEFAULT_RUN = "tb-nginx-2026-10-08T10-47-06-544Z"
TASK = "nginx-request-logging"
SIX = {"bash", "edit", "glob", "grep", "read", "write"}
GRADER_FILES = {"examples/benchmark/terminal-bench/" + n for n in
                ("stand.py", "isolated_verifier.py", "nginx_client.py",
                 "prepare_runtime.py", "prepare_verifier_dependencies.py", "objective.ts")}
GRADER_FILES.add("examples/benchmark/_lib/grader_status.py")
SINGLE_FILES = {"test/_lib.ts", "app/package.json", "app/bun.lock", "app/tsconfig.json",
                "scripts/phase1/source-snapshot.ts"}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def js_json(value) -> bytes:
    # These records have finite JSON numbers. JSON.stringify writes integral
    # numbers without '.0', keeps insertion order, and emits UTF-8 characters.
    def normalize(v):
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, list):
            return [normalize(x) for x in v]
        if isinstance(v, dict):
            return {k: normalize(x) for k, x in v.items()}
        return v
    return json.dumps(normalize(value), ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def ms(iso: str) -> int:
    return round(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def selected_source(name: str) -> bool:
    return (name.startswith("app/src/") or name.startswith("scripts/repair-2026-10-08/")
            or name in SINGLE_FILES or name in GRADER_FILES)


def inventory(directory: Path) -> list[dict]:
    return [{"path": p.relative_to(directory).as_posix(), "bytes": p.stat().st_size,
             "sha256": file_digest(p)}
            for p in sorted(directory.rglob("*")) if p.is_file()]


def usage_counts(usage: dict) -> tuple[int, int, int]:
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    cached = usage.get("prompt_cache_hit_tokens", usage.get("prompt_tokens_details", {}).get("cached_tokens", 0))
    if not all(type(n) is int and n >= 0 for n in (prompt, completion, cached)) or cached > prompt:
        raise ValueError("invalid provider token usage")
    return prompt, completion, cached


def completion_ok(data) -> bool:
    if not isinstance(data, dict) or data.get("error") or not data.get("choices"):
        return False
    for choice in data["choices"]:
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return False
        calls = message.get("tool_calls")
        if calls is not None:
            if not isinstance(calls, list):
                return False
            for call in calls:
                fn = call.get("function", {})
                if (call.get("type") != "function" or not isinstance(call.get("id"), str)
                        or not call["id"] or not isinstance(fn.get("name"), str) or not fn["name"]
                        or not isinstance(fn.get("arguments"), str)):
                    return False
        if not (isinstance(message.get("content"), str) or calls
                or isinstance(message.get("reasoning_content"), str) and message["reasoning_content"]):
            return False
        if message.get("content") is not None and not isinstance(message["content"], str):
            return False
    return True


class Audit:
    def __init__(self):
        self.checks = []
        self.keys: dict[str, bytes] = {}
        self.secret_hits: dict[str, list[str]] = {}
        self.scanned_public_files = set()
        self.scanned_zip_members = set()

    def check(self, name: str, ok, **details):
        self.checks.append({"name": name, "passed": bool(ok), **details})

    def scan(self, name: str, raw: bytes, zip_member=False):
        (self.scanned_zip_members if zip_member else self.scanned_public_files).add(name)
        for label, key in self.keys.items():
            if key in raw:
                self.secret_hits.setdefault(label, []).append(name)

    def scan_stream(self, name: str, stream):
        h, size, tail = hashlib.sha256(), 0, b""
        found = set()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
            size += len(block)
            combined = tail + block
            for label, key in self.keys.items():
                if key in combined:
                    found.add(label)
            tail = combined[-63:]
        self.scanned_zip_members.add(name)
        for label in found:
            self.secret_hits.setdefault(label, []).append(name)
        return h.hexdigest(), size


def copied_sqlite(store: Path, arm: str, scratch: Path):
    target = scratch / arm
    target.mkdir()
    for src in (store / ("worker-" + arm) / "data").glob("*.sqlite*"):
        shutil.copy2(src, target / src.name)
    return target


def candidate_from_db(db: sqlite3.Connection, task_id: str):
    task = dict(db.execute("select * from task where id=?", (task_id,)).fetchone())
    deadline = task["created_at"] + task["solve_seconds"] * 1000
    units = db.execute("select * from task_repair_tb where task=? order by unit desc", (task_id,)).fetchall()
    for unit in units:
        if unit["agent"] != "bot":
            raise ValueError("unexpected agent table; audit does not guess dynamic SQL identifiers")
        for row in db.execute("select * from agent_bot_msg where instance=? and unit=? and kind='call' and at<=? order by seq desc",
                              (unit["instance"], unit["unit"], deadline)):
            payload = json.loads(row["body"])
            for call in reversed(payload.get("calls", [])):
                if call.get("name") == "submit":
                    body = call.get("input", {}).get("answer", "")
                    body = body if isinstance(body, str) else ""
                    return task, body, dict(row), call["id"]
    return task, None, None, None


def exact_docker_observations(names: list[str], image_ids: list[str]) -> dict:
    rows = []
    for name in names:
        started = time.monotonic()
        try:
            done = subprocess.run(["docker", "inspect", "--format", "{{json .State}}", name],
                                  capture_output=True, text=True, timeout=5)
            text = (done.stderr + done.stdout).strip()
            absent = done.returncode != 0 and "no such object" in text.casefold() and name in text
            state = json.loads(done.stdout) if done.returncode == 0 else None
            rows.append({"name": name, "seconds": round(time.monotonic() - started, 4),
                         "exitCode": done.returncode, "daemonResponded": absent or done.returncode == 0,
                         "absent": absent, "state": state,
                         "diagnostic": text if done.returncode else ""})
        except subprocess.TimeoutExpired:
            rows.append({"name": name, "seconds": round(time.monotonic() - started, 4),
                         "daemonResponded": False, "absent": None, "diagnostic": "inspect timeout (5s)"})
    images = []
    for image in image_ids:
        started = time.monotonic()
        try:
            done = subprocess.run(["docker", "image", "inspect", "--format", "{{json .Id}}", image],
                                  capture_output=True, text=True, timeout=5)
            observed = json.loads(done.stdout) if done.returncode == 0 else None
            images.append({"expectedImageId": image, "observedImageId": observed,
                           "seconds": round(time.monotonic() - started, 4), "exitCode": done.returncode,
                           "matched": observed == image})
        except subprocess.TimeoutExpired:
            images.append({"expectedImageId": image, "seconds": round(time.monotonic() - started, 4),
                           "matched": False, "diagnostic": "image inspect timeout (5s)"})
    return {"observedAt": datetime.now(timezone.utc).isoformat(), "readOnly": True,
            "scope": "Exact two candidate names and four private-grader names derived from this run; two pinned images",
            "containers": rows, "images": images}


def host_observations(pids: list[int], ports: list[int]) -> dict:
    # Current process presence is corroboration only, not a historical exit code.
    process_rows = []
    for pid in pids:
        started = time.monotonic()
        command = ("$p=Get-Process -Id " + str(pid) + " -ErrorAction SilentlyContinue; "
                   "if($null -eq $p){ @{pid=" + str(pid) + ";present=$false}|ConvertTo-Json -Compress } "
                   "else { @{pid=$p.Id;present=$true;name=$p.ProcessName;start=$p.StartTime.ToUniversalTime().ToString('o')}|ConvertTo-Json -Compress }")
        try:
            done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                                  capture_output=True, text=True, timeout=5)
            row = json.loads(done.stdout) if done.returncode == 0 else {"pid": pid, "queryFailed": True}
            row["seconds"] = round(time.monotonic() - started, 4)
            process_rows.append(row)
        except (subprocess.TimeoutExpired, ValueError):
            process_rows.append({"pid": pid, "queryFailed": True})
    socket_rows = []
    ports = sorted(set(ports))
    command = ("$ErrorActionPreference='Stop'; $wanted=@(" + ",".join(map(str, ports)) + "); "
               "$active=[System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners(); "
               "$rows=@($wanted | ForEach-Object { $n=$_; $found=@($active | Where-Object {$_.Port -eq $n}); "
               "@{port=$n;listening=($found.Count -gt 0);addresses=@($found | ForEach-Object {$_.Address.ToString()})} }); "
               "ConvertTo-Json -InputObject $rows -Compress -Depth 4")
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                              capture_output=True, text=True, timeout=5)
        if done.returncode == 0:
            socket_rows = json.loads(done.stdout)
        else:
            socket_rows = [{"port": port, "listening": None, "queryFailed": True} for port in ports]
    except (subprocess.TimeoutExpired, ValueError):
        socket_rows = [{"port": port, "listening": None, "queryFailed": True} for port in ports]
    return {"observedAt": datetime.now(timezone.utc).isoformat(), "processes": process_rows,
            "localPorts": socket_rows, "portMethod": "Windows OS TCP listener enumeration; no request is sent",
            "limitation": "Current absence/closed ports do not reconstruct historical exit status; PID or port reuse is possible."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--run", default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--docker", action="store_true", help="read-only exact-object Docker inspect (5s per object)")
    args = parser.parse_args()
    root = args.root.resolve()
    meta = root / "docs/repair-2026-10-08/campaigns" / args.run
    store = root / ".phase1-data/repair" / args.run
    out = args.output or root / "docs/repair-2026-10-08/tb-pilot-independent-audit" / args.run
    out.mkdir(parents=True, exist_ok=True)
    if out.resolve().is_relative_to(store.resolve()) or out.resolve().is_relative_to(meta.resolve()):
        raise ValueError("audit output must not be inside original evidence")
    started = time.monotonic()
    a = Audit()
    metadata_before, raw_before = inventory(meta), inventory(store)
    manifest, source, frozen, summary, ledger, tool_ledger, public = [read_json(meta / (n + ".json")) for n in
        ("manifest", "source", "frozen-source", "summary", "api-ledger", "tool-ledger", "terminal-bench-public-tasks")]
    records = [read_json(meta / ("task-" + str(i) + ".json")) for i in range(2)]
    ports = []
    for arm in ("U", "F"):
        config = (store / ("worker-" + arm) / "config.yaml").read_text(encoding="utf-8")
        for name, key in re.findall(r'\b(token|publisherToken):\s*"([0-9a-f]{64})"', config):
            a.keys[arm + ":" + name] = key.encode()
        ports.append(int(re.search(r"\bport:\s*(\d+)", config)[1]))
    a.check("four_distinct_private_engine_credentials_recoverable", len(a.keys) == len(set(a.keys.values())) == 4)
    for f in metadata_before:
        a.scan("metadata/" + f["path"], (meta / f["path"]).read_bytes())
    for f in raw_before:
        name = f["path"]
        if name == "frozen-source.zip" or name.startswith("worker-"):
            continue  # private worker config/DB are deliberately outside public scope
        raw = (store / name).read_bytes()
        a.scan("raw/" + name, gzip.decompress(raw) if name.endswith(".gz") else raw)

    dataset = manifest["datasets"]["terminal-bench"]
    vendor = root / ".phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks"
    task_ids = sorted(p.parent.name for p in vendor.glob("*/task.toml"))
    a.check("predeclared_two_arms_one_fixed_task", manifest["arms"] == ["U", "F"] and
            dataset["selectedTaskIds"] == [TASK] and manifest["concurrency"] == 1 and manifest["reuse"] == "never")
    health = dataset["health"]
    a.check("paid_private_adapter_ready_without_diagnostic", manifest["profile"] == "pilot" and
            manifest["provider"] == "https://api.deepseek.com" and health["backend"] == "docker" and
            health["isolationReady"] is True and health["runtimeReady"] is True and health["dependencyReady"] is True and
            health["authenticated"] is True and health["unsafeDiagnostic"] is False and health["level"] == 2 and
            health["graders"] == health["maxLiveCandidates"] == 1 and health["supportedTaskIds"] == [TASK])
    a.check("source_denominator_preserved_89", dataset["sourceTaskCount"] == len(task_ids) == 89 and
            dataset["supportedTaskCount"] == 1 and dataset["unsupportedTaskCount"] == 88 and
            dataset["health"]["tasks"] == 89 and dataset["source"] == read_json(root / ".phase1-data/terminal-bench/source.json"),
            taskIdListSha256=digest(js_json(task_ids)))
    a.check("two_records_complete_no_omissions", summary["completed"] is True and not summary.get("fatal") and
            summary["plannedTaskRuns"] == summary["recordedTaskRuns"] == len(summary["records"]) == len(records) == 2 and
            [r["arm"] for r in records] == ["U", "F"] and all(r["officialId"] == TASK and r["replica"] == 0 for r in records))
    a.check("public_task_prompt_digest", len(public) == 1 and public[0]["officialId"] == TASK and
            dataset["publicTaskDigest"] == digest(js_json([public[0]["row"]])))
    a.check("source_metadata_digest", source["sourceDigest"] == digest(js_json(source["files"])) and
            source["executionDigest"] == digest(js_json({"sourceDigest": source["sourceDigest"],
                                                       "repairFiles": source["repairFiles"], "artifacts": source["artifacts"]})) and
            manifest["sourceExecutionDigest"] == frozen["sourceExecutionDigest"] == source["executionDigest"])

    expected = {}
    for item in source["files"] + source["repairFiles"]:
        if selected_source(item["path"]):
            expected[item["path"]] = (item, root / item["path"], "execution_source")
    for item in frozen["dependencyFiles"]:
        expected[item["path"]] = (item, root / item["path"], "actual_engine_dependency")
    for item in source["artifacts"]:
        expected["artifacts/" + item["name"]] = (item, Path(item["path"]), "runtime_or_official_artifact")
    archive = store / "frozen-source.zip"
    a.check("frozen_zip_whole_file_digest", file_digest(archive) == frozen["archiveSha256"] and
            archive.stat().st_size == frozen["archiveBytes"] and source["artifacts"] == frozen["artifacts"])
    archive_mismatches, current_mismatches, forbidden_names = [], [], []
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        a.check("frozen_zip_exact_member_set", len(names) == len(set(names)) == len(expected) and set(names) == set(expected),
                missing=sorted(set(expected) - set(names)), extra=sorted(set(names) - set(expected)), entries=len(names))
        for name in names:
            if (".." in PurePosixPath(name).parts or name.casefold().endswith("/.env") or name == ".env"
                    or name.startswith("worker-") or "broker-key.pem" in name.casefold()):
                forbidden_names.append(name)
            with z.open(name) as stream:
                got, size = a.scan_stream("zip/" + name, stream)  # EOF verifies ZIP CRC
            if name in expected:
                item, current, scope = expected[name]
                if got != item["sha256"] or "bytes" in item and size != item["bytes"]:
                    archive_mismatches.append(name)
                if not current.is_file() or file_digest(current) != item["sha256"]:
                    current_mismatches.append({"path": str(current), "scope": scope})
        official_py = z.read("artifacts/official/tests/test_outputs.py")
        official_test_names = ["test_outputs.py::" + n.name for n in ast.parse(official_py).body
                               if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
        official_limits = tomllib.loads(z.read("artifacts/official/task.toml").decode())
        dep_profile = json.loads(z.read("artifacts/manifest.json"))
        runtime_profile = json.loads(z.read("artifacts/runtime/manifest.json"))
        proof = json.loads(z.read("artifacts/preflight/proof.json"))
        guard = z.read("examples/benchmark/terminal-bench/isolated_verifier.py").decode()
        stand_source = z.read("examples/benchmark/terminal-bench/stand.py").decode()
        artifact_hashes = {item["name"]: item["sha256"] for item in source["artifacts"]}
    a.check("all_archived_sources_dependencies_artifacts_match", not archive_mismatches, mismatches=archive_mismatches)
    a.check("all_used_current_files_match_freeze", not current_mismatches, mismatches=current_mismatches)
    a.check("credential_paths_excluded_from_source_zip", not forbidden_names, names=forbidden_names)
    a.check("eight_original_official_tests", len(official_test_names) == 8)
    a.check("fixed_dependencies_and_runtime_profile_bound", dep_profile["protocol"] == manifest["isolation"]["protocol"] == proof["protocol"] and
            dep_profile["imageId"] == proof["imageId"] == manifest["isolation"]["candidateImage"]["id"] and
            runtime_profile == manifest["isolation"]["runtime"] and proof["runtimeManifestSha256"] == artifact_hashes["runtime/manifest.json"] and
            proof["dependencyProfile"]["manifestSha256"] == artifact_hashes["manifest.json"] and
            all(expected[name][0]["sha256"] == sha for name, sha in proof["sourceHashes"].items()) and
            all(artifact_hashes["official/" + name] == sha for name, sha in proof["officialSourceHashes"].items()))
    a.check("valid_frozen_empty_oracle_controls", proof.get("validated") is True and proof.get("officialGradingValid") is True and
            all(proof["phases"][phase]["valid"] is True and proof["phases"][phase]["ran"] is True and
                proof["phases"][phase]["reward"] == reward and proof["phases"][phase]["completedTests"] == 8
                for phase, reward in (("empty", 0), ("oracle", 1))))
    a.check("guard_path_checks_private_namespace_and_host_config", all(s in guard for s in
            ('private["pid"] != public["pid"]', 'private["mnt"] != public["mnt"]', 'private["net"] == public["net"]',
             'config.get("PidMode", "") == ""', 'not config.get("Binds")', 'namespace_boundary(candidate, name, box)')),
            limitation="Code-path evidence; this pilot did not persist candidate numerical pairs or private HostConfig in /ran,/passed receipts.")
    unused_changes = []
    for item in source["files"]:
        if not selected_source(item["path"]):
            path = root / item["path"]
            if not path.is_file() or file_digest(path) != item["sha256"]:
                unused_changes.append(item["path"])

    wire_rows, responses, requests = [], {}, {}
    usage_total = Counter()
    cost_total = Decimal(0)
    request_keysets, response_keysets, usage_keysets, tool_choices = Counter(), Counter(), Counter(), Counter()
    wire_faults = []
    expected_provider_files = set()
    for i, call in enumerate(ledger["calls"]):
        files = [("request", Path(call["requestFile"]), call["requestSha256"]),
                 ("response", Path(call["responseFile"]), call["responseSha256"])]
        captured = {}
        checks = []
        for kind, path, wanted in files:
            expected_provider_files.add(path.name)
            raw = gzip.decompress(path.read_bytes())  # includes gzip CRC verification
            captured[kind] = json.loads(raw)
            checks.append(digest(raw) == wanted and path.resolve().parent == store.resolve() and
                          path.name == f"provider-{i}-{kind}.json.gz")
            if kind == "request":
                request_bytes = len(raw)
        request, response = captured["request"], captured["response"]
        requests[i], responses[i] = request, response
        request_keysets[tuple(sorted(request))] += 1
        response_keysets[tuple(sorted(response))] += 1
        usage = response.get("usage", {})
        usage_keysets[tuple(sorted(usage))] += 1
        tool_choices[json.dumps(request.get("tool_choice"), sort_keys=True)] += 1
        prompt, completion, cached = usage_counts(usage)
        cost = (Decimal(prompt - cached) * Decimal("0.3") + Decimal(cached) * Decimal("0.006") +
                Decimal(completion) * Decimal("1.2")) / Decimal(1000000)
        reserve = (Decimal(request_bytes + 2048 + len(request["messages"]) * 256) * Decimal("0.3") +
                   Decimal(request["max_tokens"]) * Decimal("1.2")) / Decimal(1000000)
        usage_total.update(prompt=prompt, completion=completion, cached=cached, uncached=prompt - cached)
        cost_total += cost
        offered = {t["function"]["name"] for t in request.get("tools", [])}
        arm = call["route"].split("/")[-3]
        allowed = SIX | {"submit"} | ({"verify"} if arm == "F" else set())
        checks += [call["providerAttempted"] is True, call["httpStatus"] == 200, completion_ok(response),
                   call.get("completionValid") is True, not call.get("fault"), not call.get("completionFault"),
                   call["servedModel"] == response["model"] == request["model"] == manifest["model"],
                   call["requestId"] == response["id"], call["usage"] == usage,
                   request["temperature"] == 0, request["seed"] == 42, request["reasoning_effort"] == "none",
                   request["max_tokens"] == 8192, not request.get("stream", False), offered <= allowed,
                   ms(call["startedAt"]) <= ms(call["finishedAt"]),
                   usage.get("total_tokens") == prompt + completion,
                   usage.get("prompt_cache_miss_tokens") == prompt - cached,
                   usage.get("prompt_tokens_details", {}).get("cached_tokens") == cached,
                   call["costBasis"] == "reported_usage",
                   all(abs(Decimal(str(call[k])) - cost) < Decimal("1e-12") for k in ("usdUpperBound", "accountedUpperBoundUsd")),
                   abs(Decimal(str(call["reservationUsd"])) - reserve) < Decimal("1e-12")]
        if not all(checks):
            wire_faults.append(i)
        wire_rows.append({"index": i, "arm": arm, "checksPassed": all(checks), "requestSha256": call["requestSha256"],
                          "responseSha256": call["responseSha256"], "usage": {"prompt": prompt, "completion": completion, "cached": cached},
                          "computedCostUsd": str(cost), "computedReservationUsd": str(reserve), "offeredTools": sorted(offered)})
    a.check("all_provider_wires_semantically_valid_and_settled", not wire_faults, faultyIndices=wire_faults, calls=len(wire_rows))
    a.check("provider_gzip_exact_keyset", {p.name for p in store.glob("provider-*.json.gz")} == expected_provider_files,
            files=len(expected_provider_files))
    a.check("unique_provider_ids", len({c["requestId"] for c in ledger["calls"]}) == len(ledger["calls"]))
    routes = [args.run + "/terminal-bench/" + arm + "/0/" + TASK for arm in ("U", "F")]
    a.check("api_budget_no_pending_reserve_or_capture_faults", set(ledger["pending"]) == set(routes) and
            all(v == 0 for v in ledger["pending"].values()) and ledger["reservedUpperBoundUsd"] == 0 and
            ledger["blockedAfterDelivery"] == [] and ledger["captureErrors"] == [] and ledger["capUsd"] == manifest["capUsd"] and
            all(abs(Decimal(str(x)) - cost_total) < Decimal("1e-12") for x in
                (ledger["recordedUsageUpperBoundUsd"], summary["recordedUsageUpperBoundUsd"])) and
            cost_total + Decimal(str(ledger["priorCampaignCostUpperBoundUsd"])) <= Decimal(str(ledger["capUsd"])),
            computedUsageCostUsd=str(cost_total), pending=ledger["pending"], reservedUsd=ledger["reservedUpperBoundUsd"])

    tool_rows, tool_faults, expected_tool_files = [], [], set()
    for receipt in tool_ledger["receipts"]:
        i = receipt["index"]
        checks = [receipt.get("forwarded") is True, not receipt.get("fault"),
                  receipt.get("admittedAt", 0) <= receipt.get("finishedAt", -1)]
        payload, response_error = {}, None
        for kind in ("request", "response"):
            name = f"tool-{i}-{kind}.json.gz"
            expected_tool_files.add(name)
            raw = gzip.decompress((store / "tool-receipts" / name).read_bytes())
            checks.append(digest(raw) == receipt[kind + "Sha256"])
            if kind == "request":
                payload = json.loads(raw)
            else:
                response_error = json.loads(raw).get("error")
        checks += [payload.get("place") == receipt["place"], payload.get("tool") == receipt["tool"], receipt["tool"] in SIX]
        if not all(checks):
            tool_faults.append(i)
        tool_rows.append({"index": i, "tool": receipt["tool"], "httpStatus": receipt["httpStatus"],
                          "checksPassed": all(checks), "admittedAt": receipt["admittedAt"], "finishedAt": receipt["finishedAt"],
                          "returnedError": response_error})
    a.check("tool_wires_complete_exact_keyset", not tool_faults and
            set(range(len(tool_rows))) == {r["index"] for r in tool_ledger["receipts"]} and
            {p.name for p in (store / "tool-receipts").glob("*.json.gz")} == expected_tool_files,
            receipts=len(tool_rows), faultyIndices=tool_faults, httpStatusCounts=dict(Counter(r["httpStatus"] for r in tool_rows)))

    arms = []
    with tempfile.TemporaryDirectory(prefix="sqlite-copy-", dir=out) as scratch_name:
        scratch = Path(scratch_name)
        for i, record in enumerate(records):
            arm, route = record["arm"], routes[i]
            copied = copied_sqlite(store, arm, scratch)
            db = sqlite3.connect(copied / "h2h.sqlite")
            db.row_factory = sqlite3.Row
            a.check(arm + "_copied_h2h_sqlite_integrity", db.execute("pragma integrity_check").fetchone()[0] == "ok")
            rows = [dict(r) for r in db.execute("select * from agent_bot_msg where instance like ? order by unit,seq", (record["taskId"] + "#%",))]
            units = [dict(r) for r in db.execute("select * from agent_bot_ctx where instance like ? order by unit", (record["taskId"] + "#%",))]
            task, candidate, chosen, chosen_id = candidate_from_db(db, record["taskId"])
            proxy_bases = [r["base_url"] for r in db.execute("select base_url from api where base_url like ?", ("%" + args.run + "%",))]
            ports.extend(int(p) for url in proxy_bases for p in re.findall(r"127\.0\.0\.1:(\d+)", url))
            db.close()
            sealed = sqlite3.connect(copied / "sealed.sqlite")
            a.check(arm + "_copied_sealed_sqlite_integrity", sealed.execute("pragma integrity_check").fetchone()[0] == "ok")
            sealed.close()
            summary_record = summary["records"][i]
            a.check(arm + "_trace_units_and_summary_match_raw_database", rows == record["trace"] and units == record["units"] and
                    digest(js_json(rows)) == record["traceSha256"] and all(u["done"] == 1 for u in units) and
                    summary_record == {k: v for k, v in record.items() if k not in ("trace", "units")},
                    traceRows=len(rows), units=len(units))
            a.check(arm + "_final_candidate_reconstructed_from_raw_database", candidate == record["answer"] and
                    record["candidateHow"] == "submitted" and digest(candidate.encode()) == record["candidateSha256"] == record["acceptance"]["candidateSha256"])
            prompt = public[0]["row"]["instruction"] + "\n\nEvery bash/read/write/edit/glob/grep call runs inside your task container. Hand in the live service with submit; the answer is only an attempt label. Official tests stay outside your container. Use verify only when offered."
            a.check(arm + "_actual_budget_prompt_and_objective", task["description"] == prompt and
                    digest(prompt.encode()) == record["promptSha256"] == public[0]["promptSha256"] and
                    task["created_at"] == record["actualCreatedAt"] and task["solve_seconds"] == manifest["taskSeconds"] == 900 and
                    task["created_at"] + task["solve_seconds"] * 1000 == ms(record["deadline"]) and task["state"] == record["state"] == "done" and
                    task["max_branches"] == task["max_dead_siblings"] == 1 and
                    (task["objective"] is None if arm == "U" else task["objective"] == "sealed"))
            api = [c for c in ledger["calls"] if c["route"] == route]
            call_rows = [r for r in rows if r["kind"] == "call"]
            trace_payloads = [json.loads(r["body"]) for r in call_rows]
            provider_payloads, provider_names, offered_verify = [], Counter(), 0
            for wire_i, c in enumerate(ledger["calls"]):
                if c["route"] != route:
                    continue
                message = responses[wire_i]["choices"][0]["message"]
                calls = [{"id": t["id"], "name": t["function"]["name"], "input": json.loads(t["function"]["arguments"])}
                         for t in message.get("tool_calls", []) or []]
                provider_names.update(t["name"] for t in calls)
                provider_payloads.append({"text": message.get("content") or "", "calls": calls})
                offered_verify += any(t["function"]["name"] == "verify" for t in requests[wire_i].get("tools", []))
            a.check(arm + "_provider_calls_and_trace_bodies_match", api == record["apiCalls"] and len(api) == len(call_rows) and
                    provider_payloads == trace_payloads, calls=len(api))
            submit_calls = [{"at": r["at"], "unit": r["unit"], "seq": r["seq"], "id": t["id"],
                             "answerSha256": digest(str(t.get("input", {}).get("answer", "")).encode())}
                            for r, payload in zip(call_rows, trace_payloads) for t in payload.get("calls", []) if t["name"] == "submit"]
            submit_tools = [r for r in rows if r["kind"] == "tool" and json.loads(r["body"]).get("name") == "submit"]
            q = read_json(meta / ("quiescence-" + str(i) + ".json"))
            tr = [r for r in tool_ledger["receipts"] if r["place"] == record["place"]]
            deadline, delivered = ms(record["deadline"]), min(r["at"] for r in submit_tools)
            a.check(arm + "_all_api_and_selected_submit_within_deadline", chosen["at"] <= deadline and
                    all(ms(c["startedAt"]) <= ms(c["finishedAt"]) <= deadline for c in api))
            after_delivery = [n for n, c in enumerate(ledger["calls"]) if c["route"] == route and ms(c["startedAt"]) > delivered]
            a.check(arm + "_only_forced_submit_api_after_first_delivery", len(after_delivery) == 1 and
                    all(requests[n]["tool_choice"] == {"type": "function", "function": {"name": "submit"}} and
                        [t["function"]["name"] for t in requests[n]["tools"]] == ["submit"] and
                        all(t["function"]["name"] == "submit" for t in responses[n]["choices"][0]["message"]["tool_calls"])
                        for n in after_delivery))
            late = [r["index"] for r in tr if r["forwarded"] and r["tool"] in {"bash", "write", "edit"} and r["finishedAt"] > deadline]
            post_delivery = [r["index"] for r in tr if r["forwarded"] and r["admittedAt"] >= delivered]
            a.check(arm + "_gateway_sealed_drained_no_late_mutations", q == record["toolQuiescence"] and q["sealed"] is True and
                    q["outstanding"] == 0 and q["receipts"] == tr and all(r["finishedAt"] <= q["finishedAt"] for r in tr) and
                    not late and not post_delivery and record["engineStoppedBeforeAcceptance"] is True,
                    lateMutationIndices=late, postDeliveryToolAdmissions=post_delivery)
            a.check(arm + "_final_acceptance_valid_passed", record["generationValid"] is True and record["acceptance"]["valid"] is True and
                    record["acceptance"]["passed"] is True and all(record["acceptance"]["nodes"][n]["value"] is True and
                    record["acceptance"]["nodes"][n]["valid"] is True for n in ("ran", "passed")))
            ports.extend(int(p) for row in rows for p in re.findall(r"127\.0\.0\.1:(\d+)", row["body"]))
            arms.append({"arm": arm, "taskId": record["taskId"], "finalPassed": record["acceptance"]["passed"],
                         "apiCalls": len(api), "providerToolCallCounts": dict(provider_names), "requestsOfferingVerify": offered_verify,
                         "modelExplicitVerifyCalls": provider_names["verify"], "runtimeGradedEvents": sum(r["kind"] == "graded" for r in rows),
                         "traceRows": len(rows), "units": len(units), "candidateSha256": record["candidateSha256"],
                         "submitCalls": submit_calls, "submitToolTimes": [r["at"] for r in submit_tools],
                         "selectedSubmit": {"unit": chosen["unit"], "seq": chosen["seq"], "at": chosen["at"], "id": chosen_id},
                         "apiRequestsAfterFirstSubmitTool": sum(ms(c["startedAt"]) > delivered for c in api),
                         "computedCostUsd": str(sum((Decimal(r["computedCostUsd"]) for r in wire_rows if r["arm"] == arm), Decimal(0))),
                         "toolReceipts": len(tr), "toolHttpStatuses": dict(Counter(r["httpStatus"] for r in tr)),
                         "firstDeliveryAt": delivered, "lastToolFinishedAt": max(r["finishedAt"] for r in tr),
                         "drainFinishedAt": q["finishedAt"], "deadline": deadline, "workerPid": record["workerPid"]})

    official_runs = []
    private_names = []
    for folder in sorted((store / "stand/logs").iterdir()):
        ctrf, versions, ns = [read_json(folder / n) for n in ("ctrf.json", "dependency-versions.json", "namespaces.json")]
        reward = Decimal((folder / "reward.txt").read_text().strip())
        tests = ctrf["results"]["tests"]
        summ = ctrf["results"]["summary"]
        key = folder.name.rsplit("-", 1)[1]
        private_names.append("objrun-tb-private-" + key[:16])
        good = (reward == 1 and {t["name"] for t in tests} == set(official_test_names) and len(tests) == 8 and
                all(t["status"] == "passed" for t in tests) and summ["tests"] == summ["passed"] == 8 and
                all(summ[k] == 0 for k in ("failed", "skipped", "pending", "other")) and
                versions["python"] == dep_profile["python"] and versions["packages"] == dep_profile["packages"] and
                versions["uv"] == "uv " + dep_profile["uv"] and versions["uvSha256"] == artifact_hashes["uv"] and
                all(re.fullmatch(k + r":\[\d+\]", ns[k]) for k in ("pid", "mnt", "net")))
        official_runs.append({"directory": folder.relative_to(store).as_posix(), "validSavedOfficialEvidence": good,
                              "reward": str(reward), "completedTests": 8, "passedTests": summ["passed"], "testNames": [t["name"] for t in tests],
                              "privateNamespaces": ns, "observedDependencies": versions,
                              "guestCtrfStart": summ["start"], "guestCtrfStop": summ["stop"]})
    stand_log = (store / "stand.log").read_text(encoding="utf-8")
    result_lines = [line for line in stand_log.splitlines() if line.startswith("[tb] " + TASK + " said=")]
    ports.extend(int(p) for p in re.findall(r"127\.0\.0\.1:(\d+)", stand_log))
    a.check("four_saved_official_grades_all_original_eight_pass", len(official_runs) == 4 and all(r["validSavedOfficialEvidence"] for r in official_runs) and
            len(result_lines) == 4 and all("ran=True reward=1.0" in line and "tests=8/8" in line for line in result_lines),
            resultLines=result_lines)
    a.check("four_grade_count_agrees_with_final_and_runtime_checks", len(official_runs) ==
            len(records) + sum(x["runtimeGradedEvents"] for x in arms))
    a.check("known_engine_keys_absent_from_public_evidence", not a.secret_hits,
            recoveredKeys=len(a.keys), publicFiles=len(a.scanned_public_files), zipMembers=len(a.scanned_zip_members), hits=a.secret_hits)

    migration_path = root / "docs/repair-2026-10-08/closed-chem-tb-store-relocation.json"
    migration = read_json(migration_path)
    migrated = next(r for r in migration["runs"] if r["run"] == args.run)
    old_map = {r["relative"].replace("\\", "/"): {"path": r["relative"].replace("\\", "/"), "bytes": r["bytes"], "sha256": r["sha256"]}
               for r in migrated["files"]}
    a.check("closed_store_relocation_matches_current_bytes", migration["validated"] is True and
            len(old_map) == len(raw_before) and all(old_map.get(r["path"]) == r for r in raw_before) and
            store.resolve() == Path(migrated["target"]).resolve(), relocationReportSha256=file_digest(migration_path), files=len(raw_before))
    candidate_names = ["tb-" + r["taskId"].replace("/", "-") for r in records]
    docker = exact_docker_observations(candidate_names + private_names,
                [manifest["isolation"]["candidateImage"]["id"], runtime_profile["executorImageId"]]) if args.docker else None
    if docker:
        a.check("exact_owned_docker_objects_now_absent", all(r["absent"] is True for r in docker["containers"]),
                objects=len(docker["containers"]))
        a.check("pinned_docker_images_still_exact", all(r["matched"] for r in docker["images"]))
    host = host_observations([r["workerPid"] for r in records] + [manifest["isolation"]["standPid"]], ports)
    a.check("recorded_host_workers_stand_and_ports_now_closed", all(r.get("present") is False for r in host["processes"]) and
            all(r["listening"] is False for r in host["localPorts"]))
    metadata_after, raw_after = inventory(meta), inventory(store)
    a.check("original_metadata_and_raw_bytes_unchanged_during_audit", metadata_before == metadata_after and raw_before == raw_after)

    limitations = [
        "This is a two-arm single-task pilot: 1 supported nginx task from a source of 89, 88 unsupported. It does not recover 94.4%, establish a full-benchmark score, or estimate a U/F effect.",
        "R replicas=5 is an unused manifest default. Actual records contain U/F replica0 only; no R experiment ran.",
        "Both arms made two model submit calls. Gateway stops further tool admissions after the first submit tool row; the final-candidate policy selects the latest timely submit label. Remaining model calls are forced submission, not subsequent live-state repairs.",
        "Neither model explicitly called verify. F has runtime grading events around submission/terminal processing; this run supplies no evidence of a pre-delivery repair based on official feedback.",
        "candidateSha256 covers the submitted attempt label, not an immutable filesystem/process snapshot. Grading observes the live service; arbitrary background service writes are not sealed by the tool gateway.",
        "The pilot saves private numerical namespaces and the frozen guard that compares candidate PID/mount, shared network, and host Docker configuration before ran=true. /ran,/passed strip the full result; candidate numeric pairs and private HostConfig are not persisted here. Preflight numeric pairs are a separate control, not this run's pairs.",
        "Cold startup is enforced by frozen create/ownership checks and distinct run/arm names. Initial Docker create/config/ID receipts were not saved; current absence cannot reconstruct initial container state.",
        "Four official log directories agree with one U final, two F runtime grades, and one F final by count and stand-log labels/order. There is no explicit grading invocation ID in acceptance HTTP receipts. Guest CTRF and Windows host clocks are not calibrated; no exact cross-clock ordering claim is made.",
        "Engine stop is awaited by frozen code and recorded true before final acceptance. Current PID/port/container absence is corroboration; historical child exit codes and Docker removal receipts were not separately saved.",
        "Exact-value secret scans cover four recoverable engine API/publisher credentials over metadata, captured request/response bodies, grader logs, and every ZIP member. Private config/SQLite are excluded and access-sensitive. Ephemeral stand/gateway/broker/provider credential values were not retained, so they cannot be exact-value scanned; source header-only handling and archive-path exclusion are separate evidence.",
        "Wire bodies are captured as gzip with SHA/CRC checks, not provider response HTTP headers or a network-level transcript. Usage-priced USD uses frozen rates and reported usage; it is not a provider invoice. Model alias, temperature, and seed do not pin a provider checkpoint.",
        "The archive pins app source and 4100 files from the actual dependency directory, a conservative execution superset, not a per-import load trace. The host Bun executable/version and a historical engine exit receipt are not archived in this pilot.",
        "The 512MiB writable-layer and 1MiB stream-capture operational limits differ from official 10GiB storage; the official 900s agent/verifier deadlines and original eight assertions are retained. This constrained environment must accompany any reported pilot result.",
    ]
    def keysets(counter):
        return [{"keys": list(k), "count": v} for k, v in counter.items()]
    report = {"schemaVersion": 1, "run": args.run, "auditedAt": datetime.now(timezone.utc).isoformat(),
              "readOnly": True, "llmRequests": 0, "graderRuns": 0, "dockerMutations": 0,
              "auditSourceSha256": file_digest(Path(__file__)), "passedAllAvailableChecks": all(c["passed"] for c in a.checks),
              "independentEvidenceAuditOnly": True, "genericIsolationCertified": False, "fullBenchmarkScore": None,
              "checks": a.checks, "arms": arms, "usage": dict(usage_total), "computedCostUsd": str(cost_total),
              "providerRequestKeysets": keysets(request_keysets), "providerResponseKeysets": keysets(response_keysets),
              "providerUsageKeysets": keysets(usage_keysets), "toolChoices": dict(tool_choices), "wireReceipts": wire_rows,
              "apiReceiptKeysets": keysets(Counter(tuple(sorted(c)) for c in ledger["calls"])),
              "toolReceiptKeysets": keysets(Counter(tuple(sorted(c)) for c in tool_ledger["receipts"])),
              "toolReceipts": tool_rows, "officialRuns": official_runs,
              "source": {"executionDigest": source["executionDigest"], "archiveSha256": frozen["archiveSha256"],
                         "archiveBytes": frozen["archiveBytes"], "archiveEntries": len(expected),
                         "actualEngineDependencyFiles": len(frozen["dependencyFiles"]), "artifacts": len(source["artifacts"]),
                         "currentUsedMismatches": current_mismatches, "unusedBroadSnapshotChanges": unused_changes,
                         "officialLimits": official_limits, "dependencyProfile": dep_profile["profileId"],
                         "dependencyManifestSha256": artifact_hashes["manifest.json"], "runtimeManifestSha256": artifact_hashes["runtime/manifest.json"]},
              "secretScan": {"knownValues": len(a.keys), "publicFiles": len(a.scanned_public_files), "zipMembers": len(a.scanned_zip_members),
                             "exactValueMatches": a.secret_hits, "privateExcludedPrefixes": ["worker-U/", "worker-F/"],
                             "unavailableKeyClasses": ["stand/gateway shared header", "broker private key", "provider API key"]},
              "dockerClosure": docker, "hostClosure": host, "metadataInventory": metadata_before, "rawInventory": raw_before,
              "logicalStore": str(store), "resolvedStore": str(store.resolve()), "limitations": limitations,
              "seconds": round(time.monotonic() - started, 3)}
    (out / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = ["# nginx 试跑独立闭合审计", "", f"运行 `{args.run}`。只读审计，无 LLM、重评分或 Docker 修改。",
            "", "| 项目 | 本轮证据 |", "|---|---|",
            "| 口径 | 预定 U/F 两臂，各一题；来源 89 题，支持 1、其余 88 未支持 |",
            "| 最终判卷 | U、F 均 valid/pass；4 份私有记录均原官方 8/8 |",
            f"| API/费用 | {len(wire_rows)} 份真实回执，重算 ${cost_total}；pending/reserve=0 |",
            "| 工具闭合 | gateway seal/drain 完成，无交付后准入、无超过任务截止的 mutation |",
            f"| 源与依赖 | ZIP {len(expected)} 个成员含实际依赖 {len(frozen['dependencyFiles'])} 个；摘要逐项核对 |",
            f"| 原证据稳定 | 元数据 {len(metadata_before)} 文件、raw {len(raw_before)} 文件；审计前后 bytes/SHA 相同 |",
            "| 认证边界 | 私有 namespace 已保存，候选数字配对未保存；当前容器/PID关闭只能补充佐证 |",
            "", f"可执行核对 {sum(c['passed'] for c in a.checks)}/{len(a.checks)} 通过。`passedAllAvailableChecks` 不是通用隔离认证。",
            "", "两臂均有两次模型 submit；最终取最新及时交付标签。模型没有显式调用 verify，F 的两次 graded 是运行时提交/终态判卷，不能作为交付前反馈修复或 F 优势证据。",
            "", "工具 HTTP500 与 provider HTTP200分别核算；所有已发起工具均有完成回执，工具错误不被隐去。",
            "", "以下限制须随结果保留：", ""]
    rows.extend("- " + limit for limit in limitations)
    rows += ["", "复现（仅最后的 `--docker` 会只读核对本轮精确对象）：", "", "```powershell",
             f"python -X utf8 \"{Path(__file__)}\" --run {args.run} --docker", "```", "",
             "完整字段、原证据摘要、各项检查与当前关闭观察见同目录 `audit.json`。"]
    (out / "audit.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(json.dumps({"audit": str(out / "audit.json"), "passed": report["passedAllAvailableChecks"],
                      "checks": len(a.checks), "failedChecks": [c["name"] for c in a.checks if not c["passed"]],
                      "costUsd": str(cost_total), "rawFiles": len(raw_before), "archiveEntries": len(expected)}, ensure_ascii=False))
    return 0 if report["passedAllAvailableChecks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
