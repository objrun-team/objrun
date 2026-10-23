"""Explicit future root Apply; F-only Gate/controls by default.

All file mutations are native Python/Win32 operations in one runtime. No shell
file operations, Docker/HTTP calls, global cleanup, unknown lock repair, or
resume of a partial relocation. A failed transaction keeps its evidence.
"""
from pathlib import Path
import argparse
import ctypes
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import uuid

PROJECT = Path(__file__).resolve().parents[2]
DOCS = PROJECT / "docs/repair-2026-10-08"
MANIFEST = DOCS / "closed-cache-relocation-file-manifest-v2.json"
MANIFEST_SHA = "52ae099932f35455335a0563cf4b207c77436034eafe97497506a668165c21f8"
PARENT = Path("E:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/inactive-benchmark-archives")
PROBE = PROJECT / "scripts/repair-2026-10-08/closed-cache-consumer-probe.ps1"
POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
UNIT = 4096
CAP = 14 * 1024**3
RESERVE = 3 * 1024**3


def need(ok, why):
    if not ok:
        raise RuntimeError(why)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1024 * 1024):
            h.update(b)
    return h.hexdigest()


def pin(path):
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def read_pin(path, expected, max_bytes=8 * 1024**2):
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and not info.st_file_attributes & 0x400 and info.st_size <= max_bytes, "Pin is not an ordinary bounded file")
    need(sha(path) == expected, "Pin bytes changed")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_new(path, value):
    need(path.drive.upper() in {"F:", "E:"}, "Evidence path outside authorized transaction")
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with open(path, "xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    need(path.read_bytes() == raw, "Evidence fsync/readback failed")
    return pin(path)


def ordinary(path):
    for ancestor in [*reversed(path.parents), path]:
        s = ancestor.lstat()
        need(stat.S_ISDIR(s.st_mode) and not s.st_file_attributes & 0x400, "Nonordinary ancestor: " + str(ancestor))


def normalized(path):
    value = str(path).replace("\\", "/").lower().rstrip("/")
    for prefix in ("/run/desktop/mnt/host/", "/host_mnt/", "/mnt/host/"):
        if value.startswith(prefix):
            tail = value[len(prefix):]
            return tail[0] + ":/" + tail[2:]
    return value


def overlap(a, b):
    a, b = normalized(a), normalized(b)
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def source_hashes():
    return {str(p): sha(p) for p in [Path(__file__).resolve(), PROBE]}


def verify_tree(manifest, roots=None, original_identity=True):
    roots = roots or {r["selection"]: Path(r["sourceRoot"]) for r in manifest["roots"]}
    expected = {r["selection"]: set() for r in manifest["roots"]}
    hashes = {}
    seen = {}
    group_targets = {}
    for row in manifest["files"]:
        path = roots[row["selection"]] / row["relativePath"]
        need(path.is_relative_to(roots[row["selection"]]), "Manifest child escapes root")
        s = path.lstat()
        need(stat.S_ISREG(s.st_mode) and not s.st_file_attributes & 0x400 and s.st_size == row["bytes"], "File changed/nonregular")
        old = (row["device"], row["fileId"])
        new = (str(s.st_dev), str(s.st_ino))
        if original_identity:
            need(new == old and str(s.st_mtime_ns) == row["mtimeNs"], "Original file identity/mtime changed")
        need(old not in group_targets or group_targets[old] == new, "Hardlink topology was not preserved")
        group_targets[old] = new
        seen[new] = seen.get(new, 0) + 1
        if new not in hashes:
            hashes[new] = sha(path)
        need(hashes[new] == row["sha256"], "Per-path content SHA changed")
        expected[row["selection"]].add(row["relativePath"])
    for root in manifest["roots"]:
        home = roots[root["selection"]]
        ordinary(home)
        actual = set()
        directories = set()
        for current, children, names in os.walk(home, followlinks=False):
            current = Path(current)
            directories.add(current.relative_to(home).as_posix())
            for child in [current, *[current / n for n in children]]:
                info = child.lstat()
                need(stat.S_ISDIR(info.st_mode) and not info.st_file_attributes & 0x400, "Unknown reparse directory")
            actual.update((current / n).relative_to(home).as_posix() for n in names)
        need(actual == expected[root["selection"]] and directories == set(root["directories"]), "Unknown/missing selected tree member")
    for group in manifest["hardlinkGroups"]:
        old = (group["device"], group["fileId"])
        new = group_targets[old]
        path = roots[group["paths"][0]["selection"]] / group["paths"][0]["relativePath"]
        need(path.stat().st_nlink == seen[new] == len(group["paths"]), "External/changed hardlink names")


def mini_and_space(bound):
    wrapper = (PROJECT / "scripts/repair-2026-10-08/minif2f_public_cache_v3.ps1").read_text(encoding="utf-8-sig")
    mini = Path(re.search(r"\$CacheRoot='([^']+)'", wrapper).group(1))
    ordinary(mini)
    total = 0
    for home, children, names in os.walk(mini, followlinks=False):
        current = Path(home)
        total += UNIT * (len(children) + 1)
        for child in [current, *[current / n for n in children]]:
            s = child.lstat()
            need(stat.S_ISDIR(s.st_mode) and not s.st_file_attributes & 0x400, "Mini directory reparse; stop resource estimate")
        for name in names:
            p = current / name
            s = p.lstat()
            rel = p.relative_to(mini).as_posix()
            need(stat.S_ISREG(s.st_mode) or rel == "mathlib4/.lake/packages/batteries/docs/README.md", "Unexpected Mini file kind")
            need(not s.st_file_attributes & 0x400 or rel == "mathlib4/.lake/packages/batteries/docs/README.md", "Unexpected Mini file reparse")
            total += (s.st_size + UNIT - 1) // UNIT * UNIT
    need(total <= CAP, "Mini observed total exceeds14GiB")
    free = {letter: shutil.disk_usage(letter + ":/").free for letter in ("C", "E", "F")}
    required = CAP - total + RESERVE
    need(free["E"] - bound >= required, "Fresh E remaining-Mini+3GiB reserve would be crossed")
    need(free["F"] >= 1024**3 and free["C"] >= 1024**3, "C/F pre-relocation1GiB reserve would be crossed")
    return {"observedAtUtc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "freeBytes": free,
        "miniObservedEnvelopeBytes": total, "miniTotalCapBytes": CAP, "remainingMiniAndReserveBytes": required,
        "targetBoundStillReservedBytes": bound, "spaceGatePassed": True, "miniProtocolGatePerformed": False}


def process_probe():
    result = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-File", str(PROBE)], capture_output=True, timeout=30, check=True)
    value = json.loads(result.stdout.decode("utf-8-sig"))
    need(value["protocol"] == "closed-cache-process-path-observation-v1" and not value["consumerPathHits"] and not any(p["present"] for p in value["recordedUnitPidStates"]), "Known consumer/recorded test PID is present or unresolved")
    return value


def docker_proof(path, expected, manifest):
    evidence = read_pin(path, expected)
    when = datetime.datetime.fromisoformat(evidence["observedAtUtc"].replace("Z", "+00:00"))
    age = (datetime.datetime.now(datetime.timezone.utc) - when).total_seconds()
    need(0 <= age <= 300, "Docker consumer observation exceeds300sTTL")
    need(evidence["protocol"] == "closed-cache-running-docker-mount-observation-v1" and evidence["manifestSha256"] == MANIFEST_SHA and evidence["psSucceeded"] is True and not evidence["errors"], "Docker path proof missing/incomplete")
    ids = evidence["runningContainerIds"]
    observations = evidence["containers"]
    need(len(ids) == len(set(ids)) and set(ids) == {r["id"] for r in observations}, "Docker inspected set differs from running set")
    scopes = [r["sourceRoot"] for r in manifest["roots"]]
    for r in observations:
        need(r["inspectSucceeded"] is True, "Docker inspect unknown")
        for mount in r["mounts"]:
            if mount["type"] == "bind":
                host = normalized(mount["source"])
                need(re.match(r"^[a-z]:/", host) is not None, "Unknown bind-source normalization")
                need(not any(overlap(host, s) for s in scopes), "Running Docker bind consumes selected source")
    return {"pin": pin(path), "observedAtUtc": evidence["observedAtUtc"], "containers": ids,
        "independentlyQueriedByThisProgram": False, "scope": "Root-provided pinned running-list/inspect mount witness, not global handle absence"}


def owner_proof(path, expected, manifest):
    evidence = read_pin(path, expected)
    need(evidence["protocol"] == "closed-cache-owner-review-v1" and evidence["manifestSha256"] == MANIFEST_SHA, "Owner review identity")
    rows = evidence["selections"]
    need({r["selection"] for r in rows} == {r["selection"] for r in manifest["roots"]}, "Missing owner selection")
    for row in rows:
        need(row["ownedExecutionClosed"] is True and row["activeConsumerKnown"] is False and row["evidencePins"], "Owner has not closed selected execution")
        for p in row["evidencePins"]:
            need(Path(p["path"]).stat().st_size == p["bytes"] and sha(Path(p["path"])) == p["sha256"], "Owner evidence changed")
    return pin(path)


def native_copy(source, target, expected):
    need(sha(source) == expected, "Source copy SHA mismatch")
    with open(source, "rb") as incoming, open(target, "xb") as outgoing:
        while block := incoming.read(1024 * 1024):
            outgoing.write(block)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    need(sha(target) == expected and sha(source) == expected, "Copy/readback mismatch")


def junction(alias, target):
    need(not alias.exists() and not os.path.lexists(alias), "Junction alias must be fresh")
    ordinary(alias.parent)
    ordinary(target)
    alias.mkdir()
    substitute = ("\\??\\" + str(target.resolve())).encode("utf-16-le")
    printable = str(target.resolve()).encode("utf-16-le")
    buffer = struct.pack("<LHHHHHH", 0xA0000003, 12 + len(substitute) + len(printable), 0,
        0, len(substitute), len(substitute) + 2, len(printable)) + substitute + b"\0\0" + printable + b"\0\0"
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(alias), 0x40000000, 0, None, 3, 0x02200000, None)
    need(handle not in (None, ctypes.c_void_p(-1).value), "Native junction open failed")
    returned = ctypes.c_ulong()
    try:
        if not kernel.DeviceIoControl(handle, 0x000900A4, buffer, len(buffer), None, 0, ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)
    need(alias.resolve() == target.resolve() and alias.lstat().st_file_attributes & 0x400, "Native junction target mismatch")


def remove_exact_backup(original, backup, nonce):
    need(re.fullmatch(r"[0-9a-f]{32}", nonce) is not None, "Invalid owned nonce")
    need(backup == original.with_name(original.name + ".closed-cache-backup-" + nonce) and backup.parent == original.parent, "Exact owned backup fence")
    ordinary(backup)
    shutil.rmtree(backup)


def controls():
    home = PROJECT / (".scratch/closed-cache-native-controls-" + uuid.uuid4().hex)
    home.mkdir()
    source = home / "source"
    target = home / "target"
    source.mkdir()
    target.mkdir()
    (source / "item").write_bytes(b"bounded F native cache fixture\n")
    expected = sha(source / "item")
    native_copy(source / "item", target / "item", expected)
    checks = ["native-copy-fsync-source-and-target-sha"]
    os.link(target / "item", target / "linked")
    need((target / "item").stat().st_ino == (target / "linked").stat().st_ino and (target / "item").stat().st_nlink == 2, "Native hardlink control failed")
    checks.append("native-hardlink-same-fileid-nlink2")
    junction(home / "alias", target)
    need(sha(home / "alias/item") == expected and (home / "alias").resolve() == target, "Native alias readback failed")
    checks.append("native-junction-correct-target-and-sha")
    for name, action in [
        ("copy-mismatch-before-create", lambda: native_copy(source / "item", home / "must-not-exist", "0" * 64)),
        ("copy-no-overwrite", lambda: native_copy(source / "item", target / "item", expected)),
        ("junction-no-overwrite", lambda: junction(home / "alias", source)),
    ]:
        try:
            action()
            raise AssertionError("Expected rejection: " + name)
        except (RuntimeError, FileExistsError):
            checks.append(name)
    need(not (home / "must-not-exist").exists(), "Bad source created destination")
    need(overlap("/run/desktop/mnt/host/f/path", "F:/path/tree") and not overlap("F:/path2", "F:/path"), "Mount normalization boundary")
    checks.append("consumer-mount-path-boundary")
    fsync_real = os.fsync
    def fsync_fault(_):
        raise OSError("F control injected native fsync failure")
    os.fsync = fsync_fault
    try:
        try:
            native_copy(source / "item", home / "failed-fsync-copy", expected)
            raise AssertionError("Expected fsync rejection")
        except OSError:
            need((source / "item").read_bytes() == b"bounded F native cache fixture\n", "F fsync failure changed original")
            checks.append("copy-fsync-failure-preserves-original-and-failed-copy")
    finally:
        os.fsync = fsync_real
    try:
        remove_exact_backup(source, target, "0" * 32)
        raise AssertionError("Expected backup fence rejection")
    except RuntimeError:
        need((target / "item").exists(), "Backup fence removed foreign target")
        checks.append("foreign-backup-remove-refused")
    value = {"protocol": "closed-cache-native-controls-v1", "passed": True, "checks": checks,
        "sourceHashes": source_hashes(), "fixtureRoot": str(home), "C_E_D_modified": False,
        "apiCalls": 0, "dockerOperations": 0, "fixtureRetained": True}
    out = DOCS / ("closed-cache-native-controls-" + home.name.split("-")[-1] + ".json")
    return save_new(out, value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["gate", "apply", "controls"], default="gate")
    for name in ("owner-proof", "owner-sha", "docker-proof", "docker-sha", "controls-proof", "controls-sha", "gate-proof", "gate-sha"):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    if args.stage == "controls":
        print(json.dumps(controls()))
        return
    for name in ("owner_proof", "owner_sha", "docker_proof", "docker_sha", "controls_proof", "controls_sha"):
        need(getattr(args, name), "Explicit review/consumer/controls pins required")
    code = source_hashes()
    manifest = read_pin(MANIFEST, MANIFEST_SHA)
    need(not manifest["unknownExternalHardlinks"], "External source links cannot be removed under this profile")
    ctrl = read_pin(Path(args.controls_proof), args.controls_sha)
    need(ctrl["protocol"] == "closed-cache-native-controls-v1" and ctrl["passed"] is True and ctrl["sourceHashes"] == code, "Native controls do not bind current code")
    owner = owner_proof(Path(args.owner_proof), args.owner_sha, manifest)
    docker = docker_proof(Path(args.docker_proof), args.docker_sha, manifest)
    observation = process_probe()
    verify_tree(manifest)
    groups = manifest["hardlinkGroups"]
    bound = sum((g["bytes"] + UNIT - 1) // UNIT * UNIT for g in groups) + 65536 * (len(manifest["files"]) + sum(len(r["directories"]) for r in manifest["roots"])) + 32 * 1024**2
    space = mini_and_space(bound)
    ordinary(PARENT)
    gate = {"protocol": "closed-cache-relocation-gate-v2", "validated": True, "sourceHashes": code,
        "manifestPin": pin(MANIFEST), "ownerPin": owner, "dockerWitness": docker,
        "consumerProcessObservation": observation, "space": space, "controlsPin": pin(Path(args.controls_proof)),
        "applyExecuted": False, "globalConsumerOrHandleAbsenceCertified": False}
    if args.stage == "gate":
        print(json.dumps(save_new(DOCS / ("closed-cache-relocation-gate-" + uuid.uuid4().hex + ".json"), gate)))
        return
    need(args.gate_proof and args.gate_sha, "Apply requires independently reviewed Gate pin")
    previous = read_pin(Path(args.gate_proof), args.gate_sha)
    need(previous["protocol"] == gate["protocol"] and previous["validated"] is True and previous["sourceHashes"] == code and previous["manifestPin"] == gate["manifestPin"] and previous["ownerPin"] == owner and previous["controlsPin"] == gate["controlsPin"], "Reviewed Gate does not bind this Apply")
    nonce = uuid.uuid4().hex
    target = PARENT / ("closed-cache-v2-" + nonce)
    evidence = DOCS / ("closed-cache-relocation-transaction-" + nonce)
    evidence.mkdir()
    target.mkdir()
    sequence = 0
    def record(kind, value):
        nonlocal sequence
        sequence += 1
        return save_new(evidence / (str(sequence).zfill(5) + "-" + kind + ".json"), value)
    record("initial", {"protocol": "closed-cache-relocation-transaction-v2", "ownerNonce": nonce, "target": str(target), "gate": pin(Path(args.gate_proof)), "manifest": pin(MANIFEST), "sourceHashes": code, "space": space})
    save_new(target / "owned-relocation.json", {"ownerNonce": nonce, "manifest": pin(MANIFEST), "sourceHashes": code})
    destinations = {r["selection"]: target / r["futureTargetRelativeRoot"] for r in manifest["roots"]}
    backups = {}
    try:
        for r in manifest["roots"]:
            for name in sorted(r["directories"], key=lambda x: (x.count("/"), x)):
                (destinations[r["selection"]] / name).mkdir(exist_ok=False)
        for index, group in enumerate(groups):
            if index % 64 == 0 or group["bytes"] > 16 * 1024**2:
                record("space", mini_and_space(bound))
            first = group["paths"][0]
            item = destinations[first["selection"]] / first["relativePath"]
            native_copy(Path(group["representative"]), item, group["sha256"])
            for other in group["paths"][1:]:
                os.link(item, destinations[other["selection"]] / other["relativePath"])
        verify_tree(manifest, destinations, False)
        verify_tree(manifest)
        need(source_hashes() == code, "Source changed before alias mutations")
        record("before-alias", {"processes": process_probe(), "docker": docker_proof(Path(args.docker_proof), args.docker_sha, manifest), "space": mini_and_space(bound)})
        for r in manifest["roots"]:
            source = Path(r["sourceRoot"])
            backup = source.with_name(source.name + ".closed-cache-backup-" + nonce)
            alias = source.with_name(source.name + ".closed-cache-junction-" + nonce)
            need(not os.path.lexists(backup) and not os.path.lexists(alias), "Fresh adjacent backup/alias required")
            junction(alias, destinations[r["selection"]])
            record("rename-intent", {"source": str(source), "backup": str(backup), "alias": str(alias), "target": str(destinations[r["selection"]])})
            os.rename(source, backup)
            backups[r["selection"]] = backup
            os.rename(alias, source)
            need(source.resolve() == destinations[r["selection"]].resolve(), "Logical alias mismatch")
        verify_tree(manifest, destinations, False)
        verify_tree(manifest, backups, True)
        for r in manifest["roots"]:
            source = Path(r["sourceRoot"])
            need(source.resolve() == destinations[r["selection"]].resolve(), "Original C/F logical alias no longer matches target")
        need(source_hashes() == code, "Source changed before owned-backup removal")
        record("before-remove-owned-backups", {"processes": process_probe(), "space": mini_and_space(bound), "backupRoots": {k:str(v) for k,v in backups.items()}})
        for r in manifest["roots"]:
            original = Path(r["sourceRoot"])
            backup = backups[r["selection"]]
            # The complete backup tree was matched, all selected link names were
            # accounted for, and its ordinary ancestors were checked above.
            record("remove-intent", {"backup": str(backup), "manifestSha256": MANIFEST_SHA})
            remove_exact_backup(original, backup, nonce)
        verify_tree(manifest, destinations, False)
        final_space = mini_and_space(0)
        need(source_hashes() == code, "Execution source changed; retain transaction as uncertified")
        closed = {"validated": True, "ownerNonce": nonce, "manifest": pin(MANIFEST), "sourceHashes": code,
            "target": str(target), "logicalAliases": {r["sourceRoot"]:str(destinations[r["selection"]]) for r in manifest["roots"]},
            "initialFreeBytes": space["freeBytes"], "finalFreeBytes": final_space["freeBytes"],
            "observedFreeDeltaBytes": {k:final_space["freeBytes"][k]-space["freeBytes"][k] for k in ("C","E","F")},
            "noExternalLinkNamesChanged": True, "allSelectedPathShaAndTargetLinkGroupsChecked": True,
            "syntheticJournalPhysicalIdentityReplayCertified": False}
        result = record("closed", closed)
        save_new(target / "closed-relocation.json", closed)
        print(json.dumps(result))
    except BaseException as error:
        record("invalid-preserved", {"validated": False, "ownerNonce": nonce, "type": type(error).__name__,
            "message": str(error), "target": str(target), "backups": {k:str(v) for k,v in backups.items()},
            "automaticCleanupOrRollbackPerformed": False})
        raise


if __name__ == "__main__":
    main()
