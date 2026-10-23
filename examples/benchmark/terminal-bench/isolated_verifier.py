"""Live nginx state, private official tests, and a pinned TLS state broker.

The grader uses the original immutable task image and shares only networking
with the live candidate. It has its own PID/mount namespaces. Public file and
command observations come from the candidate through a narrow, authenticated
broker; expected values and test code never enter a solving process.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import uuid

TASK_ID = "nginx-request-logging"
IMAGE_ID = "sha256:41217bae6667f04a767dc1b2c5c12b034dfc51a18226202003313aaf86832055"
SOURCE_HASHES = {
    "task.toml": "b7a78d00be13656f75069197100b7b8c4fd268decf6f78929c853b3222a2729d",
    "tests/test.sh": "27761195f53cbfe5941fe39b573631f6c926869e64b7c43220377e1e116528e7",
    "tests/test_outputs.py": "045cc716c14efde3b0dcff5fc7c85ec5d18bfc6ce66f8b40a418fa2a3a4acda0",
}
TEST_NAMES = {"test_nginx_installed", "test_nginx_running", "test_index_page_content", "test_custom_404_page",
              "test_nginx_config_syntax", "test_nginx_config_settings", "test_log_file_creation", "test_log_file_format"}
PATHS = {"/etc/nginx/conf.d/benchmark-site.conf", "/etc/nginx/nginx.conf", "/var/log/nginx/benchmark-access.log"}
COMMANDS = {("which", "nginx"), ("nginx", "-t")}
DEPENDENCIES = Path(os.environ["TGENGIN_TB_VERIFIER_DEPS"]) if os.environ.get("TGENGIN_TB_VERIFIER_DEPS") else None
PROTOCOL = "tb-live-nginx-io-v2-preseed" if DEPENDENCIES else "tb-live-nginx-io-v1"
MAX_CAPTURE_BYTES = 1024 * 1024
MAX_WRITABLE_BYTES = 512 * 1024 * 1024
MIN_HOST_FREE_BYTES = 1024 * 1024 * 1024


class ResourceBoundaryError(RuntimeError):
    pass


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def dependency_profile() -> dict | None:
    if DEPENDENCIES is None:
        return None
    manifest = DEPENDENCIES / "manifest.json"
    profile = json.loads(manifest.read_text(encoding="utf-8"))
    if (profile.get("protocol") != "tb-live-nginx-io-v2-preseed" or profile.get("python") != "3.13.7"
            or profile.get("uv") != "0.9.5" or profile.get("imageId") != IMAGE_ID
            or any(profile.get("packages", {}).get(name) != version for name, version in
                   {"pytest": "8.4.1", "requests": "2.32.4", "pytest-json-ctrf": "0.3.5"}.items())):
        raise RuntimeError("the private dependency profile differs from the audited versions")
    if profile.get("offlineEnvironment") != {"UV_OFFLINE": "1", "UV_FIND_LINKS": "/verifier-wheels", "UV_PYTHON_DOWNLOADS": "never", "UV_NO_CONFIG": "1"}:
        raise RuntimeError("the private dependency environment differs from the audited offline configuration")
    assets = profile.get("assets", [])
    if len(assets) != 3 + len(profile["packages"]) or len({asset["path"] for asset in assets}) != len(assets):
        raise RuntimeError("the private dependency asset list is incomplete")
    for asset in assets:
        relative = Path(asset["path"])
        if relative.is_absolute() or ".." in relative.parts or not (DEPENDENCIES / relative).is_file():
            raise RuntimeError("the private dependency path is invalid")
        if file_digest(DEPENDENCIES / relative) != asset["sha256"]:
            raise RuntimeError("the private dependency asset hash changed")
    if not {"uv", "uvx", "uv-0.9.5-linux-x86_64.tar.gz"}.issubset({asset["path"] for asset in assets}):
        raise RuntimeError("the private uv asset set is incomplete")
    if sum(path.stat().st_size for path in DEPENDENCIES.rglob("*") if path.is_file()) > 100 * 1024 * 1024:
        raise ResourceBoundaryError("the private dependency profile exceeded 100 MiB")
    profile["manifestSha256"] = file_digest(manifest)
    return profile


def dependency_ready() -> bool:
    try:
        dependency_profile()
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        return False


DEPENDENCY_RECORD = """import sys,json,platform,hashlib,subprocess
from pathlib import Path
from importlib.metadata import version,PackageNotFoundError
names=['pytest','requests','pytest-json-ctrf','certifi','charset-normalizer','idna','urllib3','iniconfig','packaging','pluggy','pygments']
packages={}
for name in names:
 try: packages[name]=version(name)
 except PackageNotFoundError: packages[name]=None
uv=Path('/root/.local/bin/uv')
observed={'python':platform.python_version(),'pythonExecutable':sys.executable,'packages':packages,
          'uv':subprocess.run([str(uv),'--version'],capture_output=True,text=True).stdout.strip(),
          'uvSha256':hashlib.sha256(uv.read_bytes()).hexdigest()}
Path('/logs/verifier/dependency-versions.json').write_text(json.dumps(observed,indent=2))
"""


def supports(task: dict) -> bool:
    if task.get("id") != TASK_ID:
        return False
    root = Path(task["dir"])
    return all((root / path).is_file() and hashlib.sha256((root / path).read_bytes()).hexdigest() == expected
               for path, expected in SOURCE_HASHES.items())


def docker(*argv, timeout=30, monitor=None):
    """Bound host capture even when an untrusted candidate replaces cat/nginx."""
    command = ["docker", *argv]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    streams = [bytearray(), bytearray()]
    overflow = threading.Event()
    def drain(pipe, output):
        while chunk := pipe.read(8192):
            room = max(0, MAX_CAPTURE_BYTES - len(output))
            output.extend(chunk[:room])
            if len(chunk) > room:
                overflow.set()
    threads = [threading.Thread(target=drain, args=(pipe, output), daemon=True)
               for pipe, output in zip((proc.stdout, proc.stderr), streams)]
    for thread in threads:
        thread.start()
    started, last_check = time.monotonic(), 0.0
    try:
        while proc.poll() is None:
            if overflow.is_set():
                raise ResourceBoundaryError("Docker command output exceeded the host capture limit")
            now = time.monotonic()
            if now - started >= timeout:
                # A create argv includes the private broker token. Grading
                # faults are visible to the solver; never stringify that argv.
                raise subprocess.TimeoutExpired(["docker", str(argv[0])], timeout)
            if monitor is not None and now - last_check >= 2:
                monitor()
                last_check = now
            time.sleep(.05)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        for thread in threads:
            thread.join(timeout=2)
        proc.stdout.close()
        proc.stderr.close()
    if overflow.is_set():
        raise ResourceBoundaryError("Docker command output exceeded the host capture limit")
    return subprocess.CompletedProcess(command, proc.returncode, *(bytes(value).decode("utf-8", "replace") for value in streams))


def image_ready() -> bool:
    result = docker("image", "inspect", "--format", "{{.Id}}", IMAGE_ID)
    return result.returncode == 0 and result.stdout.strip() == IMAGE_ID


def checked(*argv, **kwargs):
    result = docker(*argv, **kwargs)
    if result.returncode:
        raise RuntimeError("Docker " + argv[0] + " failed: " + result.stderr[-300:])
    return result


def check_resources(candidate: str, grader: str | None, directory: Path):
    if shutil.disk_usage(directory).free < MIN_HOST_FREE_BYTES:
        raise ResourceBoundaryError("the host artifact disk fell below the reserved 1 GiB")
    names = [candidate, *([grader] if grader else [])]
    sizes = checked("inspect", "--size", "--format", "{{.SizeRw}}", *names, timeout=10)
    values = [int(line) for line in sizes.stdout.splitlines() if line.strip()]
    if len(values) != len(names) or any(value > MAX_WRITABLE_BYTES for value in values):
        raise ResourceBoundaryError("a container exceeded the 512 MiB operational writable-layer limit")


NAMESPACE_RECORD = "import json,os;from pathlib import Path;Path('/logs/verifier/namespaces.json').write_text(json.dumps({k:os.readlink('/proc/self/ns/'+k) for k in ('pid','mnt','net')}))"


def namespace_boundary(candidate: str, grader: str, box: Path) -> dict:
    private = json.loads((box / "namespaces.json").read_text(encoding="utf-8"))
    public = json.loads(checked("exec", candidate, "python3", "-c", "import os,json;print(json.dumps({k:os.readlink('/proc/self/ns/'+k) for k in ('pid','mnt','net')}))").stdout)
    config = json.loads(checked("inspect", "--format", "{{json .HostConfig}}", grader).stdout)
    isolated = private["pid"] != public["pid"] and private["mnt"] != public["mnt"] and private["net"] == public["net"]
    # Docker's host-side configuration is authoritative even if a candidate
    # tampers with its own python. Namespace IDs are an additional real probe.
    expected = config.get("PidMode", "") == "" and config.get("NetworkMode", "").startswith("container:") and not config.get("Binds")
    if not isolated or not expected:
        raise RuntimeError("private grader namespace boundary differs from the audited protocol")
    return {"sameNetwork": True, "differentPid": True, "differentMount": True,
            "noHostBinds": True, "private": private, "candidate": public}


def make_certificate(directory: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ObjRun isolated state broker")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=6))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("host.docker.internal"), x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .sign(key, hashes.SHA256()))
    certificate, private_key = directory / "broker-ca.pem", directory / "broker-key.pem"
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private_key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return certificate, private_key


class StateBroker:
    def __init__(self, candidate: str, directory: Path):
        self.candidate = candidate
        self.token = secrets.token_urlsafe(32)
        self.calls = Counter()
        self.faults = []
        self.gate = threading.Semaphore(2)
        certificate, private_key = make_certificate(directory)
        self.certificate = certificate
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def send(self, body, status=200):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                if self.path != "/io" or not hmac.compare_digest(self.headers.get("X-ObjRun-State-Token", "").encode(), owner.token.encode()):
                    self.send({"error": "Unauthorized"}, 401)
                    return
                try:
                    length = int(self.headers.get("content-length", 0))
                except ValueError:
                    self.send({"error": "InvalidRequest"}, 400)
                    return
                if not 0 < length <= 8192:
                    self.send({"error": "InvalidRequest"}, 400)
                    return
                try:
                    request = json.loads(self.rfile.read(length))
                    with owner.gate:
                        self.send(owner.query(request))
                except ValueError:
                    self.send({"error": "UnsupportedOperation"}, 422)
                except Exception as error:
                    owner.faults.append(type(error).__name__)
                    self.send({"error": "StateQueryFault", "errorType": type(error).__name__}, 503)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(certificate), str(private_key))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.url = f"https://host.docker.internal:{self.server.server_port}/io"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        self.thread.start()

    def query(self, request: dict):
        if not isinstance(request, dict):
            raise ValueError("expected an object")
        op = request.get("op")
        if op in ("exists", "read") and request.get("path") in PATHS and set(request) == {"op", "path"}:
            path = request["path"]
            argv = ("test", "-e", path) if op == "exists" else ("cat", path)
            self.calls[op] += 1
            result = docker("exec", self.candidate, *argv, timeout=20)
            return {"exists": result.returncode == 0} if op == "exists" else {"code": result.returncode, "stdout": result.stdout}
        if op == "command" and isinstance(request.get("argv"), list) and tuple(request["argv"]) in COMMANDS and set(request) == {"op", "argv"}:
            self.calls["command"] += 1
            result = docker("exec", self.candidate, *request["argv"], timeout=20)
            return {"code": result.returncode, "stdout": result.stdout[-100000:], "stderr": result.stderr[-100000:]}
        raise ValueError("operation is outside the audited official test interface")

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def run_verifier(task: dict, candidate: str, logs: Path) -> dict:
    if not supports(task) or not image_ready():
        raise RuntimeError("the isolated verifier is not approved for this exact task/image")
    profile = dependency_profile()
    key = uuid.uuid4().hex
    name = "objrun-tb-private-" + key[:16]
    box = logs / (TASK_ID + "-isolated-" + key)
    box.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    check_resources(candidate, None, logs)
    with tempfile.TemporaryDirectory(prefix="tb-private-", dir=logs) as tmp:
        private = Path(tmp)
        broker = StateBroker(candidate, private)
        created = False
        try:
            adapter = private / "adapter"
            adapter.mkdir()
            shutil.copy2(Path(__file__).with_name("nginx_client.py"), adapter / "nginx_client.py")
            shutil.copy2(broker.certificate, adapter / "broker-ca.pem")
            # This is only inside the private grader, not in the corpus or candidate.
            (private / "conftest.py").write_text(DEPENDENCY_RECORD + "\nsys.path.insert(0, '/isolation')\nfrom nginx_client import install\ninstall()\n", encoding="utf-8")
            (private / "hidden-marker.txt").write_text("PRIVATE-GRADER-" + secrets.token_hex(16), encoding="utf-8")
            seed = ""
            if profile:
                seed = "mkdir -p /root/.local/bin; mv /tmp/preseed-uv /root/.local/bin/uv; mv /tmp/preseed-uvx /root/.local/bin/uvx; mv /tmp/preseed-env /root/.local/bin/env; chmod +x /root/.local/bin/uv /root/.local/bin/uvx; "
                (private / "uv-env").write_text('export PATH="/root/.local/bin:$PATH"\n', encoding="utf-8")
            dependency_env = profile["offlineEnvironment"] if profile else {}
            checked("create", "--pull", "never", "--name", name, "--network", "container:" + candidate,
                    "--label", "objrun.tb.private-verifier=v1",
                    "--cpus", task["cpus"], "--memory", str(task["memory_mb"]) + "m", "--memory-swap", str(task["memory_mb"]) + "m", "-w", task["workdir"],
                    "-e", "OBJRUN_STATE_BROKER=" + broker.url, "-e", "OBJRUN_STATE_TOKEN=" + broker.token,
                    *[value for key, value in dependency_env.items() for value in ("-e", key + "=" + value)],
                    IMAGE_ID, "bash", "-c", seed + "mkdir -p /logs/verifier; python3 -c \"" + NAMESPACE_RECORD.replace('"', '\\"') + "\"; bash /tests/test.sh > /logs/verifier/test-stdout.txt 2>&1")
            created = True
            if profile:
                checked("cp", str(DEPENDENCIES / "uv"), name + ":/tmp/preseed-uv")
                checked("cp", str(DEPENDENCIES / "uvx"), name + ":/tmp/preseed-uvx")
                checked("cp", str(DEPENDENCIES / "wheels") + "/.", name + ":/verifier-wheels")
                checked("cp", str(private / "uv-env"), name + ":/tmp/preseed-env")
            checked("cp", str(Path(task["dir"]) / "tests") + "/.", name + ":/tests")
            checked("cp", str(adapter) + "/.", name + ":/isolation")
            checked("cp", str(private / "conftest.py"), name + ":/tests/conftest.py")
            checked("cp", str(private / "hidden-marker.txt"), name + ":/tests/hidden-marker.txt")
            timed_out, boundary_fault = False, ""
            try:
                result = docker("start", "-a", name, timeout=task["verify_seconds"], monitor=lambda: check_resources(candidate, name, logs))
                code = result.returncode
            except subprocess.TimeoutExpired:
                timed_out, code = True, -1
                docker("kill", name)
            except ResourceBoundaryError as error:
                boundary_fault, code = str(error), -1
                docker("kill", name)
            checked("cp", name + ":/logs/verifier/.", str(box))
            namespace = namespace_boundary(candidate, name, box)
            reward_file, ctrf = box / "reward.txt", box / "ctrf.json"
            versions_file = box / "dependency-versions.json"
            versions = json.loads(versions_file.read_text(encoding="utf-8")) if versions_file.is_file() else None
            tests = json.loads(ctrf.read_text(encoding="utf-8")).get("results", {}).get("tests", []) if ctrf.is_file() else []
            names = {test.get("name", "").split("::")[-1] for test in tests}
            complete = len(tests) == len(TEST_NAMES) and names == TEST_NAMES
            faults = bool(broker.faults or (box / "isolation-fault.json").exists())
            if profile:
                uv_hash = next(asset["sha256"] for asset in profile["assets"] if asset["path"] == "uv")
                faults = faults or not versions or versions.get("python") != profile["python"] or versions.get("uv", "").split()[:2] != ["uv", profile["uv"]] or versions.get("uvSha256") != uv_hash or versions.get("packages") != profile["packages"]
            reward = float(reward_file.read_text().strip()) if reward_file.is_file() else None
            if timed_out or boundary_fault or reward is None or not math.isfinite(reward) or reward not in (0, 1) or not complete or faults:
                return {"reward": 0.0, "ran": False, "crashed": True, "why": boundary_fault or "isolated verifier timed out, lost its state broker, or did not finish the audited official test set", "seconds": round(time.monotonic() - started, 2), "box": str(box), "protocol": PROTOCOL, "namespaceBoundary": namespace, "_tests": []}
            return {"reward": reward, "ran": True, "crashed": False, "code": code,
                    "seconds": round(time.monotonic() - started, 2), "box": str(box), "protocol": PROTOCOL,
                    "stateQueries": dict(broker.calls), "namespaceBoundary": namespace, "dependencyVersions": versions,
                    "dependencyProfile": {"id": profile["profileId"], "manifestSha256": profile["manifestSha256"]} if profile else {"id": "cold-network-original-image"}, "_tests": tests}
        finally:
            try:
                if created and docker("rm", "-f", name).returncode:
                    raise RuntimeError("the private verifier container could not be removed")
            finally:
                broker.close()
