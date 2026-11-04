"""Read-only DeepSWE chronology/source/image precheck. No scorer or model calls."""
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/repair-2026-10-08"
EXPORT = ROOT / ".local-evidence/repository/examples/benchmark/dsw-full-export"
CORPUS = ROOT / ".phase1-data/deepswe/vendor/deep-swe/tasks"
TASK = "eicrud-keyset-pagination-cursor"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp(value):
    value = int(value)
    utc = datetime.fromtimestamp(value / 1000, timezone.utc)
    return {"milliseconds": value, "utc": utc.isoformat(), "asia_shanghai": utc.astimezone(timezone(timedelta(hours=8))).isoformat()}


def source(path):
    return {"path": str(Path(path).resolve()), "bytes": Path(path).stat().st_size, "sha256": sha(path)}


def csv_rows(name):
    with (EXPORT / "csv" / name).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), reader.fieldnames


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", timeout=30)


def image_precheck():
    inventory_result = docker("image", "ls", "--no-trunc", "--format", "{{json .}}")
    if inventory_result.returncode:
        return {"valid": False, "error": inventory_result.stderr.strip(), "control_executable": False}, {}
    inventory = [json.loads(line) for line in inventory_result.stdout.splitlines() if line.strip()]
    (OUT / "legacy-deepswe-image-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    available = {r["Repository"] + ":" + r["Tag"]: r for r in inventory}
    current_tasks = {}
    for path in sorted(CORPUS.glob("*/task.toml")):
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        ref = config["environment"]["docker_image"]
        current_tasks[path.parent.name] = {"declared_image": ref, "cached": ref in available,
            "cached_image_id": available[ref]["ID"] if ref in available else None,
            "task_toml_sha256": sha(path), "base_commit": config["metadata"]["base_commit_hash"]}
    task = current_tasks[TASK]
    check = docker("image", "inspect", task["declared_image"])
    related = [r for r in inventory if "eicrud" in r["Repository"].lower() or "kh79vgnwnp3wfz0b63ft8zbs81822re8" in r["Tag"]]
    related_metadata = []
    for image in related:
        got = docker("image", "inspect", image["ID"])
        if got.returncode:
            continue
        data = json.loads(got.stdout)[0]
        related_metadata.append({"id": data["Id"], "repo_tags": data["RepoTags"], "size_bytes": data["Size"],
            "repo_digests": data["RepoDigests"], "created": data["Created"],
            "entrypoint": data["Config"].get("Entrypoint"), "cmd": data["Config"].get("Cmd"),
            "working_directory": data["Config"].get("WorkingDir"),
            "usable_official_task_environment": task["declared_image"] in (data["RepoTags"] or [])})
    config = tomllib.loads((CORPUS / TASK / "task.toml").read_text(encoding="utf-8"))
    report = {"valid": True, "current_pinned_tasks": len(current_tasks), "current_task_images_cached": sum(r["cached"] for r in current_tasks.values()),
        "eicrud_task": task, "eicrud_image_inspect_exit": check.returncode,
        "eicrud_image_inspect_error": check.stderr.strip() if check.returncode else None,
        "related_cached_images": related_metadata, "control_executable": check.returncode == 0,
        "control_decision": "NOT RUN: the complete declared official task image is absent; the related egress-proxy image is not a replacement" if check.returncode else "Declared image cached; runtime content precheck would still be required before controls",
        "official_profile": {"source": json.loads((ROOT / ".phase1-data/deepswe/source.json").read_text(encoding="utf-8")),
            "task_id": config["metadata"]["task_id"], "ext_id": config["metadata"]["ext_id"], "base_commit": config["metadata"]["base_commit_hash"],
            "declared_image": config["environment"]["docker_image"], "verifier": config["verifier"], "environment": config["environment"]},
        "eicrud_source_files": [source(p) for p in sorted((CORPUS / TASK).rglob("*")) if p.is_file()],
        "new_containers_created": 0, "images_pulled": 0, "model_calls": 0, "network_requests": 0,
        "limitation": "Current pinned source declares v1.1. Any later controls must remain separate from historical v1 results; no current image or HEAD is evidence of a historical runtime."}
    # Replace the failed ad-hoc inspect placeholder with a valid structured result.
    (OUT / "legacy-deepswe-eicrud-image-inspect-private.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report, current_tasks


def main():
    original_paths = sorted(p for p in EXPORT.rglob("*") if p.is_file())
    original_paths += [ROOT / ".local-evidence/repository/examples/benchmark/dsw-full-export.zip"]
    run_dirs = sorted(p for p in (ROOT / "runs").iterdir() if p.is_dir() and p.name.startswith("dsw"))
    for directory in run_dirs:
        original_paths += sorted(p for p in directory.iterdir() if p.is_file() and (p.suffix in {".log", ".sqlite"} or p.name.endswith(("-wal", "-shm"))))
    before = {str(p): sha(p) for p in original_paths}
    tasks, task_headers = csv_rows("tasks.csv")
    stations, station_headers = csv_rows("stations.csv")
    checks, check_headers = csv_rows("checks.csv")
    tools, tool_headers = csv_rows("tools.csv")
    by_station = defaultdict(list)
    for row in stations:
        by_station[row["task"].rsplit("/", 1)[-1]].append(row)
    by_check = defaultdict(list)
    for row in checks:
        by_check[row["task"].rsplit("/", 1)[-1]].append(row)
    ordered = sorted(tasks, key=lambda r: int(r["created_at"]))
    gaps = sorted([{"gap_ms": int(b["created_at"]) - int(a["created_at"]), "earlier_task": a["task"], "later_task": b["task"],
        "earlier_created_at": stamp(a["created_at"]), "later_created_at": stamp(b["created_at"]),
        "early_tasks": i + 1, "late_tasks": len(ordered) - i - 1,
        "early_stored_passed": sum(r["pass"] == "1" for r in ordered[:i + 1]), "late_stored_passed": sum(r["pass"] == "1" for r in ordered[i + 1:])}
        for i, (a, b) in enumerate(zip(ordered, ordered[1:]))], key=lambda r: r["gap_ms"], reverse=True)
    # Correlate timestamps with BOTH author declarations, never CSV row order.
    # The candidate grouping is explicitly not a per-event source certification.
    carried = "go-genai-streamed-function-args"
    candidates = []
    for cut in range(1, len(ordered)):
        early, late = ordered[:cut], ordered[cut:]
        failures = [r["task"] for r in early if r["pass"] != "1"]
        if sum(r["pass"] == "1" for r in early) == 53 and failures == [carried] and len(late) == 58:
            candidates.append({"earlier_stored_passed_53": [r["task"] for r in early if r["pass"] == "1"],
                "later_created_58": [r["task"] for r in late], "explicitly_retained_old_failure": carried,
                "early_last_creation": stamp(early[-1]["created_at"]), "late_first_creation": stamp(late[0]["created_at"]),
                "early_last_station_start": stamp(max(int(s["at"]) for t in early for s in by_station[t["task"]])),
                "late_first_station_start": stamp(min(int(s["at"]) for t in late for s in by_station[t["task"]])),
                "interpretation": "Unique chronology consistent with 53 early successes and the named retained failure. 59 other score rows comprise 58 later-created tasks plus the retained old go-genai; actual source revisions remain unverified."})
    cohort = {}
    if len(candidates) == 1:
        candidate = candidates[0]
        cohort = {t: "early_stored_passed_53" for t in candidate["earlier_stored_passed_53"]}
        cohort.update({t: "later_created_58" for t in candidate["later_created_58"]})
        cohort[carried] = "explicitly_retained_earlier_failure"
    per_task = []
    for row in sorted(tasks, key=lambda r: r["task"]):
        tid = row["task"]
        units, measurements = by_station[tid], by_check[tid]
        ok_times = [int(m["at"]) for m in measurements if m["pass"] == "1"]
        per_task.append({"task": tid, "id": row["id"], "stored_state": row["state"], "stored_pass": int(row["pass"]),
            "created_at": stamp(row["created_at"]), "declared_solve_seconds": int(row["solve_seconds"]),
            "declared_deadline": stamp(int(row["created_at"]) + int(row["solve_seconds"]) * 1000),
            "last_station_start_at_from_tasks_csv": stamp(row["last_at"]),
            "station_rows": len(units), "first_observed_station_start": stamp(min(int(s["at"]) for s in units)),
            "last_observed_station_start": stamp(max(int(s["at"]) for s in units)),
            "check_rows": len(measurements), "first_observed_check": stamp(min(int(m["at"]) for m in measurements)) if measurements else None,
            "last_observed_check": stamp(max(int(m["at"]) for m in measurements)) if measurements else None,
            "first_successful_check": stamp(min(ok_times)) if ok_times else None,
            "successful_check_after_declared_deadline": any(t > int(row["created_at"]) + int(row["solve_seconds"]) * 1000 for t in ok_times),
            "nonempty_candidate_digest_receipts": sum(bool(m["graded"]) for m in measurements),
            "diagnostic_chronology_cohort": cohort.get(tid), "certified_engine_revision": None, "certified_grader_revision": None,
            "certified_runtime_image_id": None, "source_identity_gap": "CSV exports contain no source commit/hash, deployment event, grader digest, task-content digest, or runtime image ID"})
    database_precheck = []
    log_precheck = []
    for directory in run_dirs:
        for path in sorted(directory.glob("*.sqlite")):
            record = {"source": source(path), "run": directory.name}
            connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
            connection.execute("PRAGMA query_only=ON")
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            table = next((name for name in ["task", "tasks"] if name in tables), None)
            if table:
                columns = {r[1] for r in connection.execute(f'PRAGMA table_info("{table}")')}
                record["task_table_columns"] = sorted(columns)
                record["dsw_full_matching_tasks"] = connection.execute(f'SELECT COUNT(*) FROM "{table}" WHERE id LIKE ?', ("dsw-full/%",)).fetchone()[0] if "id" in columns else None
            else:
                record["dsw_full_matching_tasks"] = 0
                record["task_table_absent"] = True
            connection.close()
            database_precheck.append(record)
        for path in sorted(directory.glob("*.log")):
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            hits = [i + 1 for i, line in enumerate(lines) if "dsw-full" in line]
            log_precheck.append({"source": source(path), "dsw_full_mentions": len(hits), "line_numbers": hits})
    with zipfile.ZipFile(ROOT / ".local-evidence/repository/examples/benchmark/dsw-full-export.zip") as archive:
        archive_members = [{"name": member.filename, "bytes": member.file_size, "uncompressed_sha256": hashlib.sha256(archive.read(member)).hexdigest(),
            "matches_extracted_bytes": (EXPORT / member.filename).is_file() and sha(EXPORT / member.filename) == hashlib.sha256(archive.read(member)).hexdigest()}
            for member in archive.infolist()]
    image_report, current_tasks = image_precheck()
    current_refs = {tid: {**metadata, "historical_identity_confirmed": False} for tid, metadata in current_tasks.items()}
    result_lines = (EXPORT / "RESULT.md").read_text(encoding="utf-8").splitlines()
    statements = [{"line": i + 1, "text": line} for i, line in enumerate(result_lines) if "53 道" in line or "59 道" in line or "go-genai" in line or "2026-09-02" in line]
    integrity = [{"path": name, "sha256_before": digest, "sha256_after": sha(name), "unchanged": sha(name) == digest} for name, digest in before.items()]
    assert all(r["unchanged"] for r in integrity)
    report = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "scope": "Read-only recovery of observed dates and identity gaps. No CSV-order or current-HEAD revision assignment; no score correction or new formal experiment.",
        "export": {"task_count": len(tasks), "unique_task_ids": len({r["id"] for r in tasks}), "stored_passed": sum(r["pass"] == "1" for r in tasks),
            "first_task_creation": stamp(min(int(r["created_at"]) for r in tasks)), "last_task_creation": stamp(max(int(r["created_at"]) for r in tasks)),
            "station_rows": len(stations), "check_rows": len(checks), "tools_rows": len(tools),
            "headers": {"tasks": task_headers, "stations": station_headers, "checks": check_headers, "tools": tool_headers},
            "source_identity_columns": [], "stations_status_counts": dict(Counter(r["status"] for r in stations))},
        "documented_statements": {"source": source(EXPORT / "RESULT.md"), "lines": statements},
        "chronology_reconstruction": {"candidate_count": len(candidates), "candidate_partition": candidates,
            "largest_creation_gaps": gaps[:3], "certified_pre_post_source_assignments": 0,
            "limitation": "Dates establish dispatch chronology, not code or grader identity. The 53/58/1 grouping is a diagnostic consistency reconstruction, not 53/59 certified source batches."},
        "per_task_observed_evidence": per_task, "local_later_run_database_precheck": database_precheck, "local_later_run_log_precheck": log_precheck,
        "archive": {"source": source(ROOT / ".local-evidence/repository/examples/benchmark/dsw-full-export.zip"), "members": archive_members,
            "original_engine_database_in_archive": False, "engine_logs_in_archive": False, "official_task_sources_in_archive": False},
        "eicrud_image_and_control_precheck": image_report, "current_pinned_task_references_only": current_refs,
        "legacy_source_integrity": integrity,
        "missing_material_for_certified_partition": ["Original dsw-full execution database including instance and event history, including cleared/retried tasks",
            "Timestamped engine before/after source snapshots or commit digests and restart/deployment events",
            "Original task corpus version/content digests, grader files/digests and runtime image IDs for each task",
            "Original stand/no-file oracle logs, not just the source comment and aggregated RESULT"],
        "new_containers_created": 0, "images_pulled": 0, "model_calls": 0}
    (OUT / "legacy-deepswe-investigation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "stored_passed": report["export"]["stored_passed"],
        "chronology_consistency_partitions": len(candidates), "certified_source_assignments": 0,
        "later_databases_with_dsw_full": sum((r.get("dsw_full_matching_tasks") or 0) > 0 for r in database_precheck),
        "eicrud_official_image_cached": image_report.get("control_executable"),
        "current_task_images_cached": image_report.get("current_task_images_cached"), "original_files_unchanged": len(integrity),
        "containers_created": 0, "images_pulled": 0}))


if __name__ == "__main__":
    main()
