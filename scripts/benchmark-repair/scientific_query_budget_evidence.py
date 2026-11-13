"""Count already-saved scientific trace records; never grade or open original DBs."""
from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(r"F:\git\TgEngin-handoff-2026-10-07\TgEngin")
REPORT_ROOT = PROJECT / "docs" / "repair-2026-10-08"
RUNS = (
    ("repair-2026-10-08T06-54-55-267Z", "gpqa", 1386, "campaign.ts"),
    ("repair-2026-10-08T10-25-57-408Z", "chemiq", 20, "campaign-next.ts"),
)
NO_SUBMIT = "nothing was handed in - this step takes an answer and none was given"
KNOWN_MEMBERS = (
    "app/src/objective/tool.ts",
    "app/src/objective/run.ts",
    "app/src/tree/dfs.ts",
    "app/src/main.ts",
    "app/src/msg/deliver.ts",
    "app/src/engine/registry.ts",
    "scripts/benchmark-repair/campaign-contract.ts",
)
COUNTS = (
    "task_runs", "trace_rows", "instances",
    "model_verify_requests", "model_verify_returns",
    "model_completed_decisions", "model_quota_denied",
    "model_not_ran", "model_precondition_denied", "model_grader_error",
    "model_unclassified_returns",
    "auto_submit_graded_requests", "auto_submit_graded_returns",
    "auto_submit_new_evaluate_bearing", "auto_submit_reused",
    "auto_submit_no_submit_synthetic", "auto_submit_grader_error",
    "auto_submit_unclassified",
    "wrap_up_graded_requests", "wrap_up_graded_returns",
    "wrap_up_new_evaluate_bearing", "wrap_up_no_candidate_synthetic",
    "wrap_up_grader_error", "wrap_up_unclassified",
    "online_new_evaluate_bearing_trace_records",
    "posthoc_acceptance_records", "posthoc_acceptance_with_evaluate_trace",
    "posthoc_node_trace_records", "posthoc_without_evaluate",
    "total_new_evaluate_bearing_records_including_posthoc",
)
tracked: dict[str, dict] = {}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_original(path: Path) -> bytes:
    if path.suffix.lower() in {".sqlite", ".db", ".wal", ".shm"} or any(
        marker in path.name.lower() for marker in ("sqlite-wal", "sqlite-shm")
    ):
        raise RuntimeError("Original SQLite/WAL/SHM reading is prohibited.")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("A closed input changed while being read.")
    item = {"path": str(path), "bytes": len(raw), "sha256_before": digest(raw),
            "mtime_ns_before": before.st_mtime_ns}
    existing = tracked.get(str(path))
    if existing and existing != item:
        raise RuntimeError("The same closed input changed between reads.")
    tracked[str(path)] = item
    return raw


def read_json(path: Path):
    return json.loads(read_original(path).decode("utf-8-sig"))


def parsed_body(event: dict) -> dict:
    value = event.get("body")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError("A call/graded/tool trace body is not an object.")
    return value


def binary_pass(value: dict) -> bool:
    return type(value.get("pass")) is int and value["pass"] in (0, 1)


def classify(origin: str, value: dict) -> str:
    if origin == "model":
        if value.get("valid") is True and binary_pass(value) and value.get("outcome") in ("passed", "rejected"):
            return "model_completed_decisions"
        error = value.get("error")
        if isinstance(error, str) and error.startswith("the 5 checks for this attempt are spent.") and value.get("left") == 0:
            return "model_quota_denied"
        if value.get("ran") is False:
            return "model_not_ran"
        if error in (
            "answer is required - an empty one cannot be graded",
        ) or isinstance(error, str) and ("has no grading function" in error or error.startswith("cannot tell which task ")):
            return "model_precondition_denied"
        if value.get("valid") is False and value.get("outcome") == "grader_error":
            return "model_grader_error"
        return "model_unclassified_returns"
    if origin == "auto_submit":
        if set(value) == {"pass", "why"} and type(value.get("pass")) is int and value["pass"] == 0 and value.get("why") == NO_SUBMIT:
            return "auto_submit_no_submit_synthetic"
        if value.get("valid") is True and binary_pass(value) and value.get("outcome") in ("passed", "rejected"):
            return "auto_submit_reused" if value.get("reused") is True else "auto_submit_new_evaluate_bearing"
        if value.get("valid") is False and value.get("outcome") == "grader_error":
            return "auto_submit_grader_error"
        return "auto_submit_unclassified"
    if origin == "wrap_up":
        if value.get("valid") is False and value.get("outcome") == "no_candidate":
            return "wrap_up_no_candidate_synthetic"
        if value.get("valid") is True and binary_pass(value) and value.get("outcome") in ("passed", "rejected") and value.get("reused") is not True:
            return "wrap_up_new_evaluate_bearing"
        if value.get("valid") is False and value.get("outcome") == "grader_error":
            return "wrap_up_grader_error"
        return "wrap_up_unclassified"
    raise RuntimeError("Unknown verify request origin.")


def safe_submit_links(trace: list[dict], request: dict) -> list[dict]:
    if request["origin"] != "auto_submit":
        return []
    candidates = []
    for event in trace:
        if event["instance"] != request["instance"] or event["unit"] not in (request["unit"], request["unit"] - 1) or event["kind"] != "call":
            continue
        for call in parsed_body(event).get("calls", []):
            arguments = call.get("input")
            if call.get("name") == "submit" and isinstance(arguments, dict) and isinstance(arguments.get("answer"), str):
                candidates.append({"instance": event["instance"], "unit": event["unit"],
                                   "seq": event["seq"], "id": call.get("id")})
    return candidates


def analyze_task(task: dict, filename: Path) -> dict:
    counts = Counter()
    trace = task["trace"]
    canonical_trace = json.dumps(trace, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if digest(canonical_trace) != task["traceSha256"]:
        raise RuntimeError("Saved task.trace digest differs from its frozen recorded digest.")
    counts.update(task_runs=1, trace_rows=len(trace), instances=len({r["instance"] for r in trace}))
    requests: dict[tuple[str, str], dict] = {}
    results: dict[tuple[str, str], dict] = {}
    event_keys = set()
    for event in trace:
        event_key = (event["instance"], event["unit"], event["seq"])
        if event_key in event_keys:
            raise RuntimeError("Duplicate original instance/unit/seq trace identity.")
        event_keys.add(event_key)
        if event["kind"] not in ("call", "graded", "tool"):
            continue
        body = parsed_body(event)
        if event["kind"] in ("call", "graded"):
            for call in body.get("calls", []):
                if call.get("name") != "verify":
                    continue
                if not isinstance(call.get("id"), str):
                    raise RuntimeError("Verify request lacks its call ID.")
                key = (event["instance"], call["id"])
                if key in requests:
                    raise RuntimeError("Ambiguous reused verify call ID in one instance.")
                if event["kind"] == "call":
                    origin, trigger = "model", "model_explicit"
                else:
                    arguments = call.get("input")
                    at = arguments.get("at") if isinstance(arguments, dict) else None
                    if at == "wrap-up":
                        origin, trigger = "wrap_up", "wrap-up"
                    elif isinstance(at, str) and re.fullmatch(r"submit#\d+", at) and at == f"submit#{event['unit']}":
                        origin, trigger = "auto_submit", at
                    else:
                        raise RuntimeError("Unknown auto graded trigger; do not guess its G count.")
                requests[key] = {"instance": event["instance"], "unit": event["unit"],
                                 "seq": event["seq"], "id": call["id"],
                                 "origin": origin, "trigger": trigger}
                counts[{"model": "model_verify_requests", "auto_submit": "auto_submit_graded_requests",
                        "wrap_up": "wrap_up_graded_requests"}[origin]] += 1
        elif body.get("name") == "verify":
            key = (event["instance"], body.get("id"))
            if key in results:
                raise RuntimeError("More than one verify tool response has the same instance/call ID.")
            value = body.get("value")
            if not isinstance(value, dict):
                raise RuntimeError("Verify tool response value is not an object.")
            results[key] = {"event": event, "value": value}
    if set(requests) != set(results):
        raise RuntimeError("Unmatched verify request/response IDs; record boundary instead of inventing a count.")
    links = []
    unit_counts = defaultdict(Counter)
    for key, request in requests.items():
        result = results[key]
        value, response = result["value"], result["event"]
        if request["origin"] == "model" and request["id"].startswith("g-"):
            raise RuntimeError("Model call collides with the generated graded ID namespace.")
        category = classify(request["origin"], value)
        counts[category] += 1
        counts[{"model": "model_verify_returns", "auto_submit": "auto_submit_graded_returns",
                "wrap_up": "wrap_up_graded_returns"}[request["origin"]]] += 1
        unit_counts[(request["instance"], request["unit"])][category] += 1
        links.append({**request, "responseUnit": response["unit"], "responseSeq": response["seq"],
                      "classification": category, "validFieldPresent": "valid" in value,
                      "valid": value.get("valid"), "reused": value.get("reused") is True,
                      "submitCallsInCurrentOrPrecedingUnit": safe_submit_links(trace, request)})
    online = sum(counts[c] for c in ("model_completed_decisions", "auto_submit_new_evaluate_bearing", "wrap_up_new_evaluate_bearing"))
    counts["online_new_evaluate_bearing_trace_records"] = online
    acceptance = task["acceptance"]
    if acceptance.get("candidateSha256") != task.get("candidateSha256"):
        raise RuntimeError("Existing posthoc acceptance was about a different frozen candidate.")
    counts["posthoc_acceptance_records"] = 1
    verdict = acceptance.get("verdict")
    if isinstance(verdict, dict) and isinstance(verdict.get("trace"), list) and verdict["trace"]:
        nodes = verdict["trace"]
        if [row.get("node") for row in nodes] != ["parsed", "correct"]:
            raise RuntimeError("Existing posthoc objective node trace has an unexpected scope.")
        counts["posthoc_acceptance_with_evaluate_trace"] = 1
        counts["posthoc_node_trace_records"] = len(nodes)
        node_shape = [{"node": row["node"], "hasError": bool(row.get("error")),
                       "booleanValuePresent": type(row.get("value")) is bool} for row in nodes]
    else:
        counts["posthoc_without_evaluate"] = 1
        node_shape = []
    counts["total_new_evaluate_bearing_records_including_posthoc"] = online + counts["posthoc_acceptance_with_evaluate_trace"]
    return {"index": task["index"], "officialId": task["officialId"], "taskId": task["taskId"],
            "arm": task["arm"], "replica": task["replica"], "inputPath": str(filename),
            "traceSha256RecordedAndMatched": task["traceSha256"], "counts": {k: counts[k] for k in COUNTS},
            "queryLinks": links,
            "perRequestUnitCounts": [{"instance": instance, "unit": unit, "counts": dict(values)}
                                    for (instance, unit), values in sorted(unit_counts.items())],
            "posthocExistingAcceptance": {"valid": acceptance.get("valid"), "nodeRecords": node_shape,
                                         "newScoringExecuted": False},
            "submitLinkageLimit": "Trace exports no DFS node membership; nearby submit call IDs are candidates, not a certified selection or quota-node reconstruction."}


def source_rules(archive: bytes, source: dict, runner: str) -> list[dict]:
    import io
    expected = {item["path"]: item["sha256"] for group in ("files", "repairFiles") for item in source.get(group, [])}
    selected = (*KNOWN_MEMBERS, f"scripts/benchmark-repair/{runner}")
    rules = {
        "app/src/objective/tool.ts": [(89, 130, "checksOf=5; quota guard precedes evaluate; valid decisions consume budget"),
                                      (164, 220, "per DFS node; g- automatic feedback excluded; invalid/error/nonbinary responses excluded")],
        "app/src/tree/dfs.ts": [(274, 304, "exact-text reuse only from kind=call model verify plus linked tool result"),
                                (441, 501, "no-submit emits synthetic feedback; had bypasses evaluate and marks reused")],
        "app/src/main.ts": [(145, 179, "wrap-up evaluates a submitted final candidate afresh; no candidate skips evaluate")],
        "app/src/msg/deliver.ts": [(407, 433, "graded pair is generated assistant request and linked tool reply, not a model request")],
        "app/src/objective/run.ts": [(113, 160, "evaluate visits all objective nodes; binary pass has separate execution validity")],
        "app/src/engine/registry.ts": [(228, 237, "remote handle source issues POST per node; source is not an HTTP transport ledger")],
        "scripts/benchmark-repair/campaign-contract.ts": [(131, 151, "posthoc frozen candidate, two node receipts; invalid/no candidate preconditions skip evaluate")],
    }
    entries = []
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        for name in selected:
            raw = z.read(name)
            if name not in expected or digest(raw) != expected[name]:
                raise RuntimeError("Selected executed ZIP source does not match the frozen source manifest.")
            text = raw.decode("utf-8")
            if name.endswith("campaign.ts") and "checks: 5, reuse:" not in text:
                raise RuntimeError("Frozen GPQA objective configuration changed.")
            if name.endswith("campaign-next.ts") and "checks: 5, reuse:" not in text:
                raise RuntimeError("Frozen ChemIQ objective configuration changed.")
            entries.append({"path": name, "sha256": digest(raw), "bytes": len(raw),
                            "matchedFrozenSourceManifest": True,
                            "ruleSpans": [{"first": a, "last": b, "meaning": meaning}
                                          for a, b, meaning in rules.get(name, [])]})
    return entries


def distribution(values: list[int]) -> dict:
    return {"min": min(values), "median": statistics.median(values), "max": max(values),
            "zeroTaskRuns": sum(x == 0 for x in values)}


def analyze_run(run: str, benchmark: str, expected_tasks: int, runner: str) -> dict:
    base = REPORT_ROOT / "campaigns" / run
    manifest = read_json(base / "manifest.json")
    source = read_json(base / "source.json")
    frozen = read_json(base / "frozen-source.json")
    summary = read_json(base / "summary.json")
    analysis = read_json(base / "analysis.json")
    if not (manifest["campaign"] == frozen["campaign"] == run):
        raise RuntimeError("Closed campaign identity mismatch.")
    if not (manifest["sourceExecutionDigest"] == source["executionDigest"] == frozen["sourceExecutionDigest"]):
        raise RuntimeError("Closed manifest/frozen execution source digests differ.")
    budget = {key: manifest[key] for key in ("checksPerAttempt", "maxBranchesF", "maxDeadSiblingsF", "maxBranchesUR", "independentRReplicas")}
    if budget != {"checksPerAttempt": 5, "maxBranchesF": 4, "maxDeadSiblingsF": 100000, "maxBranchesUR": 1, "independentRReplicas": 5}:
        raise RuntimeError("Actual closed scientific budget differs; do not import another run's settings.")
    archive_path = Path(frozen["archive"])
    if str(archive_path) != str(PROJECT / ".phase1-data" / "repair" / run / "frozen-source.zip"):
        raise RuntimeError("Unexpected source archive path.")
    archive = read_original(archive_path)
    if digest(archive) != frozen["archiveSha256"] or len(archive) != frozen["archiveBytes"]:
        raise RuntimeError("Original executed source archive identity differs.")
    source_entries = source_rules(archive, source, runner)
    filenames = sorted(base.glob("task-*.json"), key=lambda p: int(p.stem[5:]))
    if len(filenames) != expected_tasks or [int(p.stem[5:]) for p in filenames] != list(range(expected_tasks)):
        raise RuntimeError("Closed task denominator is incomplete or duplicated.")
    tasks = []
    groups = defaultdict(Counter)
    grouped_tasks = defaultdict(list)
    for index, filename in enumerate(filenames):
        task = read_json(filename)
        if task["index"] != index or task["benchmark"] != benchmark:
            raise RuntimeError("Task index/benchmark differs from fixed campaign scope.")
        entry = analyze_task(task, filename)
        tasks.append(entry)
        groups[entry["arm"]].update(entry["counts"])
        grouped_tasks[entry["arm"]].append(entry)
    if summary["recordedTaskRuns"] != expected_tasks or summary["plannedTaskRuns"] != expected_tasks or not analysis.get("evidenceReady"):
        raise RuntimeError("Original run is not evidence-closed under its saved analysis.")
    closing = []
    for name in ("independent-closing-audit.json", "independent-deferred-closing-audit.json"):
        if (base / name).exists():
            audit = read_json(base / name)
            closing.append({"path": str(base / name), "validated": audit.get("validated"),
                            "evidenceReady": audit.get("evidenceReady"), "keys": sorted(audit)})
    return {"run": run, "benchmark": benchmark, "taskRuns": expected_tasks,
            "sourceExecutionDigest": source["executionDigest"], "sourceArchiveSha256": frozen["archiveSha256"],
            "manifestBudget": budget, "budgetScope": "valid explicit model verify decisions per DFS attempt node; no task-wide G ceiling of five",
            "closure": {"summaryCompleted": summary.get("completed"), "analysisCompleted": analysis.get("completed"),
                        "evidenceReady": analysis.get("evidenceReady"), "independentSavedAudits": closing},
            "frozenSourceRules": source_entries,
            "groups": [{"arm": arm, "counts": {k: values[k] for k in COUNTS},
                        "onlineNewEvaluateBearingRecordsPerTask": distribution([t["counts"]["online_new_evaluate_bearing_trace_records"] for t in grouped_tasks[arm]]),
                        "modelCompletedVerifyDecisionsPerTask": distribution([t["counts"]["model_completed_decisions"] for t in grouped_tasks[arm]])}
                       for arm, values in groups.items()],
            "physicalEvaluateCallCount": None, "physicalGraderHttpRequestCount": None,
            "physicalBoundary": "Saved task traces are feedback records, not an evaluate/HTTP transport ledger. Source-backed inferred new-evaluate-bearing receipts are explicitly named; providerCalls are model requests and not G HTTP counts.",
            "sourceImpliedTwoNodeVisitsForInferredEvaluateBearingRecords": 2 * sum(t["counts"]["total_new_evaluate_bearing_records_including_posthoc"] for t in tasks),
            "sourceImpliedCountIsPhysicalMeasurement": False,
            "tasks": tasks}


def write_report(path: Path, raw: bytes) -> None:
    if path.parent != REPORT_ROOT:
        raise RuntimeError("Only this new F report directory is writable.")
    temporary = path.with_name(path.name + ".owned.tmp")
    with temporary.open("xb") as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    os.replace(temporary, path)


def markdown(report: dict) -> str:
    rows = []
    for run in report["runs"]:
        for group in run["groups"]:
            c = group["counts"]
            rows.append("| " + " | ".join(map(str, [
                run["benchmark"], group["arm"], c["task_runs"],
                f"{c['model_verify_requests']}/{c['model_verify_returns']}",
                c["model_completed_decisions"], c["model_quota_denied"],
                c["auto_submit_graded_returns"], c["auto_submit_reused"], c["auto_submit_no_submit_synthetic"],
                c["wrap_up_graded_returns"], c["online_new_evaluate_bearing_trace_records"],
                c["posthoc_acceptance_with_evaluate_trace"], c["posthoc_node_trace_records"],
            ])) + " |")
    examples = []
    for run in report["runs"]:
        for task in run["tasks"]:
            if run["benchmark"] == "gpqa" and task["index"] in (6, 538) or run["benchmark"] == "chemiq" and task["index"] == 1:
                c = task["counts"]
                examples.append(f"- {run['benchmark']} index {task['index']} ({task['arm']}): auto {c['auto_submit_graded_returns']}, reused {c['auto_submit_reused']}, no-submit {c['auto_submit_no_submit_synthetic']}, wrap-up {c['wrap_up_graded_returns']}; model verify {c['model_verify_requests']}/{c['model_verify_returns']}, completed {c['model_completed_decisions']}; online new-evaluate-bearing trace records {c['online_new_evaluate_bearing_trace_records']}; existing posthoc {c['posthoc_acceptance_with_evaluate_trace']}.")
    return "\n".join([
        "# G-query accounting for closed scientific batches",
        "",
        f"Read-only observation {report['observedAtUtc']}. Scope: 1386 task runs for GPQA 198 tasks U/R5/F, plus 20 task runs for the first 10 ChemIQ tasks U/F. Only saved JSON and original execution-source ZIPs were read; original SQLite/WAL/SHM were not opened, and no grading, model/API, Docker, network, candidate, or paper operations occurred.",
        "",
        "Both batches' actual frozen manifests specify checksPerAttempt=5, maxBranchesF=4, maxDeadSiblingsF=100000, maxBranchesUR=1, R replicas=5. CHECKS=5 limits valid verdicts received after explicit model verify in each DFS attempt node; automatic submit and wrap-up do not consume it. Traces do not export DFS node membership, so this report aligns only instance/unit/call IDs and does not claim to reconstruct per-node quota enforcement. Separate TB/SKB batches with CHECKS6/F1 are not combined with these scientific runs.",
        "",
        "Requests/returns distinguish explicit model verify with kind=call from system injections with kind=graded. Tool results match only on the same instance and complete call ID, retaining request/return unit and seq. Automatic submit uses input.at=submit#<unit>; wrap-up uses input.at=wrap-up. Synthetic no-submit feedback must also match the frozen source's exact {pass:0, why:fixed no-submit text} shape. Missing valid alone does not imply G executed or a candidate was rejected.",
        "",
        "| Batch | arm | task runs | model requests/returns | Valid explicit verdicts | Quota rejections | auto submit | reused | Synthetic no-submit | wrap-up | Records carrying inferred new online evaluate calls* | posthoc evaluate traces | posthoc node records |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
        "Of GPQA's 107 explicit returns, 106 are valid verdicts and 1 exactly matches an empty-answer precondition rejection before evaluate; explicit quota rejections are 0. Of ChemIQ's 191 explicit returns, 185 are valid and 6 exactly match 5-check quota rejection. Every verify request and tool return in both batches has a unique closed association, with no unclassified, orphaned, or multiple call-ID associations.",
        "",
        "*Records carrying inferred new online evaluate calls = valid explicit verify verdicts + non-reused, non-synthetic automatic submit verdicts + wrap-up verdicts with a candidate. This record count is inferred from fully associated traces and frozen source paths, not an independent physical evaluate/HTTP event count. physicalEvaluateCallCount and physicalGraderHttpRequestCount are both null; missing event records must not be written as 0. providerCalls counts model-provider requests, not grading G requests.",
        "",
        "reused=true re-emits an old verdict for the exact candidate without a new evaluate; synthetic no-submit feedback and quota rejection both occur before evaluate. wrap-up evaluates again when a submitted candidate exists; the source has no text-reuse branch. Unified posthoc final acceptance separately grades the pinned final candidate after generation ends. Here only saved acceptance/verdict.trace records are counted, each containing parsed/correct nodes; they are not rerun or counted against explicit model CHECKS.",
        "",
        *examples,
        "",
        "Pinned scientific G is defined in source as two nodes, parsed→correct. The evaluate source visits all nodes topologically, and the HTTP handle source sends one POST per node. JSON separately records sourceImpliedTwoNodeVisitsForInferredEvaluateBearingRecords, explicitly not certifying it as a physical HTTP count, internal service-grading count, or OPSIN/cache count. Saved posthoc node traces are more detailed than online summaries but still lack independent HTTP request-ID/timestamp event records.",
        "",
        "Input integrity: traceSha256 for all 1406 original task JSON files matches recomputation in the same field order. Before/after SHAs and byte counts are recorded individually for manifest/source/frozen-source/summary/analysis, both original execution ZIPs, and existing closure JSON. Referenced rule members in execution ZIPs individually match original source.json SHAs. Complete call associations retain only metadata, classification, and counts, not answers, GT, input.answer, graded text, why/note bodies, or keys. Original bytes/SHAs are unchanged before and after.",
        "",
        "JSON saves counts for each task run and request unit, unique call-ID associations, original fingerprints, and frozen source line spans. Nearby submit call IDs in the current/previous unit are listed only as possible associations; without a DFS node map, actual candidate selection is not falsely claimed. The report only adds new F files; it does not backfill original manifests, traces, metadata, production sources, or existing results.",
        "",
    ])


def main() -> None:
    runs = [analyze_run(*configuration) for configuration in RUNS]
    originals = []
    for filename, before in tracked.items():
        path = Path(filename)
        after = path.stat()
        raw = path.read_bytes()
        if digest(raw) != before["sha256_before"] or len(raw) != before["bytes"] or after.st_mtime_ns != before["mtime_ns_before"]:
            raise RuntimeError("An original task/meta/source changed during this read-only audit.")
        originals.append({**before, "sha256_after": digest(raw), "bytesAfter": len(raw),
                          "mtime_ns_after": after.st_mtime_ns, "unchanged": True})
    report = {"protocol": "saved-scientific-query-budget-evidence-v1",
              "observedAtUtc": datetime.now(timezone.utc).isoformat(), "validated": True,
              "helperSha256": digest(Path(__file__).read_bytes()),
              "actions": {"originalDatabaseOpened": False, "newScoringExecuted": False,
                          "modelCalled": False, "networkCalled": False, "dockerCalled": False,
                          "paperModified": False, "originalSourceEdited": False},
              "physicalCountsAvailable": False, "runs": runs, "originalInputs": originals,
              "originalInputsUnchanged": True}
    write_report(REPORT_ROOT / "scientific-query-budget-evidence.json",
                 (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    write_report(REPORT_ROOT / "scientific-query-budget-evidence.md", markdown(report).encode("utf-8"))
    print(json.dumps({"validated": True, "originalInputFiles": len(originals),
                      "taskRuns": sum(r["taskRuns"] for r in runs),
                      "runGroups": [{"run": r["run"], "groups": r["groups"],
                                     "physicalEvaluateCallCount": r["physicalEvaluateCallCount"],
                                     "physicalGraderHttpRequestCount": r["physicalGraderHttpRequestCount"]}
                                    for r in runs]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
