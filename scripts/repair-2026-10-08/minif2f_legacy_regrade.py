"""Prepare/regrade exactly three frozen last submits, locally, without an LLM.

Historical inputs are read only. The reconstruction is labelled separately;
backend failure is unavailable measurement, never a valid rejection.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

FIXED = {
    ("minif2f-f-0731", "test/amc12a_2019_p12"): "1ad93d0d3b1daad8252bf0ef17e6ab044053daddafb599d035da6db007f16568",
    ("minif2f-f-0731b", "test/mathd_algebra_184"): "7bd5742ddab252e281bda4fb466ea314cc1f8618092b8f7b5a552c5de3053283",
    ("minif2f-f-0731b", "test/mathd_numbertheory_552"): "f3972196a6915d9284d991e36d39c17756de6163e23937b7670bf13f405b2b87",
}
PROTOCOL = "reconstructed-path-workspace-v1"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+".new")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    temporary.replace(path)


def selected(bundle):
    records = bundle["records"]
    if len(records) != 3 or {(x["run"], x["task"]) for x in records} != set(FIXED):
        raise RuntimeError("fixed last-submit task set differs")
    for record in records:
        expected = FIXED[(record["run"], record["task"])]
        if record["candidate_sha256"] != expected or hashlib.sha256(record["candidate"].encode()).hexdigest() != expected:
            raise RuntimeError("fixed candidate differs")
        if len(record["candidate"].encode()) != record["candidate_bytes"]:
            raise RuntimeError("fixed candidate byte count differs")
        if not record["purpose"] == "final_submission" or not record["selection_rule"].startswith("last submit call by unit, seq, and call index"):
            raise RuntimeError("submission selection provenance differs")
        if record["at"] > record["created_at"]+1000*record["solve_seconds"]:
            raise RuntimeError("declared deadline qualification differs")
        if hashlib.sha256(record["description"].encode()).hexdigest() != record["description_sha256"]:
            raise RuntimeError("original task description differs")
    return records


def source_snapshot(entries):
    snapshots = []
    for entry in entries:
        actual = sha(entry["path"])
        if actual != entry["sha256"] or Path(entry["path"]).stat().st_size != entry["bytes"]:
            raise RuntimeError("historical source bytes changed: " + entry["path"])
        snapshots.append({**entry, "current_sha256": actual, "unchanged": True})
    return snapshots


def prepare(project):
    project = Path(project)
    source = project/"docs/repair-2026-10-08/legacy-candidates.json"
    data = json.loads(source.read_bytes())
    runs = [x for x in data["runs"] if x["benchmark"] == "minif2f"]
    records = [x for run in runs for x in run["final_records"]]
    source_files = [x for run in runs for x in run["source_files"]]
    before = source_snapshot(source_files)
    bundle = {"protocol": PROTOCOL, "scope": "post-hoc diagnosis of exactly three frozen recovered last submits",
        "legacy_candidates_sha256": sha(source), "records": records, "source_files": source_files,
        "source_unchanged_before": before, "candidate_selection": "chronology only, never outcomes",
        "original_final_grading_candidate_digest_available": False,
        "candidate_or_private_gt_sent_externally": False, "llm_called": False}
    selected(bundle)
    destination = project/".phase1-data/minif2f-restoration-private/legacy-final-3.json"
    if destination.exists():
        old = json.loads(destination.read_bytes())
        selected(old)
        if old != bundle:
            raise RuntimeError("refuse overwriting a different frozen private candidate bundle")
    else:
        save(destination, bundle)
    after = source_snapshot(source_files)
    if before != after:
        raise RuntimeError("historical files changed during local bundle preparation")
    receipt = {"path": str(destination), "sha256": sha(destination), "bytes": destination.stat().st_size,
        "records": [{k: r[k] for k in ["run", "task", "candidate_sha256", "candidate_bytes", "at", "declared_deadline_at"]} for r in records],
        "source_unchanged_after": after, "candidate_run": False, "llm_called": False}
    save(project/"docs/repair-2026-10-08/minif2f-private-bundle-receipt.json", receipt)
    print(json.dumps({"fixed_candidates": 3, "bundle_sha256": receipt["sha256"], "candidate_run": False}))


def load_runtime(path, expected_sha):
    if sha(path) != expected_sha:
        raise RuntimeError("reviewed runtime harness changed")
    spec = importlib.util.spec_from_file_location("mf2f_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def worker(root, bundle_path, bundle_sha, runtime_sha, stand_sha, output):
    root = Path(root)
    output = Path(output)
    if output.exists():
        raise RuntimeError("refuse overwriting an earlier three-candidate regrade")
    if sha(bundle_path) != bundle_sha:
        raise RuntimeError("private candidate bundle checksum differs")
    bundle = json.loads(Path(bundle_path).read_bytes())
    records = selected(bundle)
    runtime = load_runtime("/plan/minif2f_runtime.py", runtime_sha)
    prechecks_path = root/"audit/runtime-prechecks.json"
    prechecks = json.loads(prechecks_path.read_bytes())
    if prechecks["protocol"] != PROTOCOL or not prechecks["source_identities_unchanged"]:
        raise RuntimeError("reconstructed runtime prechecks absent or inconsistent")
    if sha(root/"audit/runtime-workspace.json") != prechecks["runtime_workspace_sha256"]:
        raise RuntimeError("runtime workspace receipt changed")
    if sha(root/"audit/public-controls.json") != prechecks["public_controls_sha256"]:
        raise RuntimeError("public True/sorry/False control receipt changed")
    controls = json.loads((root/"audit/public-controls.json").read_bytes())
    if not controls["controls_passed"] or controls["book_count"] != 488 or controls["candidate_run"]:
        raise RuntimeError("public dependency controls did not pass")
    if sha("/plan/stand.py") != stand_sha:
        raise RuntimeError("official adapter source changed")
    workspace = json.loads((root/"audit/runtime-workspace.json").read_bytes())
    bootstrap = json.loads((root/"audit/bootstrap.json").read_bytes())
    if sha(root/"problems.jsonl") != bootstrap["problems_sha256"] or sha(root/"vendor/kimina-lean-server/client/kimina_client/models.py") != bootstrap["models_sha256"]:
        raise RuntimeError("official problem set or official Kimina model predicates changed")
    began_audit = time.perf_counter()
    cached_before = runtime.cache_identity(root)
    if cached_before != prechecks["official_cache_identity"]:
        raise RuntimeError("official Mathlib cache fingerprint differs from prechecks")
    audit_before_seconds = round(time.perf_counter()-began_audit, 3)
    original_before = runtime.original_inputs(root)
    environment = runtime.runtime_environment(root)
    os.environ.clear()
    os.environ.update(environment)
    sys.path.insert(0, str(root/"python-support"))
    spec = importlib.util.spec_from_file_location("mf2f_original_stand", "/plan/stand.py")
    stand = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stand)
    if len(stand.BOOK) != 488:
        raise RuntimeError("exact 488-problem book unavailable")
    result = {"protocol": PROTOCOL, "classification": "post-hoc local diagnosis, not a new formal F run or historical score rewrite",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "bundle_sha256": bundle_sha,
        "runtime_harness_sha256": runtime_sha, "stand_sha256": stand_sha,
        "runtime_prechecks_sha256": sha(prechecks_path), "workspace_receipt_sha256": sha(root/"audit/runtime-workspace.json"),
        "bootstrap_receipt_sha256": sha(root/"audit/bootstrap.json"), "official_cache_identity_before": cached_before,
        "input_cache_audit_seconds": audit_before_seconds, "original_mathlib_inputs": original_before,
        "source_pins": bootstrap["pins"], "image_id": bootstrap["image_id"],
        "new_runtime_protocol": True, "network": "none", "cache_mount": "read-only", "llm_called": False,
        "candidate_or_private_gt_sent_externally": False, "timeout_seconds": 300, "cold_header_timeout_seconds": 600,
        "memory_gib": 12, "repl_pool_size": 1, "records": []}
    try:
        for record in records:
            started = time.perf_counter()
            wall_started = datetime.now(timezone.utc).isoformat()
            try:
                got = stand.judge(stand.BOOK[record["task"]], record["candidate"])
                unavailable = bool(got.get("backend_error"))
                value = None if unavailable else int(bool(got["stated"] and got["compiles"] and got["sound"]))
            except Exception as error:
                got = {"backend_error": type(error).__name__+": "+str(error)}
                unavailable, value = True, None
            result["records"].append({
                **{k: record[k] for k in ["run", "task", "candidate_sha256", "candidate_bytes", "description_sha256", "call_id", "instance", "unit", "seq", "call_index", "at", "created_at", "solve_seconds", "declared_deadline_at", "selection_rule", "stored_pass", "original_final_grading_candidate_digest_available"]},
                "deadline_eligible": record["at"] <= record["declared_deadline_at"], "started_at_utc": wall_started,
                "grading_wall_seconds": round(time.perf_counter()-started, 3), "pass": value,
                "valid": not unavailable, "outcome": "grader_error" if unavailable else "candidate_result",
                "measurement_unavailable": unavailable, "raw_local_lean_receipt": got})
            save(output, result)  # Preserve prior fixed records if a later operation fails.
    finally:
        for repl in stand.LEAN.idle:
            repl.kill()
    began_audit = time.perf_counter()
    try:
        cached_after = runtime.cache_identity(root)
        integrity_error = None
    except Exception as error:
        cached_after = None
        integrity_error = type(error).__name__+": "+str(error)
    result["output_cache_audit_seconds"] = round(time.perf_counter()-began_audit, 3)
    result["official_cache_identity_after"] = cached_after
    result["cache_and_original_inputs_unchanged"] = cached_after == cached_before and runtime.original_inputs(root) == original_before
    if not result["cache_and_original_inputs_unchanged"]:
        result["environment_integrity_error"] = True
        result["environment_integrity_error_detail"] = integrity_error
        for record in result["records"]:
            record.update({"valid": False, "pass": None, "outcome": "grader_error", "measurement_unavailable": True})
    result["summary"] = {"fixed_candidates": 3, "valid_measurements": sum(x["valid"] for x in result["records"]),
        "passed": sum(x["pass"] == 1 for x in result["records"]), "rejected": sum(x["pass"] == 0 for x in result["records"]),
        "unavailable": sum(x["measurement_unavailable"] for x in result["records"])}
    save(output, result)
    print(json.dumps(result["summary"]))


def finish(project, owned_root):
    project, owned_root = Path(project), Path(owned_root)
    bundle = json.loads((project/".phase1-data/minif2f-restoration-private/legacy-final-3.json").read_bytes())
    selected(bundle)
    after = source_snapshot(bundle["source_files"])
    raw = owned_root/"audit/legacy-regrade-output/legacy-regrade-minif2f.json"
    data = json.loads(raw.read_bytes())
    if data["protocol"] != PROTOCOL or len(data["records"]) != 3:
        raise RuntimeError("unexpected local regrade record set")
    if not data.get("summary"):
        raise RuntimeError("regrade did not reach its final environment-integrity checks")
    for record in data["records"]:
        if record["candidate_sha256"] != FIXED[(record["run"], record["task"])]:
            raise RuntimeError("regrade candidate fingerprint differs")
    data["source_unchanged_after_regrade"] = after
    data["legacy_sources_unchanged"] = True
    data["local_raw_receipt_sha256"] = sha(raw)
    destination = project/"docs/repair-2026-10-08/legacy-regrade-minif2f.json"
    if destination.exists():
        raise RuntimeError("refuse overwriting an existing miniF2F diagnosis")
    save(destination, data)
    print(json.dumps({"archived": str(destination), "legacy_sources_unchanged": True, "summary": data["summary"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "worker", "finish"])
    parser.add_argument("--project")
    parser.add_argument("--root")
    parser.add_argument("--bundle", default="/private/legacy-final-3.json")
    parser.add_argument("--bundle-sha")
    parser.add_argument("--runtime-sha")
    parser.add_argument("--stand-sha")
    parser.add_argument("--output", default="/out/legacy-regrade-minif2f.json")
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.project)
    elif args.stage == "worker":
        worker(args.root, args.bundle, args.bundle_sha, args.runtime_sha, args.stand_sha, args.output)
    else:
        finish(args.project, args.root)
