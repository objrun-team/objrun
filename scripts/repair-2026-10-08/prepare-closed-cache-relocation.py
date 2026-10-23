"""Read-only inventory for root review. This program has no apply/copy/remove mode.

Only the two JSON reports are created, under the fixed F project docs directory.
Content is hashed once per stable Windows file ID; each path receives that SHA
after a separate identity/length/mtime check. Hardlink topology is part of proof.
"""
from pathlib import Path
import ctypes
import datetime
import hashlib
import json
import os
import re
import shutil
import stat


PROJECT = Path(__file__).resolve().parents[2]
DOCS = PROJECT / "docs/repair-2026-10-08"
C_WORKSPACE = Path("C:/Users/y1252/.codex/visualizations/2026/10/08/01a119ed-fdf7-7c32-b323-de9bab1290b6")
FAST_IDS = ("013e657b977f", "0e09d9907bfe", "2d55470eeeb8", "3e9224701803", "6a898c404d1c", "9dffa617c081")
SOURCES = [
    ("public-jpg-objects", C_WORKSPACE / "project-cache/sku-jpg/objects", "C"),
    ("paid-resource-unit-fixtures", PROJECT / ".scratch/paid-resource-admission-v2", "F"),
    *[("minif-fast-toy-" + x, PROJECT / (".scratch/minif-fast-fixture-" + x), "F") for x in FAST_IDS],
]
REPORT = DOCS / "closed-cache-relocation-plan-v2.json"
MANIFEST = DOCS / "closed-cache-relocation-file-manifest-v2.json"
DESTINATION_PARENT = Path("E:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/inactive-benchmark-archives")
UNIT = 4096


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def stable(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink)


def ordinary_ancestors(path):
    checks = []
    for p in [*reversed(path.parents), path]:
        s = p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_file_attributes & 0x400:
            raise RuntimeError("Nonordinary source ancestor: " + str(p))
        checks.append({"path": str(p), "device": str(s.st_dev), "fileId": str(s.st_ino)})
    return checks


def allocated(path):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    high = ctypes.c_ulong()
    kernel.GetCompressedFileSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.GetCompressedFileSizeW.restype = ctypes.c_ulong
    low = kernel.GetCompressedFileSizeW(str(path), ctypes.byref(high))
    if low == 0xFFFFFFFF and ctypes.get_last_error():
        raise ctypes.WinError(ctypes.get_last_error())
    return (high.value << 32) | low


def write_new(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with open(path, "xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    if path.read_bytes() != raw:
        raise RuntimeError("F report readback mismatch")
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    if PROJECT.drive.upper() != "F:" or REPORT.exists() or MANIFEST.exists():
        raise RuntimeError("F-only new reports required; existing reports are never overwritten")
    began = datetime.datetime.now(datetime.timezone.utc).isoformat()
    groups, rows, summaries = {}, [], []
    for label, source, drive in SOURCES:
        ancestors = ordinary_ancestors(source)
        dirs = []
        count = 0
        size = 0
        for home, children, names in os.walk(source, followlinks=False):
            home = Path(home)
            for child in [home, *[home / n for n in children]]:
                s = child.lstat()
                if not stat.S_ISDIR(s.st_mode) or s.st_file_attributes & 0x400:
                    raise RuntimeError("Reparse/non-directory in selection: " + str(child))
            dirs.append(home.relative_to(source).as_posix())
            for name in sorted(names):
                path = home / name
                if name.casefold() == ".env":
                    raise RuntimeError("Secret configuration is outside this inventory")
                s = path.lstat()
                if not stat.S_ISREG(s.st_mode) or s.st_file_attributes & 0x400:
                    raise RuntimeError("Nonregular selected file: " + str(path))
                key = (s.st_dev, s.st_ino)
                if key not in groups:
                    before = stable(s)
                    sha = digest(path)
                    if stable(path.lstat()) != before:
                        raise RuntimeError("Selected file changed during hashing")
                    groups[key] = {"device": str(s.st_dev), "fileId": str(s.st_ino), "bytes": s.st_size,
                        "mtimeNs": str(s.st_mtime_ns), "nlink": s.st_nlink, "sha256": sha,
                        "physicalAllocationBytes": allocated(path), "representative": str(path), "paths": []}
                g = groups[key]
                if (s.st_size, str(s.st_mtime_ns), s.st_nlink) != (g["bytes"], g["mtimeNs"], g["nlink"]):
                    raise RuntimeError("Hardlink group metadata differs")
                rel = path.relative_to(source).as_posix()
                row = {"selection": label, "source": str(path), "relativePath": rel,
                    "bytes": s.st_size, "sha256": g["sha256"], "device": str(s.st_dev),
                    "fileId": str(s.st_ino), "mtimeNs": str(s.st_mtime_ns)}
                rows.append(row)
                g["paths"].append({"selection": label, "relativePath": rel})
                count += 1
                size += s.st_size
        summaries.append({"selection": label, "sourceRoot": str(source), "volume": drive,
            "files": count, "logicalBytes": size, "directories": sorted(dirs), "ordinaryAncestors": ancestors,
            "futureTargetRelativeRoot": label})
    # Every path must still identify the already hashed file at the final pass.
    for row in rows:
        s = Path(row["source"]).lstat()
        g = groups[(int(row["device"]), int(row["fileId"]))]
        if stable(s) != (int(g["device"]), int(g["fileId"]), g["bytes"], int(g["mtimeNs"]), g["nlink"]):
            raise RuntimeError("Selected file changed at final inventory pass")
    external = [g["representative"] for g in groups.values() if len(g["paths"]) != g["nlink"]]
    for s in summaries:
        owned = [g for g in groups.values() if g["paths"][0]["selection"] == s["selection"]]
        s.update(uniqueFileIdBytes=sum(g["bytes"] for g in owned),
            reportedPhysicalAllocationBytes=sum(g["physicalAllocationBytes"] for g in owned),
            contentBytesWhoseAllLinksAreSelected=sum(g["bytes"] for g in owned if len(g["paths"]) == g["nlink"]),
            allocationBytesWhoseAllLinksAreSelected=sum(g["physicalAllocationBytes"] for g in owned if len(g["paths"]) == g["nlink"]),
            allFileLinkNamesInsideSelection=all(len(g["paths"]) == g["nlink"] for g in owned))
    # Match the frozen full_scan allocation formula without executing a writer,
    # lease, GET, cache protocol gate, or cryptographic full Mini scan.
    ps = (PROJECT / "scripts/repair-2026-10-08/minif2f_public_cache_v3.ps1").read_text(encoding="utf-8-sig")
    mini = Path(re.search(r"\$CacheRoot='([^']+)'", ps).group(1))
    envelope = 0
    mini_files = 0
    for home, ds, ns in os.walk(mini, followlinks=False):
        envelope += UNIT * (len(ds) + 1)
        for n in ns:
            info = (Path(home) / n).lstat()
            envelope += (info.st_size + UNIT - 1) // UNIT * UNIT
            mini_files += 1
    cap = 14 * 1024**3
    reserve = 3 * 1024**3
    if envelope > cap:
        raise RuntimeError("Observed Mini allocation envelope is already above cap")
    free = {letter: shutil.disk_usage(letter + ":/").free for letter in ["C", "E", "F", "D"]}
    extra = cap - envelope + reserve
    # Conservative target bound preserves hardlinks, charges rounded data once,
    # plus 64KiB per path/directory and a 32MiB report/copy-journal allowance.
    destination_bound = sum((g["bytes"] + UNIT - 1) // UNIT * UNIT for g in groups.values()) + 65536 * (len(rows) + sum(len(s["directories"]) for s in summaries)) + 32 * 1024**2
    manifest = {"protocol": "closed-cache-regular-hardlink-inventory-v1", "preparedOnly": True,
        "startedAtUtc": began, "completedAtUtc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "hashMethod": "Read representative bytes once per stable file ID; each named path separately rechecked same file ID/size/mtime/nlink and assigned that SHA",
        "copyMoveDeletePerformed": False, "apiCalls": 0, "roots": summaries, "files": rows,
        "hardlinkGroups": list(groups.values()), "unknownExternalHardlinks": external}
    pin = write_new(MANIFEST, manifest)
    report = {"protocol": "closed-cache-relocation-plan-v1", "preparedOnly": True,
        "applyImplemented": False, "applyExecuted": False, "externalModelCalls": 0,
        "sourcePin": {"path": str(Path(__file__).resolve()), "sha256": digest(Path(__file__).resolve())},
        "manifestPin": pin, "roots": [{k:v for k,v in s.items() if k not in ("directories", "ordinaryAncestors")} for s in summaries],
        "freeBytes": free, "mini": {"observedEnvelopeBytes": envelope, "filesMetadataObserved": mini_files,
            "capIsTotalOwnedBytes": cap, "physicalReserveBytes": reserve, "extraRequiredBytes": extra,
            "cryptographicOrProtocolGatePerformed": False, "metadataMayChangeAfterRead": True},
        "EAfterRemainingMiniAndReserve": free["E"] - extra, "destinationAllocationUpperScenarioBytes": destination_bound,
        "EAfterMigrationUpperScenarioAndRemainingMini": free["E"] - extra - destination_bound,
        "FSelectedUniqueContentBytes": sum(s["uniqueFileIdBytes"] for s in summaries if s["volume"] == "F"),
        "FContentBytesPotentiallyReleasableAfterAllSelectedNamesRemoved": sum(s["contentBytesWhoseAllLinksAreSelected"] for s in summaries if s["volume"] == "F"),
        "FReportedAllocationPotentiallyReleasableAfterAllSelectedNamesRemoved": sum(s["allocationBytesWhoseAllLinksAreSelected"] for s in summaries if s["volume"] == "F"),
        "CSelectedUniqueContentBytes": sum(s["uniqueFileIdBytes"] for s in summaries if s["volume"] == "C"),
        "futureDestinationParent": str(DESTINATION_PARENT), "futureOwnedLeafRequiresFreshUuid": True,
        "futureDestinationAncestorsNow": ordinary_ancestors(DESTINATION_PARENT),
        "sourceConsumerProbe": "pending root fresh consumer/PID/handle check; this inventory alone does not certify absence",
        "closedEvidenceRequiredBeforeApply": True, "originalBytesAndLogicalPathsMustRemain": True,
        "actualPhysicalFreeIncrease": "Not observed; no relocation/removal. Outside-selected link names are never changed; their inode allocation is excluded from potential F release. Apply must measure actual before/after free bytes.",
        "limitation": "Relocation of synthetic139a journal paths invalidates physical directory identity for dynamic replay; only historical closed fixture bytes may be archived. Production/live journal, native4, Mini root, JPG private profile/baseZIP are excluded."}
    out_pin = write_new(REPORT, report)
    print(json.dumps({"report": out_pin, "manifest": pin, "FBytes": report["FSelectedUniqueContentBytes"],
        "CBytes": report["CSelectedUniqueContentBytes"], "EBudgetAfterFullScenario": report["EAfterMigrationUpperScenarioAndRemainingMini"]}))


if __name__ == "__main__":
    main()
