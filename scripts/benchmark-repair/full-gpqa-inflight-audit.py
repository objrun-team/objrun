"""Independent read-only audit of stored GPQA requests; no LLM/grader calls.

Writes only its separate audit JSON/Markdown. An evolving ledger/summary and
unfinished API receipts are observations of a live run, not missing evidence.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/repair-2026-10-08"
DEFAULT_RUN = "repair-2026-10-08T06-54-55-267Z"
WIRE = ["model", "temperature", "seed", "reasoning_effort", "thinking", "reasoning", "provider", "max_tokens", "max_completion_tokens", "tool_choice", "response_format", "stream"]
TOLERANCE = 1e-9


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def js_json(value):
    def normalized(item):
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, list):
            return [normalized(v) for v in item]
        if isinstance(item, dict):
            return {k: normalized(v) for k, v in item.items()}
        return item
    return json.dumps(normalized(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def snapshot(path):
    last = None
    for attempt in range(4):
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            last = error
            time.sleep(0.02)
            continue
        if before.st_size == after.st_size == len(raw) and before.st_mtime_ns == after.st_mtime_ns:
            return value, {"path": str(path), "sha256": sha(raw), "bytes": len(raw), "mtime_ns": after.st_mtime_ns, "stable_read": True, "read_attempts": attempt + 1}
        last = RuntimeError("file changed while read")
        time.sleep(0.02)
    raise RuntimeError(f"Cannot obtain a stable JSON observation: {path.name}: {type(last).__name__}")


def close_number(a, b):
    return type(a) in {int, float} and type(b) in {int, float} and math.isfinite(a) and math.isfinite(b) and abs(a - b) <= TOLERANCE


def token_counts(usage):
    if not isinstance(usage, dict):
        raise ValueError("MissingUsage")
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    cached = usage.get("prompt_cache_hit_tokens", (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0))
    if any(type(v) is not int or v < 0 or v > 2**53 - 1 for v in [prompt, completion, cached]) or cached > prompt:
        raise ValueError("InvalidUsageCounts")
    return prompt, completion, cached


def token_cost(usage, rates):
    prompt, completion, cached = token_counts(usage)
    return float(((Decimal(prompt - cached) * Decimal(str(rates["input"]))) + Decimal(cached) * Decimal(str(rates["cachedInput"])) + Decimal(completion) * Decimal(str(rates["output"]))) / Decimal(1000000))


def completion_fault(data):
    if not isinstance(data, dict) or data.get("error"):
        return "InvalidCompletionEnvelope"
    if not isinstance(data.get("choices"), list) or not data["choices"]:
        return "MissingCompletionChoices"
    for choice in data["choices"]:
        message = choice.get("message") if isinstance(choice, dict) else None
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return "InvalidCompletionMessage"
        tools = message.get("tool_calls")
        if tools is not None:
            if not isinstance(tools, list):
                return "InvalidCompletionToolCalls"
            for call in tools:
                fn = call.get("function") if isinstance(call, dict) else None
                if not isinstance(call, dict) or call.get("type") != "function" or not isinstance(call.get("id"), str) or not call["id"] or not isinstance(fn, dict) or not isinstance(fn.get("name"), str) or not fn["name"] or not isinstance(fn.get("arguments"), str):
                    return "InvalidCompletionToolCall"
        has_text = isinstance(message.get("content"), str)
        has_tools = isinstance(tools, list) and bool(tools)
        has_reasoning = any(isinstance(message.get(key), str) and bool(message[key]) for key in ("reasoning_content", "reasoning"))
        if not has_text and not has_tools and not has_reasoning:
            return "MissingCompletionMessagePayload"
        if message.get("content") is not None and not has_text:
            return "InvalidCompletionContent"
    return None


def gzip_evidence(path, expected, store):
    path = Path(path)
    if not path.resolve().is_relative_to(store.resolve()):
        raise ValueError("RawEvidencePathOutsideDeclaredStore")
    before = path.stat()
    compressed = path.read_bytes()
    after = path.stat()
    raw = gzip.decompress(compressed)  # Includes gzip CRC/size integrity checks.
    data = json.loads(raw)
    return data, raw, {"path": str(path), "compressed_sha256": sha(compressed), "compressed_bytes": len(compressed),
        "decompressed_sha256": sha(raw), "decompressed_bytes": len(raw), "receipt_digest_matches": sha(raw) == expected,
        "stable_file_read": before.st_size == after.st_size == len(compressed) and before.st_mtime_ns == after.st_mtime_ns}


def source_audit(directory, source, frozen, manifest):
    checks = []
    expected_source = {r["path"]: r for r in source["files"] + source["repairFiles"]}
    for name, item in expected_source.items():
        path = ROOT / name
        current = sha(path.read_bytes()) if path.is_file() else None
        checks.append({"path": name, "expected_sha256": item["sha256"], "observed_sha256": current, "matches": current == item["sha256"]})
    archive_path = Path(frozen["archive"])
    archive_sha = sha(archive_path.read_bytes())
    dependency_checks = []
    member_checks = []
    dependency_map = {r["path"]: r for r in frozen["dependencyFiles"]}
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            raw = archive.read(info)
            expected = dependency_map.get(info.filename) or expected_source.get(info.filename)
            current_path = ROOT / info.filename
            current_sha = sha(current_path.read_bytes()) if current_path.is_file() else None
            member_checks.append({"path": info.filename, "archive_sha256": sha(raw), "expected_sha256": expected["sha256"] if expected else None,
                "archive_matches_manifest": bool(expected) and sha(raw) == expected["sha256"], "current_matches_archive": current_sha == sha(raw),
                "scope": "dependency" if info.filename in dependency_map else "executed_source"})
        member_names = set(archive.namelist())
        dependency_checks = [{"path": name, "in_archive": name in member_names} for name in dependency_map]
    archive_source_paths = {r["path"] for r in member_checks if r["scope"] == "executed_source"}
    changed_source = [r for r in checks if not r["matches"]]
    return {"recorded_source_digest_matches_its_file_list": sha(js_json(source["files"])) == source["sourceDigest"],
        "recorded_execution_digest_matches": sha(js_json({"sourceDigest": source["sourceDigest"], "repairFiles": source["repairFiles"]})) == source["executionDigest"],
        "execution_digest_agrees_across_source_frozen_manifest": source["executionDigest"] == frozen["sourceExecutionDigest"] == manifest["sourceExecutionDigest"],
        "source_file_checks": checks, "source_files_checked": len(checks), "source_mismatches": changed_source,
        "executed_source_mismatches": [r for r in changed_source if r["path"] in archive_source_paths],
        "nonexecuted_snapshot_source_mismatches": [r for r in changed_source if r["path"] not in archive_source_paths],
        "archive": {"path": str(archive_path), "expected_sha256": frozen["archiveSha256"], "observed_sha256": archive_sha, "digest_matches": archive_sha == frozen["archiveSha256"],
            "bytes_match": archive_path.stat().st_size == frozen["archiveBytes"], "source_members": len(archive_source_paths),
            "dependency_members": len(member_checks) - len(archive_source_paths), "member_manifest_mismatches": [r for r in member_checks if not r["archive_matches_manifest"]],
            "current_member_mismatches": [r for r in member_checks if not r["current_matches_archive"]],
            "member_checks": member_checks}, "all_dependency_paths_in_archive": all(r["in_archive"] for r in dependency_checks),
        "dependency_manifest_digest_matches": sha(js_json(frozen["dependencyFiles"])) == frozen["dependencyDigest"],
        "limitation": "Source snapshot includes unused benchmark adapters; their changes are shown separately from the executed frozen source. Archive preservation does not freeze the provider checkpoint."}


def main(run, require_complete):
    if not re.fullmatch(r"repair-[0-9TZ-]+", run):
        raise ValueError("Invalid declared campaign name")
    start = datetime.now(timezone.utc)
    directory = OUT / "campaigns" / run
    store = ROOT / ".phase1-data/repair" / run
    inputs = {}
    values = {}
    for name in ["manifest.json", "source.json", "frozen-source.json", "gpqa-public-tasks.json", "api-ledger.json", "summary.json"]:
        values[name], inputs[name] = snapshot(directory / name)
    manifest, source, frozen = (values[n] for n in ["manifest.json", "source.json", "frozen-source.json"])
    ledger, summary = values["api-ledger.json"], values["summary.json"]
    calls = ledger["calls"]
    finished = [(i, r) for i, r in enumerate(calls) if r.get("finishedAt")]
    unfinished = [(i, r) for i, r in enumerate(calls) if not r.get("finishedAt")]
    rates = manifest["ratesPeakUsdPerMillion"]
    public = {r["officialId"]: r for r in values["gpqa-public-tasks.json"]}
    receipt_reports = []
    inflight_reports = []
    tool_sets = defaultdict(set)
    parameters = Counter()
    usage_totals = Counter()
    fingerprint_counts = Counter()
    finish_reason_counts = Counter()
    source_results = source_audit(directory, source, frozen, manifest)
    for index, receipt in finished:
        row = {"sequence": index, "route": receipt["route"], "startedAt": receipt.get("startedAt"), "finishedAt": receipt["finishedAt"],
            "httpStatus": receipt.get("httpStatus"), "requestId": receipt.get("requestId"), "fault": receipt.get("fault"), "errors": [], "warnings": []}
        if receipt.get("fault"):
            row["errors"].append("RecordedProviderOrCaptureFault")
        if receipt.get("httpStatus") != 200:
            row["errors"].append("ProviderHTTPFailure")
        try:
            request, raw, evidence = gzip_evidence(receipt["requestFile"], receipt["requestSha256"], store)
            row["request"] = evidence
            if not evidence["receipt_digest_matches"] or not evidence["stable_file_read"]:
                row["errors"].append("RequestDigestOrReadStabilityMismatch")
            actual_wire = {k: request[k] for k in WIRE if k in request}
            row["actual_wire_parameters"] = actual_wire
            row["actual_output_token_limit"] = request.get("max_tokens", request.get("max_completion_tokens"))
            row["wire_parameters_match_receipt"] = actual_wire == receipt.get("wireParameters")
            if not row["wire_parameters_match_receipt"]:
                row["errors"].append("WireParameterReceiptMismatch")
            limits = [request[k] for k in ["max_tokens", "max_completion_tokens"] if request.get(k) is not None]
            valid_limit = bool(limits) and all(type(v) is int and 1 <= v <= manifest["maxTokensPerRequest"] for v in limits) and len(set(limits)) == 1
            declared = {"model": manifest["model"], "temperature": manifest["temperature"], "seed": manifest["seed"], "reasoning_effort": manifest["reasoningEffort"]}
            row["wire_matches_declared_protocol"] = all(request.get(k) == v for k, v in declared.items()) and valid_limit and request.get("stream") is not True
            if not row["wire_matches_declared_protocol"]:
                row["errors"].append("WireDeclaredProtocolMismatch")
            names = {t.get("function", {}).get("name") for t in request.get("tools", []) if isinstance(t, dict)}
            names.discard(None)
            arm = receipt["route"].split("/")[2]
            tool_sets[arm].update(names)
            row["tool_names"] = sorted(names)
            if names - {"submit", "verify", "task_tree", "node_load"}:
                row["errors"].append("UndeclaredToolOnWire")
            parameters[json.dumps(actual_wire, sort_keys=True, ensure_ascii=False)] += 1
            input_upper = len(raw) + 2048 + (len(request["messages"]) * 256 if isinstance(request.get("messages"), list) else 0)
            reserve = (input_upper * rates["input"] + (limits[0] if valid_limit else 0) * rates["output"]) / 1e6
            row["recomputed_reservation_usd"] = reserve
            row["reservation_matches_request"] = close_number(receipt.get("reservationUsd"), reserve)
            if not row["reservation_matches_request"]:
                row["errors"].append("ReservationRequestMismatch")
            response, _, rsp_evidence = gzip_evidence(receipt["responseFile"], receipt.get("responseSha256"), store)
            row["response"] = rsp_evidence
            if not rsp_evidence["receipt_digest_matches"] or not rsp_evidence["stable_file_read"]:
                row["errors"].append("ResponseDigestOrReadStabilityMismatch")
            row["served_model"] = response.get("model")
            row["served_model_matches_receipt"] = response.get("model") == receipt.get("servedModel")
            row["request_id_matches_response"] = response.get("id") == receipt.get("requestId")
            row["raw_usage_matches_receipt"] = response.get("usage") == receipt.get("usage")
            row["raw_usage"] = response.get("usage")
            if not row["served_model_matches_receipt"] or not row["request_id_matches_response"] or not row["raw_usage_matches_receipt"]:
                row["errors"].append("ResponseReceiptMetadataMismatch")
            fault = completion_fault(response)
            row["recomputed_completion_fault"] = fault
            row["completion_contract_matches"] = receipt.get("completionValid") is (fault is None) and receipt.get("completionFault") == fault
            if receipt.get("httpStatus") == 200 and not row["completion_contract_matches"]:
                row["errors"].append("CompletionContractMismatch")
            usage = response.get("usage")
            prompt, completion, cached = token_counts(usage)
            usage_totals.update({"prompt_tokens": prompt, "completion_tokens": completion, "cached_tokens": cached})
            row["usage_total_tokens_consistent"] = usage.get("total_tokens") == prompt + completion
            details_cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
            row["both_cache_counts_consistent"] = details_cached is None or usage.get("prompt_cache_hit_tokens", details_cached) == details_cached
            row["cache_miss_count_consistent"] = usage.get("prompt_cache_miss_tokens", prompt - cached) == prompt - cached
            if not all(row[k] for k in ["usage_total_tokens_consistent", "both_cache_counts_consistent", "cache_miss_count_consistent"]):
                row["warnings"].append("AdditionalUsageFieldsInconsistent")
            cost = token_cost(usage, rates)
            row["recomputed_usage_upper_bound_usd"] = cost
            row["cost_matches_usage_and_accounting"] = receipt.get("costBasis") == "reported_usage" and close_number(receipt.get("usdUpperBound"), cost) and close_number(receipt.get("accountedUpperBoundUsd"), cost)
            if not row["cost_matches_usage_and_accounting"]:
                row["errors"].append("UsageCostAccountingMismatch")
            if completion > (limits[0] if valid_limit else 0):
                row["warnings"].append("ProviderCompletionUsageExceedsRequestedLimit")
            row["completion_usage_within_actual_wire_limit"] = valid_limit and completion <= limits[0]
            fingerprint_counts[str(response.get("system_fingerprint"))] += 1
            for choice in response.get("choices", []):
                finish_reason_counts[str(choice.get("finish_reason"))] += 1
        except Exception as error:
            row["errors"].append(type(error).__name__)
        receipt_reports.append(row)
    for index, receipt in unfinished:
        row = {"sequence": index, "route": receipt["route"], "startedAt": receipt.get("startedAt"), "status": "in_flight_at_ledger_observation", "finished_audit_required": True}
        try:
            request, raw, evidence = gzip_evidence(receipt["requestFile"], receipt["requestSha256"], store)
            limits = [request[k] for k in ["max_tokens", "max_completion_tokens"] if request.get(k) is not None]
            row["request_capture"] = evidence
            row["recomputed_reservation_usd"] = ((len(raw) + 2048 + len(request.get("messages", [])) * 256) * rates["input"] + limits[0] * rates["output"]) / 1e6
        except Exception as error:
            row["observation_note"] = "In-flight request capture could not be checked: " + type(error).__name__ + "; re-observe after closure"
        row["response_capture_not_required_yet"] = True
        inflight_reports.append(row)
    unfinished_by_route = dict(Counter(r["route"] for _, r in unfinished))
    pending_nonzero = {k: v for k, v in ledger["pending"].items() if v}
    spent_sum = sum(r.get("accountedUpperBoundUsd", 0) for r in calls)
    reserve_sum = sum(r.get("recomputed_reservation_usd", 0) for r in inflight_reports)
    cost_ledger = {"recorded_usage_upper_bound_usd": ledger["recordedUsageUpperBoundUsd"], "sum_accounted_receipts_usd": spent_sum,
        "recorded_cost_closed": close_number(ledger["recordedUsageUpperBoundUsd"], spent_sum),
        "reserved_upper_bound_usd": ledger["reservedUpperBoundUsd"], "unfinished_request_reservations_usd": reserve_sum,
        "reserved_cost_closed": close_number(ledger["reservedUpperBoundUsd"], reserve_sum),
        "pending_routes_match_unfinished_receipts": pending_nonzero == unfinished_by_route,
        "prior_cost_agrees_with_manifest": close_number(ledger["priorCampaignCostUpperBoundUsd"], manifest["priorCampaignCostUpperBoundUsd"]),
        "cap_agrees_with_manifest": ledger["capUsd"] == manifest["capUsd"],
        "within_declared_cap_at_observation": ledger["priorCampaignCostUpperBoundUsd"] + ledger["recordedUsageUpperBoundUsd"] + ledger["reservedUpperBoundUsd"] <= ledger["capUsd"] + TOLERANCE,
        "rates_from_frozen_manifest": rates, "meaning": "Upper bounds under the frozen peak-rate schedule, not bank settlement or a final campaign total."}
    receipt_by_key = {(r["requestFile"], r["requestSha256"]): r for r in calls}
    task_reports = []
    injection_keys = Counter()
    for record in summary["records"]:
        index = record["index"]
        report = {"index": index, "official_id": record["officialId"], "arm": record["arm"], "replica": record["replica"], "generation_valid": record["generationValid"],
            "generation_outcome": record["generationClassification"]["outcome"], "acceptance_outcome": record["acceptance"]["outcome"], "errors": [], "runtime_log_error_events": []}
        try:
            artifact, file_meta = snapshot(directory / f"task-{index}.json")
            report["artifact"] = file_meta
            report["candidate_digest_matches"] = sha(artifact["answer"].encode()) == artifact["candidateSha256"] == record["candidateSha256"]
            report["trace_digest_matches"] = sha(js_json(artifact["trace"])) == artifact["traceSha256"] == record["traceSha256"]
            report["prompt_digest_matches_preselected_public_task"] = artifact["promptSha256"] == public[artifact["officialId"]]["promptSha256"]
            immutable_keys = ["index", "benchmark", "arm", "replica", "officialId", "taskId", "state", "runtimeVerdict", "generationValid", "generationClassification", "answer", "candidateHow", "candidateSha256", "promptSha256", "traceSha256", "apiCalls", "actualCreatedAt", "deadline"]
            report["summary_immutable_fields_match_task_artifact"] = all(record.get(k) == artifact.get(k) for k in immutable_keys)
            report["task_receipt_copies_match_ledger"] = all(receipt_by_key.get((c["requestFile"], c["requestSha256"])) == c for c in artifact["apiCalls"])
            report["all_task_receipts_finished"] = all(bool(c.get("finishedAt")) for c in artifact["apiCalls"])
            expected_index = list(public).index(record["officialId"]) * 7 + ({"U": 0, "R": 1, "F": 6}[record["arm"]] + (record["replica"] if record["arm"] == "R" else 0))
            report["index_matches_frozen_gpqa_urf_plan"] = expected_index == index
            for key in ["candidate_digest_matches", "trace_digest_matches", "prompt_digest_matches_preselected_public_task", "summary_immutable_fields_match_task_artifact", "task_receipt_copies_match_ledger", "all_task_receipts_finished", "index_matches_frozen_gpqa_urf_plan"]:
                if not report[key]:
                    report["errors"].append(key)
            for trace_row in artifact["trace"]:
                if trace_row.get("role") == "system" and trace_row.get("kind") == "inject":
                    try:
                        payload = json.loads(trace_row["body"])
                    except Exception:
                        continue
                    if isinstance(payload, dict):
                        injection_keys.update(payload.keys())
                        for error_key in ["stuck", "provider_error", "grader_error", "capture_error"]:
                            if error_key in payload:
                                report["runtime_log_error_events"].append({"instance": trace_row.get("instance"), "unit": trace_row.get("unit"), "at": trace_row.get("at"), "kind": error_key})
        except Exception as error:
            report["errors"].append(type(error).__name__)
        task_reports.append(report)
    ending_ledger, ending_ledger_meta = snapshot(directory / "api-ledger.json")
    ending_summary, ending_summary_meta = snapshot(directory / "summary.json")
    errors = [r for r in receipt_reports if r["errors"]]
    task_errors = [r for r in task_reports if r["errors"] or r["runtime_log_error_events"]]
    static_changes = []
    for name in ["manifest.json", "source.json", "frozen-source.json", "gpqa-public-tasks.json"]:
        if sha((directory / name).read_bytes()) != inputs[name]["sha256"]:
            static_changes.append(name)
    captured_paths = {int(re.search(r"provider-(\d+)-", p.name).group(1)): p for p in store.glob("provider-*-request.json.gz")}
    ending_indices = set(range(len(ending_ledger["calls"])))
    # The original writer captures gzip BEFORE appending its receipt. A capture
    # appearing after our end snapshot is an active write window, not an orphan.
    unindexed = [{"sequence": seq, "mtime_ns": path.stat().st_mtime_ns,
        "classification": "new_or_active_capture_window" if path.stat().st_mtime_ns >= ending_ledger_meta["mtime_ns"] - 5_000_000_000 else "older_unindexed_capture_needs_investigation"}
        for seq, path in sorted(captured_paths.items()) if seq not in ending_indices]
    unindexed_captures = [r["sequence"] for r in unindexed if r["classification"] == "older_unindexed_capture_needs_investigation"]
    independent_logs = sorted(p for p in store.rglob("*.log") if p.is_file())
    log_hits = []
    for path in independent_logs:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        hits = [{"line": i + 1, "matched_patterns": [pattern for pattern in ["ENOSPC", "EACCES", "EIO", "EMFILE", "capture_error", "local_evidence_error", "unhandled"] if pattern.lower() in text.lower()]} for i, text in enumerate(lines)]
        hits = [h for h in hits if h["matched_patterns"]]
        log_hits.append({"path": str(path), "sha256": sha(path.read_bytes()), "error_pattern_hits": hits})
    io_findings = {"request_capture_and_initial_ledger_outside_try": {
            "executed_source": "scripts/benchmark-repair/campaign.ts", "source_lines": [77, 81, 84, 85],
            "risk": "Pre-provider request/initial-ledger I/O failure can bypass reservation/pending cleanup.",
            "observed_orphan_request_files_at_end_snapshot": unindexed_captures,
            "unindexed_capture_observation_windows": unindexed,
            "reservation_and_pending_closure": cost_ledger["reserved_cost_closed"] and cost_ledger["pending_routes_match_unfinished_receipts"],
            "finished_receipt_request_capture_failures": [r["sequence"] for r in receipt_reports if r.get("request", {}).get("receipt_digest_matches") is not True]},
        "unguarded_final_ledger_write": {"executed_source": "scripts/benchmark-repair/campaign.ts", "source_lines": [114, 117],
            "risk": "Final ledger write can throw after provider response and completion, leaving evidence/SDK delivery uncertain.",
            "finished_receipt_response_capture_failures": [r["sequence"] for r in receipt_reports if r.get("response", {}).get("receipt_digest_matches") is not True],
            "recorded_cost_closure": cost_ledger["recorded_cost_closed"], "finished_receipt_faults": sum(bool(r.get("fault")) for _, r in finished)},
        "evidence_based_conclusion": "No observable I/O-boundary failure in audited finished receipts" if not errors and not task_errors and not unindexed_captures and cost_ledger["recorded_cost_closed"] and cost_ledger["reserved_cost_closed"] and cost_ledger["pending_routes_match_unfinished_receipts"] else "Inspect listed concrete evidence failures; no blanket invalidation based on code risk",
        "limits": "Does not prove no transient filesystem exception occurred outside persisted logs. Newly growing/in-flight data must be audited after closure; original campaign lacks providerAttempted/captureErrors markers."}
    end = datetime.now(timezone.utc)
    complete_observed = ending_summary.get("completed") is True and not any(not c.get("finishedAt") for c in ending_ledger["calls"])
    report = {"audit_started_at_utc": start.isoformat(), "audit_finished_at_utc": end.isoformat(), "campaign": run,
        "scope": "Independent read-only evidence audit; no model/grader call, no candidate selection, no campaign/task mutation and no score calculation.",
        "audit_script_sha256": sha(Path(__file__).read_bytes()), "observation_inputs": inputs,
        "running_observation": {"completed_at_initial_snapshot": summary.get("completed"), "completed_at_end_snapshot": ending_summary.get("completed"),
            "planned_task_runs": summary["plannedTaskRuns"], "task_records_at_initial_snapshot": len(summary["records"]), "task_records_at_end_snapshot": len(ending_summary["records"]),
            "api_calls_at_initial_snapshot": len(calls), "finished_receipts_audited": len(finished), "unfinished_receipts_at_initial_snapshot": len(unfinished),
            "api_calls_at_end_snapshot": len(ending_ledger["calls"]), "summary_changed_during_audit": inputs["summary.json"]["sha256"] != ending_summary_meta["sha256"],
            "ledger_changed_during_audit": inputs["api-ledger.json"]["sha256"] != ending_ledger_meta["sha256"],
            "initial_summary_generated_at": summary.get("generatedAt"), "end_summary_generated_at": ending_summary.get("generatedAt"),
            "status": "closed_observed" if complete_observed else "RUNNING; pending acceptance and in-flight receipts are not missing/invalid"},
        "source_integrity": source_results, "static_observation_files_changed_during_audit": static_changes,
        "receipt_checks": receipt_reports, "finished_receipt_errors": errors, "unfinished_receipt_observations": inflight_reports,
        "wire_parameter_profiles": [{"parameters": json.loads(k), "finished_receipts": v} for k, v in parameters.items()],
        "wire_tool_names_by_arm": {k: sorted(v) for k, v in tool_sets.items()}, "reported_usage_totals_for_audited_finished_receipts": dict(usage_totals),
        "provider_token_limit_and_usage_consistency": {"finished_receipts": len(finished),
            "maximum_reported_completion_tokens": max((r.get("raw_usage", {}).get("completion_tokens", 0) for r in receipt_reports), default=None),
            "completion_usage_over_actual_wire_limit": [r["sequence"] for r in receipt_reports if r.get("completion_usage_within_actual_wire_limit") is False],
            "usage_total_inconsistent": [r["sequence"] for r in receipt_reports if r.get("usage_total_tokens_consistent") is False],
            "cache_hit_fields_inconsistent": [r["sequence"] for r in receipt_reports if r.get("both_cache_counts_consistent") is False],
            "cache_miss_inconsistent": [r["sequence"] for r in receipt_reports if r.get("cache_miss_count_consistent") is False],
            "uninterpretable_usage_or_limit": [r["sequence"] for r in receipt_reports if "completion_usage_within_actual_wire_limit" not in r],
            "rule": "No missing/invalid usage is replaced by zero. Captured wire settings, servedModel and matching hashes do not prove provider parameter enforcement or checkpoint identity."},
        "provider_system_fingerprints": dict(fingerprint_counts), "provider_finish_reasons": dict(finish_reason_counts),
        "cost_ledger_closure": cost_ledger, "task_checks": task_reports, "task_evidence_errors": task_errors,
        "trace_system_injection_key_counts": dict(injection_keys), "independent_log_file_checks": log_hits,
        "log_scope_limit": "Only stored run logs and exported structured system-injection/runtime records are inspected. Main runner terminal output is not a log file in this run directory.",
        "io_boundary_evidence": io_findings,
        "closing_rerun_command": f"& '.phase1-data/venv/Scripts/python.exe' -B -X utf8 'scripts/benchmark-repair/full-gpqa-inflight-audit.py' --run {run} --require-complete",
        "require_complete_requested": require_complete, "complete_observed": complete_observed,
        "limits": ["No full or interim GPQA score is produced. Acceptance remains pending until the campaign's post-generation scoring step.",
            "Costs are frozen-rate upper bounds from provider usage, not actual payment settlement.", "Identical declared wire parameters do not certify provider determinism or a fixed model checkpoint.",
            "The audit only certifies receipts finished at its initial ledger snapshot; later receipts need a new audit."]}
    output_json = OUT / "full-gpqa-inflight-audit.json"
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source_bad = len(source_results["executed_source_mismatches"]) + len(source_results["archive"]["member_manifest_mismatches"]) + len(source_results["archive"]["current_member_mismatches"])
    markdown = f'''# GPQA 全量运行只读审计

观察开始：{start.isoformat()}；结束：{end.isoformat()}。run：`{run}`。本次只读原件，独立保存报告，未调用 LLM 或评分服务，没有计算 GPQA 成绩。

| 核对项 | 当前观察 |
|---|---|
| 运行状态 | {report["running_observation"]["status"]} |
| 任务记录 | 初始 {len(summary["records"])}，结束 {len(ending_summary["records"])}，计划 {summary["plannedTaskRuns"]} |
| API 回执 | 初始 {len(calls)}；全部已 finished 的 {len(finished)} 条逐一核对；{len(unfinished)} 条仍在途 |
| 完成回执异常 | {len(errors)} 条；已核对 gzip CRC、解压 SHA、实际请求参数、响应字段与 usage、逐条费用 |
| 任务原件异常 | {len(task_errors)} 条；核对 candidate/trace/prompt 摘要、API回执副本和预先固定任务顺序 |
| 供应商 token 上限 | completion 超实际wire上限 {len(report["provider_token_limit_and_usage_consistency"]["completion_usage_over_actual_wire_limit"])} 条；最大报告值 {report["provider_token_limit_and_usage_consistency"]["maximum_reported_completion_tokens"]} |
| usage 分解 | total/cache hit/cache miss 不一致分别 {len(report["provider_token_limit_and_usage_consistency"]["usage_total_inconsistent"])} / {len(report["provider_token_limit_and_usage_consistency"]["cache_hit_fields_inconsistent"])} / {len(report["provider_token_limit_and_usage_consistency"]["cache_miss_inconsistent"])} 条；不可解释 {len(report["provider_token_limit_and_usage_consistency"]["uninterpretable_usage_or_limit"])} 条 |
| 冻结源码 | 检查 {source_results["source_files_checked"]} 条源文件；执行源码/归档成员不一致共 {source_bad} 条 |
| 费用闭合 | 已记账闭合：{cost_ledger["recorded_cost_closed"]}；在途预留闭合：{cost_ledger["reserved_cost_closed"]}；pending计数闭合：{cost_ledger["pending_routes_match_unfinished_receipts"]} |

本次初始账本的 recorded usage upper bound 为 ${ledger["recordedUsageUpperBoundUsd"]:.9f}；已核对回执总和为 ${spent_sum:.9f}；在途预留为 ${ledger["reservedUpperBoundUsd"]:.9f}。这些是冻结费率下的费用上界，不是已支付金额或最终全量费用。实际 wire 参数分布、原始 usage、压缩及解压摘要全部保存在 [JSON报告](full-gpqa-inflight-audit.json)，不输出模型答案、推理正文或凭证。

`finish_reason=length` 为 {finish_reason_counts.get("length", 0)} 条，保留截断事实。未解释的usage不补零；hash和账目闭合只证明捕获/计算一致，不自动证明服务器遵守参数。servedModel与system fingerprint均不认证固定模型checkpoint。

两个已知 I/O 边界分别是请求捕获/初始账本位于 try/finally 之外，以及 finally 中的账本写入无保护。本次证据结论：**{io_findings["evidence_based_conclusion"]}**。该结论只涉及已持久化的完成回执与本次闭合检查；不能据源码存在风险笼统废弃轨迹，也不能保证尚未 finished 的请求将来不会出错。

summary 与 ledger 在审计期间是否变化：{report["running_observation"]["summary_changed_during_audit"]} / {report["running_observation"]["ledger_changed_during_audit"]}。在途 response、尚未创建的后续 task 文件和 `pending_after_all_generation` acceptance 都保持运行中状态。源码快照中未执行的其他 benchmark 文件若有变化，JSON会与实际归档执行文件分开列出。

本目录可用独立日志文件：{len(independent_logs)}；另检查所有已记录 task trace 的结构化 system injection 与 runtime/generation 状态。主runner终端输出不在此目录，未声称已审阅其完整终端日志。

结束后在项目目录复跑只读命令：

```powershell
{report["closing_rerun_command"]}
```

该命令仍只改本审计自己的 JSON/Markdown。`--require-complete` 会在观察到 campaign 未完成或仍有在途回执时退出非零，不触发新调用或修改 campaign。
'''
    (OUT / "full-gpqa-inflight-audit.md").write_text(markdown, encoding="utf-8")
    print(json.dumps({"observed_at_utc": end.isoformat(), "finished_receipts_audited": len(finished), "unfinished_receipts_observed": len(unfinished),
        "finished_receipt_errors": len(errors), "task_records_audited": len(task_reports), "task_evidence_errors": len(task_errors),
        "executed_or_archived_source_mismatches": source_bad, "recorded_cost_closed": cost_ledger["recorded_cost_closed"],
        "reserved_cost_closed": cost_ledger["reserved_cost_closed"], "pending_closed": cost_ledger["pending_routes_match_unfinished_receipts"],
        "io_conclusion": io_findings["evidence_based_conclusion"], "completed": complete_observed}, ensure_ascii=False))
    if require_complete and not complete_observed:
        raise SystemExit(2)
    if errors or task_errors or source_bad or static_changes or not cost_ledger["recorded_cost_closed"] or not cost_ledger["reserved_cost_closed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default=DEFAULT_RUN)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    main(args.run, args.require_complete)
