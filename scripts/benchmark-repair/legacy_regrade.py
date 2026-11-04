"""Read-only candidate recovery and separately labelled offline legacy regrading.

prepare recovers fixed final submissions, every budget-blocked submission candidate,
and non-submission wrap-up text only as a diagnostic. worker runs inside an existing,
network-disabled scorer container. Neither command mutates legacy runs or selects a
passing candidate. Reference answers are never printed or saved in the reports.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import tomllib
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/repair-2026-10-08"
EVIDENCE = ROOT.parent / "notes/audit-2026-10-08/legacy-data-evidence.json"
GROUP_SLUGS = {"ChemIQ": "chemiq", "ChemBench": "chembench", "CMT": "cmt", "miniF2F": "minif2f", "GPQA": "gpqa"}


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def file_record(path):
    return {"path": str(Path(path).resolve()), "bytes": Path(path).stat().st_size, "sha256": file_digest(path)}


def read_connection(path):
    wal = path.with_name(path.name + "-wal")
    params = "?mode=ro" if wal.exists() and wal.stat().st_size else "?mode=ro&immutable=1"
    conn = sqlite3.connect(path.resolve().as_uri() + params, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma query_only = on")
    return conn


def snapshot_paths(home):
    return [p for p in home.iterdir() if p.is_file() and (p.name.endswith((".sqlite", ".sqlite-wal", ".csv")))]


def get_messages(conn, tid):
    instances = [r[0] for r in conn.execute("select distinct instance from task_solve where task=? order by instance", (tid,))]
    output = []
    for inst in instances:
        for row in conn.execute("select instance,unit,seq,kind,body,at,role from agent_bot_msg where instance=? and kind in ('call','prompt','tool') order by unit,seq", (inst,)):
            data = json.loads(row["body"]) if row["kind"] in {"call", "tool"} else None
            output.append(dict(row) | {"decoded": data})
    return instances, output


def candidate_receipts(messages):
    asks, records = {}, defaultdict(list)
    for row in messages:
        if row["kind"] == "call":
            for call in row["decoded"].get("calls", []):
                inp = call.get("input")
                answer = inp.get("answer") if isinstance(inp, dict) else None
                if call.get("name") == "verify" and isinstance(answer, str) and call.get("id"):
                    asks[(row["instance"], call["id"])] = digest(answer)
        elif row["kind"] == "tool" and row["decoded"].get("name") == "verify":
            data = row["decoded"]
            sha = asks.get((row["instance"], data.get("id")))
            if sha is None:
                continue
            receipt = data.get("value")
            receipt = receipt if isinstance(receipt, dict) else {}
            numeric = type(receipt.get("pass")) is int and receipt["pass"] in {0, 1}
            records[sha].append({"call_id": data.get("id"), "instance": row["instance"], "unit": row["unit"], "seq": row["seq"], "at": row["at"],
                "numeric_pass_present": numeric, "pass": receipt.get("pass") if numeric else None, "valid": receipt.get("valid"), "outcome": receipt.get("outcome"),
                "measurement_unavailable": not numeric or receipt.get("valid") is False or receipt.get("outcome") == "grader_error"})
    return records


def recover_run(slug, name, risk_rows):
    home = ROOT / "runs" / name
    tracked = snapshot_paths(home)
    before = {str(p): file_digest(p) for p in tracked}
    conn = read_connection(home / "h2h.sqlite")
    risk_by_task = defaultdict(list)
    for row in risk_rows:
        risk_by_task[row["task"]].append(row)
    selected_tasks = None if name.startswith("chembench-f-") else set(risk_by_task)
    tasks = [dict(r) for r in conn.execute("select id,description,state,result,created_at,solve_seconds from task order by id") if selected_tasks is None or r["id"] in selected_tasks]
    records, diagnostics = [], []
    for task in tasks:
        tid = task["id"]
        instances, messages = get_messages(conn, tid)
        receipts = candidate_receipts(messages)
        stored = json.loads(task["result"]) if task["result"] else None
        base = {"benchmark": slug, "run": name, "task": tid, "state": task["state"], "created_at": task["created_at"],
                "solve_seconds": task["solve_seconds"], "declared_deadline_at": task["created_at"] + 1000 * task["solve_seconds"],
                "description": task["description"], "description_sha256": digest(task["description"]),
                "stored_verdict": stored, "stored_pass": stored.get("pass") if isinstance(stored, dict) else None,
                "stored_validity_present": isinstance(stored, dict) and "valid" in stored,
                "budget_risk_task": tid in risk_by_task, "instances": instances}
        submits = []
        for row in messages:
            if row["kind"] != "call":
                continue
            for i, call in enumerate(row["decoded"].get("calls", [])):
                if call.get("name") != "submit":
                    continue
                inp = call.get("input")
                value = inp.get("answer") if isinstance(inp, dict) else None
                answer = value if isinstance(value, str) else ""
                submits.append({"candidate": answer, "candidate_sha256": digest(answer), "candidate_bytes": len(answer.encode()),
                                "call_id": call.get("id"), "instance": row["instance"], "unit": row["unit"], "seq": row["seq"],
                                "call_index": i, "at": row["at"], "argument_was_string": isinstance(value, str)})
        # A multi-instance legacy run cannot safely select a final submission from
        # unrelated numeric unit sequences. Current audited runs have one instance.
        if len(instances) > 1:
            records.append(base | {"purpose": "final_submission", "candidate": None, "candidate_selection_error": "multiple_instances_without_verified_terminal_identity"})
        elif submits:
            records.append(base | submits[-1] | {"purpose": "final_submission", "selection_rule": "last submit call by unit, seq, and call index within the sole stored task instance; independent of grades"})
        else:
            records.append(base | {"purpose": "final_submission", "candidate": None, "candidate_selection_error": "no_submit_call"})
            spoken = [r for r in messages if r["kind"] in {"prompt", "call"} and r["role"] == "assistant"]
            if spoken:
                row = spoken[-1]
                answer = row["body"] if row["kind"] == "prompt" else row["decoded"].get("text", "")
                if isinstance(answer, str):
                    diagnostics.append(base | {"purpose": "non_submission_wrapup_diagnostic", "candidate": answer,
                        "candidate_sha256": digest(answer), "candidate_bytes": len(answer.encode()),
                        "instance": row["instance"], "unit": row["unit"], "seq": row["seq"], "at": row["at"],
                        "selection_rule": "last assistant prompt or call.text only; this is not a submit and never counts as a formal final submission"})
        seen = set()
        by_call = {s["call_id"]: s for s in submits}
        for row in risk_by_task.get(tid, []):
            candidate = by_call.get(row["submit_call_id"])
            if candidate is None or candidate["candidate_sha256"] != row["answer_sha256"]:
                diagnostics.append(base | {"purpose": "budget_blocked_submission_diagnostic", "candidate": None,
                    "candidate_selection_error": "audit_submit_call_or_hash_not_found", "audit_risk": row})
                continue
            if candidate["candidate_sha256"] in seen:
                continue
            seen.add(candidate["candidate_sha256"])
            matching = [x for x in risk_by_task[tid] if x["answer_sha256"] == candidate["candidate_sha256"]]
            diagnostics.append(base | candidate | {"purpose": "budget_blocked_submission_diagnostic", "audit_risk_occurrences": matching,
                "selection_rule": "all distinct exact text candidates named by the previous audit, without any outcome selection"})
        for row in records + diagnostics:
            if row["task"] == tid:
                row["same_text_historical_verify_receipts"] = receipts.get(row.get("candidate_sha256"), [])
                row["original_final_grading_candidate_digest_available"] = False
                row["candidate_at_or_before_declared_deadline"] = row["at"] <= row["declared_deadline_at"] if row.get("at") is not None else None
                row["explicit_submission_deadline_eligible"] = row.get("candidate") is not None and row["purpose"] != "non_submission_wrapup_diagnostic" and row["candidate_at_or_before_declared_deadline"] is True
    conn.close()
    after = {str(p): file_digest(p) for p in tracked}
    if before != after:
        raise RuntimeError("Legacy source changed during read-only extraction")
    return {"run": name, "benchmark": slug, "source_files": [file_record(p) for p in tracked], "source_unchanged": True,
            "final_records": records, "diagnostic_records": diagnostics}


def literal_skip(file):
    import ast
    tree = ast.parse(file.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == "SKIP" for t in targets):
            return ast.literal_eval(node.value)
    return {}


def software_identity():
    dswhome = ROOT / ".phase1-data/deepswe"
    files = sorted((dswhome / "vendor/deep-swe/tasks").glob("*/task.toml"))
    now_ids = {p.parent.name for p in files}
    exported = ROOT / ".local-evidence/repository/examples/benchmark/dsw-full-export/csv/tasks.csv"
    rows = list(csv.DictReader(exported.open(encoding="utf-8-sig", newline="")))
    old_ids = {r["task"] for r in rows}
    dswstand = ROOT / ".local-evidence/repository/examples/benchmark/dsw-full-export/example/stand.py"
    skip = literal_skip(dswstand)
    export_result = ROOT / ".local-evidence/repository/examples/benchmark/dsw-full-export/RESULT.md"
    skbhome = ROOT / ".phase1-data/skillsbench"
    skb_current = {p.parent.name for p in (skbhome / "vendor/skillsbench/tasks").glob("*/task.md")}
    skbrun = ROOT / "runs/skb-f-c5kinf-0929/h2h.sqlite"
    conn = read_connection(skbrun)
    skb_old = {r[0].rsplit("/", 1)[-1] for r in conn.execute("select id from task")}
    conn.close()
    skbstand = ROOT / "examples/benchmark/skillsbench/stand.py"
    skbskip = literal_skip(skbstand)
    return {
        "deepswe": {"pinned_source": json.loads((dswhome / "source.json").read_text(encoding="utf-8")),
            "current_task_count": len(now_ids), "export_task_count": len(rows), "export_stored_pass": sum(r["pass"] == "1" for r in rows),
            "export_rows_duplicate_ids": len(rows) != len(old_ids), "current_minus_export": sorted(now_ids - old_ids),
            "export_minus_current": sorted(old_ids - now_ids), "export_adapter_skip_reasons": skip,
            "export_csv": file_record(exported), "export_result": file_record(export_result), "export_adapter": file_record(dswstand),
            "export_task_manifest": [{"task": r["task"], "id": r["id"], "state": r["state"], "stored_pass": r["pass"], "place": r["place"], "created_at": r["created_at"]} for r in rows],
            "source_heterogeneity": {"documented_before_fix_tasks": 53, "documented_after_fix_tasks": 59,
                "evidence": "RESULT.md section 中途改了两处，所以这112道不是一个批次", "task_partition_individually_verified": False},
            "interpretation": "112 exported task IDs and 91 stored passes are auditable. ID equality does not establish unchanged v1/v1.1 definitions. 53/59 source partitions are documented but exact task-to-commit identity is not recoverable from this export alone. No grading, new denominator, or repaired experiment score."},
        "skillsbench": {"pinned_source": json.loads((skbhome / "source.json").read_text(encoding="utf-8")),
            "current_task_count": len(skb_current), "historical_task_count": len(skb_old),
            "current_minus_run": sorted(skb_current - skb_old), "run_minus_current": sorted(skb_old - skb_current),
            "adapter_skip_reasons": skbskip, "adapter": file_record(skbstand), "historical_database": file_record(skbrun),
            "85_1_percent_provenance": {"origin": "legacy Agent-OS multi-configuration envelope according to open-items.tex", "87_denominator": "reverse-inferred from 74/87; not verified by a matching score run", "74_success_ids": None},
            "interpretation": "The 76 IDs are compared to the pinned 87-task source. Missing IDs are kept explicitly. Nine oracle self-check failures plus two absent Apptainer definitions are distinct causes; no new oracle recheck or 85.1% certification was performed."}}


def prepare():
    audit = json.loads(EVIDENCE.read_text(encoding="utf-8-sig"))
    runs = []
    for group, records in audit["groups"].items():
        if group not in GROUP_SLUGS:
            continue
        for record in records:
            risks = record.get("blocked_candidate_submissions", [])
            if risks or record["run"].startswith("chembench-f-"):
                runs.append(recover_run(GROUP_SLUGS[group], record["run"], risks))
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "evidence": file_record(EVIDENCE),
        "protocol": "Read-only recovery; fixed last submit per sole instance; all distinct audit-listed risk candidates kept separately. No model calls or result-based candidate selection; non-submit text is diagnostic only.", "runs": runs}
    candidate_path = OUT / "legacy-candidates.json"
    candidate_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    identity = software_identity()
    (OUT / "legacy-software-identity.json").write_text(json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_manifest": str(candidate_path), "runs": len(runs),
        "final_records": sum(len(r["final_records"]) for r in runs), "diagnostic_records": sum(len(r["diagnostic_records"]) for r in runs),
        "deepswe_current_minus_export": identity["deepswe"]["current_minus_export"],
        "skillsbench_missing_count": len(identity["skillsbench"]["current_minus_run"])}))


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def module_from(file):
    spec = importlib.util.spec_from_file_location("legacy_scorer_adapter", file)
    mod = importlib.util.module_from_spec(spec)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


def match_task(slug, mod, row):
    tail = row["task"].rsplit("/", 1)[-1]
    description = norm(row["description"])
    if slug == "chembench":
        key = tail.removeprefix("chb-")
        item = mod.BOOK.get(key)
        if item is None:
            return None, {"matched": False, "error": "uuid_absent_from_pinned_dataset"}
        prompt, score_map = mod.prompt_of(item)
        matched = norm(prompt) in description
        return item, {"matched": matched, "official_id": key, "prompt_and_option_order_sha256": digest(norm(prompt)),
            "scoring_input_sha256": digest(json.dumps(item, ensure_ascii=False, sort_keys=True)), "match_rule": "same uuid; complete official rendered prompt including the option order is contained verbatim after whitespace normalization", "error": None if matched else "rendered_prompt_or_option_order_mismatch"}
    if slug == "gpqa":
        key = int(tail.removeprefix("gpqa-"))
        item = mod.BOOK.get(key)
        if item is None:
            return None, {"matched": False, "error": "index_absent_from_pinned_dataset"}
        prompt = item["question"] + "\n\n" + "\n".join(k + ". " + v for k, v in item["choices"].items())
        matched = norm(prompt) in description
        return item, {"matched": matched, "official_id": item["record_id"], "official_index": key, "seed": mod.SEED,
            "prompt_and_option_order_sha256": digest(norm(prompt)), "match_rule": "same dataset index and Record ID; complete question and all four explicitly labelled options match in seed=0 order after whitespace normalization", "error": None if matched else "question_or_option_order_mismatch"}
    if slug == "chemiq":
        key = tail.removeprefix("chemiq-")
        item = mod.BOOK.get(key)
        if item is None:
            return None, {"matched": False, "error": "uuid_absent_from_pinned_dataset"}
        prompt = norm(item["prompt"])
        fmt = str(item["answer_format"])
        # The original official prompt itself prescribes the format ("integer",
        # "IUPAC name", "list of tuples" etc.). Legacy send.ts did not add a
        # separate labelled Answer format line, so require this exact full prompt.
        format_in_prompt = fmt.replace("_", " ").lower() in prompt.lower()
        matched = prompt in description and format_in_prompt
        return item, {"matched": matched, "official_id": key, "prompt_sha256": digest(prompt), "answer_format": fmt,
            "verification_method": item["verification_method"], "scoring_input_sha256": digest(json.dumps(item, ensure_ascii=False, sort_keys=True)),
            "match_rule": "same uuid; complete official prompt, including its explicit answer-format instruction, matches after whitespace normalization", "error": None if matched else "prompt_or_answer_format_mismatch"}
    if slug == "cmt":
        key = int(tail.removeprefix("cmt-"))
        item = mod.BOOK.get(key)
        if item is None:
            return None, {"matched": False, "error": "index_absent_from_pinned_dataset"}
        prompt = norm(item["prompt"])
        parameters = item.get("parameters", "") or ""
        functions = item.get("functions", "") or ""
        # Legacy send.ts emits a labelled parameter/function line only when nonempty.
        matched = prompt in description and (not parameters or norm("Symbols: " + parameters) in description) and (not functions or norm("Functions: " + functions) in description)
        return item, {"matched": matched, "official_id": key, "prompt_sha256": digest(prompt), "parameters_sha256": digest(parameters),
            "functions_sha256": digest(functions), "scoring_input_sha256": digest(json.dumps(item, ensure_ascii=False, sort_keys=True)),
            "match_rule": "same official index; exact prompt plus nonempty parameters/functions fields appear verbatim after whitespace normalization", "error": None if matched else "prompt_or_parameters_or_functions_mismatch"}
    raise ValueError("Unimplemented benchmark")


def grade(slug, mod, item, row, allow_opsin_network=False):
    said = row.get("candidate")
    if said is None:
        return {"attempted": False, "valid": False, "passed": None, "outcome": "no_candidate", "error": row.get("candidate_selection_error", "candidate_absent")}
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            if slug == "chembench":
                got = mod.judge(said, item)
                return {"attempted": True, "valid": True, "parsed": got["parsed"], "passed": got["parsed"] and got["correct"], "outcome": "passed" if got["parsed"] and got["correct"] else "rejected"}
            if slug == "gpqa":
                parsed, passed, _ = mod.judge(said, item)
                return {"attempted": True, "valid": True, "parsed": parsed, "passed": parsed and passed, "outcome": "passed" if parsed and passed else "rejected"}
            if slug == "cmt":
                parsed, passed, _ = mod.judge(said, item)
                return {"attempted": True, "valid": True, "parsed": parsed, "passed": parsed and passed, "outcome": "passed" if parsed and passed else "rejected"}
            if slug == "chemiq":
                key = row["task"].rsplit("/", 1)[-1].removeprefix("chemiq-")
                parsed = mod.PARSER.parse(key, said)
                cache_hit = bool(mod.VERIFIER._opsin_cache.get(str(parsed)))
                if item["verification_method"] == "opsin" and parsed is not False and parsed and "\n" not in str(parsed) and len(str(parsed)) <= 200 and not cache_hit and not allow_opsin_network:
                    return {"attempted": False, "valid": False, "passed": None, "outcome": "external_service_unavailable", "error": "OPSIN candidate absent from positive pinned cache; network disabled by protocol"}
                if item["verification_method"] == "opsin" and allow_opsin_network:
                    got = mod.judge(key, said)
                    if got.get("error"):
                        return {"attempted": True, "valid": False, "passed": None, "outcome": "external_service_unavailable", "error": got["error"], "opsin_source": "positive process cache" if cache_hit else "official REST request"}
                    return {"attempted": True, "valid": True, "parsed": got["parsed"], "passed": got["parsed"] and got["correct"], "outcome": "passed" if got["parsed"] and got["correct"] else "rejected", "opsin_source": "positive process cache" if cache_hit else "official REST request"}
                got = mod.VERIFIER.check_answer(key, parsed)
                return {"attempted": True, "valid": True, "parsed": parsed is not False, "passed": bool(got.get("is_correct")), "outcome": "passed" if got.get("is_correct") else "rejected", "opsin_source": "positive pinned cache" if item["verification_method"] == "opsin" else None}
        except Exception as error:
            return {"attempted": True, "valid": False, "passed": None, "outcome": "grader_error", "error": type(error).__name__}


def worker(slug, allow_opsin_network=False):
    payload = json.load(sys.stdin)
    env = {"gpqa": "TGENGIN_GPQA_HOME", "cmt": "TGENGIN_CMT_HOME", "chembench": "TGENGIN_CHB_HOME", "chemiq": "TGENGIN_CHEMIQ_HOME"}
    os.environ[env[slug]] = "/oracle"
    os.environ["TGENGIN_GPQA_SEED"] = "0"
    file = "/adapter/grader.py" if slug == "cmt" else "/adapter/stand.py"
    mod = module_from(file)
    request_log = []
    if slug == "chemiq" and allow_opsin_network:
        original_get = mod.requests.get
        def traced_get(*args, **kwargs):
            url = str(args[0] if args else kwargs.get("url", ""))
            started = time.monotonic()
            record = {"request_host": urllib.parse.urlsplit(url).hostname, "request_url_sha256": digest(url)}
            try:
                response = original_get(*args, **kwargs)
                record.update({"http_status": response.status_code, "final_host": urllib.parse.urlsplit(response.url).hostname,
                    "redirect_statuses": [r.status_code for r in response.history], "response_body_sha256": hashlib.sha256(response.content).hexdigest()})
                return response
            except Exception as error:
                record["error"] = type(error).__name__
                raise
            finally:
                record["elapsed_seconds"] = round(time.monotonic() - started, 4)
                request_log.append(record)
        mod.requests.get = traced_get
    refs = [Path("/oracle/source.json"), Path(file)]
    refs += sorted(Path("/oracle/vendor").rglob("*.py"))
    refs += sorted(Path("/oracle").glob("*.jsonl"))
    refs += [p for p in Path("/oracle/vendor").rglob("*.jsonl") if p.name == "chemiq.jsonl"]
    refs += [p for p in Path("/oracle/dataset").glob("*.csv") if p.name == "gpqa_diamond.csv"]
    if slug == "chemiq":
        refs += [Path("/oracle/vendor/ChemIQ/utils/opsin_cache.json")]
    sources = [{"path": str(p), "sha256": file_digest(p)} for p in refs if p.exists()]
    records = []
    for row in payload["records"]:
        summary = {k: v for k, v in row.items() if k not in {"description", "candidate", "stored_verdict"}}
        try:
            item, match = match_task(slug, mod, row)
        except Exception as error:
            item, match = None, {"matched": False, "error": type(error).__name__}
        before_requests = len(request_log)
        result = grade(slug, mod, item, row, allow_opsin_network) if match["matched"] else {"attempted": False, "valid": False, "passed": None, "outcome": "identity_mismatch", "error": match.get("error")}
        if allow_opsin_network:
            result["opsin_requests"] = request_log[before_requests:]
        records.append(summary | {"identity": match, "regrade": result})
    report = {"benchmark": slug, "created_at_utc": datetime.now(timezone.utc).isoformat(), "candidate_manifest_sha256": payload["candidate_manifest_sha256"],
        "sources": sources, "scope": "offline post-hoc diagnostics; current official scorer applied only after exact task-content identity match; no model call, outcome selection, or new formal F experiment",
        "scorer_variant": "deterministic ChemBench regex branch; no LLM fallback/refusal model" if slug == "chembench" else "current official local scorer adapter",
        "network": "bridge for official OPSIN REST only" if allow_opsin_network else "none", "records": records}
    print(json.dumps(report, ensure_ascii=False))


def summarise():
    manifest_path = OUT / "legacy-candidates.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    workers = [json.loads((OUT / f"legacy-regrade-{slug}.json").read_text(encoding="utf-8")) for slug in ["chembench", "chemiq", "cmt", "gpqa"]]
    if any(r["candidate_manifest_sha256"] != file_digest(manifest_path) for r in workers):
        raise RuntimeError("Regrade report candidate-manifest digest is stale")
    records = [row for report in workers for row in report["records"]]
    counts = []
    keys = sorted({(r["benchmark"], r["run"], r["purpose"]) for r in records})
    for benchmark, run, purpose in keys:
        subset = [r for r in records if (r["benchmark"], r["run"], r["purpose"]) == (benchmark, run, purpose)]
        counts.append({"benchmark": benchmark, "run": run, "purpose": purpose, "records": len(subset),
            "identity_matched": sum(r["identity"]["matched"] for r in subset), "attempted": sum(r["regrade"]["attempted"] for r in subset),
            "valid": sum(r["regrade"]["valid"] for r in subset), "passed": sum(r["regrade"]["passed"] is True for r in subset),
            "rejected": sum(r["regrade"]["valid"] and r["regrade"]["passed"] is False for r in subset),
            "unavailable": sum(not r["regrade"]["valid"] for r in subset),
            "terminal_state_records": sum(r["state"] in {"done", "failed"} for r in subset),
            "terminal_state_regrade_passed": sum(r["state"] in {"done", "failed"} and r["regrade"]["passed"] is True for r in subset),
            "deadline_eligible_candidates": sum(r["explicit_submission_deadline_eligible"] for r in subset),
            "deadline_eligible_valid": sum(r["explicit_submission_deadline_eligible"] and r["regrade"]["valid"] for r in subset),
            "deadline_eligible_passed": sum(r["explicit_submission_deadline_eligible"] and r["regrade"]["passed"] is True for r in subset),
            "submitted_after_declared_deadline": sum(r["purpose"] != "non_submission_wrapup_diagnostic" and r["candidate_at_or_before_declared_deadline"] is False for r in subset)})
    differences = [r for r in records if r["purpose"] == "final_submission" and r["regrade"]["valid"] and r["stored_pass"] in {0, 1} and bool(r["stored_pass"]) != r["regrade"]["passed"]]
    ungradable = [r for run in manifest["runs"] if run["benchmark"] == "minif2f" for r in run["final_records"] + run["diagnostic_records"]]
    mini = [{k: v for k, v in r.items() if k not in {"description", "candidate", "stored_verdict"}} | {"regrade": {"attempted": False, "valid": False, "passed": None, "outcome": "environment_unavailable", "error": "no prepared pinned miniF2F problems, Lean 4.15.0 REPL/Mathlib/Kimina client environment in .phase1-data"}} for r in ungradable]
    source_checks = []
    for run in manifest["runs"]:
        checked = [{"path": item["path"], "extraction_sha256": item["sha256"], "post_regrade_sha256": file_digest(item["path"])} for item in run["source_files"]]
        unchanged = all(item["extraction_sha256"] == item["post_regrade_sha256"] for item in checked)
        source_checks.append({"run": run["run"], "unchanged": unchanged, "files": checked})
        if not unchanged:
            raise RuntimeError("Legacy source changed during regrade")
    risk = [r for r in records if r["purpose"] == "final_submission" and r["budget_risk_task"]]
    risk_summary = {"task_instances": len(risk) + len({(r["run"], r["task"]) for r in mini}), "valid_offline": sum(r["regrade"]["valid"] for r in risk),
        "passed_offline": sum(r["regrade"]["passed"] is True for r in risk), "rejected_offline": sum(r["regrade"]["valid"] and r["regrade"]["passed"] is False for r in risk),
        "opsin_unavailable": sum(r["regrade"]["outcome"] == "external_service_unavailable" for r in risk), "lean_unavailable": len({(r["run"], r["task"]) for r in mini})}
    opsin_file = OUT / "legacy-regrade-chemiq-opsin.json"
    opsin = json.loads(opsin_file.read_text(encoding="utf-8")) if opsin_file.exists() else None
    opsin_records = opsin["records"] if opsin and opsin["candidate_manifest_sha256"] == file_digest(manifest_path) else []
    opsin_finals = [r for r in opsin_records if r["purpose"] == "final_submission"]
    opsin_summary = {"records": len(opsin_records), "final_candidates": len(opsin_finals), "valid_final_candidates": sum(r["regrade"]["valid"] for r in opsin_finals),
        "passed_final_candidates": sum(r["regrade"]["passed"] is True for r in opsin_finals), "failed_measurements": sum(not r["regrade"]["valid"] for r in opsin_finals), "source": file_record(opsin_file) if opsin_records else None}
    if not opsin_records:
        opsin_summary["execution_status"] = "not run: automatic approval review rejected sending historical candidate strings to the external OPSIN service"
        opsin_summary["approval_review_reason"] = "User authorized project LLM APIs but had not explicitly authorized this external destination and candidate payload. No request was sent; no indirect bypass was attempted."
        opsin_summary["pending_candidates"] = 4
        opsin_summary["external_destinations"] = ["opsin.ch.cam.ac.uk", "www.ebi.ac.uk/opsin/ws"]
    local_path = OUT / "legacy-regrade-chemiq-local-opsin.json"
    local = json.loads(local_path.read_text(encoding="utf-8")) if local_path.exists() else None
    local_records = local["records"] if local else []
    if local and (local["candidate_manifest_sha256"] != file_digest(manifest_path) or local.get("external_requests") != 0):
        raise RuntimeError("Local OPSIN report has a stale manifest or external requests")
    local_finals = [r for r in local_records if r["purpose"] == "final_submission"]
    key_of = lambda row: (row["benchmark"], row["run"], row["task"], row["purpose"], row["candidate_sha256"])
    primary_risk_keys = {key_of(r) for r in risk}
    if any(key_of(r) not in primary_risk_keys for r in local_finals):
        raise RuntimeError("Local OPSIN final did not match the exact primary recovered candidate")
    replacement = {key_of(r): r for r in local_finals}
    supplemented_risk = [replacement.get(key_of(r), r) for r in risk]
    local_summary = {"source": file_record(local_path) if local else None,
        "profile": local.get("variant") if local else None, "jar_sha256": local.get("jar_sha256_verified") if local else None,
        "records": len(local_records), "final_candidates": len(local_finals),
        "valid_final_candidates": sum(r["regrade"]["valid"] for r in local_finals),
        "passed_final_candidates": sum(r["regrade"]["passed"] is True for r in local_finals),
        "rejected_final_candidates": sum(r["regrade"]["valid"] and r["regrade"]["passed"] is False for r in local_finals),
        "deadline_eligible_final_candidates": sum(r["explicit_submission_deadline_eligible"] for r in local_finals),
        "deadline_eligible_passed": sum(r["explicit_submission_deadline_eligible"] and r["regrade"]["passed"] is True for r in local_finals),
        "positive_cache_control_summary": local.get("control_summary") if local else None,
        "final_records": local_finals, "external_requests": 0,
        "limitation": "Independent pinned OPSIN 2.8 variant; old REST version remains unknown. The primary offline report is preserved, and no revised mapping length policy is applied to legacy candidates."}
    supplemented_summary = {"task_instances": risk_summary["task_instances"],
        "valid_with_local_opsin_variant": sum(r["regrade"]["valid"] for r in supplemented_risk),
        "passed_with_local_opsin_variant": sum(r["regrade"]["passed"] is True for r in supplemented_risk),
        "rejected_with_local_opsin_variant": sum(r["regrade"]["valid"] and r["regrade"]["passed"] is False for r in supplemented_risk),
        "opsin_unavailable": sum(r["regrade"]["outcome"] == "external_service_unavailable" for r in supplemented_risk),
        "lean_unavailable": risk_summary["lean_unavailable"],
        "deadline_eligible_valid": sum(r["explicit_submission_deadline_eligible"] and r["regrade"]["valid"] for r in supplemented_risk),
        "deadline_eligible_passed": sum(r["explicit_submission_deadline_eligible"] and r["regrade"]["passed"] is True for r in supplemented_risk),
        "protocol": "Composite diagnostic coverage only. Contains independent local OPSIN 2.8 measurements, not a formal score or old REST equivalence certification."}
    summary = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "candidate_manifest": file_record(manifest_path), "counts": counts,
        "deadline_rule": "actual submit-call timestamp <= task.created_at + solve_seconds * 1000; all-stored candidates and deadline-eligible candidates are reported separately; no late submission is promoted to legitimate historical delivery",
        "risk_final_candidate_summary": risk_summary, "legacy_source_integrity_after_regrade": source_checks,
        "opsin_supplement": opsin_summary,
        "local_opsin_supplement": local_summary,
        "risk_final_candidate_summary_with_local_opsin_variant": supplemented_summary,
        "final_submission_differences": differences, "minif2f_unavailable_records": mini,
        "limits": ["Post-hoc regrading does not undo the changed search path produced by the budget-reuse bug.", "Positive diagnostic candidates are never used to pick each task's best answer or replace a formal score.", "No-submission diagnostic text does not count as an explicit final submission.", "Legacy source revisions and original grader versions remain unverified.", "Stored denominators and original SQLite/CSV results are not changed."]}
    (OUT / "legacy-regrade-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": counts, "risk_final_candidate_summary": risk_summary,
        "risk_final_candidate_summary_with_local_opsin_variant": supplemented_summary,
        "final_submission_difference_count": len(differences), "minif2f_unavailable_records": len(mini)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "worker", "summarise"])
    parser.add_argument("--benchmark", choices=["chembench", "gpqa", "chemiq", "cmt"])
    parser.add_argument("--allow-opsin-network", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    elif args.action == "worker":
        worker(args.benchmark, args.allow_opsin_network)
    else:
        summarise()
