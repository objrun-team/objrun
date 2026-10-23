"""F-only public source inventory; no task, verifier, oracle, or Docker execution."""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat


ROOT = Path(__file__).resolve().parents[2]
TASKS_ROOT = ROOT / ".phase1-data/skillsbench/vendor/skillsbench/tasks"
OUT = ROOT / "docs/repair-2026-10-08/skillsbench-ten-artifact-readonly-preflight/selection-v1"
SELECTED = {
    "3d-scan-calc": {
        "format": "JSON", "output": "/root/mass_report.json",
        "inputs": [("environment/scan_data.stl", "/root/scan_data.stl")],
        "reason": "Small static mesh calculation and a JSON report; only data parsing in verifier.",
    },
    "citation-check": {
        "format": "JSON", "output": "/root/answer.json", "inputs": [],
        "reason": "Bibliography validation with a JSON output; private verifier is offline data validation.",
    },
    "dapt-intrusion-detection": {
        "format": "CSV", "output": "/root/network_stats.csv",
        "inputs": [("environment/packets.pcap", "/root/packets.pcap")],
        "reason": "Packet statistics to CSV; one additional public PCAP fixture, no candidate execution.",
    },
    "econ-detrending-correlation": {
        "format": "TXT", "output": "/root/answer.txt", "inputs": [],
        "reason": "Spreadsheet inputs produce a small text result; private tests read the output as data.",
    },
    "court-form-filling": {
        "format": "PDF", "output": "/root/sc100-filled.pdf",
        "inputs": [("environment/sc100-blank.pdf", "/root/sc100-blank.pdf")],
        "reason": "PDF form fields and text; fixed trusted pdftotext is the only verifier subprocess.",
    },
    "offer-letter-generator": {
        "format": "DOCX", "output": "/root/offer_letter_filled.docx",
        "inputs": [("environment/employee_data.json", "/root/employee_data.json")],
        "reason": "DOCX template completion; fixed public employee data, python-docx only.",
    },
    "pptx-reference-formatting": {
        "format": "PPTX", "output": "/root/Awesome-Agent-Papers_processed.pptx",
        "inputs": [("environment/Awesome-Agent-Papers.pptx", "/root/Awesome-Agent-Papers.pptx")],
        "reason": "PPTX ZIP/XML changes relative to a pinned public reference; no candidate code execution.",
    },
    "jpg-ocr-stat": {
        "format": "XLSX", "output": "/app/workspace/stat_ocr.xlsx", "inputs": [],
        "reason": "Existing cached complete task image and the separately frozen JPG RAM foundation.",
    },
    "lab-unit-harmonization": {
        "format": "CSV", "output": "/root/ckd_lab_data_harmonized.csv", "inputs": [],
        "reason": "Second CSV path exercises pandas and a fractional reward; two public input CSVs exist.",
    },
    "earthquake-plate-calculation": {
        "format": "JSON", "output": "/root/answer.json", "inputs": [],
        "reason": "Geospatial JSON inputs and JSON output; private tests do not execute the candidate.",
    },
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def ordinary(path: Path, directory: bool = False) -> os.stat_result:
    info = path.lstat()
    if info.st_file_attributes & 0x400 or stat.S_ISLNK(info.st_mode):
        raise ValueError(f"Unexpected reparse/symlink: {path}")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError(f"Unexpected file kind: {path}")
    return info


def pin(path: Path) -> dict:
    info = ordinary(path)
    data = path.read_bytes()
    after = ordinary(path)
    if (info.st_size, info.st_mtime_ns, info.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError(f"Source changed during read: {path}")
    return {"path": str(path), "bytes": len(data), "sha256": digest(data)}


def tree(path: Path) -> dict:
    ordinary(path, True)
    files, directories, identities = [], [], []
    pending = [path]
    while pending:
        current = pending.pop()
        for entry in sorted(os.scandir(current), key=lambda x: x.name):
            child = Path(entry.path)
            info = child.lstat()
            rel = child.relative_to(path).as_posix()
            if info.st_file_attributes & 0x400 or stat.S_ISLNK(info.st_mode):
                raise ValueError(f"Unexpected source reparse: {child}")
            identities.append([rel, info.st_size, info.st_mtime_ns, info.st_ino, info.st_mode])
            if stat.S_ISDIR(info.st_mode):
                directories.append(rel)
                pending.append(child)
            elif stat.S_ISREG(info.st_mode):
                p = pin(child)
                files.append({"path": rel, "bytes": p["bytes"], "sha256": p["sha256"]})
            else:
                raise ValueError(f"Unexpected source member: {child}")
    files.sort(key=lambda x: x["path"])
    directories.sort()
    identities.sort()
    value = {"files": files, "directories": directories}
    return {
        "protocol": "ordered-ordinary-source-tree-v1",
        "root": str(path), "fileCount": len(files), "fileBytes": sum(x["bytes"] for x in files),
        "treeSha256": digest(canonical(value)), "identitySha256": digest(canonical(identities)),
        **value,
    }


def resource_blocks(text: str) -> tuple[dict, str, str]:
    parts = re.split(r"(?m)^---[ \t]*\r?\n", text, maxsplit=2)
    if len(parts) != 3 or parts[0]:
        raise ValueError("Expected task frontmatter delimiters")
    parsed, section, stack = {}, None, []
    blocks = []
    for line in parts[1].splitlines(keepends=True):
        m = re.match(r"^(\w+):\s*(.*?)\s*$", line)
        if m:
            section = m[1] if m[1] in {"verifier", "agent", "environment"} else None
            stack = []
            if section:
                if m[2]:
                    raise ValueError("Unexpected inline resource section")
                parsed[section] = {}
                blocks.append(line)
            continue
        if not section:
            continue
        blocks.append(line)
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^( +)(\w+):\s*(.*?)\s*$", line)
        if not m or len(m[1]) not in (2, 4):
            raise ValueError(f"Unsupported resource line {line!r}")
        indent, key, literal = len(m[1]), m[2], m[3]
        while stack and stack[-1][0] >= indent:
            stack.pop()
        target = stack[-1][1] if stack else parsed[section]
        if not literal:
            target[key] = {}
            stack.append((indent, target[key]))
        elif literal in {"true", "false"}:
            target[key] = literal == "true"
        elif re.fullmatch(r"\d+(?:\.0)?", literal):
            target[key] = int(float(literal))
        else:
            target[key] = literal
    expected = {"verifier", "agent", "environment"}
    if set(parsed) != expected:
        raise ValueError("Missing original resource section")
    return parsed, "".join(blocks), parts[2]


def ast_metadata(path: Path) -> dict:
    source = path.read_bytes().decode("utf-8")
    syntax = ast.parse(source)
    imports, tests, executions, reads = set(), set(), [], set()
    for n in ast.walk(syntax):
        if isinstance(n, ast.Import):
            imports.update(x.name for x in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            imports.add(n.module)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):
            tests.add(n.name)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            if n.value.startswith(("/root/", "/app/", "/verifier/")) and "\n" not in n.value and len(n.value) < 240:
                reads.add(n.value)
        elif isinstance(n, ast.Call):
            name = ast.unparse(n.func)
            if name in {"exec", "eval", "compile", "os.system", "os.popen", "subprocess.run", "subprocess.Popen", "subprocess.check_output", "subprocess.check_call", "subprocess.call"}:
                argv0 = None
                if n.args and isinstance(n.args[0], (ast.List, ast.Tuple)) and n.args[0].elts:
                    first = n.args[0].elts[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        argv0 = first.value
                executions.append({"function": name, "line": n.lineno, "literalArgv0": argv0,
                    "shellTrue": any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in n.keywords)})
    return {"imports": sorted(imports), "testFunctionNames": sorted(tests),
            "absolutePathLiterals": sorted(reads), "executionCalls": executions,
            "staticOnly": True, "actualPytestCollectionValidated": False}


def write_fresh(path: Path, data: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve().is_relative_to(OUT.resolve()) is False:
        raise ValueError("Output outside exact report directory")
    with path.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    actual = pin(path)
    if actual["bytes"] != len(data) or actual["sha256"] != digest(data):
        raise ValueError("F report readback mismatch")
    return actual


def main() -> None:
    if OUT.exists():
        raise ValueError("Immutable report output already exists; select a new reviewed revision")
    ordinary(ROOT, True)
    ordinary(TASKS_ROOT, True)
    names = sorted(SELECTED)
    if len(names) != 10 or len(set(names)) != 10:
        raise ValueError("Expected ten distinct public task IDs")
    rows, source_before = [], {}
    source_file = ROOT / ".phase1-data/skillsbench/source.json"
    source_pin = pin(source_file)
    provenance = json.loads(source_file.read_bytes())
    inventory_pin = pin(ROOT / "docs/repair-2026-10-08/skillsbench-ten-artifact-readonly-preflight/inventory.json")
    cache_pin = pin(ROOT / "docs/repair-2026-10-08/skillsbench-ten-artifact-readonly-preflight/cached-images.json")
    cache = json.loads(Path(cache_pin["path"]).read_bytes())
    for task_id in names:
        task = TASKS_ROOT / task_id
        before = tree(task)
        source_before[task_id] = before
        env = tree(task / "environment")
        verifier = tree(task / "verifier")
        oracle = tree(task / "oracle")
        task_pin = pin(task / "task.md")
        resources, original_resource_block, prompt = resource_blocks((task / "task.md").read_bytes().decode("utf-8"))
        if resources["verifier"].get("hardening", {}).get("cleanup_conftests") is not True:
            raise ValueError("Unexpected original conftest hardening")
        docker_pin, shell_pin = pin(task / "environment/Dockerfile"), pin(task / "verifier/test.sh")
        docker_text = (task / "environment/Dockerfile").read_bytes().decode("utf-8")
        shell_text = (task / "verifier/test.sh").read_bytes().decode("utf-8")
        output = SELECTED[task_id]["output"]
        analyses = {x["path"]: ast_metadata(task / "verifier" / x["path"]) for x in verifier["files"] if x["path"].endswith(".py")}
        execution_calls = [x for a in analyses.values() for x in a["executionCalls"]]
        if execution_calls and not (task_id == "court-form-filling" and len(execution_calls) == 1 and execution_calls[0]["literalArgv0"] == "pdftotext" and not execution_calls[0]["shellTrue"]):
            raise ValueError(f"Unreviewed verifier execution: {task_id}")
        fixtures = [{"sourcePin": pin(task / rel), "containerPath": destination, "role": "source-pinned public fixture; never candidate file"}
                    for rel, destination in SELECTED[task_id]["inputs"]]
        task_images = [x for x in cache["images"] if x.get("TaskLabels", {}).get("objrun.skb.task-id") == task_id]
        row = {
            "taskId": task_id, "format": SELECTED[task_id]["format"], "selectionReason": SELECTED[task_id]["reason"],
            "taskSourcePin": task_pin, "promptBytes": len(prompt.encode("utf-8")), "promptSha256": digest(prompt.encode("utf-8")),
            "originalResources": resources, "originalResourceBlockSha256": digest(original_resource_block.encode("utf-8")),
            "originalResourceBlock": original_resource_block,
            "dockerfilePin": docker_pin, "verifierRunnerPin": shell_pin,
            "environmentSource": env, "verifierSource": verifier, "oracleSourceMetadata": oracle,
            "taskSourceIdentity": {k: before[k] for k in ("protocol", "fileCount", "fileBytes", "treeSha256", "identitySha256")},
            "staticVerifierMetadata": analyses,
            "outputArtifacts": [{"containerPath": output, "format": SELECTED[task_id]["format"], "acceptedKind": "regular-only", "maxBytes": None, "maxBytesStatus": "pending task-specific operational envelope; original metadata gives only total storage"}],
            "privatePublicFixtures": fixtures, "hiddenFixtures": [x for x in verifier["files"] if not x["path"].endswith((".py", ".sh"))],
            "originalBaseRefs": re.findall(r"(?mi)^FROM\s+(\S+)", docker_text),
            "originalDockerExactPackageTokens": sorted(set(re.findall(r"(?<![\w.-])([A-Za-z][A-Za-z0-9_.-]*==[0-9][A-Za-z0-9_.-]*)", docker_text))),
            "originalVerifierExactPackageTokens": sorted(set(re.findall(r"(?<![\w.-])([A-Za-z][A-Za-z0-9_.-]*==[0-9][A-Za-z0-9_.-]*)", shell_text))),
            "originalRunnerHasRuntimeInstall": any(token in shell_text for token in ("apt-get ", "pip install ", "pip3 install ", "curl -LsSf")),
            "rewardSemantics": "original fractional three-decimal passed/(passed+failed), binary fallback when total zero; requires independent actual result-set validation" if task_id == "lab-unit-harmonization" else "original binary reward from pytest exit status; requires complete expected result-set validation",
            "cachedCompleteTaskImages": task_images,
            "readiness": {"publicSourcesPresent": True, "actualBuiltImagePinned": task_id == "jpg-ocr-stat", "newPrivateAdapterImplemented": task_id == "jpg-ocr-stat", "newPrivateColdValidated": False, "actualOracleControlsValidated": False, "paidReady": False},
        }
        # Only small trusted code/prompt copies, never public datasets or hidden answer workbooks.
        snapshots = []
        paths = [task / "task.md", task / "environment/Dockerfile"] + [task / "verifier" / x["path"] for x in verifier["files"] if x["path"].endswith((".py", ".sh"))]
        for p in paths:
            snapshots.append(write_fresh(OUT / "source-snapshots" / task_id / p.relative_to(task), p.read_bytes()))
        row["smallSourceSnapshotPins"] = snapshots
        rows.append(row)
    if sum(x["bytes"] for r in rows for x in r["smallSourceSnapshotPins"]) > 2 * 1024 * 1024:
        raise ValueError("Unexpected code-only snapshot size")
    source_after = {task_id: tree(TASKS_ROOT / task_id) for task_id in names}
    if source_before != source_after or source_pin != pin(source_file):
        raise ValueError("Original public sources changed during inventory")
    matrix = [{"taskId": r["taskId"], "promptSha256": r["promptSha256"], "taskSourceSha256": r["taskSourcePin"]["sha256"],
               "environmentTreeSha256": r["environmentSource"]["treeSha256"], "verifierTreeSha256": r["verifierSource"]["treeSha256"],
               "originalResources": r["originalResources"]} for r in rows]
    selection_pin = write_fresh(OUT / "ten-task-list.json", canonical({"protocol": "skillsbench-ten-public-task-list-v1", "taskCount": 10, "methods": ["U", "F"], "sameOrderedListRequired": True, "tasks": matrix}) + b"\n")
    report = {
        "protocol": "skillsbench-ten-artifact-readonly-preflight-v1", "recordedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": provenance, "sourcePin": source_pin, "readerSourcePin": pin(Path(__file__)),
        "inventory87Pin": inventory_pin, "cacheObservationPin": cache_pin,
        "scope": {"taskCount": 10, "publicTaskCount": 87, "methods": ["U", "F"], "historyResultsRead": False, "modelCalls": 0, "DockerMutations": 0, "DockerCommandsInThisReader": 0, "DOrEWrites": 0, "networkCalls": 0, "oracleExecution": 0, "testExecution": 0, "scoresIssued": 0},
        "selectionManifestPin": selection_pin, "sourceBeforeAfterEqual": True, "taskSourceIdentities": {r["taskId"]: r["taskSourceIdentity"] for r in rows},
        "tasks": rows,
        "boundary": [
            "Ten task IDs are a proposed paired U/F pilot, not 87-task coverage or ten ready environments.",
            "Source tree hash uses an explicit new metadata protocol and is not the old JPG image environment-label hash.",
            "Only JPG has a cached complete task image; nine task images and their adapters/depot/cold controls remain pending.",
            "Original ubuntu:24.04 and python:3.12-slim plus apt repository resolutions are mutable; each rebuild must freeze original Dockerfile, derived FROM mapping, resulting image and installed package receipts, and declare the rebuild protocol.",
            "Cached python:3.12.11-slim-bookworm is a proposed pinned reconstruction variant, not proof that the original python:3.12-slim tag resolved to it.",
            "Original network_mode is public; a net-none private verifier is an explicit trusted grading variant. Any candidate network change must be separately declared.",
            "Every original task declares storage_mb=10240. D evidence cap=3GiB and the existing JPG solver256MiB overlay limit do not certify that official task workspace allowance.",
            "All original tests remain pinned. A new offline runner must be separately reviewed and prove full original test collection, exact dependency versions and original reward semantics; no fake install commands.",
            "Source-level AST execution scan is evidence for this frozen revision, not a runtime containment or parser safety certificate.",
        ],
    }
    report_pin = write_fresh(OUT / "public-metadata.json", json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")
    print(json.dumps({"reportPin": report_pin, "selectionManifestPin": selection_pin, "taskCount": len(rows), "originalSourcesUnchanged": True,
        "environmentBytes": {r["taskId"]: r["environmentSource"]["fileBytes"] for r in rows}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
