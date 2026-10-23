"""Download a bounded, hash-checked public dependency profile for private grading.

No global installation, Docker image pull/build, candidate or secret upload.
The original task image already has CPython 3.13.7; only uv and Python wheels
are prepared here. The official tests remain unchanged.
"""
import hashlib
import json
from pathlib import Path
import shutil
import ssl
import tarfile
import urllib.parse
import urllib.request

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).with_name(".verifier-deps") / "uv095-python3137-v1"
LIMIT = 100 * 1024 * 1024
UV_URL = "https://github.com/astral-sh/uv/releases/download/0.9.5/uv-x86_64-unknown-linux-gnu.tar.gz"
UV_API_URL = "https://api.github.com/repos/astral-sh/uv/releases/assets/306970260"
UV_SHA256 = "2cf10babba653310606f8b49876cfb679928669e7ddaa1fb41fb00ce73e64f66"
PINS = {"pytest": "8.4.1", "requests": "2.32.4", "pytest-json-ctrf": "0.3.5",
        "certifi": "2025.8.3", "charset-normalizer": "3.4.3", "idna": "3.10", "urllib3": "2.5.0",
        "iniconfig": "2.1.0", "packaging": "25.0", "pluggy": "1.6.0", "pygments": "2.19.2"}
ALLOWED_HOSTS = {"api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "pypi.org", "files.pythonhosted.org"}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def size():
    return sum(path.stat().st_size for path in OUTPUT.rglob("*") if path.is_file())


def admit(additional=0):
    if size() + additional > LIMIT:
        raise RuntimeError("the project dependency profile would exceed the authorized 100 MiB")
    if shutil.disk_usage(OUTPUT).free - additional < 1024 * 1024 * 1024:
        raise RuntimeError("the artifact drive would fall below its reserved 1 GiB")


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = urllib.parse.urlparse(newurl)
        if destination.scheme != "https" or destination.hostname not in ALLOWED_HOSTS:
            raise RuntimeError("public dependency redirect left the official source allowlist")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Do not inherit authenticated proxy settings or other user environments.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), OfficialRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def download(url, target, expected_sha=None, max_bytes=LIMIT, headers=None):
    if target.is_file() and expected_sha and digest(target) == expected_sha:
        return
    if urllib.parse.urlparse(url).hostname not in ALLOWED_HOSTS:
        raise RuntimeError("public dependency source is outside the allowlist")
    temporary = target.with_suffix(target.suffix + ".partial")
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ObjRun-public-dependency-preflight", **(headers or {})})
    with OPENER.open(request, timeout=45) as response:
        declared = int(response.headers.get("content-length", 0))
        if declared > max_bytes:
            raise RuntimeError("dependency response exceeded its per-file limit")
        admit(declared)
        written = 0
        with temporary.open("wb") as output:
            while chunk := response.read(128 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise RuntimeError("dependency response exceeded its per-file limit")
                admit(len(chunk))
                output.write(chunk)
    actual = digest(temporary)
    if expected_sha and actual != expected_sha:
        raise RuntimeError("public dependency digest differs from its official metadata")
    temporary.replace(target)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    before = shutil.disk_usage(OUTPUT).free
    admit()
    metadata = {}
    target_env = {**default_environment(), "python_version": "3.13", "python_full_version": "3.13.7", "sys_platform": "linux",
                  "os_name": "posix", "platform_system": "Linux", "platform_machine": "x86_64", "extra": ""}
    for name, version in PINS.items():
        file = OUTPUT / "metadata" / (name + ".json")
        download("https://pypi.org/pypi/" + name + "/" + version + "/json", file, max_bytes=1024 * 1024)
        metadata[name] = json.loads(file.read_text(encoding="utf-8"))
        if not SpecifierSet(metadata[name]["info"].get("requires_python") or "").contains("3.13.7"):
            raise RuntimeError(name + " is incompatible with the private Python patch")
    for name, document in metadata.items():
        for item in document["info"].get("requires_dist") or []:
            requirement = Requirement(item)
            if requirement.marker and not requirement.marker.evaluate(target_env):
                continue
            dependency = canonicalize_name(requirement.name)
            if dependency not in PINS or not requirement.specifier.contains(PINS[dependency]):
                raise RuntimeError(name + " has an unfulfilled frozen dependency: " + str(requirement))
    assets = []
    archive = OUTPUT / "uv-0.9.5-linux-x86_64.tar.gz"
    download(UV_API_URL, archive, UV_SHA256, max_bytes=24 * 1024 * 1024,
             headers={"Accept": "application/octet-stream", "X-GitHub-Api-Version": "2022-11-28"})
    assets.append({"path": archive.name, "source": UV_URL, "retrievalUrl": UV_API_URL, "sha256": digest(archive), "bytes": archive.stat().st_size})
    with tarfile.open(archive, "r:gz") as package:
        for filename in ("uv", "uvx"):
            members = [member for member in package.getmembers() if member.name.rsplit("/", 1)[-1] == filename and member.isfile()]
            if len(members) != 1:
                raise RuntimeError("uv release lacks one unambiguous regular " + filename + " file")
            target = OUTPUT / filename
            official = hashlib.sha256()
            with package.extractfile(members[0]) as source:
                while chunk := source.read(128 * 1024):
                    official.update(chunk)
            if target.is_file() and digest(target) != official.hexdigest():
                raise RuntimeError("existing uv executable differs from its verified official archive")
            if not target.is_file():
                admit(members[0].size)
                with package.extractfile(members[0]) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, 128 * 1024)
            assets.append({"path": filename, "source": UV_URL, "archiveSha256": UV_SHA256,
                           "sha256": digest(target), "bytes": target.stat().st_size})
    for name, document in metadata.items():
        wheels = [wheel for wheel in document["urls"] if wheel["filename"].endswith("-py3-none-any.whl") and not wheel.get("yanked")]
        if len(wheels) != 1:
            raise RuntimeError(name + " needs one unambiguous pure Python wheel")
        wheel = wheels[0]
        if Path(wheel["filename"]).name != wheel["filename"] or "/" in wheel["filename"] or "\\" in wheel["filename"]:
            raise RuntimeError("the official wheel filename is not a basename")
        target = OUTPUT / "wheels" / wheel["filename"]
        download(wheel["url"], target, wheel["digests"]["sha256"], max_bytes=10 * 1024 * 1024)
        assets.append({"path": "wheels/" + target.name, "source": wheel["url"], "sha256": digest(target), "bytes": target.stat().st_size,
                       "distribution": name, "version": PINS[name]})
        print(name + "==" + PINS[name] + " verified", flush=True)
    manifest = {"profileId": "nginx-private-preseed-uv095-python3137-v1", "protocol": "tb-live-nginx-io-v2-preseed",
                "python": "3.13.7", "pythonSource": "original immutable private grader image; no Python download",
                "imageId": "sha256:41217bae6667f04a767dc1b2c5c12b034dfc51a18226202003313aaf86832055",
                "uv": "0.9.5", "packages": PINS, "assets": assets, "officialScriptsUnchanged": True,
                "offlineEnvironment": {"UV_OFFLINE": "1", "UV_FIND_LINKS": "/verifier-wheels", "UV_PYTHON_DOWNLOADS": "never", "UV_NO_CONFIG": "1"},
                "newProjectBytes": size(), "authorizedMaximumBytes": LIMIT, "driveFreeBefore": before,
                "llmRequests": 0, "imagePulls": False, "globalInstall": False,
                "cacheInventory": {"windows": "pytest9.1.1/requests2.34.2, no exact requested set", "ubuntu": "uv0.11.14/pytest9.0.2+9.0.3/requests2.33.0+2.33.1, no exact requested set"}}
    raw = json.dumps(manifest, indent=2)
    admit(len(raw.encode("utf-8")))
    (OUTPUT / "manifest.json").write_text(raw, encoding="utf-8")
    admit()
    print(json.dumps({"profile": str(OUTPUT), "projectBytes": size(), "newDownloadLimitBytes": LIMIT}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
