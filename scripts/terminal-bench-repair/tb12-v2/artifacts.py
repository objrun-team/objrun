"""Capture whitelisted regular data from paused, exactly owned candidates.

Docker's archive transport is read as data. No candidate Python/shell/parser is
run on the host or private checker. No tar extraction writes supplied paths.
"""
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import tarfile

from docker_owned import sha
from profiles import PROFILES


class ArtifactFault(RuntimeError):
    pass


def absent_file(receipt, path):
    text = Path(receipt["stderr"]["path"]).read_text(encoding="utf-8", errors="replace").lower()
    return receipt["exitCode"] != 0 and "could not find" in text and path.lower() in text


def capture_file(native, cid, path, maximum, folder):
    receipt = native.command(["cp", cid + ":" + path, "-"], timeout=300, stdout_limit=maximum + 1024 ** 2)
    if receipt["exitCode"] != 0:
        if absent_file(receipt, path):
            return {"path": path, "exists": False, "receipt": receipt}
        raise ArtifactFault("Archive transport failed for a whitelisted file")
    archive_path = Path(receipt["stdout"]["path"])
    with tarfile.open(archive_path, mode="r:") as archive:
        members = archive.getmembers()
        if len(members) != 1 or not members[0].isfile() or members[0].linkname:
            raise ArtifactFault("Only one regular non-link artifact is admitted")
        member = members[0]
        if PurePosixPath(member.name).name != PurePosixPath(path).name or not 0 <= member.size <= maximum:
            raise ArtifactFault("Artifact archive name/size mismatch")
        target = Path(folder) / path.lstrip("/")
        if not target.resolve().is_relative_to(Path(folder).resolve()):
            raise ArtifactFault("Artifact output escaped its owned capsule")
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.extractfile(member) as source, target.open("xb") as output:
            while part := source.read(1024 ** 2):
                output.write(part)
        if target.stat().st_size != member.size:
            raise ArtifactFault("Short artifact archive body")
        return {"path": path, "exists": True, "bytes": member.size, "sha256": sha(target), "originalMode": member.mode & 0o777, "originalMtime": member.mtime, "archiveName": member.name, "stored": str(target), "receipt": receipt}


def capture_directory_presence(native, cid, path):
    receipt = native.command(["cp", cid + ":" + path, "-"], timeout=60, stdout_limit=32 * 1024 ** 2)
    if receipt["exitCode"] != 0:
        if absent_file(receipt, path):
            return {"path": path, "exists": False, "receipt": receipt}
        raise ArtifactFault("Directory archive transport failed")
    with tarfile.open(Path(receipt["stdout"]["path"]), mode="r:") as archive:
        first = archive.next()
        if first is None or not first.isdir() or PurePosixPath(first.name).name != PurePosixPath(path).name:
            raise ArtifactFault("Whitelisted directory must be a regular directory")
    return {"path": path, "exists": True, "originalMode": first.mode & 0o777, "receipt": receipt}


def sealed_capsule(native, cid, task_id, folder):
    profile = PROFILES[task_id]
    if profile["kind"] == "live-nginx":
        raise ArtifactFault("Live nginx uses its separate narrow service interface")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    before = native.assert_actor(cid)
    pause = native.pause(cid) if not before["State"]["Paused"] else {"alreadyPaused": True, "observedState": before}
    paused = native.assert_actor(cid)
    if not paused["State"]["Paused"] or paused["Id"] != before["Id"]:
        raise ArtifactFault("Exact candidate pause not proven")
    files = []
    directories = []
    # On any failure the candidate stays paused until explicit owned cleanup.
    for path, maximum in profile["artifacts"].items():
        files.append(capture_file(native, cid, path, maximum, folder))
    for path in profile.get("directories", []):
        directories.append(capture_directory_presence(native, cid, path))
    result = {"protocol": "tb12-sealed-data-capsule-v1", "taskId": task_id, "sourceCid": cid, "capturedAtUtc": datetime.now(timezone.utc).isoformat(), "initialActorState": before, "pauseReceipt": pause, "pausedActorState": paused, "files": files, "directories": directories, "candidateCodeExecutedInPrivateChecker": False}
    target = folder / "capsule.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result, target


def stage_checker_image(native, private_base, task, context_directory, capsule, config, output):
    """Build a passive data layer; only trusted mkdir/chmod execute in builder."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    cid, initial, create = native.create("snapshot-builder", private_base, "/bin/sh", ["-c", "sleep 3600"], network="none")
    native.start(cid)
    checker_source = Path(__file__).parent / "private_checker.py"
    checker_copy = output / "private_checker.py"
    checker_copy.write_bytes(checker_source.read_bytes())
    config["checkerSourceSha256"] = sha(checker_copy)
    native.upload(checker_copy, cid, "/opt/tb12/checker/private_checker.py")
    # Remove the base image's public task files before adding this capsule.
    # Exact fixed paths only; no candidate-provided path is used here.
    for path in PROFILES[task["taskId"]]["artifacts"]:
        native.execute(cid, ["/bin/rm", "-f", "--", path])
    for path in PROFILES[task["taskId"]].get("directories", []):
        native.execute(cid, ["/bin/rm", "-rf", "--", path])
    private_tests = Path(context_directory) / "tasks" / task["taskId"] / "tests"
    native.upload(private_tests, cid, "/tests")
    private_inputs = Path(context_directory) / "tasks" / task["taskId"] / "inputs"
    if private_inputs.is_dir():
        native.upload(private_inputs, cid, "/inputs")
    for directory in capsule.get("directories", []):
        if directory["exists"]:
            native.execute(cid, ["/bin/mkdir", "-p", directory["path"]])
    for item in capsule["files"]:
        if not item["exists"]:
            continue
        parent = str(PurePosixPath(item["path"]).parent)
        native.execute(cid, ["/bin/mkdir", "-p", parent])
        native.upload(item["stored"], cid, item["path"])
        native.execute(cid, ["/bin/chmod", f"{item['originalMode']:04o}", item["path"]])
    config_path = output / "checker-config.json"
    config_path.write_text(json.dumps(config, separators=(",", ":")), encoding="utf-8")
    native.upload(config_path, cid, "/opt/tb12/checker-config.json")
    if task["taskId"] == "nginx-request-logging":
        native.upload(config["nginxAdapterSource"], cid, "/opt/checker/lib/python3.13/site-packages/nginx_client.py")
        native.upload(config["nginxBrokerCaDirectory"], cid, "/isolation")
    if task["taskId"] == "openssl-selfsigned-cert":
        worker_path = output / "worker-result.json"
        worker_path.write_text(json.dumps(config["untrustedWorkerResult"], separators=(",", ":")), encoding="utf-8")
        native.upload(worker_path, cid, "/opt/tb12/worker-result.json")
    stopped = native.stop(cid)
    image, commit = native.commit(cid, "snapshot-checker")
    removal, absence = native.remove(cid)
    return image, {"builderCid": cid, "initialState": initial, "createReceipt": create, "stopReceipt": stopped, "commitReceipt": commit, "removalReceipt": removal, "absenceReceipt": absence}
