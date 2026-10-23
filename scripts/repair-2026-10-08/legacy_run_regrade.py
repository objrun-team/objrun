"""Run prepared legacy candidates in existing read-only offline scorer containers."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/repair-2026-10-08"
MANIFEST = OUT / "legacy-candidates.json"
WORKER = Path(__file__).with_name("legacy_regrade.py")


def run(slug, records, image_id, sha, allow_opsin_network=False):
    adapter = ROOT / f"examples/benchmark/{slug}/" / ("grader.py" if slug == "cmt" else "stand.py")
    command = ["docker", "run", "--rm", "-i", "--network", "bridge" if allow_opsin_network else "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--memory", "1g", "--cpus", "2", "--pids-limit", "128", "--tmpfs", "/tmp:rw,nosuid,size=128m"]
    for source, target in [(WORKER, "/workspace/scripts/repair/legacy_regrade.py"), (adapter, "/adapter/" + adapter.name),
            (ROOT / f".phase1-data/{slug}", "/oracle"), (ROOT / ".phase1-data/python-extras", "/extras")]:
        command += ["--mount", f"type=bind,source={source},target={target},readonly"]
    command += ["-e", "PYTHONPATH=/extras", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "MPLCONFIGDIR=/tmp/matplotlib",
        image_id, "python", "/workspace/scripts/repair/legacy_regrade.py", "worker", "--benchmark", slug]
    if allow_opsin_network:
        command += ["--allow-opsin-network"]
    payload = {"candidate_manifest_sha256": sha, "records": records}
    result = subprocess.run(command, input=json.dumps(payload, ensure_ascii=False), text=True, encoding="utf-8", capture_output=True, timeout=300)
    if result.returncode:
        path = OUT / f"legacy-regrade-{slug}-failure.log"
        path.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        return {"benchmark": slug, "returncode": result.returncode, "error_log": str(path), "error_log_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    report = json.loads(result.stdout)
    report["runtime"] = {"image_id": image_id, "command": command, "completed_at_utc": datetime.now(timezone.utc).isoformat(), "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest()}
    suffix = "-opsin" if allow_opsin_network else ""
    (OUT / f"legacy-regrade-{slug}{suffix}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"benchmark": slug, "returncode": 0, "records": len(report["records"]),
            "identity_matched": sum(r["identity"]["matched"] for r in report["records"]),
            "valid": sum(r["regrade"]["valid"] for r in report["records"]), "passed": sum(r["regrade"]["passed"] is True for r in report["records"])}


if __name__ == "__main__":
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sha = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    inspect = subprocess.run(["docker", "image", "inspect", "objrun-scicode:phase1", "--format", "{{.Id}}"], capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
    image_id = inspect.stdout.strip()
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmarks", nargs="*", choices=["chembench", "chemiq", "gpqa", "cmt"])
    parser.add_argument("--allow-opsin-network", action="store_true")
    options = parser.parse_args()
    chosen = set(options.benchmarks) or {"chembench", "chemiq", "gpqa", "cmt"}
    if options.allow_opsin_network and chosen != {"chemiq"}:
        raise ValueError("Network permission is restricted to the ChemIQ OPSIN supplement")
    jobs = []
    for slug in sorted(chosen):
        rows = [row for runrow in manifest["runs"] if runrow["benchmark"] == slug for row in runrow["final_records"] + runrow["diagnostic_records"]]
        if options.allow_opsin_network:
            previous = json.loads((OUT / "legacy-regrade-chemiq.json").read_text(encoding="utf-8"))
            unavailable = {(r["run"], r["task"], r["purpose"], r["candidate_sha256"]) for r in previous["records"] if r["regrade"]["outcome"] == "external_service_unavailable"}
            rows = [r for r in rows if (r["run"], r["task"], r["purpose"], r["candidate_sha256"]) in unavailable]
        jobs.append((slug, rows))
    failed = False
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(run, slug, rows, image_id, sha, options.allow_opsin_network) for slug, rows in jobs]
        for future in as_completed(futures):
            summary = future.result()
            print(json.dumps(summary), flush=True)
            failed = failed or summary["returncode"] != 0
    if failed:
        raise SystemExit(1)
