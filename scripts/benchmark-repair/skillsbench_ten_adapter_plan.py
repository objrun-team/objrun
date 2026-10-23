"""Emit a fresh F-only source-bound plan; never build, download, or grade."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/repair-2026-10-08/skillsbench-ten-artifact-readonly-preflight/selection-v1"


def pin(p: Path) -> dict:
    b = p.read_bytes()
    return {"path": str(p), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}


def fresh(p: Path, value: object) -> dict:
    b = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    with p.open("xb") as f:
        f.write(b); f.flush(); os.fsync(f.fileno())
    actual = pin(p)
    if actual["sha256"] != hashlib.sha256(b).hexdigest():
        raise ValueError("F readback mismatch")
    return actual


def main() -> None:
    public_pin = pin(DIRECTORY / "public-metadata.json")
    public = json.loads(Path(public_pin["path"]).read_bytes())
    selection_pin = public["selectionManifestPin"]
    if pin(Path(selection_pin["path"])) != selection_pin:
        raise ValueError("Task selection drift")
    source = ROOT / "scripts/benchmark-repair"
    frozen_expected = {
        "jpg_d_storage_profile.py": "0d0b20832d60248605a3e0314aa5e029091c536dc6f80e3bccf5623da1f18c17",
        "jpg_private_ram_profile.py": "00a9f978b9e2ae90d912a7bd48bc522107c6c0db50a6a6c91df5b800df122ee3",
        "jpg_private_ram_executor.py": "c00404ce4700a1702572f1960877ca7ff178b12dd35e01ead356064d469a5e59",
        "jpg-d-storage-profile.ts": "afbfb9d71fcc0652acb96bbfe72c05c8ae9889821127a1bceab158fbd202c7cc",
    }
    frozen_pins = {name: pin(source / name) for name in frozen_expected}
    if any(frozen_pins[name]["sha256"] != sha for name, sha in frozen_expected.items()):
        raise ValueError("Protected JPG source drift")
    bases = {
        "ubuntu:24.04": {"cachedImageId": "sha256:6232b38791000e3818b58d8847b5a8f5612d606929e01156dd8febc423e0f2ef", "derivedFrom": "ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3", "variant": "fixed-digest reconstruction of a mutable Ubuntu tag"},
        "python:3.12-slim": {"cachedImageId": "sha256:688a685f6a1fa9250d7c6cee916889cbca364e4b027520110e0fce80c64a13e0", "derivedFrom": "python@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7", "variant": "explicit Python3.12.11-slim-bookworm reconstruction; original dynamic tag identity unknown"},
    }
    build_plans = []
    for task in public["tasks"]:
        if task["taskId"] == "jpg-ocr-stat":
            continue
        old = task["dockerfilePin"]
        if pin(Path(old["path"])) != old:
            raise ValueError("Original Dockerfile drift")
        data = Path(old["path"]).read_bytes()
        text = data.decode("utf-8")
        original = task["originalBaseRefs"]
        if len(original) != 1 or original[0] not in bases:
            raise ValueError("Unreviewed Docker base")
        base = bases[original[0]]
        derived, count = re.subn(r"(?m)^FROM[ \t]+" + re.escape(original[0]) + r"[ \t]*\r?$", "FROM " + base["derivedFrom"], text)
        if count != 1:
            raise ValueError("Expected exactly one FROM replacement")
        destination = DIRECTORY / "solver-build-plans" / task["taskId"] / "Dockerfile.fixed-base"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as f:
            f.write(derived.encode("utf-8")); f.flush(); os.fsync(f.fileno())
        build_plans.append({"taskId": task["taskId"], "protocol": "skillsbench-minimal-fixed-base-rebuild-v1",
            "originalDockerfilePin": old, "derivedDockerfilePin": pin(destination), "onlyDockerfileChange": "one FROM base ref",
            "sourceContextRoot": task["environmentSource"]["root"], "sourceContextTree": {k: task["environmentSource"][k] for k in ("protocol", "treeSha256", "fileCount", "fileBytes")},
            "originalBaseRef": original[0], "fixedBase": base, "buildTimeoutSec": task["originalResources"]["environment"]["build_timeout_sec"],
            "originalRuntimeResources": task["originalResources"], "actualImageId": None, "actualBuildProofPin": None,
            "futureReceiptRequirements": ["actual fixed base ID before/after", "complete sourceContext SHA before/after", "derived Dockerfile SHA", "bounded stdout/stderr/monotonic elapsed", "actual image ID/config/labels", "all apt/pip installed package versions and source/depot hashes", "exact owned build actor lifecycle", "no Docker daemon cancellation assumption from CLI exit"],
            "imageBuilt": False})
    direct = {
        "pytest": "8.4.1", "pytest-json-ctrf": "0.3.5", "openpyxl": "3.1.5", "pypdf": "5.1.0",
        "python-docx": "1.1.2", "lxml": "5.3.0", "defusedxml": "0.7.1", "six": "1.17.0",
        "rapidfuzz": "3.14.3", "numpy": "1.26.4", "pandas": "2.2.2",
    }
    plan = {
        "protocol": "skillsbench-ten-private-depot-and-adapter-plan-v1", "recordedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "writerSourcePin": pin(Path(__file__)), "publicMetadataPin": public_pin, "selectionManifestPin": selection_pin,
        "protectedJpgSources": frozen_pins, "readOnlySourceIdentityVerified": True,
        "solverImagePlans": build_plans,
        "privateRuntimePlan": {
            "protocol": "sealed-offline-data-verifier-v1", "scope": "new grading reconstruction, not certification of historical verifier environments",
            "proposedBaseChoices": [bases["ubuntu:24.04"]["derivedFrom"], "sha256:92892771245d31d0b1af4a0c603effbdaf02bf62c1c055081f44a462f5261ced"],
            "oneChosenActualBaseRequired": True, "trustedBasePythonPath": "/usr/bin/python3.12", "expectedPythonVersion": "3.12.3", "actualPythonSha256": None,
            "venvLocation": "/opt/objrun-verifier", "venvBakedInReadOnlyImage": True, "directDependencies": direct,
            "originalVersionBoundary": "lab original pytest and ctrf were unpinned; above choices form explicit rebuilt protocol",
            "transitiveDependencies": None, "resolvedWheelPins": None, "depotFinalized": False,
            "dependencyResolutionReceipt": ["Linux amd64 / cp312 ABI and wheel compatibility", "all direct and transitive exact versions", "original published SHA when available and actual downloaded SHA", "source URL and byte count", "offline --require-hashes installation", "actual imported module locations and versions", "source before/after"],
            "oldJpgDepotBoundary": "Existing UV0.9.7 and exact 8-wheel depot may be reused only for covered packages; it is not a complete ten-task depot.",
            "courtExecutable": {"path": "/usr/bin/pdftotext", "actualSha256": None, "actualVersion": None, "packageReceiptPin": None, "elfDependencyPins": None,
                "call": "fixed verifier subprocess argv0=pdftotext, shell=False; only fixed readonly PATH, no candidate executable lookup"},
            "containerPolicy": {"readOnlyRootfs": True, "hostBinds": [], "network": "none", "sharedTmpfsBytes": 536870912, "actualCommonSuperblockProofRequired": True, "freshNamespaceProofPerGrade": True},
            "runtimeTimeCpuMemory": "exact per-task original CPU/RAM/verifier timeout; no generic JPG600s/4GB assumption",
            "actualImageId": None, "actualColdProofPin": None},
        "minimalAdapterInterface": {
            "TaskDescriptor": {
                "protocol": "skillsbench-data-task-descriptor-v1", "fields": [
                    "taskId", "selectionManifestPin", "taskSourcePin", "promptSha256", "environmentTreePin", "verifierTreePin", "oracleTreePin",
                    "originalResources", "candidateImageProofPin", "privateRuntimeProofPin", "depotPin", "trustedInterpreterPin", "trustedExecutablePins",
                    "outputArtifacts[{containerPath,format,regularOnly,maxBytes}]", "privatePublicFixturePins[{containerPath,sourcePin}]", "hiddenFixturePins",
                    "originalTestRunnerPin", "offlineRunnerPin", "expectedCollectionPin", "scoreRule", "operationalEnvelopePin"],
                "exactTenAllowlist": [t["taskId"] for t in public["tasks"]], "readinessMayNotBeOnlyBoolean": True},
            "capture_artifacts": {"signature": "capture_artifacts(taskDescriptorPin, exactStoppedSolverOwnerPin, freshOutputDirectory) -> CaptureReceiptPin",
                "requirements": ["exact immutable image/CID/role/task/nonce identity", "actual stopped state", "only declared output paths", "no directory or snapshot capture", "bounded daemon TAR; reject links/special/duplicates/traversal", "fsync then SHA/bytes readback", "typed absent/format/budget failure cannot be caller-forged empty"]},
            "grade_captured": {"signature": "grade_captured(taskDescriptorPin, captureReceiptPin, freshDOperationDirectory, phase) -> GradeReportPin",
                "phases": ["feedback", "final", "control"], "requirements": ["fixed private interpreter and source/depot before/after", "original verifier/fixtures immutable", "candidate files treated only as data", "one fresh owned RAM namespace with bounded logs", "exact per-task runtime limits", "no candidate shell/venv/config/plugin", "complete actual collection and node outcomes", "original reward semantics", "actual fsync and exact container/volume/lease cleanup graph"]},
            "validate_grade_report": {"signature": "validate_grade_report(taskDescriptorPin, GradeReportPin) -> typed owner/input/score graph",
                "returns": ["taskId", "capturePin", "sourcePins", "actualExpectedCollectionPin", "testResultPins", "originalReward", "collectionValidated", "containerIds", "volumeNames", "cliAndCommandChildPids", "leaseClosurePins", "operationOwnerPin"],
                "requiresSeparateParentActorClosure": True, "doesNotReleasePaidLock": True},
            "implementationBoundary": "One new shared adapter and descriptor data, not ten separate orchestration frameworks. Reuse frozen engine/six-tools/proxy/journal/cash; do not monkeypatch fixed JPG executor or import candidate code."},
        "runnerSemantics": {"originalTestsUnchanged": True, "originalTestShArchived": True, "networkInstallCommandsNotPretendedExecuted": True,
            "newRunnerSourceRequired": True, "fullActualCollectionRequired": True, "binaryTaskCount": 9,
            "fractionalTask": "lab-unit-harmonization", "fractionalRule": "round(passed/(passed+failed),3) from original shell; original binary fallback at zero total; collection validity independently required",
            "skipErrorExtraMissingNodesReject": True, "officialTaskPassedCertificateNotOnlyExitCode": True},
        "actualControlPlan": {"perTask": ["fresh absent/format capture", "source-pinned official oracle in separate solver container -> sealed artifact -> same private grader", "wrong/malformed regular artifact", "full collection and expected reward", "fixed interpreter/depot/executable identity", "source/raw/namespace/lease/container/volume/actors closed"],
            "noPreFilledOraclePass": True, "allTenRequiredBeforePairedPaid": True, "jpgOnlyPaidRejected": True,
            "actualDockerControlsExecuted": 0, "actualModelsExecuted": 0},
        "resourceBoundary": {"originalStorageMiBEach": 10240, "originalNetworkEach": "public", "DStoreCapBytes": 3221225472, "DMinimumFreeBytes": 3221225472,
            "DStoreCapIsEvidenceOnly": True, "originalJpgSolverCapBytes": 268435456, "notAutomaticallyOtherTaskSolverCap": True,
            "newTaskArtifactAndSolverCaps": "pending explicit source-bound operational envelope; must not silently substitute for original10GiB metadata",
            "FEnvelope": "background1GiB + sum remaining owned solver writable allowances + metadata; no unknown Docker VHD slack credit",
            "CEnvelope": "new D/TEMP writes profile with background1GiB; original C/F gates untouched"},
        "execution": {"networkCalls": 0, "DockerMutations": 0, "DOrEWrites": 0, "oracleExecutions": 0, "gradingExecutions": 0, "modelCalls": 0, "paidReady": False},
    }
    plan_pin = fresh(DIRECTORY / "private-depot-and-adapter-plan.json", plan)
    markdown_pin = pin(DIRECTORY / "private-depot-and-adapter-plan.md")
    if any(pin(source / name) != frozen_pins[name] for name in frozen_pins) or pin(Path(public_pin["path"])) != public_pin:
        raise ValueError("Protected inputs changed")
    record_pin = fresh(DIRECTORY / "delivery.json", {"protocol": "skillsbench-ten-public-preflight-delivery-v1", "sourceBeforeAfterEqual": True,
        "publicMetadataPin": public_pin, "selectionManifestPin": selection_pin, "planPin": plan_pin, "markdownPin": markdown_pin,
        "protectedSourcesUnchanged": frozen_pins, "execution": plan["execution"]})
    print(json.dumps({"planPin": plan_pin, "markdownPin": markdown_pin, "deliveryPin": record_pin, "solverBuildPlanCount": len(build_plans)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
