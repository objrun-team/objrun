"""All 200 IUPAC tasks: actual local OPSIN positive/negative controls, no LLM."""
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/repair-2026-10-08"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare_worker():
    from legacy_regrade import module_from
    os.environ["TGENGIN_CHEMIQ_HOME"] = "/oracle"
    os.environ["TGENGIN_CHEMIQ_OPSIN_PROFILE"] = "rest"
    mod = module_from("/adapter/stand.py")
    local_conversions = json.load(sys.stdin)
    from rdkit import rdBase
    names_by_structure = {}
    with rdBase.BlockLogs(), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        for row in sorted(local_conversions["controls"], key=lambda r: r["name"]):
            name = row["name"]
            if not row["local_smiles"] or len(name) > 200:
                continue
            canonical = mod.VERIFIER._canonicalize_smiles(row["local_smiles"])
            if canonical is not None:
                names_by_structure.setdefault(canonical, []).append(name)
        records = []
        for uuid, task in mod.BOOK.items():
            if task["verification_method"] != "opsin":
                continue
            expected = mod.VERIFIER._canonicalize_smiles(task["answer"])
            names = names_by_structure.get(expected, [])
            name = next((n for n in names if mod.PARSER.parse(uuid, n) == n), None)
            records.append({"task": "chemiq-" + uuid, "uuid": uuid, "reference_name": name,
                "reference_name_sha256": hashlib.sha256(name.encode()).hexdigest() if name else None,
                "reference_found": name is not None, "missing_reason": None if name else "No eligible old-cache name whose actual pinned local-2.8 conversion matched the official GT",
                "wrong_structure_name": "ethane" if expected == "C" else "methane"})
    if len(records) != 200:
        raise ValueError("Pinned corpus does not contain exactly 200 OPSIN tasks")
    print(json.dumps({"records": records, "source_data_sha256": sha("/oracle/vendor/ChemIQ/questions/chemiq.jsonl"), "source_verifier_sha256": sha("/oracle/vendor/ChemIQ/utils/answer_verifier.py"),
        "selection": "Lexically first eligible name from the fixed-cache name corpus, using actual local OPSIN 2.8 conversion plus official RDKit-to-GT equality; cached REST SMILES are never used as a grading result."}, ensure_ascii=False))


def query(port, task, name):
    values = {}
    for node in ["parsed", "correct"]:
        body = {"input": {"task": {"id": task}, "result": {"body": name}}}
        request = urllib.request.Request(f"http://127.0.0.1:{port}/{node}", json.dumps(body, ensure_ascii=False).encode(), {"content-type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
            if type(result.get("value")) is not bool:
                raise ValueError("Nonboolean local-profile node")
            values[node] = result["value"]
        except Exception as error:
            return {"valid": False, "error": type(error).__name__, "nodes": values}
    return {"valid": True, "nodes": values}


def run(port):
    conversion_path = OUT / "legacy-local-opsin-conversion-private.json"
    conversions = json.loads(conversion_path.read_text(encoding="utf-8"))
    if conversions.get("jar_sha256_verified") != "d25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab" or conversions.get("external_requests") != 0:
        raise ValueError("Unverified local conversion corpus")
    image = subprocess.run(["docker", "image", "inspect", "objrun-scicode:phase1", "--format", "{{.Id}}"], capture_output=True, text=True, check=True).stdout.strip()
    command = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "1g", "--cpus", "2", "--pids-limit", "128", "--tmpfs", "/tmp:rw,nosuid,size=128m"]
    for source, target in [(Path(__file__).resolve(), "/workspace/scripts/repair/legacy_chemiq_controls.py"), (Path(__file__).with_name("legacy_regrade.py").resolve(), "/workspace/scripts/repair/legacy_regrade.py"),
            (ROOT / "examples/benchmark/chemiq/stand.py", "/adapter/stand.py"), (ROOT / ".phase1-data/chemiq", "/oracle"), (ROOT / ".phase1-data/python-extras", "/extras")]:
        command += ["--mount", f"type=bind,source={source},target={target},readonly"]
    command += ["-e", "PYTHONPATH=/extras", "-e", "PYTHONDONTWRITEBYTECODE=1", image, "python", "/workspace/scripts/repair/legacy_chemiq_controls.py", "prepare-worker"]
    result = subprocess.run(command, input=json.dumps(conversions, ensure_ascii=False), text=True, encoding="utf-8", capture_output=True, check=True, timeout=90)
    references = json.loads(result.stdout)
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as response:
        health = json.load(response)
    if not health.get("ok") or health.get("opsin", {}).get("rest_fallback") is not False or health["opsin"]["jar_sha256"] != conversions["jar_sha256_verified"]:
        raise ValueError("Local scoring service profile changed")
    length_policy = health.get("length_policy", "official-parsed")
    suffix = "" if length_policy == "official-parsed" else "-raw-length"
    (OUT / ("legacy-chemiq-200-controls-private-references" + suffix + ".json")).write_text(json.dumps(references, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    records = []
    print(json.dumps({"tasks": len(references["records"]), "reference_names_found": sum(r["reference_found"] for r in references["records"]), "stage": "Actual local-profile HTTP positive, wrong-format, and wrong-structure controls"}), flush=True)
    for reference in references["records"]:
        row = {k: v for k, v in reference.items() if k not in {"reference_name", "wrong_structure_name"}}
        row["positive"] = query(port, reference["task"], reference["reference_name"]) if reference["reference_found"] else {"valid": False, "error": "NoReferenceName"}
        row["wrong_format"] = query(port, reference["task"], "Z" * 301)
        row["wrong_structure"] = query(port, reference["task"], reference["wrong_structure_name"])
        row["positive_passed"] = row["positive"]["valid"] and row["positive"].get("nodes") == {"parsed": True, "correct": True}
        row["wrong_format_rejected"] = row["wrong_format"]["valid"] and row["wrong_format"].get("nodes") == {"parsed": False, "correct": False}
        row["wrong_structure_rejected"] = row["wrong_structure"]["valid"] and row["wrong_structure"].get("nodes") == {"parsed": True, "correct": False}
        records.append(row)
        if len(records) % 25 == 0:
            print(json.dumps({"completed": len(records), "positive_passed": sum(r["positive_passed"] for r in records), "wrong_structure_rejected": sum(r["wrong_structure_rejected"] for r in records)}), flush=True)
    report = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "profile": health, "length_policy": length_policy, "tasks": 200, "full_benchmark_denominator": 816,
        "local_reference_names_found": sum(r["reference_found"] for r in records), "positive_passed": sum(r["positive_passed"] for r in records),
        "wrong_format_rejected": sum(r["wrong_format_rejected"] for r in records), "wrong_structure_rejected": sum(r["wrong_structure_rejected"] for r in records),
        "source_conversion_sha256": sha(conversion_path), "reference_selection": references["selection"], "source_data_sha256": references["source_data_sha256"], "source_verifier_sha256": references["source_verifier_sha256"],
        "adapter_sha256": sha(ROOT / "examples/benchmark/chemiq/stand.py"), "script_sha256": sha(__file__),
        "records": records, "external_requests": 0, "limitation": "Official GT is used only by private reference controls. No reference name or judgment is exposed to a solver. Missing controls are retained explicitly; the benchmark denominator stays 816."}
    (OUT / ("legacy-chemiq-200-iupac-controls" + suffix + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["tasks", "local_reference_names_found", "positive_passed", "wrong_format_rejected", "wrong_structure_rejected", "external_requests"]}), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "prepare-worker":
        prepare_worker()
    else:
        run(int(sys.argv[2]) if len(sys.argv) > 2 else 17917)
