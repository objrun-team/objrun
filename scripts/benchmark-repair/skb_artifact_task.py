"""Source-bound ten-task descriptors. Inert imports and pure preparation only."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

REPO = Path(__file__).resolve().parents[2]
PROTOCOL = "skillsbench-data-task-descriptor-v1"
PUBLIC = REPO / "docs/repair-2026-10-08/skillsbench-ten-artifact-readonly-preflight/selection-v1/public-metadata.json"
PUBLIC_SHA = "6cab5bd04910a9a8e1cb5285c0d6ccd905a7e5b172af9b6373c3f711d61466ee"
SELECTION_SHA = "f4b8781fc636d67af17265bfffe41d9ff76195f4e9539d6cd37b5db6b29ee021"
TASK_IDS = ("3d-scan-calc", "citation-check", "court-form-filling", "dapt-intrusion-detection",
            "earthquake-plate-calculation", "econ-detrending-correlation", "jpg-ocr-stat", "lab-unit-harmonization",
            "offer-letter-generator", "pptx-reference-formatting")
MAX_ARTIFACT = 8 * 1024**2
REQUIREMENTS = {"pytest": "8.4.1", "pytest-json-ctrf": "0.3.5", "openpyxl": "3.1.5", "pypdf": "5.1.0",
                "python-docx": "1.1.2", "lxml": "5.3.0", "defusedxml": "0.7.1", "six": "1.17.0", "rapidfuzz": "3.14.3",
                "numpy": "1.26.4", "pandas": "2.2.2"}


class TaskFault(RuntimeError):
    def __init__(self, kind, detail):
        super().__init__(detail); self.kind = kind


def demand(value, kind, detail):
    if not value: raise TaskFault(kind, detail)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def pin(path):
    p = Path(path); a = p.lstat()
    demand(stat.S_ISREG(a.st_mode) and not getattr(a, "st_file_attributes", 0) & 0x400,
           "input_kind", "Source Pin requires an ordinary regular file")
    with p.open("rb") as f: sha = hashlib.file_digest(f, "sha256").hexdigest()
    b = p.lstat()
    demand((a.st_ino, a.st_size, a.st_mtime_ns) == (b.st_ino, b.st_size, b.st_mtime_ns), "input_race", "Pinned file changed")
    return {"path": str(p), "bytes": a.st_size, "sha256": sha}


def verify_pin(value, maximum=2*1024**2):
    demand(isinstance(value, dict) and set(value) == {"path", "bytes", "sha256"} and isinstance(value["path"], str)
           and type(value["bytes"]) is int and 0 <= value["bytes"] <= maximum and re.fullmatch("[0-9a-f]{64}", value["sha256"]),
           "pin", "Exact complete bounded Pin required")
    demand(pin(value["path"]) == value, "pin_drift", "Source/raw input Pin changed")
    return value


def read_json(value, maximum=2*1024**2):
    verify_pin(value, maximum)
    raw = Path(value["path"]).read_bytes()
    demand(hashlib.sha256(raw).hexdigest() == value["sha256"], "pin_drift", "Input changed before parse")
    data = json.loads(raw); verify_pin(value, maximum)
    return data


def public_metadata():
    p = pin(PUBLIC); demand(p["sha256"] == PUBLIC_SHA, "public_source", "Exact reviewed public metadata changed")
    value = read_json(p)
    demand(value.get("protocol") == "skillsbench-ten-artifact-readonly-preflight-v1" and value.get("sourceBeforeAfterEqual") is True
           and tuple(x["taskId"] for x in value["tasks"]) == TASK_IDS, "public_source", "Wrong fixed ten-task public source set")
    selection = value["selectionManifestPin"]; verify_pin(selection)
    demand(selection["sha256"] == SELECTION_SHA, "selection", "Fixed U/F list changed")
    return value


def metadata(task_id):
    demand(task_id in TASK_IDS, "task_id", "Task outside fixed paired ten-task list")
    return next(x for x in public_metadata()["tasks"] if x["taskId"] == task_id)


def read_prompt(task_id):
    row = metadata(task_id); p = row["taskSourcePin"]; verify_pin(p)
    raw = Path(p["path"]).read_bytes()
    parts = re.split(rb"(?m)^---[ \t]*\r?\n", raw, maxsplit=2)
    demand(len(parts) == 3 and not parts[0] and len(parts[2]) == row["promptBytes"]
           and hashlib.sha256(parts[2]).hexdigest() == row["promptSha256"], "prompt", "Original exact prompt body changed")
    verify_pin(p); return parts[2].decode("utf-8", errors="strict")


def original_sources(task_id):
    row = metadata(task_id); root = Path(row["taskSourcePin"]["path"]).parent
    result = [row["taskSourcePin"]]
    for scope in ("environmentSource", "verifierSource", "oracleSourceMetadata"):
        for item in row[scope]["files"]:
            p = Path(row[scope]["root"]) / item["path"]
            result.append({"path": str(p), "bytes": item["bytes"], "sha256": item["sha256"]})
    for item in result: verify_pin(item, 64*1024**2)
    return result


def descriptor(task_id, candidate_image_proof_pin=None, private_runtime_proof_pin=None, collection_proof_pin=None):
    row = metadata(task_id); root = Path(row["taskSourcePin"]["path"]).parent
    resource = row["originalResources"]
    verifier_files = [{"sourcePin": {"path": str(root / "verifier" / x["path"]), "bytes": x["bytes"], "sha256": x["sha256"]},
                       "containerPath": "/verifier/" + x["path"], "role": "original-verifier"} for x in row["verifierSource"]["files"]]
    return {"protocol": PROTOCOL, "taskId": task_id, "sourceModulePin": pin(__file__),
            "publicMetadataPin": pin(PUBLIC), "selectionManifestPin": public_metadata()["selectionManifestPin"],
            "taskSourcePin": row["taskSourcePin"],
            "prompt": {"bodySha256": row["promptSha256"], "bodyBytes": row["promptBytes"], "extractionProtocol": "raw-yaml-frontmatter-body-v1"},
            "originalResources": resource,
            "environmentTreeIdentity": {k: row["environmentSource"][k] for k in ("protocol", "treeSha256", "fileCount", "fileBytes")},
            "verifierTreeIdentity": {k: row["verifierSource"][k] for k in ("protocol", "treeSha256", "fileCount", "fileBytes")},
            "oracleTreeIdentity": {k: row["oracleSourceMetadata"][k] for k in ("protocol", "treeSha256", "fileCount", "fileBytes")},
            "outputArtifacts": [{"containerPath": row["outputArtifacts"][0]["containerPath"], "format": row["format"], "regularOnly": True, "maximumBytes": MAX_ARTIFACT}],
            "artifactCapOrigin": "explicit new eight-MiB bounded artifact replay policy, not a limit stated in official task metadata; cold oracle must fit",
            "privatePublicFixturePins": row["privatePublicFixtures"], "verifierFilePins": verifier_files,
            "originalTestRunnerPin": row["verifierRunnerPin"],
            "rewardDomain": "fractional" if task_id == "lab-unit-harmonization" else "binary",
            "scoreRule": "original-three-decimal-passed-over-passed-plus-failed" if task_id == "lab-unit-harmonization" else "original-pytest-exit-binary",
            "solverWritableBudgetBytes": 256*1024**2 if task_id == "jpg-ocr-stat" else resource["environment"]["storage_mb"]*1024**2,
            "solverWritableBudgetOrigin": "existing JPG256MiB operational bound preserved" if task_id == "jpg-ocr-stat" else "original task10GiB storage metadata, sampled budget is not a kernel-quota certificate",
            "privateSharedRamBytes": 512*1024**2, "originalNetworkMode": "public", "privateNetworkMode": "none",
            "offlineRunnerProtocol": "sealed-offline-data-verifier-v1", "runnerSourcePin": pin(Path(__file__).with_name("skb_artifact_private_eval.py")),
            "candidateImageProofPin": candidate_image_proof_pin, "privateRuntimeProofPin": private_runtime_proof_pin,
            "expectedCollectionPin": collection_proof_pin,
            "preparedOnly": candidate_image_proof_pin is None or private_runtime_proof_pin is None or collection_proof_pin is None,
            "modelsExecuted": 0, "claimHistoricalEnvironment": False}


def validate_descriptor(value, require_ready=False):
    demand(isinstance(value, dict) and value.get("protocol") == PROTOCOL, "task_descriptor", "Wrong explicit multi-task descriptor")
    expected = descriptor(value.get("taskId"), value.get("candidateImageProofPin"), value.get("privateRuntimeProofPin"), value.get("expectedCollectionPin"))
    demand(value == expected, "task_descriptor", "Task descriptor/source/resources/artifact/score policy differs")
    original_sources(value["taskId"]); read_prompt(value["taskId"])
    if require_ready: validate_ready_graph(value)
    return value


def validate_ready_graph(value, require_collection=True):
    demand(value.get("candidateImageProofPin") is not None and value.get("privateRuntimeProofPin") is not None,
           "not_ready", "Actual built candidate image and sealed private runtime missing")
    if require_collection:
        demand(value.get("preparedOnly") is False, "not_ready", "Actual full collection proof missing")
    candidate = read_json(value["candidateImageProofPin"])
    private = read_json(value["privateRuntimeProofPin"])
    demand(candidate.get("protocol") == "skillsbench-fixed-task-image-v1" and candidate.get("taskId") == value["taskId"]
           and candidate.get("environmentTreeIdentity") == value["environmentTreeIdentity"] and candidate.get("taskSourcePin") == value["taskSourcePin"],
           "candidate_build", "Exact task build source graph differs")
    demand(re.fullmatch(r"sha256:[0-9a-f]{64}", candidate.get("imageId", "")) and candidate.get("sourceBeforeAfterEqual") is True,
           "candidate_build", "Actual immutable built image/source closure missing")
    # These are source-bound build/probe receipts, not a caller-provided ready flag.
    for name in ("imageInspectPin", "installedPackagesPin", "buildActorClosurePin"):
        verify_pin(candidate.get(name))
    actual_image = read_json(candidate["imageInspectPin"])
    demand(isinstance(actual_image, list) and len(actual_image) == 1 and actual_image[0].get("Id") == candidate["imageId"]
           and actual_image[0].get("Architecture") == "amd64" and actual_image[0].get("Os") == "linux",
           "candidate_build", "Immutable image/config metadata differs")
    demand(private.get("protocol") == "skillsbench-sealed-private-runtime-v1" and private.get("runnerSourcePin") == value["runnerSourcePin"]
           and private.get("pythonVersion") == "3.12.3" and private.get("pythonPath") == "/opt/objrun-verifier/bin/python"
           and re.fullmatch(r"sha256:[0-9a-f]{64}", private.get("imageId", ""))
           and re.fullmatch(r"[0-9a-f]{64}", private.get("pythonSha256", "")) and private.get("dependencies") == REQUIREMENTS,
           "private_runtime", "Fixed sealed offline Python/depot/source differs")
    for name in ("imageInspectPin", "wheelDepotManifestPin", "installedPackagesPin", "buildActorClosurePin"):
        verify_pin(private.get(name))
    image = read_json(private["imageInspectPin"])
    demand(isinstance(image, list) and len(image) == 1 and image[0].get("Id") == private["imageId"], "private_runtime", "Private immutable image substituted")
    if value["taskId"] == "court-form-filling":
        executable = private.get("pdftotext") or {}
        demand(executable.get("path") == "/usr/bin/pdftotext" and re.fullmatch("[0-9a-f]{64}", executable.get("sha256", ""))
               and isinstance(executable.get("version"), str) and executable["version"], "private_binary", "Fixed pdftotext required")
        verify_pin(executable.get("packageReceiptPin")); verify_pin(executable.get("elfDependencyManifestPin"))
    if not require_collection:
        return {"candidate": candidate, "private": private, "collection": None}
    collection = read_json(value["expectedCollectionPin"])
    demand(collection.get("protocol") == "skillsbench-private-collection-v1" and collection.get("taskId") == value["taskId"]
           and collection.get("verifierTreeIdentity") == value["verifierTreeIdentity"] and collection.get("runnerSourcePin") == value["runnerSourcePin"]
           and collection.get("privateRuntimeProofPin") == value["privateRuntimeProofPin"], "collection", "Actual source/runtime collection graph differs")
    nodes = collection.get("nodeIds")
    demand(isinstance(nodes, list) and nodes and len(nodes) <= 4096 and all(isinstance(x, str) and 0 < len(x) <= 1024 for x in nodes)
           and len(set(nodes)) == len(nodes), "collection", "Complete duplicate-free actual collected node IDs required")
    verify_pin(collection.get("rawResultPin")); verify_pin(collection.get("ownedClosurePin"))
    return {"candidate": candidate, "private": private, "collection": collection}


def private_job(value, inputs, mode="grade"):
    demand(mode in ("grade", "collect"), "mode", "Only private grade or actual collection")
    validate_descriptor(value)
    graph = validate_ready_graph(value, mode == "grade")
    private, collection = graph["private"], graph["collection"]
    return {"protocol": "skillsbench-private-offline-job-v1", "taskId": value["taskId"], "mode": mode,
            "taskDescriptorSha256": hashlib.sha256(canonical(value)).hexdigest(), "runnerSourceSha256": value["runnerSourcePin"]["sha256"],
            "pythonPath": private["pythonPath"], "pythonSha256": private["pythonSha256"], "pythonVersion": private["pythonVersion"],
            "dependencies": REQUIREMENTS, "inputs": inputs, "expectedNodeIds": collection["nodeIds"] if collection else None,
            "outputArtifactPath": value["outputArtifacts"][0]["containerPath"], "scoreRule": value["scoreRule"],
            "pdftotext": private.get("pdftotext"), "memoryBytes": value["originalResources"]["environment"]["memory_mb"]*1024**2,
            "timeoutSec": value["originalResources"]["verifier"]["timeout_sec"]}

