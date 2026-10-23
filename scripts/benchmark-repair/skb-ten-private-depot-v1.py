"""Download/freeze exact Linux private wheels; no host install, Docker or model."""
from __future__ import annotations
from datetime import datetime, timezone
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import urllib.parse
import urllib.request
import uuid
import zipfile
import skb_artifact_task_v2 as task
import skb_artifact_transport_v2 as transport

ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path("D:/ProgramData/anaconda3/python.exe")
HOME = ROOT / "docs/repair-2026-10-08/skillsbench-ten-takeover-v1/wheel-depots"


def save(path, raw):
    with path.open("xb") as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    task.demand(path.read_bytes() == raw, "readback", "Private depot bytes did not read back")
    return task.pin(path)


def main():
    box = HOME / uuid.uuid4().hex
    box.mkdir(parents=True, exist_ok=False)
    wheels = box / "wheels"; wheels.mkdir()
    tmp = box / "tmp"; tmp.mkdir()
    sources = [task.pin(__file__), task.pin(task.__file__), task.pin(transport.__file__), task.pin(PYTHON)] + transport.component_pins()
    requirements = save(box / "requirements.direct.txt", ("\n".join(name + "==" + version for name, version in task.REQUIREMENTS.items()) + "\n").encode())
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "PATH", "PATHEXT") if k in os.environ}
    env.update({"TEMP": str(tmp), "TMP": str(tmp), "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_CONFIG_FILE": os.devnull})
    def guard(amount=0):
        task.demand(shutil.disk_usage("F:/").free >= 1024**3 + 256*1024**2 + amount,
                    "depot_room", "F download/depot evidence reserve missing")
    argv = [str(PYTHON), "-B", "-X", "utf8", "-m", "pip", "--no-cache-dir", "download",
            "--index-url", "https://pypi.org/simple", "--only-binary=:all:", "--python-version", "312",
            "--implementation", "cp", "--abi", "cp312"]
    for platform in ("manylinux_2_39_x86_64", "manylinux_2_35_x86_64", "manylinux_2_34_x86_64", "manylinux_2_31_x86_64",
                     "manylinux_2_28_x86_64", "manylinux_2_24_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64"):
        argv += ["--platform", platform]
    argv += ["--dest", str(wheels), "--requirement", requirements["path"]]
    print(json.dumps({"phase": "actual-linux-wheel-download", "directory": str(box), "modelCalls": 0}), flush=True)
    records = []; package_rows = []; fault = None
    try:
        row, out, err = transport.bounded_child(argv, env, box, 1, guard, 600, 4*1024**2)
        record = task.pin(box / "command-001.json")
        transport.validate_command_record(record, os.getpid(), 1, argv, box, 4*1024**2); records.append(record)
        task.demand(row["exitCode"] == 0, "pip_download", "Actual Linux wheel resolution/download failed; raw stdout/stderr retained")
        packages = set()
        for wheel in sorted(wheels.iterdir()):
            guard()
            task.demand(wheel.suffix == ".whl" and wheel.is_file(), "wheel_kind", "Only ordinary Linux wheel bytes admitted")
            wheel_pin = task.pin(wheel)
            with zipfile.ZipFile(wheel) as archive:
                names = [x for x in archive.namelist() if x.endswith(".dist-info/METADATA")]
                task.demand(len(names) == 1, "wheel_metadata", "Exact single wheel distribution metadata required")
                metadata = BytesParser().parsebytes(archive.read(names[0]))
            name, version = metadata["Name"], metadata["Version"]
            normalized = re.sub(r"[-_.]+", "-", name).lower()
            task.demand(normalized not in packages, "wheel_duplicate", "Resolved wheel distributions duplicate")
            packages.add(normalized)
            url = "https://pypi.org/pypi/" + urllib.parse.quote(name, safe="") + "/" + urllib.parse.quote(version, safe="") + "/json"
            with urllib.request.urlopen(url, timeout=20) as response:
                task.demand(response.status == 200, "upstream_http", "Official PyPI digest query failed")
                raw = response.read(4*1024**2 + 1)
            task.demand(len(raw) <= 4*1024**2, "upstream_cap", "Official wheel provenance exceeds parser bound")
            pypi_pin = save(box / ("pypi-" + normalized + ".json"), raw)
            document = json.loads(raw)
            links = [x for x in document["urls"] if x["filename"] == wheel.name]
            task.demand(len(links) == 1 and links[0]["digests"]["sha256"] == wheel_pin["sha256"] and links[0]["size"] == wheel_pin["bytes"]
                        and links[0]["url"].startswith("https://files.pythonhosted.org/"), "upstream_digest", "Downloaded wheel does not match upstream published bytes/digest")
            package_rows.append({"name": name, "normalizedName": normalized, "version": version, "wheelPin": wheel_pin,
                                 "upstreamJsonPin": pypi_pin, "upstreamJsonUrl": url, "downloadUrl": links[0]["url"],
                                 "publishedSha256": links[0]["digests"]["sha256"], "metadataRequiresDist": metadata.get_all("Requires-Dist", [])})
            print(json.dumps({"phase": "wheel-digest-verified", "name": name, "version": version, "bytes": wheel_pin["bytes"]}), flush=True)
        versions = {x["normalizedName"]: x["version"] for x in package_rows}
        task.demand(all(versions.get(re.sub(r"[-_.]+", "-", name).lower()) == version for name, version in task.REQUIREMENTS.items()),
                    "direct_versions", "Frozen direct Python dependency versions differ")
        locked = "\n".join(x["normalizedName"] + "==" + x["version"] + " --hash=sha256:" + x["wheelPin"]["sha256"] for x in package_rows) + "\n"
        lock_pin = save(box / "requirements.lock.txt", locked.encode())
    except BaseException as error:
        fault = {"type": type(error).__name__, "kind": getattr(error, "kind", None)}
        lock_pin = None
    after = [task.pin(__file__), task.pin(task.__file__), task.pin(transport.__file__), task.pin(PYTHON)] + transport.component_pins()
    task.demand(sources == after, "source_drift", "Depot download producer source changed")
    value = {"protocol": "skillsbench-linux-private-wheel-depot-v1", "observedAtUtc": datetime.now(timezone.utc).isoformat(),
             "actorPid": os.getpid(), "sourcePins": sources, "requirementsDirectPin": requirements, "requirementsLockPin": lock_pin,
             "wheelDirectory": str(wheels), "wheels": package_rows, "dependencies": task.REQUIREMENTS,
             "commandRecordPins": records, "fault": fault, "downloadComplete": fault is None,
             "actualLinuxInstallationValidated": False, "privateImageBuilt": False, "parentActorClosureRequired": True,
             "hostPackagesInstalled": 0, "DockerCommands": 0, "DOrEWrites": 0, "modelCalls": 0, "paidReady": False}
    manifest = save(box / "depot.json", task.canonical(value))
    print(json.dumps({"depotPin": manifest, "resolvedWheels": len(package_rows), "downloadComplete": fault is None, "fault": fault, "modelCalls": 0}), flush=True)
    raise SystemExit(1 if fault else 0)


if __name__ == "__main__": main()
