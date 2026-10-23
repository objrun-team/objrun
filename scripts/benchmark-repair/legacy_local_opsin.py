"""OPSIN 2.8.0 CLI locally, followed by official RDKit checks without a network.

Uses all fixed positive OPSIN-cache entries as behavior controls. No REST request,
LLM call, candidate revision, best-outcome selection, or mutation of old runs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/repair-2026-10-08"
JAR = ROOT / ".phase1-data/opsin/opsin-cli-2.8.0-jar-with-dependencies.jar"
JAR_SHA = "d25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab"


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha_text(value):
    return hashlib.sha256(value.encode()).hexdigest()


def load_parser():
    source = ROOT / ".phase1-data/chemiq/vendor/ChemIQ/utils/parser.py"
    spec = importlib.util.spec_from_file_location("legacy_official_parser", source)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.AnswerParser(str(ROOT / ".phase1-data/chemiq/vendor/ChemIQ/questions/chemiq.jsonl"), doClean=True)


def convert():
    if sha_file(JAR) != JAR_SHA:
        raise ValueError("Official JAR digest mismatch")
    sys.dont_write_bytecode = True
    parser = load_parser()
    manifest_path = OUT / "legacy-candidates.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    previous = json.loads((OUT / "legacy-regrade-chemiq.json").read_text(encoding="utf-8"))
    unavailable = {(r["run"], r["task"], r["purpose"], r["candidate_sha256"]) for r in previous["records"] if r["regrade"]["outcome"] == "external_service_unavailable"}
    rows = [r for run in manifest["runs"] if run["benchmark"] == "chemiq" for r in run["final_records"] + run["diagnostic_records"]
            if (r["run"], r["task"], r["purpose"], r["candidate_sha256"]) in unavailable]
    parsed_names = []
    for row in rows:
        parsed = parser.parse(row["task"].removeprefix("chemiq-"), row["candidate"])
        if not isinstance(parsed, str) or not parsed or "\n" in parsed or "\r" in parsed:
            raise ValueError("Pending candidate does not have a single nonempty parsed name")
        parsed_names.append(parsed)
    cache_path = ROOT / ".phase1-data/chemiq/vendor/ChemIQ/utils/opsin_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    controls = sorted(k for k, value in cache.items() if isinstance(value, str) and value)
    if any(not k or "\n" in k or "\r" in k for k in controls):
        raise ValueError("Control names violate CLI line protocol")
    names = controls + parsed_names
    input_path = OUT / "legacy-local-opsin-input.txt"
    output_path = OUT / "legacy-local-opsin-smiles.txt"
    input_path.write_text("\n".join(names) + "\n", encoding="utf-8")
    java = shutil.which("java")
    if not java:
        raise RuntimeError("Local Java is unavailable")
    env = os.environ.copy()
    for variable in ["JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"]:
        env.pop(variable, None)
    command = [java, "-Xmx512m", "-Dfile.encoding=UTF-8", "-Djava.net.useSystemProxies=false", "-jar", str(JAR), "-osmi", str(input_path), str(output_path)]
    version = subprocess.run([java, "-version"], capture_output=True, text=True, encoding="utf-8", env=env, timeout=20, check=True)
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=env, timeout=300)
    log_path = OUT / "legacy-local-opsin-cli.log"
    log_path.write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError("Local OPSIN CLI failed; inspect the private log")
    outputs = output_path.read_text(encoding="utf-8").splitlines()
    if len(outputs) != len(names):
        raise ValueError(f"OPSIN line alignment failure: {len(outputs)} != {len(names)}")
    controls_payload = [{"name": name, "local_smiles": smiles, "original_verifier_length_eligible": len(name) <= 200} for name, smiles in zip(controls, outputs[:len(controls)])]
    records = [row | {"local_opsin_name": name, "local_opsin_smiles": smiles} for row, name, smiles in zip(rows, parsed_names, outputs[len(controls):])]
    evidence = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "candidate_manifest_sha256": sha_file(manifest_path),
        "variant": "OPSIN 2.8.0 default CLI configuration; independent local variant, old REST version unknown",
        "source": json.loads((JAR.parent / "source.json").read_text(encoding="utf-8")), "jar_sha256_verified": JAR_SHA,
        "cache_sha256": sha_file(cache_path), "parser_sha256": sha_file(ROOT / ".phase1-data/chemiq/vendor/ChemIQ/utils/parser.py"),
        "java_command": command, "java_version": (version.stdout + version.stderr).strip(),
        "input": {"path": str(input_path), "sha256": sha_file(input_path)}, "output": {"path": str(output_path), "sha256": sha_file(output_path)},
        "private_cli_log": {"path": str(log_path), "sha256": sha_file(log_path)}, "cli_exit_code": completed.returncode,
        "controls": controls_payload, "records": records, "external_requests": 0,
        "privacy": "Contains fixed-cache names and local candidate conversions; private diagnostic material. No REST or other external service is used."}
    payload_path = OUT / "legacy-local-opsin-conversion-private.json"
    payload_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"conversion_file": str(payload_path), "positive_cache_controls": len(controls), "pending_candidate_records": len(records), "local_cli_recognized": sum(bool(x["local_opsin_smiles"]) for x in records), "external_requests": 0}), flush=True)
    return payload_path


def compare_worker():
    from legacy_regrade import module_from, match_task
    payload = json.load(sys.stdin)
    os.environ["TGENGIN_CHEMIQ_HOME"] = "/oracle"
    mod = module_from("/adapter/stand.py")
    def no_network(*args, **kwargs):
        raise RuntimeError("External requests prohibited in local OPSIN variant")
    mod.requests.get = no_network
    mod.requests.post = no_network
    controls = []
    source_cache = json.loads(Path("/oracle/vendor/ChemIQ/utils/opsin_cache.json").read_text(encoding="utf-8"))
    if sha_file("/oracle/vendor/ChemIQ/utils/opsin_cache.json") != payload["cache_sha256"]:
        raise ValueError("Fixed cache changed between conversion and comparison")
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        for row in payload["controls"]:
            expected = source_cache[row["name"]]
            canonical_local = mod.VERIFIER._canonicalize_smiles(row["local_smiles"]) if row["local_smiles"] else None
            canonical_cache = mod.VERIFIER._canonicalize_smiles(expected)
            controls.append({"name_sha256": sha_text(row["name"]), "local_smiles_sha256": sha_text(row["local_smiles"]),
                "cache_smiles_sha256": sha_text(expected), "local_recognized": bool(row["local_smiles"]),
                "cache_rdkit_valid": canonical_cache is not None, "local_rdkit_valid": canonical_local is not None,
                "canonical_match": canonical_cache is not None and canonical_cache == canonical_local,
                "original_verifier_length_eligible": row["original_verifier_length_eligible"]})
    records = []
    for row in payload["records"]:
        summary = {k: v for k, v in row.items() if k not in {"description", "candidate", "stored_verdict", "local_opsin_name", "local_opsin_smiles"}}
        item, identity = match_task("chemiq", mod, row)
        uuid = row["task"].removeprefix("chemiq-")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            parsed = mod.PARSER.parse(uuid, row["candidate"])
            if not identity["matched"] or parsed != row["local_opsin_name"]:
                result = {"attempted": False, "valid": False, "passed": None, "outcome": "identity_mismatch"}
            else:
                # Only the OPSIN conversion result is injected. The pinned official
                # check_answer length/format gate and RDKit graph comparison remain.
                local_smiles = row["local_opsin_smiles"] or False
                mod.VERIFIER._get_opsin = lambda name, said=parsed, smiles=local_smiles: smiles if name == said else no_network()
                try:
                    got = mod.VERIFIER.check_answer(uuid, parsed)
                    valid = got.get("opsin_smiles") is not None
                    result = {"attempted": True, "valid": valid, "parsed": parsed is not False, "passed": bool(got["is_correct"]) if valid else None,
                        "outcome": "grader_timeout_or_error" if not valid else "passed" if got["is_correct"] else "rejected",
                        "local_opsin_recognized": bool(row["local_opsin_smiles"]), "conversion_source": "local OPSIN 2.8.0 CLI; no REST"}
                except Exception as error:
                    result = {"attempted": True, "valid": False, "passed": None, "outcome": "grader_error", "error": type(error).__name__}
        records.append(summary | {"identity": identity, "regrade": result, "parsed_name_sha256": sha_text(str(parsed)), "local_smiles_sha256": sha_text(row["local_opsin_smiles"])})
    eligible_controls = [r for r in controls if r["original_verifier_length_eligible"]]
    report = {key: payload[key] for key in ["created_at_utc", "candidate_manifest_sha256", "variant", "source", "jar_sha256_verified", "cache_sha256", "parser_sha256", "java_command", "java_version", "input", "output", "private_cli_log", "cli_exit_code", "external_requests"]}
    report.update({"benchmark": "chemiq", "network": "native local Java CLI file I/O; RDKit comparison in Docker network=none",
        "official_sources": [{"path": str(p), "sha256": sha_file(p)} for p in [Path("/adapter/stand.py"), Path("/oracle/vendor/ChemIQ/utils/parser.py"), Path("/oracle/vendor/ChemIQ/utils/answer_verifier.py"), Path("/oracle/vendor/ChemIQ/questions/chemiq.jsonl")]],
        "control_summary": {"total": len(controls), "canonical_match": sum(r["canonical_match"] for r in controls),
            "cache_rdkit_invalid": sum(not r["cache_rdkit_valid"] for r in controls), "local_unrecognized": sum(not r["local_recognized"] for r in controls),
            "length_eligible": len(eligible_controls), "length_eligible_canonical_match": sum(r["canonical_match"] for r in eligible_controls)},
        "controls": controls, "records": records, "limitation": "Cache agreement is a behavior control, not proof that the unknown historical REST deployment ran OPSIN 2.8.0 or that this is a new formal F experiment."})
    print(json.dumps(report, ensure_ascii=False))


def run():
    payload_path = convert()
    image_id = subprocess.run(["docker", "image", "inspect", "objrun-scicode:phase1", "--format", "{{.Id}}"], capture_output=True, text=True, encoding="utf-8", check=True, timeout=20).stdout.strip()
    command = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "1g", "--cpus", "2", "--pids-limit", "128", "--tmpfs", "/tmp:rw,nosuid,size=128m"]
    for source, target in [(Path(__file__).resolve(), "/workspace/scripts/repair/legacy_local_opsin.py"), (Path(__file__).with_name("legacy_regrade.py").resolve(), "/workspace/scripts/repair/legacy_regrade.py"),
        (ROOT / "examples/benchmark/chemiq/stand.py", "/adapter/stand.py"), (ROOT / ".phase1-data/chemiq", "/oracle"), (ROOT / ".phase1-data/python-extras", "/extras")]:
        command += ["--mount", f"type=bind,source={source},target={target},readonly"]
    command += ["-e", "PYTHONPATH=/extras", "-e", "PYTHONDONTWRITEBYTECODE=1", image_id, "python", "/workspace/scripts/repair/legacy_local_opsin.py", "compare-worker"]
    result = subprocess.run(command, input=payload_path.read_text(encoding="utf-8"), text=True, encoding="utf-8", capture_output=True, timeout=180)
    if result.returncode:
        (OUT / "legacy-local-opsin-rdkit-failure.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        raise RuntimeError("Offline RDKit comparison failed; inspect the private log")
    report = json.loads(result.stdout)
    report["runtime"] = {"image_id": image_id, "docker_command": command, "worker_script_sha256": sha_file(Path(__file__)), "conversion_payload_sha256": sha_file(payload_path), "stdout_sha256": sha_text(result.stdout), "stderr_sha256": sha_text(result.stderr), "completed_at_utc": datetime.now(timezone.utc).isoformat()}
    path = OUT / "legacy-regrade-chemiq-local-opsin.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path), "control_summary": report["control_summary"], "regrade_outcomes": dict(Counter(r["regrade"]["outcome"] for r in report["records"])), "external_requests": 0}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["run", "compare-worker"])
    args = parser.parse_args()
    if args.action == "run":
        run()
    else:
        compare_worker()
