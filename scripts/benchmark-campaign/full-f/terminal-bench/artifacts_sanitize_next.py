"""Capture whitelisted regular data from paused, exactly owned candidates.

Docker's archive transport is read as data. No candidate Python/shell/parser is
run on the host or private checker. No tar extraction writes supplied paths.
"""
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import tarfile
import fnmatch

from docker_owned import sha
from profiles_sanitize_next import PROFILES


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


def capture_tree(native, cid, path, maximum, folder, maximum_entries=10000):
    """Capture an explicit passive directory; never extract tar-supplied paths."""
    receipt = native.command(["cp", cid + ":" + path, "-"], timeout=300, stdout_limit=maximum + 8 * 1024 ** 2)
    if receipt["exitCode"] != 0:
        if absent_file(receipt, path):
            return [], [{"path": path, "exists": False, "receipt": receipt}]
        raise ArtifactFault("Directory tree archive transport failed")
    files, directories, seen, total = [], [], set(), 0
    root = PurePosixPath(path)
    with tarfile.open(Path(receipt["stdout"]["path"]), mode="r:") as archive:
        members = archive.getmembers()
        if not members or len(members) > maximum_entries:
            raise ArtifactFault("Directory tree archive entry bound")
        first = members[0]
        if not first.isdir() or PurePosixPath(first.name).as_posix().rstrip("/") != root.name:
            raise ArtifactFault("Directory archive must start with exact root directory")
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or not name.parts or name.parts[0] != root.name:
                raise ArtifactFault("Directory archive path outside declared tree")
            if name in seen or member.linkname or not (member.isfile() or member.isdir()):
                raise ArtifactFault("Directory archive duplicate, link, or special file")
            seen.add(name)
            relative = PurePosixPath(*name.parts[1:])
            actual_path = str(root / relative)
            if member.isdir():
                directories.append({"path": actual_path, "exists": True, "originalMode": member.mode & 0o777, "receipt": receipt})
                continue
            if member.size < 0:
                raise ArtifactFault("Negative archive size")
            total += member.size
            if total > maximum:
                raise ArtifactFault("Directory archive total data bound")
            target = Path(folder) / actual_path.lstrip("/")
            if not target.resolve().is_relative_to(Path(folder).resolve()):
                raise ArtifactFault("Directory archive destination escaped capsule")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as output:
                while part := source.read(1024 ** 2):
                    output.write(part)
            if target.stat().st_size != member.size:
                raise ArtifactFault("Short directory archive body")
            files.append({"path": actual_path, "exists": True, "bytes": member.size, "sha256": sha(target),
                          "originalMode": member.mode & 0o777, "originalMtime": member.mtime,
                          "archiveName": member.name, "stored": str(target), "receipt": receipt})
    return files, directories


def capture_metadata_glob(native, cid, root_path, pattern, folder):
    """Exact path/name presence for tests that never read candidate C source."""
    receipt=native.command(['cp',cid+':'+root_path,'-'],timeout=300,stdout_limit=512*1024**2)
    if receipt['exitCode']!=0:raise ArtifactFault('Metadata directory archive transport failed')
    root=PurePosixPath(root_path);files=[];directories=[];seen=set()
    with tarfile.open(Path(receipt['stdout']['path']),mode='r:') as archive:
        for member in archive:
            name=PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0]!=root.name:
                raise ArtifactFault('Metadata archive path outside declared root')
            if len(name.parts)<2 or not fnmatch.fnmatchcase(name.parts[1],pattern):continue
            if name in seen or member.linkname or not(member.isdir() or member.isfile()):
                raise ArtifactFault('Metadata archive duplicate, link, or special file')
            seen.add(name)
            if len(seen)>10000:raise ArtifactFault('Metadata archive entry bound')
            path=str(root/PurePosixPath(*name.parts[1:]))
            if member.isdir():
                directories.append({'path':path,'exists':True,'originalMode':member.mode&0o777,'receipt':receipt})
            elif name.suffix=='.c' and len(name.parts)>=4 and name.parts[2]=='src':
                target=Path(folder)/path.lstrip('/')
                if not target.resolve().is_relative_to(Path(folder).resolve()):raise ArtifactFault('Metadata destination escaped capsule')
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'')
                files.append({'path':path,'exists':True,'bytes':0,'originalBytes':member.size,'sha256':sha(target),
                    'originalMode':member.mode&0o777,'stored':str(target),'metadataOnly':True,'receipt':receipt})
    return files,directories


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
    for path, maximum in profile.get("trees", {}).items():
        tree_files, tree_directories = capture_tree(native, cid, path, maximum, folder)
        files.extend(tree_files)
        directories.extend(tree_directories)
    for root,pattern in profile.get('metadataGlobs',{}).items():
        meta_files,meta_directories=capture_metadata_glob(native,cid,root,pattern,folder)
        files.extend(meta_files);directories.extend(meta_directories)
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
    checker_source = Path(__file__).parent / "private_checker_sanitize_next.py"
    checker_copy = output / "private_checker.py"
    checker_copy.write_bytes(checker_source.read_bytes())
    config["checkerSourceSha256"] = sha(checker_copy)
    native.execute(cid, ["/bin/mkdir", "-p", "/opt/tb12/checker"])
    native.upload(checker_copy, cid, "/opt/tb12/checker/private_checker.py")
    # Remove the base image's public task files before adding this capsule.
    # Exact fixed paths only; no candidate-provided path is used here.
    for path in PROFILES[task["taskId"]]["artifacts"]:
        native.execute(cid, ["/bin/rm", "-f", "--", path])
    for path in PROFILES[task["taskId"]].get("directories", []):
        native.execute(cid, ["/bin/rm", "-rf", "--", path])
    for path in PROFILES[task["taskId"]].get("trees", {}):
        assert path == '/app'
        native.execute(cid, ["/bin/sh", "-c", "find /app -mindepth 1 -maxdepth 1 -exec /bin/rm -rf -- {} +"])
    private_tests = Path(context_directory) / "tasks" / task["taskId"] / "tests"
    native.upload(private_tests, cid, "/tests")
    private_inputs = Path(context_directory) / "tasks" / task["taskId"] / "inputs"
    if private_inputs.is_dir():
        native.upload(private_inputs, cid, "/inputs")
    for entry in capsule['files']:
        assert entry['path'] in PROFILES[task['taskId']]['artifacts']
        if entry['exists']:
            source=Path(entry['stored']);assert not source.is_symlink() and sha(source)==entry['sha256']
            native.execute(cid,['/bin/mkdir','-p',str(Path(entry['path']).parent)])
            native.upload(source,cid,entry['path'])
    router_copy=output/'sanitize_private_router_next.py'
    router_copy.write_bytes((Path(__file__).parent/'sanitize_private_router_next.py').read_bytes())
    config['routerSourceSha256']=sha(router_copy)
    native.upload(router_copy,cid,
                  '/opt/tb12/checker/sanitize_private_router_next.py')
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
    if task['taskId']=='caffe-cifar-10':
        worker_path=output/'caffe-worker-result.json'
        worker_path.write_text(json.dumps(config['caffeWorkerResult'],separators=(',',':')),encoding='utf-8')
        native.upload(worker_path,cid,'/opt/tb12/caffe-worker-result.json')
    if task['taskId']=='build-pmars':
        worker_path=output/'pmars-worker-result.json'
        worker_path.write_text(json.dumps(config['pmarsWorkerResult'],separators=(',',':')),encoding='utf-8')
        native.upload(worker_path,cid,'/opt/tb12/pmars-worker-result.json')
    if task['taskId']=='build-pov-ray':
        worker_path=output/'povray-cli-result.json'
        worker_path.write_text(json.dumps(config['povrayCliResult'],separators=(',',':')),encoding='utf-8')
        native.upload(worker_path,cid,'/opt/tb12/povray-cli-result.json')
    if task['taskId']=='polyglot-c-py':
        worker_path=output/'polyglot-result.json'
        worker_path.write_text(json.dumps(config['polyglotResult'],separators=(',',':')),encoding='utf-8')
        native.upload(worker_path,cid,'/opt/tb12/polyglot-result.json')
    if task['taskId']=='polyglot-rust-c':
        worker_path=output/'rust-polyglot-result.json'
        worker_path.write_text(json.dumps(config['rustPolyglotResult'],separators=(',',':')),encoding='utf-8')
        native.upload(worker_path,cid,'/opt/tb12/rust-polyglot-result.json')
    if task['taskId']=='git-leak-recovery':
        worker_path=output/'git-leak-result.json'
        worker_path.write_text(json.dumps(config['gitLeakResult'],separators=(',',':')),encoding='utf-8')
        native.upload(worker_path,cid,'/opt/tb12/git-leak-result.json')
    if task['taskId']=='custom-memory-heap-crash':
        worker_path=output/'heap-result.json'
        worker_path.write_text(json.dumps(config['heapResult'],separators=(',',':')),encoding='utf-8')
        native.upload(worker_path,cid,'/opt/tb12/heap-result.json')
    if task['taskId']=='gpt2-codegolf':
        worker_path=output/'gpt2-result.json'
        worker_path.write_text(json.dumps(config['gpt2Result'],separators=(',',':')),encoding='utf-8')
        native.upload(worker_path,cid,'/opt/tb12/gpt2-result.json')
    if task['taskId'] in {'prove-plus-comm','rstan-to-pystan','winning-avg-corewars'}:
        worker_path=output/'fixed-cli-result.json'
        worker_path.write_text(json.dumps(config['fixedCliResult'],separators=(',',':')),encoding='utf-8')
        native.upload(worker_path,cid,'/opt/tb12/fixed-cli-result.json')
    stopped = native.pause(cid)
    image, commit = native.commit(cid, "snapshot-checker")
    removal, absence = native.remove(cid)
    return image, {"builderCid": cid, "initialState": initial, "createReceipt": create, "builderFreezeMethod":"pause", "pauseReceipt": stopped, "commitReceipt": commit, "removalReceipt": removal, "absenceReceipt": absence}
