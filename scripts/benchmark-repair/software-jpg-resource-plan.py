"""Read-only public dependency accounting for the single JPG SkillsBench task.

This never installs, builds, pulls, runs a container, or calls an LLM. It reads an
existing APT simulation and small official metadata/remote ZIP directories only.
The APT snapshot is a planning estimate; it is not a completed Docker build.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import threading
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/repair-2026-10-08"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LOCK = threading.Lock()
RECEIVED = 0
LIMIT = 4 * 1024 * 1024


def fetch(url: str, *, headers: dict | None = None, cap: int = 1024 * 1024) -> tuple[bytes, dict]:
    global RECEIVED
    if not url.startswith(("https://pypi.org/", "https://files.pythonhosted.org/", "https://api.github.com/")):
        raise ValueError("Only official public metadata origins are allowed")
    request = urllib.request.Request(url, headers={"User-Agent": "ObjRun-public-resource-plan", **(headers or {})})
    with OPENER.open(request, timeout=30) as response:
        if headers and "Range" in headers and response.status != 206:
            raise RuntimeError("Server did not honor metadata-only byte range")
        data = response.read(cap + 1)
        if len(data) > cap:
            raise RuntimeError("Public metadata response cap exceeded")
        with LOCK:
            RECEIVED += len(data)
            if RECEIVED > LIMIT:
                raise RuntimeError("Public metadata total cap exceeded")
        return data, dict(response.headers)


def wheel(package: str, version: str | None) -> dict:
    url = "https://pypi.org/pypi/" + package + "/" + ((version + "/") if version else "") + "json"
    raw, _ = fetch(url)
    metadata = json.loads(raw)
    version = metadata["info"]["version"]
    choices = [item for item in metadata["urls"] if item["packagetype"] == "bdist_wheel" and
               (item["filename"].endswith("py3-none-any.whl") or
                ("cp312-cp312" in item["filename"] and "manylinux" in item["filename"] and "x86_64" in item["filename"]))]
    if not choices:
        raise RuntimeError("No matching Python 3.12 Linux wheel: " + package)
    def priority(item: dict) -> tuple[int, str]:
        # Ubuntu 24.04's glibc is 2.39; pip prefers the highest compatible PEP
        # 600 platform tag, rather than the first filename alphabetically.
        minors = [int(n) for n in re.findall(r"manylinux_2_(\d+)_x86_64", item["filename"]) if int(n) <= 39]
        return (max(minors, default=17 if "manylinux2014" in item["filename"] else 0), item["filename"])
    item = max(choices, key=priority)
    result = {"name": package, "version": version, "filename": item["filename"], "url": item["url"],
              "downloadBytes": item["size"], "publishedSha256": item["digests"]["sha256"],
              "metadataUrl": url, "metadataSha256": hashlib.sha256(raw).hexdigest(),
              "requiresDist": metadata["info"].get("requires_dist") or [], "archiveDownloaded": False}
    # ZIP's central directory records exact unpacked member sizes. Only fetch this
    # public directory; never claim the whole wheel's SHA was independently checked.
    start = max(0, item["size"] - 65557)
    tail, _ = fetch(item["url"], headers={"Range": f"bytes={start}-{item['size']-1}"}, cap=65557)
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise RuntimeError("Missing wheel ZIP directory")
    fields = struct.unpack_from("<4s4H2LH", tail, eocd)
    count, length, offset = fields[4], fields[5], fields[6]
    if length > 1024 * 1024:
        raise RuntimeError("Wheel ZIP directory exceeds metadata cap")
    if offset >= start:
        directory = tail[offset - start:offset - start + length]
    else:
        directory, _ = fetch(item["url"], headers={"Range": f"bytes={offset}-{offset+length-1}"}, cap=length)
    position, unpacked, members = 0, 0, []
    while position < len(directory):
        values = struct.unpack_from("<4s6H3L5H2L", directory, position)
        if values[0] != b"PK\x01\x02":
            raise RuntimeError("Malformed ZIP metadata")
        filename_length, extra, comment = values[10:13]
        filename = directory[position+46:position+46+filename_length].decode("utf-8")
        unpacked += values[9]
        members.append({"path": filename, "bytes": values[9]})
        position += 46 + filename_length + extra + comment
    if len(members) != count:
        raise RuntimeError("Incomplete ZIP metadata")
    result.update(unpackedMemberBytes=unpacked, memberCount=len(members), centralDirectorySha256=hashlib.sha256(directory).hexdigest())
    return result


def main() -> None:
    apt = json.loads((DOCS / "software-build-jpg-apt-plan.json").read_text(encoding="utf-8"))
    packages = [("pytesseract", "0.3.13"), ("Pillow", "12.0.0"), ("openpyxl", "3.1.5"),
                ("packaging", None), ("et-xmlfile", None)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        wheels = list(pool.map(lambda pair: wheel(*pair), packages))
    raw, _ = fetch("https://api.github.com/repos/astral-sh/uv/releases/tags/0.9.7")
    release = json.loads(raw)
    asset = next(a for a in release["assets"] if a["name"] == "uv-x86_64-unknown-linux-gnu.tar.gz")
    uv = {"version": "0.9.7", "name": asset["name"], "downloadBytes": asset["size"],
          "url": asset["browser_download_url"], "publishedDigest": asset.get("digest"),
          "metadataUrl": "https://api.github.com/repos/astral-sh/uv/releases/tags/0.9.7",
          "metadataSha256": hashlib.sha256(raw).hexdigest(), "archiveDownloaded": False,
          "unpackedBinaryBytes": None, "unpackedBinaryEstimateBytes": 56 * 1024 * 1024,
          "unpackedEstimateBasis": "conservative planning allocation; 0.9.7 archive not downloaded"}
    inventory = json.loads((DOCS / "software-preflight.json").read_text(encoding="utf-8"))
    task = next(t for t in inventory["tasks"] if t["taskId"] == "jpg-ocr-stat")
    build_wheel_bytes = sum(w["downloadBytes"] for w in wheels)
    build_unpacked = sum(w["unpackedMemberBytes"] for w in wheels)
    private_cached_wheels = json.loads((ROOT / "examples/benchmark/terminal-bench/.verifier-deps/uv095-python3137-v1/manifest.json").read_text(encoding="utf-8"))
    report = {"taskId": "jpg-ocr-stat", "denominator": 87, "readOnly": True, "readyTaskIds": [],
              "newMetadataBytes": RECEIVED, "metadataByteCap": LIMIT, "imageBuilds": 0, "imagePulls": 0, "containerRuns": 0,
              "aptPlan": "software-build-jpg-apt-plan.json", "apt": {k: apt[k] for k in ["aptPackageArchiveBytes", "aptIndexGzipDownloadBytes", "sumNewPackageInstalledBytes", "netInstalledPackageBytes"]},
              "buildWheels": wheels, "privateUv": uv,
              "privatePython": {"source": "untampered original built task image", "path": "/usr/bin/python3", "version": "3.12.3", "additionalInterpreterDownloadBytes": 0,
                                "packageVersion": "3.12.3-1ubuntu0.17", "actualRuntimeVersionVerified": False},
              "contextBytes": task["environment"]["buildContextBytes"], "environmentSha256": task["environment"]["sha256"],
              "cachedBaseImages": task["image"]["baseImages"], "officialBudget": task["officialBudget"],
              "privateTestDependencies": {"pytest": "8.4.1", "pytest-json-ctrf": "0.3.5", "openpyxl": "3.1.5",
                                          "existingTbManifestPath": str(ROOT / "examples/benchmark/terminal-bench/.verifier-deps/uv095-python3137-v1/manifest.json"),
                                          "existingTbManifestSha256": hashlib.sha256((ROOT / "examples/benchmark/terminal-bench/.verifier-deps/uv095-python3137-v1/manifest.json").read_bytes()).hexdigest(),
                                          "existingWheelsMayBeReused": True, "uv095MayBeReusedAs097": False},
              "downloadAccounting": {"aptAndIndexBytes": apt["aptPackageArchiveBytes"]+apt["aptIndexGzipDownloadBytes"],
                                     "buildWheelArchiveBytes": build_wheel_bytes,
                                     "uniqueNewArchivesAndOneAptIndexLowerBoundBytes": apt["aptPackageArchiveBytes"]+apt["aptIndexGzipDownloadBytes"]+build_wheel_bytes+uv["downloadBytes"],
                                     "sameDependenciesInRepeatedColdVerifierAreAdditionalTransfers": True,
                                     "releaseFilesCurlPackageAndMetadataOverheadExcluded": True},
              "layerAccounting": {"aptNetInstalledPackageBytes": apt["netInstalledPackageBytes"], "buildWheelsUnpackedMembersBytes": build_unpacked,
                                  "taskInputCopyBytesUpperBound": task["environment"]["buildContextBytes"],
                                  "finalAdditionalImagePayloadLowerBoundBytes": apt["netInstalledPackageBytes"]+build_unpacked,
                                  "pythonBytecodePipHttpCacheDpkgAndLayerTarOverheadExcluded": True,
                                  "aptRunPeakPlanningBytes": apt["sumNewPackageInstalledBytes"]+apt["aptPackageArchiveBytes"]+apt["aptIndexGzipDownloadBytes"],
                                  "dockerBuilderPeakIsNotEqualToPackageInstalledSize": True,
                                  "suggestedBoundedDockerStorageGrowthBytes": 1024*1024*1024,
                                  "suggestedSingleBuildWritableBoundaryBytes": 512*1024*1024,
                                  "suggestedPrivateGraderWritableBoundaryBytes": 256*1024*1024},
              "workspaceDisk": {"path": str(ROOT), "freeBytes": shutil.disk_usage(ROOT).free, "minimumReserveBytes": 1024*1024*1024},
              "limits": {"downloadBytes": 100*1024*1024, "singleWritableLayerBytes": 256*1024*1024},
              "formalSafeAdapter": {"existingSnapshotGraderUsesCandidateBashPython": True, "requiredProtocol": "skb-jpg-output-v1-preseed",
                                    "requiredPrivateImage": "fixed complete original task image, never candidate snapshot",
                                    "transferOnly": "/app/workspace/stat_ocr.xlsx", "officialTestCount": 1,
                                    "controls": {"empty": "unrun", "oracle": "unrun", "wrongWorkbook": "unrun"}},
              "metadataSnapshotOnly": True}
    report["within100MiBDownload"] = report["downloadAccounting"]["uniqueNewArchivesAndOneAptIndexLowerBoundBytes"] <= report["limits"]["downloadBytes"]
    report["within256MiBFinalPayloadBeforeInputsAndOverhead"] = report["layerAccounting"]["finalAdditionalImagePayloadLowerBoundBytes"] <= report["limits"]["singleWritableLayerBytes"]
    output = DOCS / "software-build-jpg-resource-plan.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(output), "newMetadataBytes": RECEIVED, "downloadAccounting": report["downloadAccounting"],
                      "layerAccounting": report["layerAccounting"], "within100MiBDownload": report["within100MiBDownload"],
                      "within256MiBFinalPayloadBeforeInputsAndOverhead": report["within256MiBFinalPayloadBeforeInputsAndOverhead"]}))


if __name__ == "__main__":
    main()
