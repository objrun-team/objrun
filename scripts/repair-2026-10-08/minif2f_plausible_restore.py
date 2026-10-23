"""Restore only the 18 pinned plausible source files deleted by actual Lake.

No Lake/Git/network/compiler/candidate execution. A separate root review and E
authorization must precede stage restore; gate only reads the existing state.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import tarfile

HELPER_SHA = "cc00c3aff60949865ebb3df3a1d89fc45170981c6057ad55c8f89294d06b91c0"
ARCHIVE_SHA = "84993a398df78fc1a14df0ec6c90c8070b1f01deb4d7af8be81f40f72d202933"
PREFIX = "plausible-2c57364ef83406ea86d0f78ce3e342079a2fece5"
RESERVATION = 32*1024**2
PROTOCOL = "exact-plausible-source-restoration-v1"


def load_helper(path):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != HELPER_SHA:
        raise RuntimeError("reviewed public helper changed")
    spec = importlib.util.spec_from_file_location("frozen_public_helper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sources(archive):
    if hashlib.sha256(Path(archive).read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise RuntimeError("exact original plausible archive differs")
    files = []
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        for member in members:
            pure = PurePosixPath(member.name)
            if (pure.is_absolute() or ".." in pure.parts or pure.parts[0] != PREFIX
                    or not (member.isdir() or member.isfile())):
                raise RuntimeError("pinned plausible source member shape differs")
            if member.isfile():
                with source.extractfile(member) as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                files.append({"path": PurePosixPath(*pure.parts[1:]).as_posix(), "bytes": member.size, "sha256": digest})
        if len(files) != 18 or sum(f["bytes"] for f in files) > 4*1024**2:
            raise RuntimeError("exact plausible source count/size differs")
    return files


def verify(destination, files):
    actual = set()
    for home, dirs, names in os.walk(destination, followlinks=False):
        for name in dirs:
            if not stat.S_ISDIR((Path(home)/name).lstat().st_mode):
                raise RuntimeError("restored source directory is not ordinary")
        for name in names:
            path = Path(home)/name
            actual.add(path.relative_to(destination).as_posix())
    if actual != {f["path"] for f in files}:
        raise RuntimeError("restored source file set differs")
    for entry in files:
        path = destination/entry["path"]
        if (not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size != entry["bytes"]
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]):
            raise RuntimeError("restored original source bytes differ")


def main(args):
    helper = load_helper(args.helper)
    root = helper.exact_root(args.root)
    helper.allocation_unit()
    helper.inputs(root, args.public, args.core)
    helper.volume_reserves(RESERVATION)
    initial_probe = helper.writer_probe()
    archive = Path(args.public)/"package-plausible.tar.gz"
    files = sources(archive)
    destination = root/"mathlib4/.lake/packages/plausible"
    if os.path.lexists(destination):
        raise RuntimeError("refuse replacing any existing/partial plausible path")
    inputs_before = {n: helper.sha(root/"mathlib4"/n) for n in ["lakefile.lean", "lean-toolchain", "lake-manifest.json"]}
    if args.stage == "gate":
        print(json.dumps({"protocol": PROTOCOL, "original_directory_missing": True, "exact_files": len(files),
            "archive_sha256": ARCHIVE_SHA, "writer_probe": initial_probe, "e_write": False,
            "source_mutation_previously_observed": True, "candidate_run": False}))
        return
    lease = helper.Lease(root/"audit"/helper.LEASE_NAME)
    lease.acquire()
    work = root/"repair-plausible-source"
    receipt = root/"audit/plausible-source-restoration.json"
    try:
        helper.writer_probe()
        if work.exists() or receipt.exists() or os.path.lexists(destination):
            raise RuntimeError("unknown/previous restoration artifact requires review")
        before = helper.full_scan(root)
        if before["allocated_envelope_bytes"]+RESERVATION > helper.CAP:
            raise RuntimeError("exact restoration reservation exceeds owned cap")
        helper.volume_reserves(RESERVATION)
        work.mkdir()
        with tarfile.open(archive, "r:gz") as source:
            source.extractall(work, filter="data")
        staged = work/PREFIX
        verify(staged, files)
        for entry in files:
            with (staged/entry["path"]).open("r+b") as stream:
                os.fsync(stream.fileno())
        if os.path.lexists(destination):
            raise RuntimeError("another plausible destination appeared; do not overwrite")
        staged.rename(destination)
        work.rmdir()  # Only the exact newly created, now empty staging directory.
        verify(destination, files)
        after = helper.full_scan(root)
        if after["allocated_envelope_bytes"]+65536 > helper.CAP:
            raise RuntimeError("post-restoration owned envelope exceeds finalization allowance")
        inputs_after = {n: helper.sha(root/"mathlib4"/n) for n in inputs_before}
        if inputs_after != inputs_before:
            raise RuntimeError("original Mathlib hash inputs changed during restoration")
        for name, metadata in before["files"].items():
            if name != "audit/"+helper.LEASE_NAME and after["files"].get(name) != metadata:
                raise RuntimeError("unrelated pre-existing owned file changed during exact restoration: "+name)
        helper.writer_probe()
        record = {"protocol": PROTOCOL, "recorded_at_utc": helper.stamp(), "lease_id": lease.id,
            "original_directory_was_deleted": True, "source_state_was_not_continuously_unchanged": True,
            "restored_from_exact_original_archive": True, "archive_sha256": ARCHIVE_SHA, "revision": PREFIX[len("plausible-"):],
            "restored_files": files, "files_fsynced": True, "unrelated_preexisting_files_unchanged_by_metadata": True,
            "mathlib_three_hash_inputs_unchanged": True, "mathlib_three_hash_inputs": inputs_after,
            "before_allocated_envelope_bytes": before["allocated_envelope_bytes"],
            "after_allocated_envelope_bytes": after["allocated_envelope_bytes"], "network": "none-used-by-host-restorer",
            "lake_git_or_compiler_run": False, "candidate_run": False,
            "invalid_second_runtime_workspace_preserved": True}
        helper.durable_json(receipt, record)
        helper.volume_reserves(65536)
        lease.write({"held": False, "released_at_utc": helper.stamp(), "outcome": "complete", "phase": PROTOCOL,
                     "restoration_receipt_sha256": helper.sha(receipt)})
    except Exception as error:
        lease.write({"held": False, "released_at_utc": helper.stamp(), "outcome": "aborted", "phase": PROTOCOL,
                     "error": (type(error).__name__+": "+str(error))[:4096], "partial_requires_review": True})
        raise
    finally:
        lease.close()
    print(json.dumps({"plausible_exact_source_restored": True, "files": 18, "lease_handle_closed": True,
                      "receipt_sha256": helper.sha(receipt), "source_not_continuously_unchanged": True,
                      "candidate_run": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["gate", "restore"])
    parser.add_argument("--root", required=True)
    parser.add_argument("--public", required=True)
    parser.add_argument("--helper", required=True)
    parser.add_argument("--core", required=True)
    main(parser.parse_args())
