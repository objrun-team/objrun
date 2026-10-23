"""One bounded original-instruction replay build; no image pull and no LLM.

The pinned JPG Dockerfile has only two dependency RUNs and one public COPY.
Replay them in one owned builder so its writable layer can be measured before
the final commit. APT uses an official-origin public cache; pip uses verified
official wheels. This is an explicitly seeded build profile, not a cold build.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("jpg_private_build", HERE / "software-jpg-private-grader.py")
GRADE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(GRADE)
ROOT, TASK = GRADE.ROOT, GRADE.TASK
DEFAULT_CACHE = Path("C:/Users/y1252/.codex/visualizations/2026/10/08/01a119ed-fdf7-7c32-b323-de9bab1290b6/project-cache/sku-jpg")
VHD = Path("F:/Docker/DockerDesktopWSL/disk/docker_data.vhdx")
PUBLIC_LIMIT, HOST_LIMIT = 160*1024*1024, 224*1024*1024
BUILD_LIMIT = 375*1024*1024
GROWTH_LIMIT = 1024*1024*1024
LAYOUT_INVALID_IMAGE = "sha256:a1886ce02bdbee6996a9804098717fb148a7a9a6851631ac2524e58117f0bc7c"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def allocated(path: Path) -> int:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    method = kernel.GetCompressedFileSizeW
    method.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    method.restype = ctypes.c_uint32
    high = ctypes.c_uint32()
    ctypes.set_last_error(0)
    low = method(str(path), ctypes.byref(high))
    if low == 0xffffffff and ctypes.get_last_error():
        raise GRADE.InvalidGrading("Cannot measure actual VHD allocated storage")
    return low + (high.value << 32)


def directory_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


class PublicCache:
    def __init__(self, root: Path, report: Path):
        self.root, self.report = root, report
        self.objects = root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.rows: dict[str, dict] = {}
        # Reuse the exact public signed snapshot from this repair's earlier
        # completed downloads, rather than silently re-resolving latest APT.
        for previous in sorted((ROOT / "docs/repair-2026-10-08").glob("software-jpg-build-*/public-artifacts.json")):
            for item in json.loads(previous.read_text(encoding="utf-8")).get("artifacts", []):
                if (self.objects / item["sha256"]).is_file():
                    self.rows[item["url"]] = {**item, "fromCache": True, "recordedPreviously": True}
        self.wire_bytes = 0
        self.semaphore = threading.Semaphore(2)
        self.server = None
        self.fault = None

    def boundaries(self) -> None:
        if sum(p.stat().st_size for p in self.objects.iterdir() if p.is_file() and not p.name.startswith("tmp-")) > PUBLIC_LIMIT or directory_bytes(self.root) > HOST_LIMIT:
            raise GRADE.InvalidGrading("Public or host dependency cache boundary reached")
        if shutil.disk_usage("C:/").free < GRADE.MIN_C_FREE or shutil.disk_usage("F:/").free < GRADE.MIN_F_FREE:
            raise GRADE.InvalidGrading("Host reserve reached during public dependency preparation")

    def get(self, url: str, expected: str | None = None, headers: dict | None = None, source: str | None = None) -> Path:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {"archive.ubuntu.com", "security.ubuntu.com", "files.pythonhosted.org", "api.github.com"}:
            raise GRADE.InvalidGrading("Only explicit official public dependency URLs are allowed")
        with self.semaphore:
            self.boundaries()
            if expected and (self.objects / expected).is_file():
                target = self.objects / expected
                if GRADE.sha(target) != expected:
                    raise GRADE.InvalidGrading("Cached public artifact changed")
                self.rows[url] = {"url": source or url, "sha256": expected, "bytes": target.stat().st_size, "fromCache": True}
                return target
            if url in self.rows:
                cached = self.objects / self.rows[url]["sha256"]
                if GRADE.sha(cached) != self.rows[url]["sha256"]:
                    raise GRADE.InvalidGrading("Recorded public snapshot cache changed")
                return cached
            temporary = self.objects / ("tmp-"+uuid.uuid4().hex)
            digest, count = hashlib.sha256(), 0
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "ObjRun-public-dependency-cache", **(headers or {})})
                with OPENER.open(request, timeout=30) as response, temporary.open("wb") as out:
                    final = urllib.parse.urlparse(response.geturl())
                    if final.scheme != "https" or not (final.hostname in {"archive.ubuntu.com", "security.ubuntu.com", "files.pythonhosted.org", "api.github.com"} or final.hostname.endswith(".githubusercontent.com")):
                        raise GRADE.InvalidGrading("Unexpected official artifact redirect")
                    length = int(response.headers.get("Content-Length", "0"))
                    if length > 32*1024*1024:
                        raise GRADE.InvalidGrading("Public dependency response is too large")
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > 32*1024*1024:
                            raise GRADE.InvalidGrading("Public dependency response cap exceeded")
                        out.write(chunk); out.flush(); digest.update(chunk)
                        self.boundaries()
                signature = digest.hexdigest()
                if expected and signature != expected:
                    raise GRADE.InvalidGrading("Official published artifact SHA mismatch")
                target = self.objects / signature
                with self.lock:
                    self.wire_bytes += count
                    if target.exists():
                        temporary.unlink()
                    else:
                        temporary.replace(target)
                    self.rows[url] = {"url": source or url, "sha256": signature, "bytes": count, "fromCache": False}
                    self.report.write_text(json.dumps({"artifacts": list(self.rows.values()), "wireBytes": self.wire_bytes}, indent=2), encoding="utf-8")
                self.boundaries()
                return target
            finally:
                if temporary.exists():
                    temporary.unlink()

    def proxy(self) -> str:
        cache = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                try:
                    url = urllib.parse.urlparse(self.path)
                    if url.scheme != "http" or url.hostname not in {"archive.ubuntu.com", "security.ubuntu.com"} or url.query or not (url.path.startswith("/ubuntu/dists/noble") or url.path.startswith("/ubuntu/pool/")):
                        self.send_error(403); return
                    path = cache.get("https://"+url.hostname+url.path)
                    self.send_response(200); self.send_header("Content-Length", str(path.stat().st_size)); self.end_headers()
                    with path.open("rb") as stream:
                        shutil.copyfileobj(stream, self.wfile, length=65536)
                except Exception:
                    cache.fault = "official_public_apt_cache_fetch_failed"
                    self.send_error(502)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return "http://host.docker.internal:"+str(self.server.server_address[1])

    def stop(self):
        if self.server:
            self.server.shutdown(); self.server.server_close()


class BuilderDocker(GRADE.Docker):
    def __init__(self, output: Path, cache: PublicCache, history: dict | None = None):
        super().__init__(output)
        self.cache = cache
        self.initial_allocated = allocated(VHD)
        self.initial_logical = VHD.stat().st_size
        if history:
            self.initial_allocated = history["samples"][0]["vhdAllocatedBytes"]

    def check_resources(self):
        super().check_resources()
        current = allocated(VHD)
        self.samples[-1].update(vhdAllocatedBytes=current, vhdLogicalBytes=VHD.stat().st_size,
                               vhdActualGrowthBytes=max(0, current-self.initial_allocated))
        if current-self.initial_allocated > GROWTH_LIMIT:
            raise GRADE.InvalidGrading("Actual Docker VHD growth boundary reached")
        self.cache.boundaries()


def actual_deb_index(cache: PublicCache) -> dict:
    """Read public .deb control metadata; never run its maintainer scripts."""
    windows = cache.objects.resolve()
    linux = "/mnt/"+windows.drive[0].lower()+"/"+windows.as_posix().split(":/", 1)[1]
    script = '''import pathlib,subprocess,json,hashlib,sys
rows=[]
for path in pathlib.Path(sys.argv[1]).iterdir():
 if not path.is_file() or path.name.startswith("tmp-"):continue
 with path.open("rb") as stream:
  if stream.read(8)!=b"!<arch>\\n":continue
 result=subprocess.run(["dpkg-deb","--field",str(path),"Package","Version","Architecture"],capture_output=True,text=True,timeout=10)
 if result.returncode:raise RuntimeError("Public deb metadata unreadable")
 data=dict(line.split(": ",1) for line in result.stdout.splitlines() if ": " in line)
 digest=hashlib.sha256(path.read_bytes()).hexdigest()
 if digest!=path.name:raise RuntimeError("Public .deb SHA changed")
 rows.append({"name":data["Package"],"version":data["Version"],"architecture":data["Architecture"],"sha256":digest,"bytes":path.stat().st_size})
print(json.dumps(rows))
'''
    result = subprocess.run(["wsl", "-d", "Ubuntu", "--", "python3", "-c", script, linux], capture_output=True, text=True, encoding="utf-8", timeout=60)
    if result.returncode:
        raise GRADE.InvalidGrading("Actual public dependency control metadata capture failed")
    rows = json.loads(result.stdout)
    for item in rows:
        item["sources"] = [row["url"] for row in cache.rows.values() if row["sha256"] == item["sha256"]]
        if not item["sources"]:
            raise GRADE.InvalidGrading("Actual public dependency has no official source ledger")
    return {(item["name"], item["version"]): item for item in rows}


def actual_workspace(docker: GRADE.Docker, name: str) -> dict:
    command = "import json,pathlib,hashlib;root=pathlib.Path('/app/workspace');print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}))"
    return json.loads(docker.checked("exec", name, "/usr/bin/python3", "-c", command).stdout)


def repair_history(path: Path, original: dict) -> dict:
    """Only this repair's known, layout-invalid dependency image is eligible.

    This is not a candidate snapshot or a general alternate FROM facility.
    Its dependencies are re-read and matched to the exact public deb ledger.
    """
    history = json.loads(path.read_text())
    if history.get("imageId") != LAYOUT_INVALID_IMAGE or not history.get("validated") or not history.get("actualBuildCompleted") or history.get("sourceHashes") != original or history.get("baseImageId") != GRADE.BASE_ID or history.get("protocol") != "original-instruction-replay-public-cache-v1":
        raise GRADE.InvalidGrading("Only the recorded, known layout-invalid original dependency build can be repaired")
    limits = {"uniquePublicCacheBytes": PUBLIC_LIMIT, "hostDependencyCacheBytes": HOST_LIMIT,
              "maxBuildWritableBytes": BUILD_LIMIT, "dockerHostGrowthBytes": GROWTH_LIMIT}
    if any(type(history.get(k)) is not int or not 0 <= history[k] <= maximum for k, maximum in limits.items()) or history.get("minimumCFreeBytes", 0) < GRADE.MIN_C_FREE or history.get("minimumFFreeBytes", 0) < GRADE.MIN_F_FREE:
        raise GRADE.InvalidGrading("Referenced actual dependency build did not satisfy the approved resource profile")
    return history


def private_profile(cache: PublicCache, image: str, plan: dict) -> Path:
    release = json.loads(cache.get("https://api.github.com/repos/astral-sh/uv/releases/tags/0.9.7").read_text())
    item = next(a for a in release["assets"] if a["name"] == "uv-x86_64-unknown-linux-gnu.tar.gz")
    digest = item["digest"].split(":", 1)[1]
    archive = cache.get("https://api.github.com/repos/astral-sh/uv/releases/assets/"+str(item["id"]), digest,
                        {"Accept": "application/octet-stream"}, source=item["browser_download_url"])
    profile_dir = cache.root / "private-profile"
    profile_dir.mkdir(exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        for name in ["uv", "uvx"]:
            member = next(m for m in tar.getmembers() if Path(m.name).name == name and m.isfile())
            if member.size > 64*1024*1024:
                raise GRADE.InvalidGrading("UV unpacked executable boundary")
            target = profile_dir / name
            with tar.extractfile(member) as inp, target.open("wb") as out:
                shutil.copyfileobj(inp, out, length=65536)
            cache.boundaries()
    wheels = profile_dir / "wheels"
    wheels.mkdir(exist_ok=True)
    packages = {}
    tb = ROOT / "examples/benchmark/terminal-bench/.verifier-deps/uv095-python3137-v1"
    tb_manifest = json.loads((tb / "manifest.json").read_text())
    wanted = {"pytest", "pytest-json-ctrf", "iniconfig", "pluggy", "pygments"}
    for asset in tb_manifest["assets"]:
        if asset.get("distribution") in wanted:
            source = tb / asset["path"]
            if GRADE.sha(source) != asset["sha256"]:
                raise GRADE.InvalidGrading("Frozen compatible Linux test wheel changed")
            shutil.copyfile(source, wheels / source.name)
            packages[asset["distribution"]] = asset["version"]
    for item in plan["buildWheels"]:
        if item["name"].lower() in {"openpyxl", "packaging", "et-xmlfile"}:
            source = cache.get(item["url"], item["publishedSha256"])
            shutil.copyfile(source, wheels / item["filename"])
            packages[item["name"]] = item["version"]
    assets = [{"path": p.relative_to(profile_dir).as_posix(), "bytes": p.stat().st_size, "sha256": GRADE.sha(p)} for p in sorted(profile_dir.rglob("*")) if p.is_file() and not p.name.startswith("manifest")]
    path = profile_dir / ("manifest-"+image[7:19]+".json")
    content = json.dumps({"protocol": GRADE.PROTOCOL, "imageId": image, "python": "3.12.3", "uv": "0.9.7", "packages": packages,
                         "uvArchivePublishedSha256": digest, "uvArchiveActualSha256": GRADE.sha(archive), "assets": assets}, indent=2)
    if path.exists() and path.read_text() != content:
        raise GRADE.InvalidGrading("An existing immutable image dependency profile differs")
    if not path.exists():
        path.write_text(content, encoding="utf-8")
    cache.boundaries()
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--repair-workspace-from", type=Path, help="Only the known original dependency-build proof with the verified nested COPY defect")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=ROOT / ("docs/repair-2026-10-08/software-jpg-build-"+uuid.uuid4().hex[:10]))
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "prepared_requires_explicit_execute", "protocol": "original-instruction-replay-public-cache-v2-copy-verified", "llmRequests": 0,
                          "limits": {"publicCacheBytes": PUBLIC_LIMIT, "hostCacheBytes": HOST_LIMIT, "buildWritableBytes": BUILD_LIMIT,
                                     "vhdActualGrowthBytes": GROWTH_LIMIT, "earlyStopFFreeBytes": GRADE.MIN_F_FREE}}, indent=2)); return
    args.output.mkdir(parents=True, exist_ok=False)
    original = GRADE.sources()
    history = repair_history(args.repair_workspace_from, original) if args.repair_workspace_from else None
    executor_hashes = {path.name: GRADE.sha(path) for path in [Path(__file__).resolve(), HERE / "software-jpg-private-grader.py"]}
    plan = json.loads((ROOT / "docs/repair-2026-10-08/software-build-jpg-resource-plan.json").read_text())
    report = {"taskId": GRADE.TASK_ID, "denominator": 87, "validated": False, "actualBuildCompleted": False, "llmRequests": 0,
              "imagePulls": 0, "protocol": "original-instruction-replay-public-cache-v2-copy-verified", "sourceHashes": original, "baseImageId": GRADE.BASE_ID,
              "cachePath": str(args.cache), "vhdBackingFile": str(VHD), "executorSourceHashes": executor_hashes}
    if history:
        report.update(dependencyInstallationReused=True, repairedLayoutInvalidImage=LAYOUT_INVALID_IMAGE,
                      dependencyBuildProofPath=str(args.repair_workspace_from), dependencyBuildProofSha256=GRADE.sha(args.repair_workspace_from))
    cache = PublicCache(args.cache, args.output / "public-artifacts.json")
    # The Docker wrapper measures one active original-instruction builder, and
    # stops that owned process on the early reserve or writable-layer boundary.
    GRADE.MAX_WRITABLE = BUILD_LIMIT
    docker = BuilderDocker(args.output, cache, history)
    name = None
    committed = False
    image = None
    lease = GRADE.OwnedInstanceLease()
    try:
        lease.acquire()
        docker.record_lease(lease)
        docker.check_resources()
        actual_base = json.loads(docker.checked("image", "inspect", "ubuntu:24.04").stdout)[0]
        if actual_base["Id"] != GRADE.BASE_ID:
            raise GRADE.InvalidGrading("Cached FROM image changed")
        if not history:
            depot = args.cache / "build-wheels"
            depot.mkdir(exist_ok=True)
            for wheel in plan["buildWheels"]:
                downloaded = cache.get(wheel["url"], wheel["publishedSha256"])
                target = depot / wheel["filename"]
                shutil.copyfile(downloaded, target)
                cache.boundaries()
            proxy = cache.proxy()
        name = docker.create(LAYOUT_INVALID_IMAGE if history else GRADE.BASE_ID, "layout-repair" if history else "original-build",
                             "none" if history else "bridge", ["-c", "sleep infinity"], {"DEBIAN_FRONTEND": "noninteractive"})
        docker.checked("start", name)
        text = (TASK / "environment/Dockerfile").read_text()
        runs = re.findall(r"(?ms)^RUN (.*?)(?=\n\s*\n|\Z)", text)
        if len(runs) != 2 or original["environment/Dockerfile"] != "8eac22e4261d1d8b4bba9e1f2010e77a6eeeafd489ada9a3b38fb456f971b61a":
            raise GRADE.InvalidGrading("Instruction replay only supports the exact pinned two-RUN Dockerfile")
        if history:
            nested = {"workspace/"+key: value for key, value in GRADE.public_workspace_files().items()}
            if actual_workspace(docker, name) != nested:
                raise GRADE.InvalidGrading("Known incorrect public COPY layout does not match the original file SHA set")
            docker.checked("exec", name, "/bin/rm", "-rf", "/app/workspace/workspace")
        else:
            apt = docker.checked("exec", "-e", "http_proxy="+proxy, name, "/bin/bash", "-c", runs[0], timeout=1800)
            (args.output / "apt-execution.txt").write_text(apt.stdout+apt.stderr, encoding="utf-8")
            if cache.fault:
                raise GRADE.InvalidGrading(cache.fault)
            docker.checked("cp", str(depot), name+":/public-wheel-depot")
            pip = docker.checked("exec", "-e", "PIP_NO_INDEX=1", "-e", "PIP_FIND_LINKS=/public-wheel-depot", name, "/bin/bash", "-c", runs[1], timeout=600)
            (args.output / "pip-execution.txt").write_text(pip.stdout+pip.stderr, encoding="utf-8")
            docker.checked("exec", name, "/bin/rm", "-rf", "/public-wheel-depot")
        docker.checked("exec", name, "/bin/mkdir", "-p", "/app/workspace")
        # /app/workspace already exists because Docker creates the working dir.
        # Copy its contents explicitly, matching Dockerfile COPY semantics.
        docker.checked("cp", str(TASK / "environment/workspace")+"/.", name+":/app/workspace")
        observed_workspace = actual_workspace(docker, name)
        (args.output / "actual-public-workspace.json").write_text(json.dumps(observed_workspace, indent=2), encoding="utf-8")
        if observed_workspace != GRADE.public_workspace_files():
            raise GRADE.InvalidGrading("Original public COPY path/file SHA verification failed")
        report["publicWorkspaceVerification"] = GRADE.public_workspace_identity()
        versions = docker.checked("exec", name, "/usr/bin/python3", "-c", "import sys,json,importlib.metadata as m;print(json.dumps({'python':sys.version.split()[0],'packages':{n:m.version(n) for n in ['pytesseract','Pillow','openpyxl','packaging','et-xmlfile']}}))")
        report["actualSystemPython"] = json.loads(versions.stdout)
        if report["actualSystemPython"]["python"] != "3.12.3":
            raise GRADE.InvalidGrading("Actual original system interpreter changed")
        package_record = docker.checked("exec", name, "/usr/bin/dpkg-query", "-W", "-f=${Package}\t${Version}\n")
        (args.output / "actual-dpkg-packages.txt").write_text(package_record.stdout, encoding="utf-8")
        expected = json.loads((ROOT / "docs/repair-2026-10-08/software-build-jpg-apt-plan.json").read_text())["packages"]
        installed = dict(line.split("\t", 1) for line in package_record.stdout.splitlines() if "\t" in line)
        actual_debs = actual_deb_index(cache)
        recorded, drift = [], []
        for package in expected:
            version = installed.get(package["name"])
            if (package["name"], version) not in actual_debs:
                raise GRADE.InvalidGrading("Actual installed APT dependency has no exact downloaded SHA: "+package["name"])
            recorded.append(actual_debs[(package["name"], version)])
            if version != package["version"]:
                drift.append({"name": package["name"], "planningVersion": package["version"], "actualVersion": version})
        report["actualAptArchives"] = recorded
        report["planningSnapshotDifferences"] = drift
        report["aptDependencyProfile"] = {"kind": "actual-cached-original-ubuntu-apt-verified",
            "sha256": hashlib.sha256(json.dumps(recorded, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "packageCount": len(recorded), "signedMetadataVerifiedByOriginalApt": True}
        docker.check_resources()
        size = docker.samples[-1]["writableBytes"]
        # Allow a worst-case additional full layer copy for commit while keeping
        # the early-stop buffer. No optimistic assumption about sparse reuse.
        if shutil.disk_usage("F:/").free < GRADE.MIN_F_FREE + size:
            raise GRADE.InvalidGrading("Insufficient physical F headroom for a conservative final-layer commit")
        tag = "objrun-skb-jpg:"+uuid.uuid4().hex[:12]
        result = docker.checked("commit", "--change", "WORKDIR /app/workspace", "--change", "ENTRYPOINT []", "--change", 'CMD ["/bin/bash"]',
            "--change", "LABEL objrun.skb.task-id=jpg-ocr-stat", "--change", "LABEL objrun.skb.environment-sha256="+GRADE.ENV_HASH, name, tag, timeout=600)
        image = result.stdout.strip()
        committed = True
        report.update(imageId=image, tag=tag)
        docker.remove(name); name = None
        if GRADE.sources() != original:
            raise GRADE.InvalidGrading("Original task assets changed during construction")
        manifest = {"taskId": GRADE.TASK_ID, "imageId": image, "baseImageId": GRADE.BASE_ID, "environmentSha256": GRADE.ENV_HASH,
                    "completeOriginalTaskImage": True, "sourceHashes": original, "constructionProtocol": report["protocol"], "seededEnvironment": True,
                    "officialDockerfileInstructionsUnchanged": True, "actualSystemPython": report["actualSystemPython"],
                    "aptDependencyProfile": report["aptDependencyProfile"], "executorSourceHashes": executor_hashes,
                    "publicWorkspaceVerification": report["publicWorkspaceVerification"]}
        (args.output / "image-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        profile = private_profile(cache, image, plan)
        report.update(validated=True, actualBuildCompleted=True, dependencyProfilePath=str(profile), imageManifestPath=str(args.output / "image-manifest.json"))
    except Exception as error:
        report.update(reason=str(error), status="unexecuted_or_invalid_resource_or_infrastructure")
    finally:
        for owned_name in list(docker.owned):
            try:
                docker.remove(owned_name)
            except Exception as error:
                report.update(validated=False, reason=str(error), status="owned_cleanup_failed")
        cache.stop()
        cache.report.write_text(json.dumps({"artifacts": list(cache.rows.values()), "wireBytes": cache.wire_bytes}, indent=2), encoding="utf-8")
        try:
            if docker.owned:
                raise GRADE.InvalidGrading("Unreconciled owned containers; retaining the operation lease")
            lease.release()
            docker.record_lease_release()
        except Exception as error:
            report.update(validated=False, reason=str(error), status="owned_lease_release_failed")
        # Include cleanup/commit's delayed actual allocation in the retained proof.
        try:
            docker.check_resources()
        except Exception as error:
            report.update(validated=False, reason=str(error), status="final_resource_boundary_reached")
        if GRADE.sources() != original or any(GRADE.sha(HERE / name) != digest for name, digest in executor_hashes.items()):
            report.update(validated=False, reason="Task or build executor source changed during construction", status="source_changed_during_execution")
        report.update(samples=docker.samples, uniquePublicCacheBytes=sum(p.stat().st_size for p in cache.objects.iterdir() if p.is_file()),
                      hostDependencyCacheBytes=directory_bytes(args.cache), wirePublicBytes=cache.wire_bytes,
                      maxBuildWritableBytes=max([s["writableBytes"] for s in docker.samples]+([history["maxBuildWritableBytes"]] if history else [0])),
                      dockerHostGrowthBytes=max((s["vhdActualGrowthBytes"] for s in docker.samples if "vhdActualGrowthBytes" in s), default=None),
                      minimumCFreeBytes=min((s["freeCBytes"] for s in docker.samples), default=shutil.disk_usage("C:/").free),
                      minimumFFreeBytes=min((s["freeFBytes"] for s in docker.samples), default=shutil.disk_usage("F:/").free),
                      imageCommitted=committed)
        if history:
            report["currentRepairMaxWritableBytes"] = max((s["writableBytes"] for s in docker.samples), default=0)
            report["minimumCFreeBytes"] = min(report["minimumCFreeBytes"], history["minimumCFreeBytes"])
            report["minimumFFreeBytes"] = min(report["minimumFFreeBytes"], history["minimumFFreeBytes"])
        (args.output / "build-proof.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(args.output / "build-proof.json"), "validated": report["validated"], "reason": report.get("reason"), "imageId": image}, ensure_ascii=False))


if __name__ == "__main__":
    main()
