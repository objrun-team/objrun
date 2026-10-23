"""Trusted private image runner. Imports are inert; only --job executes tests.

This file never executes a candidate program. Pytest sources and all fixtures
are fixed host-provided inputs, and candidate input is one regular data file.
The Docker/namespace/actor proof is verified independently by the host executor.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

PROTOCOL = "sealed-offline-data-verifier-v1"
TASK_OUTPUTS = {
    "3d-scan-calc": "/root/mass_report.json", "citation-check": "/root/answer.json",
    "court-form-filling": "/root/sc100-filled.pdf", "dapt-intrusion-detection": "/root/network_stats.csv",
    "earthquake-plate-calculation": "/root/answer.json", "econ-detrending-correlation": "/root/answer.txt",
    "jpg-ocr-stat": "/app/workspace/stat_ocr.xlsx", "lab-unit-harmonization": "/root/ckd_lab_data_harmonized.csv",
    "offer-letter-generator": "/root/offer_letter_filled.docx", "pptx-reference-formatting": "/root/Awesome-Agent-Papers_processed.pptx",
}
PUBLIC_INPUTS = {
    "3d-scan-calc": ["/root/scan_data.stl"], "dapt-intrusion-detection": ["/root/packets.pcap"],
    "court-form-filling": ["/root/sc100-blank.pdf"], "offer-letter-generator": ["/root/employee_data.json"],
    "pptx-reference-formatting": ["/root/Awesome-Agent-Papers.pptx"],
}
RESOURCE = {"3d-scan-calc": (4096, 900), "citation-check": (2048, 900), "court-form-filling": (4096, 600),
            "dapt-intrusion-detection": (2048, 600), "earthquake-plate-calculation": (4096, 900),
            "econ-detrending-correlation": (4096, 240), "jpg-ocr-stat": (4096, 600),
            "lab-unit-harmonization": (4096, 1800), "offer-letter-generator": (4096, 900),
            "pptx-reference-formatting": (2048, 600)}
DEPENDENCIES = {"pytest": "8.4.1", "pytest-json-ctrf": "0.3.5", "openpyxl": "3.1.5", "pypdf": "5.1.0",
                "python-docx": "1.1.2", "lxml": "5.3.0", "defusedxml": "0.7.1", "six": "1.17.0",
                "rapidfuzz": "3.14.3", "numpy": "1.26.4", "pandas": "2.2.2"}
MAX_FILE, MAX_RESULT = 64*1024**2, 1024**2


class EvaluationFault(RuntimeError):
    def __init__(self, kind, detail): super().__init__(detail); self.kind = kind


def demand(value, kind, detail):
    if not value: raise EvaluationFault(kind, detail)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def ordinary_file(path, maximum):
    p = Path(path); a = p.lstat()
    demand(stat.S_ISREG(a.st_mode) and not stat.S_ISLNK(a.st_mode) and a.st_nlink == 1 and 0 <= a.st_size <= maximum,
           "input_kind", "Only bounded ordinary singly-linked data/source is admitted")
    with p.open("rb") as f: sha = hashlib.file_digest(f, "sha256").hexdigest()
    b = p.lstat()
    demand((a.st_ino, a.st_size, a.st_mtime_ns) == (b.st_ino, b.st_size, b.st_mtime_ns), "input_race", "Input changed while read")
    return {"path": str(p), "bytes": a.st_size, "sha256": sha}


def directory(path):
    p = Path(path)
    demand(p.is_absolute(), "directory", "Absolute private path required")
    for ancestor in (p, *p.parents):
        a = ancestor.lstat()
        demand(stat.S_ISDIR(a.st_mode) and not stat.S_ISLNK(a.st_mode), "directory", "Ordinary private ancestors required")


def verify_inputs(job):
    task_id = job["taskId"]
    trusted = {"/verifier/test_outputs.py", "/verifier/test.sh"}
    if task_id == "jpg-ocr-stat": trusted.add("/verifier/stat_oracle.xlsx")
    public = set(PUBLIC_INPUTS.get(task_id, []))
    optional = {TASK_OUTPUTS[task_id]}
    items = job.get("inputs")
    demand(isinstance(items, list) and len(items) <= 16, "input_manifest", "Complete small input manifest required")
    seen, rows = set(), []
    for item in items:
        demand(isinstance(item, dict) and set(item) == {"path", "bytes", "sha256", "role"}
               and type(item["bytes"]) is int and re.fullmatch("[0-9a-f]{64}", item["sha256"]), "input_manifest", "Input Pin/role malformed")
        path, role = item["path"], item["role"]
        demand(path not in seen and ((path in trusted and role == "original-verifier") or
               (path in public and role == "trusted-public-fixture") or (path in optional and role == "candidate-data")),
               "input_scope", "Undeclared file/duplicate/candidate code/private input substitution")
        directory(Path(path).parent)
        maximum = 8*1024**2 if role == "candidate-data" else MAX_FILE
        actual = ordinary_file(path, maximum)
        demand(actual == {k: item[k] for k in ("path", "bytes", "sha256")}, "input_sha", "Private copied input differs")
        seen.add(path); rows.append(item)
    demand(trusted | public <= seen, "input_manifest", "Original tests/fixtures incomplete")
    if job["mode"] == "grade": demand(optional <= seen, "candidate_missing", "Grade requires its single sealed regular artifact")
    return rows


def validate_job(job):
    keys = {"protocol", "taskId", "mode", "taskDescriptorSha256", "runnerSourceSha256", "pythonPath", "pythonSha256",
            "pythonVersion", "dependencies", "inputs", "expectedNodeIds", "outputArtifactPath", "scoreRule", "pdftotext", "memoryBytes", "timeoutSec"}
    demand(isinstance(job, dict) and set(job) == keys and job["protocol"] == "skillsbench-private-offline-job-v1"
           and job["taskId"] in TASK_OUTPUTS and job["mode"] in ("grade", "collect"), "job", "Wrong fixed private job schema/task/mode")
    demand(all(isinstance(job[k], str) and re.fullmatch("[0-9a-f]{64}", job[k]) for k in
               ("taskDescriptorSha256", "runnerSourceSha256", "pythonSha256")), "job_pin", "Source/interpreter/descriptor hashes required")
    demand(job["pythonPath"] == "/opt/objrun-verifier/bin/python" and job["pythonVersion"] == "3.12.3"
           and job["dependencies"] == DEPENDENCIES and job["outputArtifactPath"] == TASK_OUTPUTS[job["taskId"]], "job_policy", "Fixed interpreter/depot/output changed")
    memory, seconds = RESOURCE[job["taskId"]]
    demand(job["memoryBytes"] == memory*1024**2 and job["timeoutSec"] == seconds, "job_resource", "Exact original task resource changed")
    score_rule = "original-three-decimal-passed-over-passed-plus-failed" if job["taskId"] == "lab-unit-harmonization" else "original-pytest-exit-binary"
    demand(job["scoreRule"] == score_rule, "job_score", "Original score domain changed")
    nodes = job["expectedNodeIds"]
    if job["mode"] == "grade":
        demand(isinstance(nodes, list) and 0 < len(nodes) <= 4096 and len(set(nodes)) == len(nodes)
               and all(isinstance(n, str) and 0 < len(n) <= 1024 for n in nodes), "expected_collection", "Actual complete expected node IDs required")
    else: demand(nodes is None, "expected_collection", "Collection bootstrap cannot impersonate a completed grade")
    return job


def score_result(job, node_ids, reports, pytest_exit_code, collection_errors):
    """Pure result rules; this function alone is not an execution certificate."""
    validate_job(job)
    demand(job["mode"] == "grade" and node_ids == job["expectedNodeIds"] and not collection_errors,
           "collection", "Complete source-bound collection changed, errored or omitted")
    demand(pytest_exit_code in (0, 1) and isinstance(reports, list), "pytest_exit", "Incomplete/interrupted test execution")
    phases = {n: {} for n in node_ids}
    for row in reports:
        demand(isinstance(row, dict) and set(row) == {"nodeId", "phase", "outcome"} and row["nodeId"] in phases
               and row["phase"] in ("setup", "call", "teardown") and row["outcome"] in ("passed", "failed", "skipped")
               and row["phase"] not in phases[row["nodeId"]], "test_events", "Unknown/duplicate/partial test report")
        phases[row["nodeId"]][row["phase"]] = row["outcome"]
    passed = failed = 0
    for state in phases.values():
        demand(set(state) == {"setup", "call", "teardown"} and state["setup"] == state["teardown"] == "passed"
               and state["call"] in ("passed", "failed"), "test_phases", "Skip/setup/teardown error or missing test phase")
        passed += state["call"] == "passed"; failed += state["call"] == "failed"
    demand((pytest_exit_code == 0) == (failed == 0), "pytest_exit", "Actual test outcomes disagree with pytest exit status")
    reward = round(passed/(passed+failed), 3) if job["taskId"] == "lab-unit-harmonization" else int(pytest_exit_code == 0)
    return {"valid": True, "pass": reward == 1, "score": reward, "outcome": "all_passed" if reward == 1 else "tests_failed",
            "passedTests": passed, "failedTests": failed, "collectedTests": len(node_ids), "collectionValidated": True}


def fresh_result(path, value):
    raw = canonical(value); demand(len(raw) <= MAX_RESULT, "result_cap", "Result metadata exceeds1MiB")
    directory(Path(path).parent)
    with Path(path).open("xb") as f:
        demand(f.write(raw) == len(raw), "short_write", "Result incomplete")
        f.flush(); os.fsync(f.fileno())
    demand(ordinary_file(path, MAX_RESULT)["sha256"] == hashlib.sha256(raw).hexdigest(), "readback", "Result fsync/readback differs")


def execute_job(job):
    """Actual private execution only inside reviewed immutable Docker image."""
    validate_job(job)
    demand(sys.platform == "linux" and sys.flags.isolated == 1 and sys.dont_write_bytecode, "private_interpreter", "Private isolated -I -B Linux interpreter required")
    demand(sys.executable == job["pythonPath"] and sys.version.split()[0] == job["pythonVersion"]
           and ordinary_file(sys.executable, MAX_FILE)["sha256"] == job["pythonSha256"], "private_interpreter", "Actual fixed sealed Python differs")
    demand(ordinary_file(__file__, MAX_FILE)["sha256"] == job["runnerSourceSha256"], "runner_source", "Trusted baked runner source differs")
    before = verify_inputs(job)
    versions = {k: importlib.metadata.version(k) for k in DEPENDENCIES}
    demand(versions == DEPENDENCIES, "dependencies", "Actual complete direct dependency versions differ")
    if job["taskId"] == "court-form-filling":
        binary = job["pdftotext"] or {}
        demand(binary.get("path") == "/usr/bin/pdftotext" and ordinary_file(binary["path"], MAX_FILE)["sha256"] == binary.get("sha256"),
               "trusted_binary", "Fixed readonly pdftotext bytes differ")
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "VIRTUAL_ENV"):
        os.environ.pop(key, None)
    os.environ["PATH"] = "/opt/objrun-verifier/bin:/usr/bin:/bin"
    os.environ["PYTHONNOUSERSITE"] = "1"; os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    directory("/verifier"); directory("/logs/verifier")
    # Original packages/tests are unchanged; this new explicit wrapper replaces
    # network installation and cwd/plugin discovery, never fakes those commands.
    config = Path("/verifier/objrun-empty.ini")
    with config.open("x", encoding="utf-8") as f: f.write("[pytest]\n"); f.flush(); os.fsync(f.fileno())
    import pytest  # only the sealed read-only private environment
    entries = [x for x in importlib.metadata.distribution("pytest-json-ctrf").entry_points if x.group == "pytest11"]
    demand(len(entries) == 1, "plugin", "Exact trusted CTRF entrypoint missing/ambiguous")
    plugin = entries[0].load()

    class Witness:
        def __init__(self): self.nodes=[]; self.reports=[]; self.collection_errors=[]
        def pytest_collection_finish(self, session): self.nodes=[x.nodeid for x in session.items]
        def pytest_collectreport(self, report):
            if report.failed: self.collection_errors.append({"nodeId":report.nodeid,"outcome":"failed"})
        def pytest_runtest_logreport(self, report):
            self.reports.append({"nodeId":report.nodeid,"phase":report.when,"outcome":report.outcome})

    witness = Witness(); started = time.monotonic()
    args = ["-c", str(config), "--confcutdir=/verifier", "--ctrf", "/logs/verifier/ctrf.json", "/verifier/test_outputs.py", "-rA"]
    if job["taskId"] == "lab-unit-harmonization": args += ["-v", "--tb=short"]
    if job["mode"] == "collect": args += ["--collect-only", "-q"]
    result_code = int(pytest.main(args, plugins=[plugin, witness]))
    demand(before == verify_inputs(job), "source_drift", "Tests, public/hidden inputs or captured artifact changed")
    demand(0 < len(witness.nodes) <= 4096 and len(set(witness.nodes)) == len(witness.nodes) and not witness.collection_errors,
           "collection", "Actual private test collection missing/duplicated/errored")
    result = {"protocol": PROTOCOL, "taskId": job["taskId"], "mode": job["mode"], "taskDescriptorSha256":job["taskDescriptorSha256"],
              "runnerSourceSha256":job["runnerSourceSha256"], "pythonPath":sys.executable,"pythonVersion":sys.version.split()[0],
              "pythonSha256":job["pythonSha256"],"dependencies":versions,"ctrfEntryPoint":{"name":entries[0].name,"value":entries[0].value},
              "sourceInputsBefore":before,"sourceInputsAfter":verify_inputs(job),"nodeIds":witness.nodes,"reports":witness.reports,
              "pytestExitCode":result_code,"elapsedSeconds":time.monotonic()-started,"actualTestsExecuted":job["mode"]=="grade",
              "actualCollectionExecuted":True,"collectionErrors":witness.collection_errors,"scoreCertificate":False}
    if job["mode"] == "grade": result["evaluation"] = score_result(job, witness.nodes, witness.reports, result_code, witness.collection_errors)
    else:
        demand(result_code == 0 and not witness.reports, "collection", "Collection bootstrap executed tests or failed")
        result["evaluation"] = None
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True); parser.add_argument("--job-sha256", required=True)
    parser.add_argument("--output", type=Path, default=Path("/logs/verifier/private-result.json"))
    args=parser.parse_args()
    demand(args.job == Path("/verifier/job.json") and args.output == Path("/logs/verifier/private-result.json"), "path", "Exact trusted private paths required")
    raw=args.job.read_bytes();demand(len(raw)<=256*1024 and hashlib.sha256(raw).hexdigest()==args.job_sha256, "job_pin", "Complete fixed private job Pin required")
    result=execute_job(json.loads(raw));fresh_result(args.output,result)
    # Host retains full bounded raw evidence. Engine-facing feedback is filtered
    # by the caller; private tests/logs/fixtures are never sent as model input here.
    print(json.dumps({"protocol":PROTOCOL,"taskId":result["taskId"],"mode":result["mode"],"resultSha256":ordinary_file(args.output,MAX_RESULT)["sha256"]}))


if __name__ == "__main__": main()
