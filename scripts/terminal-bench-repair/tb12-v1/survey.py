"""Read-only source/image/resource survey for the fixed TB12 scope.

Writes only a new nonce directory under this benchmark's preparation folder.
Does not fetch credentials, contact a provider, pull/build/run/remove containers,
or change the shared paid lock or any other benchmark's state.
"""
import ctypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/repair-2026-10-08"
DOCKER = r"D:\Program\resources\bin\docker.exe"
PINS = {
    "scope": ("tb-multitask-twelve-scope-v1/task-scope.json", "79756c3601092682a9b19e733f84caebc4ab70d5bf3738faa1c1ce1e5ec6a729"),
    "images": ("tb-twelve-public-image-pulls-fd2e444e83ca407ebc1e172e10b16ac8/images.json", "f0f8e6419d55ff395725125a3c709d190368e494c1e2e33aa5b14fb238b0fc4b"),
    "probes": ("tb-twelve-immutable-image-probes-3b003ce040b14e869d7d4ecb699655ec/probes.json", "8735c1f0fac63a1b977b14685151e65cd80a4fd0d9b473b8a1b9d5e3a67cc816"),
    "depot": ("tb-multitask-offline-depot-v2/manifest.json", "c5d936affb8a132179daa0b0a59c2bb88b7db815cd4cf246b53b262c38e3be44"),
}


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while part := stream.read(1024 ** 2):
            h.update(part)
    return h.hexdigest()


class Memory(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ulong), ("loadPercent", ctypes.c_ulong)] + [(key, ctypes.c_ulonglong) for key in ("totalPhysical", "availablePhysical", "totalPageFile", "availablePageFile", "totalVirtual", "availableVirtual", "availableExtendedVirtual")]


def main():
    assert ROOT == Path(r"F:\git\TgEngin-handoff-2026-10-07\TgEngin")
    nonce = uuid.uuid4().hex
    out = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/observations" / nonce
    out.mkdir(parents=True, exist_ok=False)
    inputs = {}
    for key, (relative, expected) in PINS.items():
        path = DOC / relative
        assert sha(path) == expected, relative
        inputs[key] = json.loads(path.read_bytes())
    scope = inputs["scope"]
    assert len(scope["taskIds"]) == len(set(scope["taskIds"])) == 12
    source = scope["sourcePin"]
    assert Path(source["path"]).stat().st_size == source["bytes"] and sha(Path(source["path"])) == source["sha256"]
    input_files = []
    for task in scope["records"]:
        for key in ("publicInputs", "environmentSourcePins", "rubricSourcePins"):
            for pin in task[key]:
                path = Path(pin["path"])
                assert path.stat().st_size == pin["bytes"] and sha(path) == pin["sha256"], str(path)
                input_files.append(pin)
    depot_path = DOC / PINS["depot"][0]
    for asset in inputs["depot"]["assets"]:
        path = depot_path.parent / asset["path"]
        assert path.stat().st_size == asset["bytes"] and sha(path) == asset["sha256"], str(path)
    receipts = []

    def docker(label, args):
        argv = [DOCKER, "--host", "npipe:////./pipe/dockerDesktopLinuxEngine", *args]
        started = datetime.now(timezone.utc).isoformat()
        result = subprocess.run(argv, capture_output=True, timeout=60, check=False)
        stdout, stderr = out / (label + ".stdout.txt"), out / (label + ".stderr.txt")
        stdout.write_bytes(result.stdout)
        stderr.write_bytes(result.stderr)
        receipts.append({"label": label, "argv": argv, "startedAtUtc": started, "finishedAtUtc": datetime.now(timezone.utc).isoformat(), "exitCode": result.returncode, "stdout": str(stdout), "stdoutSha256": sha(stdout), "stderr": str(stderr), "stderrSha256": sha(stderr)})
        return result

    version_result = docker("version", ["version", "--format", "{{json .}}"])
    version = json.loads(version_result.stdout) if version_result.returncode == 0 else None
    records = []
    if version:
        for task in scope["records"]:
            row = next(value for value in inputs["images"]["records"] if value["taskId"] == task["taskId"])
            result = docker("image-" + task["taskId"], ["image", "inspect", row["immutableImageId"]])
            image = json.loads(result.stdout)[0] if result.returncode == 0 else None
            records.append({"taskId": task["taskId"], "expectedImageId": row["immutableImageId"], "observedImageId": image.get("Id") if image else None, "sameImage": bool(image and image["Id"] == row["immutableImageId"]), "repoDigests": image.get("RepoDigests") if image else None, "agentSeconds": task["agentSeconds"], "verifierSeconds": task["verifierSeconds"], "officialEnvironment": task["officialEnvironment"]})
        docker("running-actors", ["ps", "--no-trunc", "--format", "{{json .}}"])
    memory = Memory()
    memory.length = ctypes.sizeof(memory)
    assert ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))
    result = {"protocol": "tb12-readonly-preparation-survey-v1", "nonce": nonce, "observedAtUtc": datetime.now(timezone.utc).isoformat(), "projectRoot": str(ROOT), "sourcePinsVerified": len(input_files), "depotAssetsVerified": len(inputs["depot"]["assets"]), "depotVerifiedAssetBytes": sum(asset["bytes"] for asset in inputs["depot"]["assets"]), "taskIds": scope["taskIds"], "taskRecords": records, "dockerVersion": version, "receipts": receipts, "resources": {"disks": {drive: dict(zip(("total", "used", "free"), shutil.disk_usage(drive))) for drive in ("C:/", "D:/", "F:/")}, "memory": {key: getattr(memory, key) for key in ("totalPhysical", "availablePhysical", "loadPercent")}}, "sharedPaidLockPresent": (ROOT / ".phase1-data/owned-paid-campaign.lock.json").exists(), "newModelCalls": 0, "dockerMutations": 0, "privateScorerReady": False, "newPaidRunAllowed": False}
    report = out / "survey.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report), "sourcePinsVerified": result["sourcePinsVerified"], "depotAssetsVerified": result["depotAssetsVerified"], "depotVerifiedAssetBytes": result["depotVerifiedAssetBytes"], "dockerReadSuccess": bool(version), "matchingImages": sum(row["sameImage"] for row in records), "resources": result["resources"], "newModelCalls": 0, "dockerMutations": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
