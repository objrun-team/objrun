"""Private per-task positive/semantic-negative/format controls for 616 tasks.

Reference answers remain in private control files and are never given to a solver.
Both preparation and actual grading preserve the pinned official 200-character
guard after parsing. Compact mapping input does not override that guard.
"""
import ast
from collections import Counter
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

from legacy_chemiq_controls import query, sha

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/repair-2026-10-08"


def prepare_worker():
    from legacy_regrade import module_from
    os.environ["TGENGIN_CHEMIQ_HOME"] = "/oracle"
    os.environ["TGENGIN_CHEMIQ_OPSIN_PROFILE"] = "rest"
    mod = module_from("/adapter/stand.py")
    # These controls never require OPSIN. Explicitly make any accidental request
    # a fatal failure, in addition to the container's network=none boundary.
    def blocked_request(*args, **kwargs):
        raise RuntimeError("UnexpectedNetworkInNonOPSINControl")
    mod.requests.get = blocked_request
    from rdkit import rdBase
    records = []
    with rdBase.BlockLogs(), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        for uuid, task in mod.BOOK.items():
            method = task["verification_method"]
            if method == "opsin":
                continue
            answer = task["answer"]
            if method == "list_of_tuples":
                pairs = ast.literal_eval(answer) if isinstance(answer, str) else answer
                positive = "[" + ",".join("(" + ",".join(str(n) for n in pair) + ")" for pair in pairs) + "]"
                negative = "[(999,999)]"
            elif method == "range":
                low, high = ast.literal_eval(task["answer_range"])
                mid = (float(low) + float(high)) / 2
                if mid == 0 and float(low) != 0:
                    mid = float(low)
                positive = repr(mid)
                negative = repr(float(high) + max(1.0, abs(float(high) - float(low))))
            elif method == "exact_match":
                positive = str(answer)
                negative = str(int(answer) + 1)
            elif method == "canonical_smi_match":
                positive = str(answer)
                expected = mod.VERIFIER._canonicalize_smiles(positive)
                negative = "CC" if expected == "C" else "C"
            else:
                raise ValueError("Unexpected non-OPSIN method")
            parsed = mod.PARSER.parse(uuid, positive)
            official = mod.VERIFIER.check_answer(uuid, parsed)
            profile = mod.judge(uuid, positive)
            parsed_length = len(str(parsed))
            missing = None
            if parsed is False:
                missing = "Official parser rejects the stored positive reference"
            elif not parsed:
                missing = "Official verifier rejects this falsey parsed reference before dispatch"
            elif "\n" in str(parsed) or parsed_length > 200:
                missing = "Official post-parse single-line/200-character guard rejects the reference, including compact raw mapping"
            elif not official["is_correct"]:
                missing = "Official verifier rejects the stored positive reference"
            official_gap = missing
            if profile.get("error"):
                missing = "Selected profile reports a grading infrastructure error"
            elif profile["correct"]:
                missing = None
            elif mod.LENGTH_POLICY == "raw-input-length" and method == "list_of_tuples" and (len(positive) > 200 or "\n" in positive or "\r" in positive):
                missing = "Selected mapping raw-input single-line/200-character guard rejects the reference"
            records.append({"task": "chemiq-" + uuid, "uuid": uuid,
                "category": task["question_category"], "sub_category": task["sub_category"], "method": method,
                "positive_input": positive, "negative_input": negative, "format_input": "Z" * 301,
                "positive_sha256": hashlib.sha256(positive.encode()).hexdigest(),
                "positive_raw_length": len(positive), "positive_parsed_length": parsed_length,
                "positive_parsed": parsed is not False, "positive_official_precheck": bool(official["is_correct"]),
                "positive_profile_precheck": bool(profile["correct"]), "positive_control_gap": missing,
                "official_control_gap": official_gap, "n_atoms": (task.get("meta_data") or {}).get("n_atoms")})
    if len(records) != 616:
        raise ValueError("Pinned corpus does not contain exactly 616 non-OPSIN tasks")
    print(json.dumps({"records": records, "source_data_sha256": sha("/oracle/vendor/ChemIQ/questions/chemiq.jsonl"),
        "source_verifier_sha256": sha("/oracle/vendor/ChemIQ/utils/answer_verifier.py"),
        "source_parser_sha256": sha("/oracle/vendor/ChemIQ/utils/parser.py"),
        "selection": "Stored official GT; range midpoint; compact raw mapping syntax; official parser and equality implementation. Length policy is explicitly reported and mapping guard changes only under raw-input-length."}, ensure_ascii=False))


def run(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as response:
        health = json.load(response)
    if not health.get("ok") or health.get("opsin", {}).get("profile") != "local-2.8" or health["opsin"].get("rest_fallback") is not False:
        raise ValueError("Local scoring service profile changed")
    length_policy = health.get("length_policy", "official-parsed")
    suffix = "" if length_policy == "official-parsed" else "-raw-length"
    image = subprocess.run(["docker", "image", "inspect", "objrun-scicode:phase1", "--format", "{{.Id}}"], capture_output=True, text=True, check=True).stdout.strip()
    command = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "1g", "--cpus", "2", "--pids-limit", "128", "--tmpfs", "/tmp:rw,nosuid,size=128m"]
    for source, target in [(Path(__file__).resolve(), "/workspace/scripts/repair/legacy_chemiq_nonopsin_controls.py"),
            (Path(__file__).with_name("legacy_chemiq_controls.py").resolve(), "/workspace/scripts/repair/legacy_chemiq_controls.py"),
            (Path(__file__).with_name("legacy_regrade.py").resolve(), "/workspace/scripts/repair/legacy_regrade.py"),
            (ROOT / "examples/benchmark/chemiq/stand.py", "/adapter/stand.py"),
            (ROOT / ".phase1-data/chemiq", "/oracle"), (ROOT / ".phase1-data/python-extras", "/extras")]:
        command += ["--mount", f"type=bind,source={source},target={target},readonly"]
    command += ["-e", "PYTHONPATH=/extras", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "TGENGIN_CHEMIQ_LENGTH_POLICY=" + length_policy, image, "python", "/workspace/scripts/repair/legacy_chemiq_nonopsin_controls.py", "prepare-worker"]
    result = subprocess.run(command, text=True, encoding="utf-8", capture_output=True, check=True, timeout=90)
    references = json.loads(result.stdout)
    private_path = OUT / ("legacy-chemiq-616-controls-private-references" + suffix + ".json")
    private_path.write_text(json.dumps(references, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    records = []
    print(json.dumps({"tasks": len(references["records"]), "positive_prechecks": sum(r["positive_profile_precheck"] for r in references["records"]), "length_policy": length_policy,
        "stage": "Actual local-profile HTTP controls, with every reference gap still attempted and recorded"}), flush=True)
    for reference in references["records"]:
        row = {k: v for k, v in reference.items() if k not in {"positive_input", "negative_input", "format_input"}}
        row["positive"] = query(port, reference["task"], reference["positive_input"])
        row["wrong_value"] = query(port, reference["task"], reference["negative_input"])
        row["wrong_format"] = query(port, reference["task"], reference["format_input"])
        row["positive_passed"] = row["positive"]["valid"] and row["positive"].get("nodes") == {"parsed": True, "correct": True}
        row["wrong_value_rejected"] = row["wrong_value"]["valid"] and row["wrong_value"].get("nodes") == {"parsed": True, "correct": False}
        row["wrong_format_rejected"] = row["wrong_format"]["valid"] and row["wrong_format"].get("nodes") == {"parsed": False, "correct": False}
        row["precheck_matches_service"] = row["positive"]["valid"] and row["positive"].get("nodes", {}).get("correct") is row["positive_profile_precheck"]
        records.append(row)
        if len(records) % 100 == 0:
            print(json.dumps({"completed": len(records), "positive_passed": sum(r["positive_passed"] for r in records),
                "wrong_value_rejected": sum(r["wrong_value_rejected"] for r in records), "wrong_format_rejected": sum(r["wrong_format_rejected"] for r in records)}), flush=True)
    report = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "profile": health, "length_policy": length_policy, "tasks": len(records), "full_benchmark_denominator": 816,
        "positive_passed": sum(r["positive_passed"] for r in records), "positive_gaps": sum(bool(r["positive_control_gap"]) for r in records),
        "wrong_value_rejected": sum(r["wrong_value_rejected"] for r in records), "wrong_format_rejected": sum(r["wrong_format_rejected"] for r in records),
        "precheck_matches_service": sum(r["precheck_matches_service"] for r in records),
        "gap_methods": dict(Counter(r["method"] for r in records if r["positive_control_gap"])),
        "reference_selection": references["selection"], "source_data_sha256": references["source_data_sha256"],
        "source_verifier_sha256": references["source_verifier_sha256"], "source_parser_sha256": references["source_parser_sha256"],
        "adapter_sha256": sha(ROOT / "examples/benchmark/chemiq/stand.py"), "script_sha256": sha(__file__),
        "preparation_docker_command": command, "reference_manifest_sha256": sha(private_path),
        "records": records, "external_requests": 0,
        "limitation": "Positive reference failures are control gaps, not model failures. The selected explicit length policy is reported; raw-input-length revises the mapping guard only. No task is omitted from 816 and no reference input is exposed to a solver."}
    (OUT / ("legacy-chemiq-616-nonopsin-controls" + suffix + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["tasks", "positive_passed", "positive_gaps", "wrong_value_rejected", "wrong_format_rejected", "precheck_matches_service", "gap_methods", "external_requests"]}), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "prepare-worker":
        prepare_worker()
    else:
        run(int(sys.argv[2]) if len(sys.argv) > 2 else 17917)
