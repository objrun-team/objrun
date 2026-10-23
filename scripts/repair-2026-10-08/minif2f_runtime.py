"""Explicit reconstructed-path-workspace-v1 runtime; never impersonates Git.

The official Mathlib root hash inputs and package sources remain unchanged.
A separate Lake path workspace supplies the same pinned libraries to the real
Lake/REPL executables. Mathematical predicates remain in the original stand.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import zipfile

PROTOCOL = "reconstructed-path-workspace-v1"
LEAN_COMMIT = "11651562caae0a0b3973811508db2ab8903d3854"
BATTERIES_ARCHIVE_SHA = "42e427e6f8e35430c5ca5c16a7eec5ccc03d30a2e5551a12ac6ef86be06c581e"
BATTERIES_LINK_MEMBER = "batteries-e8dc5fc16c625fc4fe08f42d625523275ddbbb4b/docs/README.md"
BATTERIES_LINK_TARGET = "../README.md"
BATTERIES_TARGET_SHA = "757c07bff79755bcc7b9e86ead61627ead6ec64a5fe8d94073f90121a485dc51"
BATTERIES_TARGET_BYTES = 3302


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_core(path, expected_sha):
    if sha(path) != expected_sha:
        raise RuntimeError("reviewed restoration core changed")
    spec = importlib.util.spec_from_file_location("mf2f_restore_core", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def original_inputs(root):
    return {name: sha(root/"mathlib4"/name) for name in ["lakefile.lean", "lean-toolchain", "lake-manifest.json"]}


def source_archive_identity(archive_path, destination):
    verified = []
    archive_digest = sha(archive_path)
    destination = Path(destination)
    if not stat.S_ISDIR(destination.lstat().st_mode) or destination.resolve() != destination.absolute():
        raise RuntimeError("fixed source package root is not its actual ordinary directory")
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        roots = {PurePosixPath(m.name).parts[0] for m in members}
        if len(roots) != 1:
            raise RuntimeError("source archive root differs")
        by_name = {m.name: m for m in members}
        for member in members:
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or ".." in pure.parts:
                raise RuntimeError("source archive path is outside its fixed package root")
            if member.isdir():
                directory = destination.joinpath(*pure.parts[1:])
                if not stat.S_ISDIR(directory.lstat().st_mode) or not directory.resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError("actual pinned source directory is not an ordinary in-package directory")
                continue
            relative = member.name.split("/", 1)[1]
            path = destination/relative
            if not member.isfile():
                # Exactly one link exists in all nine pinned source archives.
                # Hardlinks and every other symlink/nonregular member remain
                # rejected; this is not a general path/link exception.
                if (not member.issym() or archive_digest != BATTERIES_ARCHIVE_SHA
                        or member.name != BATTERIES_LINK_MEMBER or member.linkname != BATTERIES_LINK_TARGET):
                    raise RuntimeError("source archive contains an unreviewed nonregular member")
                target_member = by_name.get(member.name.split("/", 1)[0]+"/README.md")
                if target_member is None or not target_member.isfile() or target_member.size != BATTERIES_TARGET_BYTES:
                    raise RuntimeError("fixed source link archive target differs")
                with archive.extractfile(target_member) as incoming:
                    archive_target_sha = hashlib.file_digest(incoming, "sha256").hexdigest()
                if archive_target_sha != BATTERIES_TARGET_SHA:
                    raise RuntimeError("fixed source link archive target bytes differ")
                target = destination/"README.md"
                if (not stat.S_ISLNK(path.lstat().st_mode) or os.readlink(path) != BATTERIES_LINK_TARGET
                        or not path.resolve().is_relative_to(destination.resolve()) or path.resolve() != target.resolve()
                        or not stat.S_ISREG(target.lstat().st_mode) or target.stat().st_size != BATTERIES_TARGET_BYTES
                        or sha(target) != BATTERIES_TARGET_SHA or sha(path) != BATTERIES_TARGET_SHA):
                    raise RuntimeError("actual fixed source link or its in-package target bytes differ")
                verified.append({"path": relative, "type": "symlink", "linkname": member.linkname,
                                 "target": "README.md", "target_bytes": BATTERIES_TARGET_BYTES,
                                 "target_sha256": BATTERIES_TARGET_SHA})
                continue
            with archive.extractfile(member) as incoming:
                expected = hashlib.file_digest(incoming, "sha256").hexdigest()
            if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size != member.size or sha(path) != expected:
                raise RuntimeError("pinned source bytes differ: " + relative)
            verified.append({"path": relative, "bytes": member.size, "sha256": expected})
    aggregate = hashlib.sha256(json.dumps(verified, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"files": len(verified), "file_manifest_sha256": aggregate, "archive_sha256": archive_digest}


def toolchain_identity(root):
    receipt = json.loads((root/"audit/lean-download.json").read_bytes())
    path = root/"downloads/lean-4.15.0-linux.zip"
    if sha(path) != receipt["sha256"] or path.stat().st_size != 427590493:
        raise RuntimeError("acquired Lean archive checksum differs")
    files = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = info.filename.split("/", 1)[1]
            destination = root/"toolchain"/relative
            with archive.open(info) as incoming:
                expected = hashlib.file_digest(incoming, "sha256").hexdigest()
            if destination.stat().st_size != info.file_size or sha(destination) != expected:
                raise RuntimeError("fixed toolchain bytes differ: " + relative)
            files.append({"path": relative, "bytes": info.file_size, "sha256": expected})
    return {"archive_sha256": receipt["sha256"], "files": files}


def runtime_environment(root):
    root = Path(root)
    receipt_path = root/"audit/runtime-workspace.json"
    receipt = json.loads(receipt_path.read_bytes())
    if receipt["protocol"] != PROTOCOL or original_inputs(root) != receipt["original_mathlib_inputs"]:
        raise RuntimeError("runtime protocol or original Mathlib hash inputs changed")
    for name, expected in receipt["runtime_files"].items():
        if sha(root/"runtime-lake"/name) != expected:
            raise RuntimeError("reviewed runtime workspace bytes changed")
    if sha(root/"repl/.lake/build/bin/repl") != receipt["repl_sha256"]:
        raise RuntimeError("fixed REPL binary changed")
    env = dict(os.environ)
    for name in ["LEAN_CC", "LEAN_AR", "LEAN_PATH", "LEAN_SRC_PATH", "LEAN_GITHASH", "LEAN_SYSROOT", "LAKE_HOME", "LAKE_OVERRIDE_LEAN", "ELAN_HOME", "ELAN_TOOLCHAIN"]:
        env.pop(name, None)
    env.update({"PATH": str(root/"runtime-lake/bin")+":"+str(root/"toolchain/bin")+":/usr/local/bin:/usr/bin:/bin",
        "HOME": str(root/"home"), "XDG_CACHE_HOME": str(root/"xdg-cache"), "TMPDIR": "/tmp",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(root/"python-support"),
        "TGENGIN_MF2F_HOME": str(root), "TGENGIN_MF2F_BACKEND": "repl", "TGENGIN_MF2F_REPLS": "1",
        "TGENGIN_MF2F_MEM_GB": "12", "TGENGIN_MF2F_TIMEOUT": "300", "TGENGIN_MF2F_MAX_USES": "4",
        "TGENGIN_MF2F_STRICT_AXIOMS": "0"})
    return env


def create_workspace(core, root, public, lock_sha, stand_sha):
    root = core.owner(root)
    public = Path(public)
    core.public_lock(public, lock_sha)
    if sha("/plan/stand.py") != stand_sha:
        raise RuntimeError("original reviewed stand changed")
    bootstrap = json.loads((root/"audit/bootstrap.json").read_bytes())
    if bootstrap["pins"] != core.PINS or bootstrap["public_lock_sha256"] != lock_sha:
        raise RuntimeError("completed Bootstrap pins/lock differ")
    before = original_inputs(root)
    for name in before:
        if before[name] != sha(public/("mathlib-"+name)):
            raise RuntimeError("original Mathlib hash input no longer equals the frozen official file")
    identities = {"mathlib4": source_archive_identity(public/"mathlib-source.tar.gz", root/"mathlib4")}
    manifest = json.loads((root/"mathlib4/lake-manifest.json").read_bytes())
    for package in manifest["packages"]:
        identities[package["name"]] = {"revision": package["rev"], **source_archive_identity(
            public/("package-"+package["name"]+".tar.gz"), root/"mathlib4/.lake/packages"/package["name"])}
    chain = toolchain_identity(root)
    core.dump(root/"audit/toolchain-file-manifest.json", chain)
    runtime = root/"runtime-lake"
    if runtime.exists():
        raise RuntimeError("runtime workspace already exists; inspect its receipt before rerunning")
    runtime.mkdir()
    by_name = {p["name"]: p for p in manifest["packages"]}
    original_config = (root/"mathlib4/lakefile.lean").read_text()
    # Preserve the original seven root dependency declarations and order. The
    # inherited Cli entry stays in the separate manifest, resolved via importGraph.
    requirements = re.findall(r'^require\s+"([^"]+)"\s*/\s*"([^"]+)"', original_config, re.M)
    if {name for _, name in requirements} != {p["name"] for p in manifest["packages"] if not p["inherited"]}:
        raise RuntimeError("original root dependency declaration set differs")
    config = ['name = "mathlib"', 'manifestFile = "../runtime-lake/lake-manifest.json"', '']
    for scope, name in requirements:
        if scope != by_name[name]["scope"]:
            raise RuntimeError("original dependency scope differs")
        config += ['[[require]]', f'name = "{name}"', f'scope = "{scope}"', f'path = ".lake/packages/{name}"', '']
    for name in ["Mathlib", "Cache", "LongestPole", "MathlibTest", "Archive", "Counterexamples", "docs"]:
        config += ['[[lean_lib]]', f'name = "{name}"', '']
    (runtime/"lakefile.toml").write_text("\n".join(config)+"\n")
    path_entries = [{"name": p["name"], "scope": p["scope"], "type": "path", "dir": ".lake/packages/"+p["name"],
                     "inherited": p["inherited"], "configFile": p["configFile"], "manifestFile": p["manifestFile"]}
                    for p in manifest["packages"]]
    path_manifest = {"version": manifest["version"], "name": manifest["name"], "lakeDir": manifest["lakeDir"],
                     "packagesDir": manifest["packagesDir"], "packages": path_entries}
    core.dump(runtime/"lake-manifest.json", path_manifest)
    launcher = runtime/"bin/lake"
    launcher.parent.mkdir()
    # This is a narrow, honestly labelled launcher for the actual Lake binary.
    # It does not intercept Git or manufacture repository metadata or grades.
    launcher.write_text(f'''#!/bin/sh
set -eu
if [ "$#" -ne 2 ] || [ "$1" != env ] || [ "$2" != "{root}/repl/.lake/build/bin/repl" ]; then
  echo "{PROTOCOL}: only the fixed REPL lake env invocation is allowed" >&2
  exit 2
fi
exec "{root}/toolchain/bin/lake" -d "{root}/mathlib4" -f ../runtime-lake/lakefile.toml env "$2"
''')
    launcher.chmod(0o755)
    runtime_files = {name: sha(runtime/name) for name in ["lakefile.toml", "lake-manifest.json", "bin/lake"]}
    preliminary = {"protocol": PROTOCOL, "original_mathlib_inputs": before, "runtime_files": runtime_files,
                   "repl_sha256": bootstrap["repl_binary_sha256"]}
    core.dump(root/"audit/runtime-workspace.json", preliminary)
    env = runtime_environment(root)
    native_lake = root/"toolchain/bin/lake"
    native_probe = [str(native_lake), "-d", str(root/"mathlib4"), "-f", "../runtime-lake/lakefile.toml", "env"]
    result = core.run(native_probe+['python', '-c',
        'import os,json; print(json.dumps({k:os.environ.get(k) for k in ["LEAN_PATH","LEAN_SRC_PATH","LD_LIBRARY_PATH","LEAN_SYSROOT","LEAN_GITHASH","PATH"]}))'],
        root, cwd=root/"mathlib4", env=env)
    paths = json.loads(result)
    actual = {str((Path(p) if Path(p).is_absolute() else root/"mathlib4"/p).resolve()) for p in paths["LEAN_PATH"].split(":") if p}
    expected = {str((root/"mathlib4/.lake/build/lib").resolve()), str((root/"toolchain/lib/lean").resolve())}
    expected |= {str((root/"mathlib4/.lake/packages"/p["name"]/".lake/build/lib").resolve()) for p in manifest["packages"]}
    if actual != expected or paths["LEAN_GITHASH"] != LEAN_COMMIT or Path(paths["LEAN_SYSROOT"]).resolve() != (root/"toolchain").resolve():
        raise RuntimeError("real Lake environment does not map to the exact pinned library roots/toolchain")
    if before != original_inputs(root):
        raise RuntimeError("original Mathlib root inputs changed while creating the isolated workspace")
    core.dump(root/"audit/runtime-workspace.json", {**preliminary,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "source_identities": identities,
        "toolchain_file_manifest_sha256": sha(root/"audit/toolchain-file-manifest.json"),
        "native_lake_environment": paths, "native_lake_sha256": sha(native_lake), "stand_sha256": stand_sha,
        "public_lock_sha256": lock_sha, "bootstrap_receipt_sha256": sha(root/"audit/bootstrap.json"),
        "original_source_inputs_unchanged": True, "new_runtime_protocol": True, "candidate_run": False,
        "root_library_options_note": "Lake env adds paths/install variables; original leanOptions/moreServerOptions are build/server settings and are not injected into this REPL invocation."})
    print(json.dumps({"runtime_protocol": PROTOCOL, "native_lake_environment_verified": True, "candidate_run": False}))


def cache_identity(root):
    root = Path(root)
    receipt = root/"audit/cache-unpacked.jsonl"
    manifest = []
    for row in (json.loads(line) for line in receipt.read_text().splitlines()):
        for entry in row["files"]:
            path = root/"mathlib4"/entry["path"]
            if not path.is_file() or path.stat().st_size != entry["bytes"] or sha(path) != entry["sha256"]:
                raise RuntimeError("official cached build bytes changed: " + entry["path"])
            manifest.append(entry)
    return {"files": len(manifest), "bytes": sum(x["bytes"] for x in manifest),
        "unpacked_receipts_sha256": sha(receipt),
        "file_manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def unpack_and_probe(core, root):
    root = core.owner(root)
    before = original_inputs(root)
    runtime_environment(root)  # Hard gate before any original lake env call.
    # Explicit harness integration: only the runtime environment function is
    # replaced; the audited official unpack and original stand controls remain.
    core.environment = runtime_environment
    core.unpack_probe(root)
    cached = cache_identity(root)
    after = original_inputs(root)
    if before != after:
        raise RuntimeError("original Mathlib hash input changed")
    workspace = json.loads((root/"audit/runtime-workspace.json").read_bytes())
    identity = {"mathlib4": source_archive_identity(Path('/public/mathlib-source.tar.gz'), root/"mathlib4")}
    source_manifest = json.loads((root/"mathlib4/lake-manifest.json").read_bytes())
    for p in source_manifest["packages"]:
        identity[p["name"]] = {"revision": p["rev"], **source_archive_identity(Path('/public')/("package-"+p["name"]+".tar.gz"), root/"mathlib4/.lake/packages"/p["name"])}
    if identity != workspace["source_identities"]:
        raise RuntimeError("original source bytes changed during official unpack/prechecks")
    core.dump(root/"audit/runtime-prechecks.json", {"protocol": PROTOCOL, "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_workspace_sha256": sha(root/"audit/runtime-workspace.json"), "public_controls_sha256": sha(root/"audit/public-controls.json"),
        "restoration_complete_sha256": sha(root/"audit/restoration-complete.json"), "original_mathlib_inputs": after,
        "official_cache_identity": cached, "source_identities_unchanged": True, "candidate_run": False})
    print(json.dumps({"runtime_protocol": PROTOCOL, "prechecks_passed": True, "candidate_run": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["workspace", "unpack-probe"])
    parser.add_argument("--root", required=True)
    parser.add_argument("--public", default="/public")
    parser.add_argument("--lock-sha", required=True)
    parser.add_argument("--core-sha", required=True)
    parser.add_argument("--stand-sha", required=True)
    args = parser.parse_args()
    core = load_core("/plan/minif2f_restore.py", args.core_sha)
    if args.stage == "workspace":
        create_workspace(core, Path(args.root), args.public, args.lock_sha, args.stand_sha)
    else:
        core.public_lock(args.public, args.lock_sha)
        if sha("/plan/stand.py") != args.stand_sha:
            raise RuntimeError("original stand source changed")
        unpack_and_probe(core, Path(args.root))
