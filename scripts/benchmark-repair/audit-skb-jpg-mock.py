"""Independently audit a closed Docker JPG mock, without executing its harness.

No model, grader, Docker mutation, dependency extraction, or candidate program is
run. SQLite is copied together with WAL/SHM before querying. Exact Docker inspect
is optional. Production source and original receipts are never rewritten.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile

# Reuse only our independent auditor's inert, standard-library read/hash helpers.
# This does not import any production runner, bridge, grader, or application code.
COMMON_PATH = Path(__file__).with_name("audit-tb-live-pilot.py")
spec = importlib.util.spec_from_file_location("independent_tb_audit", COMMON_PATH)
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
Audit, sha, file_sha, js_json, inventory, ms = (common.Audit, common.digest, common.file_digest,
                                             common.js_json, common.inventory, common.ms)
read_json = common.read_json
TASK, PROTOCOL = "jpg-ocr-stat", "skb-jpg-output-v1-preseed"
RUN = "skb-jpg-2026-10-08T11-29-26-467Z"
FIXED = "/app/workspace/stat_ocr.xlsx"
IMAGE = "sha256:92892771245d31d0b1af4a0c603effbdaf02bf62c1c055081f44a462f5261ced"
SIX = {"bash", "read", "write", "edit", "glob", "grep"}


def direct_source(name):
    return name.startswith(("app/src/", "scripts/benchmark-repair/")) or name in common.SINGLE_FILES


def copied_db(store, arm, scratch):
    target = scratch / arm
    target.mkdir()
    for source in (store / ("worker-" + arm) / "data").glob("*.sqlite*"):
        shutil.copy2(source, target / source.name)
    return target


def reconstruct_candidate(db, task_id):
    task = dict(db.execute("select * from task where id=?", (task_id,)).fetchone())
    deadline = task["created_at"] + task["solve_seconds"] * 1000
    for unit in db.execute("select * from task_repair_jpg where task=? order by unit desc", (task_id,)):
        if unit["agent"] != "bot":
            raise ValueError("unexpected dynamic message table")
        for row in db.execute("select * from agent_bot_msg where instance=? and unit=? and kind='call' and at<=? order by seq desc",
                              (unit["instance"], unit["unit"], deadline)):
            for call in reversed(json.loads(row["body"]).get("calls", [])):
                if call["name"] == "submit":
                    answer = call.get("input", {}).get("answer", "")
                    return task, answer if isinstance(answer, str) else "", dict(row)
    return task, None, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=RUN)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--docker", action="store_true", help="read-only exact-object inspect, 5s per object")
    args = parser.parse_args()
    root = args.root.resolve()
    meta = root / "docs/repair-2026-10-08/software-preparation" / args.run
    manifest = read_json(meta / "manifest.json")
    store = Path(manifest["storage"]["store"])
    out = args.output or root / "docs/repair-2026-10-08/skb-jpg-independent-audit" / args.run
    if any(out.resolve().is_relative_to(p.resolve()) for p in (store, meta)):
        raise ValueError("audit must not write inside original evidence")
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    a = Audit()
    before_meta, before_raw = inventory(meta), inventory(store)
    source, frozen, summary, ledger, tool_ledger, cleanup, secret_certificate, public = [read_json(meta / (n + ".json")) for n in
        ("source", "frozen-source", "summary", "api-ledger", "tool-ledger", "cleanup", "evidence-secret-audit", "skillsbench-public-tasks")]
    records = [read_json(meta / ("task-" + str(i) + ".json")) for i in range(2)]
    ports, configs = [], []
    for arm in ("U", "F"):
        path = store / ("worker-" + arm) / "config.yaml"
        configs.append(path.resolve())
        text = path.read_text(encoding="utf-8")
        for name, key in re.findall(r'\b(token|publisherToken):\s*"([0-9a-f]{64})"', text):
            a.keys[arm + ":" + name] = key.encode()
        ports.append(int(re.search(r"\bport:\s*(\d+)", text)[1]))
    a.check("four_distinct_recoverable_engine_credentials", len(a.keys) == len(set(a.keys.values())) == 4)
    # Unlike a SQLite connection, reading the evidence bytes cannot modify SHM.
    workbook_member_count = 0
    for prefix, folder, items in (("metadata", meta, before_meta), ("raw", store, before_raw)):
        for item in items:
            path = folder / item["path"]
            if path.resolve() in configs or path.suffix == ".zip":
                continue
            raw = path.read_bytes()
            a.scan(prefix + "/" + item["path"], gzip.decompress(raw) if path.suffix == ".gz" else raw)
            if path.suffix == ".xlsx":
                with zipfile.ZipFile(path) as workbook:
                    for name in workbook.namelist():
                        a.scan(prefix + "/" + item["path"] + "::" + name, workbook.read(name))
                        workbook_member_count += 1

    a.check("mock_and_formal_flags_are_separate", manifest["executionMode"] == "docker-mock" and
            manifest["provider"] == "local-mock" and manifest["mockOnly"] is True and
            summary["completed"] is False and summary["mockCompleted"] is True and
            summary["dockerArtifactClosedLoopValidated"] is True and summary["formalLlmClosedLoopValidated"] is False and
            summary["readyTaskIds"] == [] and not summary.get("fatal"))
    dataset = manifest["datasets"]["skillsbench"]
    environment_manifest_path = root / ".local-evidence/repository/test/fixtures/repair/software-preflight.json"
    environment_manifest = read_json(environment_manifest_path)
    a.check("source_87_one_task_two_arms_no_denominator_loss", dataset["sourceTaskCount"] == 87 and
            dataset["supportedTaskCount"] == 1 and dataset["unsupportedTaskCount"] == 86 and
            dataset["selectedTaskIds"] == [TASK] and dataset["readyTaskIds"] == [] and manifest["arms"] == ["U", "F"] and
            manifest["concurrency"] == 1 and summary["plannedTaskRuns"] == summary["recordedTaskRuns"] == len(summary["records"]) == 2 and
            dataset["source"] == read_json(root / ".phase1-data/skillsbench/source.json"))
    definition_faults = [t["taskId"] for t in environment_manifest["tasks"]
                         if not Path(t["definition"]["path"]).is_file() or
                         file_sha(Path(t["definition"]["path"])) != t["definition"]["sha256"]]
    a.check("all_87_definition_inventory_fingerprints_match", len(environment_manifest["tasks"]) ==
            len({t["taskId"] for t in environment_manifest["tasks"]}) == environment_manifest["denominator"] == 87 and
            TASK in {t["taskId"] for t in environment_manifest["tasks"]} and not definition_faults and
            all(environment_manifest["source"][k] == dataset["source"][k] for k in ("repository", "commit", "archiveSha256")),
            inventorySha256=file_sha(environment_manifest_path), changedDefinitions=definition_faults,
            scope="Only the pinned 87 task definitions; historical image-cache availability in that old preflight is not current readiness.")
    a.check("public_prompt_and_deadlines", len(public) == 1 and public[0]["officialId"] == TASK and
            dataset["publicTaskDigest"] == public[0]["promptSha256"] == sha(public[0]["row"]["prompt"].encode()) and
            manifest["taskSeconds"] == 1800 and manifest["verifierSeconds"] == 600 and
            manifest["checksPerAttempt"] == 6 and "declares no number" in manifest["queryBudgetSource"])

    refs = frozen["dependencyReferences"]
    base = Path(refs["path"])
    base_sha_before = file_sha(base)
    refs_digest = sha(json.dumps(refs["members"], sort_keys=True, separators=(",", ":")).encode())
    pre_freeze_digest = sha(js_json({"sourceDigest": source["sourceDigest"], "repairFiles": source["repairFiles"],
                                   "artifacts": source["artifacts"], "dependencyArchiveReference": source["dependencyArchiveReference"]}))
    a.check("source_and_nested_execution_digests", source["sourceDigest"] == sha(js_json(source["files"])) and
            source["executionDigest"] == sha(js_json({"preFreezeExecutionDigest": pre_freeze_digest, "dependencyMembersDigest": refs_digest})) and
            manifest["sourceExecutionDigest"] == frozen["sourceExecutionDigest"] == source["executionDigest"] and
            manifest["dependencyMembersDigest"] == refs["membersSha256"] == refs_digest and
            source["dependencyArchiveReference"] == manifest["dependencyArchiveReference"] and
            base_sha_before == refs["sha256"] == source["dependencyArchiveReference"]["sha256"])
    a.check("dependency_reference_whitelist_and_uniqueness", len(refs["members"]) == len({r["name"] for r in refs["members"]}) == 4115 and
            all(r["name"].startswith(("app/node_modules/", "artifacts/runtime/", "artifacts/grader-dependencies/")) for r in refs["members"]))
    expected = {item["path"]: (item, root / item["path"]) for item in source["files"] + source["repairFiles"] if direct_source(item["path"])}
    for item in source["artifacts"]:
        if not item["name"].startswith(("runtime/", "grader-dependencies/")):
            expected["artifacts/" + item["name"]] = (item, Path(item["path"]))
    archive = Path(frozen["archive"])
    a.check("new_source_zip_hash_and_size", archive.resolve() == (store / "frozen-source.zip").resolve() and
            file_sha(archive) == frozen["archiveSha256"] and archive.stat().st_size == frozen["archiveBytes"] == 7867944)
    direct_faults, ref_faults, current_faults, forbidden_paths = [], [], [], []
    with zipfile.ZipFile(archive) as direct, zipfile.ZipFile(base) as cache:
        names = direct.namelist()
        a.check("new_zip_exact_120_current_members", set(names) == set(expected) and len(names) == len(set(names)) == frozen["members"] == 120)
        for name in names:
            if (".." in PurePosixPath(name).parts or name.endswith("/.env") or name.startswith("worker-")
                    or "broker-key.pem" in name or name == ".env"):
                forbidden_paths.append(name)
            with direct.open(name) as stream:
                got, size = a.scan_stream("direct/" + name, stream)
            item, current = expected[name]
            if got != item["sha256"] or "bytes" in item and size != item["bytes"]:
                direct_faults.append(name)
            if not current.is_file() or file_sha(current) != item["sha256"]:
                current_faults.append(str(current))
        for item in refs["members"]:
            with cache.open(item["name"]) as stream:
                got, size = a.scan_stream("reference/" + item["name"], stream)
            if got != item["sha256"] or size != item["bytes"]:
                ref_faults.append(item["name"])
            current = Path(item["sourcePath"])
            if not current.is_file() or file_sha(current) != item["sha256"]:
                current_faults.append(str(current))
        gates = {n: json.loads(direct.read("artifacts/gate/" + n + ".json")) for n in ("controls", "image", "build", "profile")}
        grader_source = direct.read("scripts/benchmark-repair/software-jpg-private-grader.py").decode()
        bridge_source = direct.read("scripts/benchmark-repair/skb-jpg-stand.py").decode()
        runner_source = direct.read("scripts/benchmark-repair/skb-jpg-campaign.ts").decode()
        helper_source = direct.read("scripts/benchmark-repair/skb-jpg-host-ops.py").decode()
        budget_source = direct.read("app/src/objective/tool.ts").decode()
        runtime = json.loads(cache.read("artifacts/runtime/manifest.json"))
    a.check("all_direct_and_referenced_bytes_match_current", not direct_faults and not ref_faults and not current_faults,
            directMismatches=direct_faults, referenceMismatches=ref_faults, currentMismatches=current_faults)
    a.check("private_config_and_credential_paths_not_archived", not forbidden_paths, paths=forbidden_paths)
    item_hashes = {item["name"]: item["sha256"] for item in source["artifacts"]}
    grader_sha = next(r["sha256"] for r in source["repairFiles"] if r["path"].endswith("software-jpg-private-grader.py"))
    controls, image, build, profile = [gates[n] for n in ("controls", "image", "build", "profile")]
    a.check("fixed_complete_image_and_three_real_control_gate", image["imageId"] == build["imageId"] == profile["imageId"] == controls["imageId"] == manifest["actualImage"]["Id"] == IMAGE and
            image["completeOriginalTaskImage"] is True and build["validated"] is True and build["actualBuildCompleted"] is True and
            controls["validated"] is True and controls["graderSourceSha256"] == grader_sha and
            controls["controlValidatedTaskIds"] == [TASK] and controls["denominator"] == 87 and controls["unsupportedTaskCount"] == 86 and
            all(controls["phases"][name]["valid"] is True and controls["phases"][name]["ran"] is True and
                controls["phases"][name]["reward"] == reward and controls["phases"][name]["completedTests"] == 1 and
                controls["phases"][name]["imageId"] == IMAGE for name, reward in (("empty", 0), ("oracle", 1), ("wrongWorkbook", 0))) and
            controls["originalSourceHashes"] == image["sourceHashes"] and runtime == manifest["runtime"] and
            manifest["gate"]["passed"] is True)
    a.check("fresh_private_grader_fixed_executable_and_network_guard", all(text in grader_source for text in
            ('self.docker.create(self.image, "grader", "none"', 'config["HostConfig"].get("Binds")',
             'config["HostConfig"].get("PidMode")', 'config["HostConfig"]["NetworkMode"] != network',
             '"UV_PYTHON": "/usr/bin/python3"', '"PYTHONPATH": ""', '"PYTHONNOUSERSITE": "1"')) and
            'self.docker.create(self.image,\'candidate\',\'bridge\'' in bridge_source and
            'self.docker.checked(\'stop\',\'--time\',\'0\',self.name)' in bridge_source,
            limitation="Frozen inspected guard path; complete historical candidate/private HostConfig is not archived.")
    a.check("mock_provider_and_feedback_budget_source_are_explicit", "if(paid)return await fetch(url,init)" in runner_source and
            "model:'local-mock'" in runner_source and "rates:{input:0,cachedInput:0,output:0}" in runner_source and
            'id 以 `g-` 开头' in budget_source,
            limitation="CHECKS=6 applies to explicit model verify. Runtime grading and final independent acceptance are separately counted.")

    expected_wire_files, responses, requests, wire_rows, wire_faults = set(), {}, {}, [], []
    for i, receipt in enumerate(ledger["calls"]):
        bodies = {}
        passed = []
        for kind in ("request", "response"):
            name = f"provider-{i}-{kind}.json.gz"
            expected_wire_files.add(name)
            path = Path(receipt[kind + "File"])
            raw = gzip.decompress(path.read_bytes())
            passed.append(path.resolve().parent == store.resolve() and path.name == name and sha(raw) == receipt[kind + "Sha256"])
            bodies[kind] = json.loads(raw)
        request, response = bodies["request"], bodies["response"]
        requests[i], responses[i] = request, response
        passed += [receipt["httpStatus"] == 200, receipt["servedModel"] == response["model"] == "local-mock",
                   response["id"] == receipt["requestId"], response["usage"] == receipt["usage"] == {"prompt_tokens": 1, "completion_tokens": 1},
                   common.completion_ok(response), receipt["completionValid"] is True, not receipt.get("fault"),
                   all(receipt[k] == 0 for k in ("reservationUsd", "usdUpperBound", "accountedUpperBoundUsd")),
                   request["model"] == manifest["model"] and request["max_tokens"] == 8192 and request["temperature"] == 0 and
                   request["seed"] == 42 and request["reasoning_effort"] == "none", ms(receipt["startedAt"]) <= ms(receipt["finishedAt"])]
        if not all(passed):
            wire_faults.append(i)
        wire_rows.append({"index": i, "validLocalMockEnvelope": all(passed), "requestSha256": receipt["requestSha256"],
                          "responseSha256": receipt["responseSha256"], "providerAttempted": receipt["providerAttempted"],
                          "servedModel": response["model"], "simulatedUsage": response["usage"]})
    a.check("19_mock_wires_complete_and_no_real_provider_bill", len(ledger["calls"]) == 19 and not wire_faults and
            {p.name for p in store.glob("provider-*.json.gz")} == expected_wire_files and
            ledger["recordedUsageUpperBoundUsd"] == ledger["reservedUpperBoundUsd"] == summary["recordedUsageUpperBoundUsd"] == 0 and
            all(v == 0 for v in ledger["pending"].values()) and ledger["captureErrors"] == [] and ledger["blockedAfterDelivery"] == [],
            faultyIndices=wire_faults, semanticRealLlmRequests=0)
    expected_tool_files, tool_faults = set(), []
    for receipt in tool_ledger["receipts"]:
        i = receipt["index"]
        passed = [receipt["forwarded"] is True, receipt["httpStatus"] == 200, not receipt.get("fault"),
                  receipt["admittedAt"] <= receipt["finishedAt"], receipt["tool"] in SIX]
        for kind in ("request", "response"):
            name = f"tool-{i}-{kind}.json.gz"
            expected_tool_files.add(name)
            raw = gzip.decompress((store / "tool-receipts" / name).read_bytes())
            passed.append(sha(raw) == receipt[kind + "Sha256"])
            if kind == "request":
                data = json.loads(raw)
                passed.append(data["place"] == receipt["place"] and data["tool"] == receipt["tool"])
        if not all(passed):
            tool_faults.append(i)
    a.check("16_real_tool_rpc_receipts_complete", len(tool_ledger["receipts"]) == 16 and not tool_faults and
            {p.name for p in (store / "tool-receipts").glob("*.json.gz")} == expected_tool_files,
            faultyIndices=tool_faults)

    capture_rows, capture_by_sha = [], {}
    for path in sorted((store / "stand").glob("capture-*/capture-receipt.json")):
        receipt = read_json(path)
        workbook = Path(receipt["hostArtifactPath"])
        evidence = receipt["daemonEvidence"]
        data = workbook.read_bytes()
        valid = (receipt["taskId"] == TASK and receipt["protocol"] == PROTOCOL and receipt["artifactPath"] == FIXED and
                 receipt["containerStopped"] is True and receipt["mock"] is False and receipt["state"] == "regular" and
                 receipt["ownedContainerID"] == evidence["containerId"] and re.fullmatch("[0-9a-f]{64}", receipt["ownedContainerID"]) and
                 evidence["method"] == "docker-cp-tar" and evidence["memberKind"] == "regular" and evidence["memberName"] == "stat_ocr.xlsx" and
                 receipt["artifactBytes"] == evidence["size"] == len(data) <= 8 * 1024**2 and receipt["artifactSha256"] == sha(data) and
                 evidence["rawTarCaptureComplete"] is True and re.fullmatch("[0-9a-f]{64}", evidence["rawTarSha256"]))
        with zipfile.ZipFile(workbook) as z:
            valid = valid and z.testzip() is None
            cells = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            cells = [{"cell": c.attrib["r"], "type": c.attrib.get("t"), "text": "".join(c.itertext())} for c in cells.findall(".//x:c", ns)]
        row = {"receiptPath": str(path), "receiptSha256": file_sha(path), "ownedContainerID": receipt["ownedContainerID"],
               "artifactSha256": receipt["artifactSha256"], "artifactBytes": len(data), "final": receipt["final"],
               "stoppedAt": receipt["stoppedAt"], "validSavedCaptureEvidence": bool(valid), "cells": cells,
               "rawTarRetained": False, "rawTarSha256Recorded": evidence["rawTarSha256"]}
        capture_rows.append(row)
        capture_by_sha[row["receiptSha256"]] = (receipt, row)
    a.check("three_regular_bounded_workbooks_match_capture_digests", len(capture_rows) == 3 and
            all(r["validSavedCaptureEvidence"] for r in capture_rows) and sum(r["final"] for r in capture_rows) == 2,
            limitation="Raw Docker TAR bytes were not retained; their header/CRC cannot be replayed independently from the saved XLSX.")

    arms = []
    with tempfile.TemporaryDirectory(prefix="sqlite-copy-", dir=out) as scratch_name:
        for i, record in enumerate(records):
            arm = record["arm"]
            target = copied_db(store, arm, Path(scratch_name))
            db = sqlite3.connect(target / "h2h.sqlite")
            db.row_factory = sqlite3.Row
            a.check(arm + "_copied_h2h_integrity", db.execute("pragma integrity_check").fetchone()[0] == "ok")
            rows = [dict(r) for r in db.execute("select * from agent_bot_msg where instance like ? order by unit,seq", (record["taskId"] + "#%",))]
            units = [dict(r) for r in db.execute("select * from agent_bot_ctx where instance like ? order by unit", (record["taskId"] + "#%",))]
            task, candidate, chosen = reconstruct_candidate(db, record["taskId"])
            ports.extend(int(p) for r in db.execute("select base_url from api where base_url like ?", ("%" + args.run + "%",)) for p in re.findall(r"127\.0\.0\.1:(\d+)", r[0]))
            db.close()
            sealed = sqlite3.connect(target / "sealed.sqlite")
            sealed.row_factory = sqlite3.Row
            a.check(arm + "_copied_sealed_integrity", sealed.execute("pragma integrity_check").fetchone()[0] == "ok")
            objective = sealed.execute("select * from objective where task=?", (record["taskId"],)).fetchone()
            a.check(arm + "_sealed_feedback_budget", objective is None if arm == "U" else objective["checks"] == 6 and
                    json.loads(objective["body"])["checks"] == 6 and json.loads(objective["body"])["reuse"] == "never")
            if objective is not None:
                ports.extend(int(p) for p in re.findall(r"127\.0\.0\.1:(\d+)", objective["body"]))
            sealed.close()
            a.check(arm + "_database_trace_units_candidate_and_prompt_match", rows == record["trace"] and units == record["units"] and
                    sha(js_json(rows)) == record["traceSha256"] and all(u["done"] == 1 for u in units) and candidate == record["answer"] == "mock-workbook" and
                    sha(candidate.encode()) == record["candidateSha256"] == record["acceptance"]["candidateSha256"] and
                    task["description"] == public[0]["row"]["prompt"] and sha(task["description"].encode()) == record["promptSha256"] and
                    summary["records"][i] == {k: v for k, v in record.items() if k not in ("trace", "units")})
            route = args.run + "/skillsbench/" + arm + "/0/" + TASK
            api = [c for c in ledger["calls"] if c["route"] == route]
            call_rows = [r for r in rows if r["kind"] == "call"]
            payloads, model_tools = [], Counter()
            for n, receipt in enumerate(ledger["calls"]):
                if receipt["route"] != route:
                    continue
                message = responses[n]["choices"][0]["message"]
                calls = [{"id": c["id"], "name": c["function"]["name"], "input": json.loads(c["function"]["arguments"])} for c in message["tool_calls"]]
                model_tools.update(c["name"] for c in calls)
                payloads.append({"text": message.get("content") or "", "calls": calls})
            a.check(arm + "_mock_wires_match_recorded_model_calls", api == record["apiCalls"] and
                    len(api) == len(call_rows) and payloads == [json.loads(r["body"]) for r in call_rows])
            submitted = [r for r in rows if r["kind"] == "tool" and json.loads(r["body"]).get("name") == "submit"]
            verify_rows = [json.loads(r["body"]) for r in rows if r["kind"] == "tool" and json.loads(r["body"]).get("name") == "verify"]
            explicit = [r for r in verify_rows if not r["id"].startswith("g-")]
            internal = [r for r in verify_rows if r["id"].startswith("g-")]
            a.check(arm + "_query_categories_and_remaining_budget", len(explicit) == (1 if arm == "F" else 0) and
                    all(r["value"]["valid"] is True and r["value"]["left"] == 5 for r in explicit) and
                    len(internal) == (3 if arm == "F" else 0), explicitFeedback=len(explicit), runtimeGrades=len(internal))
            tr = [r for r in tool_ledger["receipts"] if r["place"] == record["place"]]
            q = read_json(meta / ("quiescence-" + str(i) + ".json"))
            capture = read_json(meta / ("capture-" + str(i) + ".json"))
            persisted = read_json(Path(capture["captureReceiptPath"]))
            cold = read_json(meta / ("cold-candidate-" + arm + ".json"))
            auth = read_json(meta / ("host-auth-" + arm + ".json"))
            deadline = task["created_at"] + task["solve_seconds"] * 1000
            delivered = min(r["at"] for r in submitted)
            a.check(arm + "_real_cold_candidate_environment_gate", cold["mock"] is False and cold["alive"] is True and
                    cold["ownedContainerID"] == cold["environmentAudit"]["containerId"] == capture["ownedContainerID"] and
                    cold["environmentAudit"]["forbiddenHostKeysPresent"] is False and cold["environmentAudit"]["standTokenPresent"] is False and
                    cold["environmentAudit"]["imageEnvironmentSha256"] == sha(json.dumps(manifest["actualImage"]["Config"]["Env"], sort_keys=True).encode()))
            a.check(arm + "_six_existing_host_auth_probes_rejected", auth["missingAndForgedRejected"] is True and
                    len(auth["probes"]) == 6 and all(r["status"] == 401 for r in auth["probes"]),
                    limitation="Saved host-origin engine endpoint probes; no new candidate-origin probe was run in this audit.")
            a.check(arm + "_tool_completions_precede_both_drain_and_immutable_capture", q == record["toolQuiescence"] and q["sealed"] is True and q["outstanding"] == 0 and
                    q["receipts"] == tr and len(tr) == 8 and all(r["finishedAt"] <= min(q["finishedAt"], capture["stoppedAt"]) and capture["stoppedAt"] <= deadline and
                    r["admittedAt"] < delivered for r in tr) and capture == record["artifactCapture"] == record["acceptance"]["artifactCapture"] and
                    persisted == {k: v for k, v in capture.items() if k != "captureReceiptPath"} and record["engineStoppedBeforeAcceptance"] is True and
                    deadline == ms(record["deadline"]) and task["solve_seconds"] == 1800 and chosen["at"] <= deadline and
                    all(ms(c["finishedAt"]) <= deadline for c in api))
            verdict = record["acceptance"]["verdict"]
            a.check(arm + "_valid_negative_is_not_infrastructure_failure", record["generationValid"] is True and record["acceptance"]["valid"] is True and
                    record["acceptance"]["passed"] is False and record["acceptance"]["outcome"] == "rejected" and
                    verdict["valid"] is True and verdict["ran"] is True and verdict["reward"] == 0 and verdict["completedTests"] == 1 and
                    verdict["artifactSha256"] == capture["artifactSha256"] == record["artifactSha256"])
            ports.extend(int(p) for row in rows for p in re.findall(r"127\.0\.0\.1:(\d+)", row["body"]))
            arms.append({"arm": arm, "state": task["state"], "apiMockCalls": len(api), "modelToolCounts": dict(model_tools),
                         "explicitModelVerify": len(explicit), "remainingExplicitChecks": explicit[0]["value"]["left"] if explicit else None,
                         "runtimeAutomaticGrades": len(internal), "independentFinalAcceptanceGrades": 1,
                         "expectedPhysicalGrades": len(explicit) + len(internal) + 1,
                         "toolRpcReceipts": len(tr), "candidateContainerId": capture["ownedContainerID"], "finalArtifactSha256": capture["artifactSha256"],
                         "selectedSubmitAt": chosen["at"], "firstDeliveryAt": delivered, "drainFinishedAt": q["finishedAt"],
                         "captureStoppedAt": capture["stoppedAt"], "deadline": deadline, "workerPid": record["workerPid"],
                         "traceRows": len(rows), "units": len(units), "validFinalReward": 0})

    grades, identities, process_ids = [], [], [r["workerPid"] for r in records]
    capture_grade_counts = Counter()
    for path in sorted((store / "stand").glob("grade-*/report.json")):
        report = read_json(path)
        v = report["candidateVerdict"]
        owner = read_json(path.parent / "operation-owner.json")
        actual = read_json(path.parent / "candidate/dependency-versions.json")
        ctrf = read_json(path.parent / "candidate/ctrf.json")["results"]
        reward = (path.parent / "candidate/reward.txt").read_text().strip()
        receipt, captured = capture_by_sha[report["captureReceiptSha256"]]
        capture_grade_counts[captured["receiptSha256"]] += 1
        valid = (report["validated"] is True and report["officialGradingValid"] is True and report["graderSourceSha256"] == grader_sha and
                 report["denominator"] == 87 and report["unsupportedTaskCount"] == 86 and report["formalLlmClosedLoopValidated"] is False and
                 report["imageId"] == v["imageId"] == IMAGE and report["transferOnly"] == FIXED and
                 report["imageManifestSha256"] == item_hashes["gate/image.json"] and report["buildProofSha256"] == item_hashes["gate/build.json"] and
                 report["dependencyProfileSha256"] == item_hashes["gate/profile.json"] and report["originalSourceHashes"] == controls["originalSourceHashes"] and
                 v["valid"] is True and v["ran"] is True and v["reward"] == v["passedTests"] == 0 and v["completedTests"] == 1 and
                 v["artifactSha256"] == receipt["artifactSha256"] == file_sha(path.parent / "candidate-stat_ocr.xlsx") and float(reward) == 0 and
                 ctrf["summary"]["tests"] == ctrf["summary"]["failed"] == 1 and ctrf["summary"]["passed"] == 0 and
                 len(ctrf["tests"]) == 1 and ctrf["tests"][0]["name"] == "test_outputs.py::test_outputs" and ctrf["tests"][0]["status"] == "failed" and
                 actual == v["dependencyVersions"] and actual["python"] == "3.12.3" and actual["baseExecutable"] == "/usr/bin/python3.12" and
                 actual["packages"] == profile["packages"] and actual["uv"] == "uv 0.9.7" and
                 actual["uvSha256"] == item_hashes["grader-dependencies/uv"] and v["graderNetwork"] == "none" and
                 all(v[k] is False for k in ("candidateSnapshotUsed", "candidateExecutablesUsed", "hostBinds")) and owner["lease"]["released"] is True and
                 len(owner["containers"]) == 1 and owner["containers"][0]["state"] == "removed" and owner["containers"][0]["role"] == "grader")
        grades.append({"path": str(path), "reportSha256": file_sha(path), "validSavedOfficialGrade": valid,
                       "captureReceiptSha256": captured["receiptSha256"], "artifactSha256": v["artifactSha256"],
                       "sealedPrivateInputSha256": file_sha(path.parent / "candidate-stat_ocr.xlsx"),
                       "containerId": owner["containers"][0]["containerId"], "namespaces": actual["namespaces"], "network": v["graderNetwork"],
                       "processId": owner["processId"],
                       "completedTests": 1, "reward": 0, "hostStart": min(r["at"] for r in report["resourceSamples"]),
                       "hostStop": max(r["at"] for r in report["resourceSamples"]), "maxWritableBytes": max(r["writableBytes"] for r in report["resourceSamples"]),
                       "minimumCFreeBytes": min(r["freeCBytes"] for r in report["resourceSamples"]), "minimumFFreeBytes": min(r["freeFBytes"] for r in report["resourceSamples"])})
        identities.extend(owner["containers"])
        process_ids.append(owner["processId"])
    candidate_owner = read_json(store / "stand/operation-owner.json")
    identities.extend(candidate_owner["containers"])
    process_ids.append(candidate_owner["processId"])
    a.check("six_fresh_grades_bound_to_saved_captures", len(grades) == sum(r["expectedPhysicalGrades"] for r in arms) == 6 and
            all(g["validSavedOfficialGrade"] for g in grades) and len({g["containerId"] for g in grades}) == 6 and
            all(next(r for r in capture_rows if r["receiptSha256"] == g["captureReceiptSha256"])["stoppedAt"] <= g["hostStart"] * 1000 for g in grades))
    a.check("all_six_private_resource_samples_inside_mock_limits", all(g["maxWritableBytes"] <= 128 * 1024**2 and
            g["minimumCFreeBytes"] >= 1536 * 1024**2 and g["minimumFFreeBytes"] >= 1152 * 1024**2 for g in grades),
            scope="Observed mock grader samples only; current paid reserves must be freshly admitted.")
    a.check("eight_exact_owners_recorded_removed_and_leases_released", len(identities) == len({x["containerId"] for x in identities}) == 8 and
            all(r["state"] == "removed" and r["expectedImageId"] == IMAGE for r in identities) and candidate_owner["lease"]["released"] is True and
            {r["containerId"] for r in candidate_owner["containers"]} == {r["candidateContainerId"] for r in arms})
    a.check("runner_cleanup_and_receipts_closed", cleanup["closed"] is True and cleanup["receiptsClosed"] is True and cleanup["candidateRemoved"] is True and
            cleanup["errors"] == [] and summary["receiptClosure"] is True and summary["sourceClosure"] is True and summary["cleanupClosed"] is True)
    a.check("original_six_secret_certificate_no_matches", secret_certificate["passed"] is True and secret_certificate["secretValuesChecked"] == 6 and
            secret_certificate["archiveMembersChecked"] == 4235 and secret_certificate["findings"] == [] and
            {Path(p).resolve() for p in secret_certificate["excludedPrivateConfigPaths"]} == set(configs) and "audit_evidence" in helper_source,
            certificateSha256=file_sha(meta / "evidence-secret-audit.json"), independentlyRecoverableValues=4,
            limitation="Two ephemeral stand/gateway and mock proxy credentials are unavailable after exit; their original six-value scan cannot be independently repeated by value.")
    a.check("recoverable_four_keys_absent_in_current_public_bytes_and_members", not a.secret_hits,
            files=len(a.scanned_public_files), zipMembers=len(a.scanned_zip_members), workbookXmlMembers=workbook_member_count, hits=a.secret_hits)
    docker = common.exact_docker_observations([i["containerId"] for i in identities], [IMAGE, runtime["executorImageId"]]) if args.docker else None
    if docker:
        a.check("eight_exact_container_ids_now_absent", all(r["absent"] is True for r in docker["containers"]))
        a.check("two_fixed_images_still_match", all(r["matched"] for r in docker["images"]))
    host = common.host_observations(sorted(set(process_ids)), ports)
    a.check("recorded_processes_and_endpoint_ports_now_closed", all(r.get("present") is False for r in host["processes"]) and
            all(r["listening"] is False for r in host["localPorts"]))
    lease_path = Path(candidate_owner["lease"]["path"])
    a.check("shared_owned_instance_lease_now_absent", not lease_path.exists(), path=str(lease_path))
    a.check("all_original_bytes_and_base_zip_unchanged_during_audit", before_meta == inventory(meta) and before_raw == inventory(store) and base_sha_before == file_sha(base))
    limitations = [
        "This is a local model replacement driving real Docker tools and official private graders. 19 HTTP200 mock receipts and toy token counts are not 19 LLM calls or a model score. providerAttempted=true means the local providerFetch branch was attempted.",
        "Only jpg-ocr-stat is implemented/control-validated; the source denominator remains 87 with 86 unsupported. No real LLM closed loop is validated here and readyTaskIds remains empty.",
        "CHECKS=6 limits explicit model verify only. This mock uses one explicit F verify (left5), three automatic runtime grades, and one independent F final grade; U has one final grade. These six physical grades must not be conflated with the model feedback budget or equal-budget causal comparisons.",
        "Candidate cold receipts save immutable container IDs and an environment check, not full historical HostConfig or candidate namespace numbers. Fixed source checks bridge/no shared host PID/no binds during create. Private grade records save none/no binds and PID/mount/network inodes, but namespace values can be reused after a container is removed.",
        "Capture receipts save Docker TAR completion, regular-file metadata, size and TAR SHA; the raw TAR bytes are not archived. The saved XLSX bytes, internal ZIP CRC/XML, capture hashes, grade receipt hashes and final artifact digests are independently verified here; the historical TAR parser cannot be replayed from bytes.",
        "F's final workbook was already stopped and captured during an earlier runtime submit grade, then the same sealed capture was returned after terminal drain. All actual tool completions precede both freeze and drain; the capture's earlier stoppedAt is not rewritten to the later host acceptance time.",
        "The original closure scans six live secret values, including two ephemeral credentials no longer recoverable after exit. This auditor independently repeats exact-value scans for four engine credentials, including raw SQLite and decoded workbook members. Private worker configs are deliberately excluded from public scans and must stay access-restricted.",
        "The new ZIP contains current executable source and task/gate data. Its immutable base ZIP is used only for 4115 enumerated npm/Node/private dependencies; older runner/core/task data elsewhere in that base are not executed or extracted.",
        "Current exact ID/PID/port absence and released-lease records corroborate cleanup. Historical process exit codes and complete Docker inspect results are not separately archived, so this is not generic isolation certification.",
        "Host resource limits (candidate writable256MiB, private128MiB, XLSX8MiB, tool890s/transfer90s/privateCLI650s) are additional operational constraints. Official agent1800s/verifier600s/CPU4/memory4096MiB are retained; 10GiB official storage is not reproduced by the writable caps.",
        "Real execution still requires a fresh paid source/gate freeze, current C/F reserves, shared paid lock, explicit feedback/runtime/final-grade accounting, project credential and root budget scheduling. The passing mock does not grant itself paid execution readiness.",
    ]
    result = {"schemaVersion": 1, "run": args.run, "auditedAt": datetime.now(timezone.utc).isoformat(), "readOnly": True,
              "auditSources": {str(Path(__file__)): file_sha(Path(__file__)), str(COMMON_PATH): file_sha(COMMON_PATH)},
              "passedAllAvailableChecks": all(c["passed"] for c in a.checks), "checks": a.checks,
              "newLlmRequests": 0, "newGraderRuns": 0, "dockerMutations": 0, "realLlmRequestsInAuditedRun": 0,
              "mockApiRequests": len(wire_rows), "recordedMockCostUsd": 0, "formalLlmClosedLoopValidated": False,
              "genericIsolationCertified": False, "readyTaskIds": [], "arms": arms, "captures": capture_rows, "physicalGrades": grades,
              "captureGradeCounts": dict(capture_grade_counts), "wireReceipts": wire_rows,
              "sourceArchive": {"path": str(archive), "sha256": frozen["archiveSha256"], "bytes": frozen["archiveBytes"], "members": 120},
              "referencedDependencies": {"path": str(base), "sha256": refs["sha256"], "members": 4115, "membersSha256": refs_digest},
              "sourceExecutionDigest": source["executionDigest"], "secretCertificate": secret_certificate,
              "definitionInventorySha256": file_sha(environment_manifest_path),
              "independentSecretScan": {"recoverableValues": 4, "publicFileOrDecodedMemberScans": len(a.scanned_public_files),
                                        "directAndReferencedZipMembers": len(a.scanned_zip_members), "workbookMembers": workbook_member_count,
                                        "findings": a.secret_hits, "unrecoverableEphemeralValues": 2},
              "dockerClosure": docker, "hostClosure": host, "ownerIdentities": identities,
              "historicalPidReuses": {str(pid): count for pid, count in Counter(process_ids).items() if count > 1},
              "metadataInventory": before_meta, "rawInventory": before_raw, "limits": manifest["hostOperationalLimits"],
              "limitations": limitations, "seconds": round(time.monotonic() - started, 3)}
    (out / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text = ["# Independent audit of the JPG Docker mock end-to-end run", "", f"Run `{args.run}`; read-only audit with no new model requests, regrading, or Docker changes.", "",
            "| Item | Independent verification |", "|---|---|",
            "| Scope | Source contains 87 tasks; only JPG is implemented, and the other 86 are unsupported |",
            "| Model | 19 local substitute receipts, 0 actual LLM requests, $0 |",
            "| Live path | Independent cold candidates for U/F, 8 RPCs each, pinned XLSX capture, and actual official private grading |",
            "| Final verdict | Both arms have valid=true/reward0: valid negative controls using intentionally incorrect workbooks |",
            "| Grading count | U: 1 final; F: 1 explicit feedback, 3 automatic, 1 independent final; 6 fresh graders in total |",
            "| Query budget | CHECKS=6 limits only explicit model verify calls; F used 1 here, leaving 5 |",
            "| Source/dependencies | 120 members in the new ZIP; references only 4115 public dependencies in base, with each SHA matching the current file |",
            "| Credentials | No hits for the original 6 values in the closure certificate; 4 independently recoverable values were checked again, and 2 temporary values are no longer retained |",
            "", f"Executable checks: {sum(c['passed'] for c in a.checks)}/{len(a.checks)} passed; the formal model experiment has not run, and `readyTaskIds=[]`.", "",
            "Evidence limitations:", ""]
    text += ["- " + item for item in limitations]
    text += ["", "Reproduction (`--docker` only performs read-only checks of the exact stored container IDs for this run):", "", "```powershell",
             f"python -X utf8 \"{Path(__file__)}\" --run {args.run} --docker", "```", "",
             "See `audit.json` in the same directory for detailed checks, output/grade binding, current closure observations, original file digests, and the audit source digest."]
    (out / "audit.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    print(json.dumps({"audit": str(out / "audit.json"), "passed": result["passedAllAvailableChecks"],
                      "checks": len(a.checks), "failedChecks": [c["name"] for c in a.checks if not c["passed"]],
                      "physicalGrades": len(grades), "rawFiles": len(before_raw), "realLlmRequests": 0}, ensure_ascii=False))
    return 0 if result["passedAllAvailableChecks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
