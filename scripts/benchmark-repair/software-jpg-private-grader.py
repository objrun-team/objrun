"""Limited artifact-only SkillsBench grader and three benign control runs.

Only jpg-ocr-stat is implemented. No candidate snapshot, candidate executable,
candidate environment, or candidate directory is used by the private scorer.
The sole imported artifact is a regular stat_ocr.xlsx file. This script never
builds/pulls an image or calls an LLM. A separately recorded complete original
task image, dependency profile, and actual build resource proof are required.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / ".phase1-data/skillsbench/vendor/skillsbench/tasks/jpg-ocr-stat"
TASK_ID = "jpg-ocr-stat"
PROTOCOL = "skb-jpg-output-v1-preseed"
ARTIFACT = "/app/workspace/stat_ocr.xlsx"
BASE_ID = "sha256:6232b38791000e3818b58d8847b5a8f5612d606929e01156dd8febc423e0f2ef"
ENV_HASH = "3f8c727f88febafc7e4849c40dbbfe438b5e3ff13813731faf5b2b681e055d00"
MAX_ARTIFACT = 8 * 1024 * 1024
MAX_WRITABLE = 128 * 1024 * 1024
MIN_C_FREE = 1536 * 1024 * 1024
MIN_F_FREE = 1152 * 1024 * 1024  # 128 MiB early-stop buffer above the 1 GiB reserve
MEMORY = "4096m"
CPUS = "4"
OFFICIAL_ORACLE_SECONDS = 1800
OFFICIAL_VERIFY_SECONDS = 600


class InvalidGrading(RuntimeError):
    pass


class OwnedInstanceLease:
    """Fail closed across CLI processes; never remove a foreign/stale lease."""
    def __init__(self):
        self.path = Path("C:/Users/y1252/.codex/visualizations/2026/10/08/01a119ed-fdf7-7c32-b323-de9bab1290b6/project-cache/sku-jpg/owned-instance.lock")
        self.nonce = uuid.uuid4().hex
        self.held = False

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise InvalidGrading("Another owned JPG operation or unreconciled lease exists") from error
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump({"pid": os.getpid(), "nonce": self.nonce}, file)
        self.held = True

    def release(self):
        if self.held:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("nonce") != self.nonce:
                raise InvalidGrading("Owned instance lease changed")
            self.path.unlink()
            self.held = False


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_sha(path: Path) -> str:
    h = hashlib.sha256()
    for file in sorted(path.rglob("*")):
        if file.is_file():
            h.update(file.relative_to(path).as_posix().encode())
            with file.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
    return h.hexdigest()


def sources() -> dict:
    if tree_sha(TASK / "environment") != ENV_HASH:
        raise InvalidGrading("Pinned task environment changed")
    source = {relative: sha(TASK / relative) for relative in ["task.md", "environment/Dockerfile", "oracle/solve.sh",
              "verifier/test.sh", "verifier/test_outputs.py", "verifier/stat_oracle.xlsx"]}
    tests = ast.parse((TASK / "verifier/test_outputs.py").read_text(encoding="utf-8"))
    names = [n.name for n in tests.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    if names != ["test_outputs"]:
        raise InvalidGrading("The exact official one-test contract changed")
    return source


def public_workspace_files() -> dict[str, str]:
    root = TASK / "environment/workspace"
    if any(path.is_symlink() for path in root.rglob("*")):
        raise InvalidGrading("Pinned public workspace contains a link")
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def public_workspace_identity() -> dict:
    files = public_workspace_files()
    return {"path": "/app/workspace", "verified": True, "fileCount": len(files),
            "filesSha256": hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def read_output_tar(raw: bytes) -> bytes:
    """Accept only the fixed regular file, without extracting TAR paths or modes."""
    if len(raw) > MAX_ARTIFACT + 1024 * 1024:
        raise InvalidGrading("Artifact transfer exceeds the documented bound")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
        members = archive.getmembers()
        if len(members) != 1 or not members[0].isfile() or Path(members[0].name).name != "stat_ocr.xlsx":
            raise InvalidGrading("Artifact transfer is not the sole regular output file")
        if members[0].size > MAX_ARTIFACT:
            raise InvalidGrading("Artifact is too large")
        result = archive.extractfile(members[0]).read(MAX_ARTIFACT + 1)
        if len(result) != members[0].size:
            raise InvalidGrading("Incomplete output transfer")
        return result


def write_wrong_workbook(path: Path) -> None:
    """A normal, readable XLSX with task-schema columns and deliberately wrong rows."""
    content = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="results" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>filename</t></is></c><c r="B1" t="inlineStr"><is><t>date</t></is></c><c r="C1" t="inlineStr"><is><t>total_amount</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>007.jpg</t></is></c><c r="B2" t="inlineStr"><is><t>2001-01-01</t></is></c><c r="C2" t="inlineStr"><is><t>0.00</t></is></c></row></sheetData></worksheet>',
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, text in content.items():
            archive.writestr(name, text)


def require_build(manifest: dict, proof: dict, source: dict) -> str:
    image = manifest.get("imageId", "")
    if not (len(image) == 71 and image.startswith("sha256:") and all(c in "0123456789abcdef" for c in image[7:])):
        raise InvalidGrading("A complete immutable original task image ID is required")
    if image == BASE_ID:
        raise InvalidGrading("The cached base is not a complete task environment")
    if manifest.get("taskId") != TASK_ID or manifest.get("environmentSha256") != ENV_HASH or manifest.get("baseImageId") != BASE_ID:
        raise InvalidGrading("Unsupported task or substituted base/environment")
    if manifest.get("sourceHashes") != source or not manifest.get("completeOriginalTaskImage"):
        raise InvalidGrading("Original task build provenance is incomplete")
    expected_workspace = public_workspace_identity()
    if manifest.get("publicWorkspaceVerification") != expected_workspace or proof.get("publicWorkspaceVerification") != expected_workspace:
        raise InvalidGrading("Actual original public workspace path/file SHA verification is missing")
    limits = {"uniquePublicCacheBytes": 160*1024*1024, "hostDependencyCacheBytes": 224*1024*1024,
              "maxBuildWritableBytes": 375*1024*1024, "dockerHostGrowthBytes": 1024*1024*1024}
    if not proof.get("validated") or not proof.get("actualBuildCompleted") or proof.get("imageId") != image:
        raise InvalidGrading("Actual bounded image construction has not been certified")
    if any(not isinstance(proof.get(key), int) or isinstance(proof.get(key), bool) or not 0 <= proof[key] <= maximum for key, maximum in limits.items()):
        raise InvalidGrading("Actual build exceeded its approved bound")
    if proof.get("minimumCFreeBytes", 0) < MIN_C_FREE or proof.get("minimumFFreeBytes", 0) < 1024*1024*1024:
        raise InvalidGrading("Actual build did not preserve host reserves")
    return image


def require_dependencies(path: Path, image: str) -> tuple[dict, dict[str, Path]]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile.get("protocol") != PROTOCOL or profile.get("imageId") != image or profile.get("uv") != "0.9.7" or profile.get("python") != "3.12.3":
        raise InvalidGrading("Wrong private dependency protocol")
    packages = profile.get("packages", {})
    if any(packages.get(name) != version for name, version in {"pytest": "8.4.1", "pytest-json-ctrf": "0.3.5", "openpyxl": "3.1.5"}.items()):
        raise InvalidGrading("Official fixed test dependencies are missing")
    assets = {}
    for asset in profile.get("assets", []):
        name = asset["path"]
        target = (path.parent / name).resolve()
        if not target.is_relative_to(path.parent.resolve()) or name in assets or not target.is_file() or target.stat().st_size != asset["bytes"] or sha(target) != asset["sha256"]:
            raise InvalidGrading("Private dependency asset changed")
        if name not in {"uv", "uvx"} and not (name.startswith("wheels/") and name.endswith(".whl")):
            raise InvalidGrading("Unrecognized private executable or dependency asset")
        assets[name] = target
    if not {"uv", "uvx"}.issubset(assets) or not any(n.startswith("wheels/") for n in assets):
        raise InvalidGrading("No verified Linux UV/wheel depot")
    return profile, assets


class Docker:
    def __init__(self, output: Path):
        self.output = output
        self.prefix = "objrun-jpg-" + uuid.uuid4().hex[:12]
        self.active: str | None = None
        self.owned: set[str] = set()
        self.identities: dict[str, dict] = {}
        self.lease_identity = None
        self.samples = []

    def record_ownership(self) -> None:
        """Host-only recovery evidence, persisted before Docker create starts.

        Windows force termination does not run Python finally. A trusted parent
        can use this receipt to inspect and remove only matching exact resources.
        Neither a pending name nor this receipt alone proves cleanup completed.
        """
        path = self.output / "operation-owner.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"schemaVersion": 1, "taskId": TASK_ID, "protocol": PROTOCOL,
            "processId": os.getpid(), "ownerLabelKey": "objrun.jpg-owner", "ownerLabelValue": self.prefix,
            "lease": self.lease_identity, "containers": list(self.identities.values())}, indent=2), encoding="utf-8")
        temporary.replace(path)

    def record_lease(self, lease: OwnedInstanceLease) -> None:
        self.lease_identity = {"path": str(lease.path), "nonce": lease.nonce, "released": False}
        self.record_ownership()

    def record_lease_release(self) -> None:
        if self.lease_identity:
            self.lease_identity["released"] = True
        self.record_ownership()

    def check_resources(self) -> None:
        free_c, free_f = shutil.disk_usage("C:/").free, shutil.disk_usage("F:/").free
        writable = 0
        if self.active:
            result = subprocess.run(["docker", "inspect", "--size", "--format", "{{.SizeRw}}", self.active], capture_output=True, timeout=10)
            if result.returncode:
                raise InvalidGrading("Owned writable-layer measurement failed")
            writable = int(result.stdout.strip())
        self.samples.append({"at": time.time(), "freeCBytes": free_c, "freeFBytes": free_f, "container": self.active, "writableBytes": writable})
        if free_c < MIN_C_FREE or free_f < MIN_F_FREE or writable > MAX_WRITABLE:
            raise InvalidGrading("Host reserve or private writable-layer boundary reached")

    def run(self, *args: str, timeout: float = 60, binary: bool = False, cap: int = 1024*1024) -> subprocess.CompletedProcess:
        self.check_resources()
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(["docker", *args], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if time.monotonic()-started > timeout:
                        raise InvalidGrading("Docker operation exceeded its official/operational deadline")
                    self.check_resources()
                    if os.fstat(stdout.fileno()).st_size > cap or os.fstat(stderr.fileno()).st_size > 1024*1024:
                        raise InvalidGrading("Docker output exceeded capture boundary")
                    time.sleep(0.15)
                self.check_resources()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
            stdout.seek(0); stderr.seek(0)
            out, err = stdout.read(cap+1), stderr.read(1024*1024+1)
            if len(out) > cap or len(err) > 1024*1024:
                raise InvalidGrading("Docker output exceeded capture boundary")
        return subprocess.CompletedProcess(args, process.returncode, out if binary else out.decode("utf-8", "replace"), err if binary else err.decode("utf-8", "replace"))

    def checked(self, *args: str, **kwargs) -> subprocess.CompletedProcess:
        result = self.run(*args, **kwargs)
        if result.returncode:
            raise InvalidGrading("Owned Docker operation failed: " + args[0])
        return result

    def create(self, image: str, role: str, network: str, command: list[str], env: dict | None = None) -> str:
        if self.active:
            raise InvalidGrading("Only one task/grader instance may be active")
        name = self.prefix + "-" + role + "-" + uuid.uuid4().hex[:8]
        argv = ["create", "--pull", "never", "--name", name, "--label", "objrun.jpg-owner="+self.prefix,
                "--cpus", CPUS, "--memory", MEMORY, "--memory-swap", MEMORY, "--network", network, "-w", "/app/workspace", "--entrypoint", "/bin/bash"]
        for key, value in (env or {}).items():
            argv += ["-e", key+"="+value]
        # Register before mutation: a successful create can be followed by a
        # resource-check exception, before the caller receives its name.
        self.owned.add(name)
        self.identities[name] = {"name": name, "expectedImageId": image, "role": role,
                                 "containerId": None, "state": "creation_pending"}
        self.record_ownership()
        self.checked(*argv, image, *command)
        self.active = name
        config = json.loads(self.checked("inspect", name).stdout)[0]
        self.identities[name].update(containerId=config["Id"], state="created")
        self.record_ownership()
        if config["Image"] != image or config["Config"]["Image"] != image or (config["Config"].get("Labels") or {}).get("objrun.jpg-owner") != self.prefix or config["HostConfig"].get("Binds") or config["HostConfig"].get("PidMode") or config["HostConfig"]["NetworkMode"] != network:
            raise InvalidGrading("Private original-image namespace configuration changed")
        return name

    def remove(self, name: str) -> None:
        if name not in self.owned:
            raise InvalidGrading("Refusing to remove a foreign container")
        # Cleanup must still work after a reserve breach; it cannot be gated by a
        # pre-command reserve check that would leave the owned process running.
        inspected = subprocess.run(["docker", "inspect", name], capture_output=True, timeout=10)
        if inspected.returncode:
            diagnostic = inspected.stderr.decode("utf-8", "replace")
            if "No such object: " + name not in diagnostic and "No such container: " + name not in diagnostic:
                raise InvalidGrading("Cannot establish owned container identity for cleanup")
            self.owned.remove(name)
            if self.active == name:
                self.active = None
            self.identities[name]["state"] = "absent_after_create_attempt"
            self.record_ownership()
            return
        config = json.loads(inspected.stdout)[0]
        recorded = self.identities[name]
        if config["Name"] != "/"+name or config["Image"] != recorded["expectedImageId"] or (config["Config"].get("Labels") or {}).get("objrun.jpg-owner") != self.prefix or recorded["containerId"] and config["Id"] != recorded["containerId"]:
            raise InvalidGrading("Refusing cleanup of a substituted or foreign container")
        recorded["containerId"] = config["Id"]
        # Use the verified immutable container ID, rather than a replaceable name.
        result = subprocess.run(["docker", "rm", "-f", config["Id"]], capture_output=True, timeout=30)
        if result.returncode:
            raise InvalidGrading("Owned container cleanup failed")
        self.owned.remove(name)
        if self.active == name:
            self.active = None
        recorded["state"] = "removed"
        self.record_ownership()


def conftest(profile: dict, uv_sha: str) -> str:
    return '''import hashlib,json,os,sys,subprocess,importlib.metadata
def pytest_sessionstart(session):
    p="/root/.local/bin/uv"
    data={"python":sys.version.split()[0],"executable":sys.executable,"baseExecutable":getattr(sys,"_base_executable",None),
      "packages":{name:importlib.metadata.version(name) for name in ''' + repr(list(profile["packages"])) + '''},
      "uv":subprocess.check_output([p,"--version"],text=True).strip(),"uvSha256":hashlib.sha256(open(p,"rb").read()).hexdigest(),
      "namespaces":{n:os.readlink("/proc/self/ns/"+n) for n in ["pid","mnt","net"]}}
    with open("/logs/verifier/dependency-versions.json","w") as out:json.dump(data,out)
'''


def accepted_result(reward: str, ctrf: dict, versions: dict, profile: dict, uv_sha: str) -> dict:
    try:
        number = float(reward.strip())
    except ValueError as error:
        raise InvalidGrading("Non-numeric reward") from error
    tests = ctrf.get("results", {}).get("tests", [])
    # pytest-json-ctrf 0.3.5 emits the qualified node name. The official task has
    # one function in this exact file; accepting an arbitrary suffix is unsafe.
    if not math.isfinite(number) or number not in (0.0, 1.0) or len(tests) != 1 or tests[0].get("name") != "test_outputs.py::test_outputs" or tests[0].get("status") not in {"passed", "failed"}:
        raise InvalidGrading("Original one-test contract did not complete")
    if (number == 1) != (tests[0]["status"] == "passed"):
        raise InvalidGrading("Reward/test verdict mismatch")
    if versions.get("python") != "3.12.3" or versions.get("baseExecutable") != "/usr/bin/python3.12" or versions.get("uv", "").split()[:2] != ["uv", "0.9.7"] or versions.get("uvSha256") != uv_sha or versions.get("packages") != profile["packages"]:
        raise InvalidGrading("Actual private interpreter/dependency version mismatch")
    return {"valid": True, "ran": True, "reward": number, "completedTests": 1, "passedTests": int(number), "protocol": PROTOCOL}


class PrivateGrader:
    def __init__(self, docker: Docker, image: str, profile: dict, assets: dict[str, Path], output: Path):
        self.docker, self.image, self.profile, self.assets, self.output = docker, image, profile, assets, output

    def grade(self, workbook: Path | None, phase: str) -> dict:
        before = sources()
        if workbook is not None and (not workbook.is_file() or workbook.is_symlink() or workbook.stat().st_size > MAX_ARTIFACT):
            raise InvalidGrading("Only a bounded regular workbook may be transferred")
        box = self.output / phase
        box.mkdir(parents=True, exist_ok=False)
        env = {"UV_OFFLINE": "1", "UV_FIND_LINKS": "/verifier-wheels", "UV_PYTHON_DOWNLOADS": "never", "UV_NO_CONFIG": "1", "UV_PYTHON": "/usr/bin/python3",
               "PYTHONNOUSERSITE": "1", "PYTHONPATH": "", "PYTHONSTARTUP": "", "LC_ALL": "C.UTF-8"}
        name = self.docker.create(self.image, "grader", "none", ["-c", "mkdir -p /logs/verifier /root/.local/bin /verifier-wheels; sleep infinity"], env)
        try:
            self.docker.checked("start", name)
            self.docker.checked("exec", name, "/bin/mkdir", "-p", "/logs/verifier", "/root/.local/bin", "/verifier-wheels")
            self.docker.checked("cp", str(TASK / "verifier")+"/.", name+":/verifier")
            for relative, path in self.assets.items():
                destination = "/root/.local/bin/"+relative if relative in {"uv", "uvx"} else "/verifier-wheels/"+path.name
                self.docker.checked("cp", str(path), name+":"+destination)
            seed_env = box / "env"
            seed_env.write_text('export PATH="$HOME/.local/bin:$PATH"\n', encoding="utf-8")
            self.docker.checked("cp", str(seed_env), name+":/root/.local/bin/env")
            cf = box / "conftest.py"
            cf.write_text(conftest(self.profile, sha(self.assets["uv"])), encoding="utf-8")
            self.docker.checked("cp", str(cf), name+":/verifier/conftest.py")
            self.docker.checked("exec", name, "/bin/chmod", "+x", "/root/.local/bin/uv", "/root/.local/bin/uvx")
            if workbook is not None:
                self.docker.checked("cp", str(workbook), name+":"+ARTIFACT)
            run = self.docker.run("exec", name, "/bin/bash", "/verifier/test.sh", timeout=OFFICIAL_VERIFY_SECONDS)
            (box / "test-stdout.txt").write_text(run.stdout+run.stderr, encoding="utf-8")
            if run.returncode:
                raise InvalidGrading("Official verifier did not return normally")
            for filename in ["reward.txt", "ctrf.json", "dependency-versions.json"]:
                self.docker.checked("cp", name+":/logs/verifier/"+filename, str(box / filename))
            result = accepted_result((box / "reward.txt").read_text(), json.loads((box / "ctrf.json").read_text()),
                                     json.loads((box / "dependency-versions.json").read_text()), self.profile, sha(self.assets["uv"]))
            if sources() != before:
                raise InvalidGrading("Official source changed during grading")
            result.update(imageId=self.image, originalSourceHashes=before, artifactSha256=sha(workbook) if workbook else None,
                          candidateSnapshotUsed=False, candidateExecutablesUsed=False, hostBinds=False, graderNetwork="none",
                          dependencyVersions=json.loads((box / "dependency-versions.json").read_text()), operationalProfile="offline private UV seed; original test.sh unchanged")
            return result
        finally:
            self.docker.remove(name)


def oracle_workbook(docker: Docker, image: str, output: Path) -> tuple[Path, dict]:
    name = docker.create(image, "official-oracle", "bridge", ["-c", "sleep infinity"])
    try:
        docker.checked("start", name)
        docker.checked("cp", str(TASK / "oracle")+"/.", name+":/oracle")
        started = time.monotonic()
        run = docker.run("exec", name, "/bin/bash", "/oracle/solve.sh", timeout=OFFICIAL_ORACLE_SECONDS)
        (output / "oracle-execution.txt").write_text(run.stdout+run.stderr, encoding="utf-8")
        if run.returncode:
            raise InvalidGrading("Original oracle failed; nonzero output retained in oracle-execution.txt")
        raw = docker.checked("cp", name+":"+ARTIFACT, "-", binary=True, cap=MAX_ARTIFACT+1024*1024).stdout
        file = output / "oracle-stat_ocr.xlsx"
        file.write_bytes(read_output_tar(raw))
        return file, {"ran": True, "exit": 0, "seconds": round(time.monotonic()-started, 2), "artifactSha256": sha(file), "officialOracleSha256": sha(TASK / "oracle/solve.sh")}
    finally:
        docker.remove(name)


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--controls", action="store_true")
    mode.add_argument("--grade", action="store_true", help="Host-only grading of a sealed/captured regular candidate workbook")
    artifact = parser.add_mutually_exclusive_group()
    artifact.add_argument("--candidate-output", type=Path)
    artifact.add_argument("--captured-absent", action="store_true", help="Trusted host capture confirmed the fixed output does not exist")
    artifact.add_argument("--captured-format-failure", choices=["directory", "symlink", "too_large"], help="Trusted host capture observed a declared artifact delivery failure")
    parser.add_argument("--candidate-sha256")
    parser.add_argument("--capture-receipt", type=Path)
    parser.add_argument("--image-manifest", type=Path)
    parser.add_argument("--build-proof", type=Path)
    parser.add_argument("--dependency-profile", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / ("docs/repair-2026-10-08/software-jpg-controls-"+uuid.uuid4().hex[:10]))
    args = parser.parse_args()
    original = sources()
    grader_source_sha = sha(Path(__file__).resolve())
    report = {"taskId": TASK_ID, "denominator": 87, "implementedTaskIds": [TASK_ID], "readyTaskIds": [], "unsupportedTaskCount": 86,
              "protocol": PROTOCOL, "validated": False, "formalLlmClosedLoopValidated": False, "controlValidatedTaskIds": [],
              "graderSourceSha256": grader_source_sha,
              "llmRequests": 0, "imagePulls": 0, "imageBuilds": 0, "originalSourceHashes": original,
              "transferOnly": ARTIFACT, "officialTestCount": 1, "phases": {key: {"ran": False, "valid": False} for key in ["empty", "oracle", "wrongWorkbook"]}}
    if not args.controls and not args.grade:
        report["status"] = "prepared_requires_complete_original_image_dependency_profile_and_actual_resource_proof"
        print(json.dumps(report, ensure_ascii=False, indent=2)); return
    args.output.mkdir(parents=True, exist_ok=False)
    docker = Docker(args.output)
    lease = OwnedInstanceLease()
    try:
        lease.acquire()
        docker.record_lease(lease)
        if not all([args.image_manifest, args.build_proof, args.dependency_profile]):
            raise InvalidGrading("No actual original-image build/profile proof supplied")
        manifest, proof = json.loads(args.image_manifest.read_text()), json.loads(args.build_proof.read_text())
        image = require_build(manifest, proof, original)
        profile, assets = require_dependencies(args.dependency_profile, image)
        report.update(imageId=image, imageManifestSha256=sha(args.image_manifest), buildProofSha256=sha(args.build_proof),
                      dependencyProfileSha256=sha(args.dependency_profile), publicWorkspaceVerification=manifest.get("publicWorkspaceVerification"))
        actual = json.loads(docker.checked("image", "inspect", image).stdout)[0]
        labels = actual["Config"].get("Labels") or {}
        if actual["Id"] != image or labels.get("objrun.skb.task-id") != TASK_ID or labels.get("objrun.skb.environment-sha256") != ENV_HASH:
            raise InvalidGrading("Original image identity/labels do not match the recorded build")
        grader = PrivateGrader(docker, image, profile, assets, args.output)
        if args.grade:
            if not args.capture_receipt:
                raise InvalidGrading("A protected host capture receipt is required")
            receipt = json.loads(args.capture_receipt.read_text(encoding="utf-8"))
            state = "absent" if args.captured_absent else args.captured_format_failure or "regular"
            container_id = receipt.get("ownedContainerID", "")
            evidence = receipt.get("daemonEvidence") or {}
            if receipt.get("taskId") != TASK_ID or receipt.get("protocol") != PROTOCOL or receipt.get("artifactPath") != ARTIFACT or receipt.get("state") != state or receipt.get("containerStopped") is not True or not isinstance(container_id, str) or len(container_id) != 64 or any(c not in "0123456789abcdef" for c in container_id) or evidence.get("containerId") != container_id:
                raise InvalidGrading("Capture receipt does not certify the exact stopped-container artifact")
            if state == "absent" and evidence.get("missingFileDiagnosticMatched") is not True:
                raise InvalidGrading("Absent capture was not a specific Docker-daemon missing-file result")
            if state == "regular" and (receipt.get("artifactSha256") != args.candidate_sha256 or evidence.get("memberKind") != "regular" or evidence.get("method") != "docker-cp-tar"):
                raise InvalidGrading("Capture receipt/workbook SHA mismatch")
            report["captureReceiptSha256"] = sha(args.capture_receipt)
            captured = None
            if args.captured_absent or args.captured_format_failure:
                if args.candidate_sha256:
                    raise InvalidGrading("Absent/format capture cannot also assert workbook bytes")
                report["artifactCapture"] = {"trustedHostCapture": True, "state": "absent" if args.captured_absent else args.captured_format_failure}
            else:
                if not args.candidate_output or not args.candidate_sha256 or not args.candidate_output.is_file() or args.candidate_output.is_symlink() or sha(args.candidate_output) != args.candidate_sha256:
                    raise InvalidGrading("A host-sealed/captured regular candidate workbook and exact SHA are required")
                if args.candidate_output.stat().st_size > MAX_ARTIFACT:
                    report["artifactCapture"] = {"trustedHostCapture": True, "state": "too_large"}
                else:
                    captured = args.output / "candidate-stat_ocr.xlsx"
                    shutil.copyfile(args.candidate_output, captured)
                    if sha(captured) != args.candidate_sha256:
                        raise InvalidGrading("Candidate artifact changed during host capture")
                    report["artifactCapture"] = {"trustedHostCapture": True, "state": "regular", "sha256": args.candidate_sha256}
            report["candidateVerdict"] = grader.grade(captured, "candidate")
            capture_state = report["artifactCapture"]["state"]
            if capture_state in {"directory", "symlink", "too_large"}:
                report["candidateVerdict"].update(experimentalFailure=True, outcome="budget_exhausted" if capture_state == "too_large" else "invalid_artifact", artifactCaptureState=capture_state)
            elif capture_state == "absent":
                report["candidateVerdict"]["artifactCaptureState"] = "absent"
            report.update(validated=True, imageId=image, status="valid_artifact_only_verdict_formal_llm_not_validated")
            return
        report["phases"]["empty"] = grader.grade(None, "empty")
        workbook, execution = oracle_workbook(docker, image, args.output)
        report["oracleExecution"] = execution
        report["phases"]["oracle"] = grader.grade(workbook, "oracle")
        wrong = args.output / "wrong-stat_ocr.xlsx"
        write_wrong_workbook(wrong)
        report["phases"]["wrongWorkbook"] = grader.grade(wrong, "wrong-workbook")
        report["validated"] = all(report["phases"][key].get("reward") == expected for key, expected in [("empty", 0), ("oracle", 1), ("wrongWorkbook", 0)])
        report["status"] = "three_benign_controls_passed_formal_llm_not_validated" if report["validated"] else "official_oracle_control_failed"
        if report["validated"]:
            report["controlValidatedTaskIds"] = [TASK_ID]
        report["imageId"] = image
    except Exception as error:
        report.update(status="unexecuted_or_invalid_infrastructure", reason=str(error), validated=False)
    finally:
        for name in list(docker.owned):
            try:
                docker.remove(name)
            except Exception as error:
                report.update(status="owned_cleanup_failed", reason=str(error), validated=False, readyTaskIds=[])
        try:
            if docker.owned:
                raise InvalidGrading("Unreconciled owned containers; retaining the operation lease")
            lease.release()
            docker.record_lease_release()
        except Exception as error:
            report.update(status="owned_lease_release_failed", reason=str(error), validated=False, readyTaskIds=[], controlValidatedTaskIds=[])
        report["resourceSamples"] = docker.samples
        if sha(Path(__file__).resolve()) != grader_source_sha or sources() != original:
            report.update(status="source_changed_during_execution", validated=False, readyTaskIds=[], controlValidatedTaskIds=[])
        report["officialGradingValid"] = report["validated"]
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.grade:
            print(json.dumps({"path": str(args.output / "report.json"), "validated": report["validated"], "status": report["status"], "candidateVerdict": report.get("candidateVerdict"), "formalLlmClosedLoopValidated": False}, ensure_ascii=False))
    if not args.grade:
        print(json.dumps({"path": str(args.output / "report.json"), "validated": report["validated"], "status": report["status"], "readyTaskIds": report["readyTaskIds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
