"""Temporary public-source fixture and actual native Lean-DSL v2 env probe.

Fixture stage writes only its caller-provided F fixture. Probe stage writes
only tmpfs; all copied source bytes and the original toolchain are mounted RO.
No proof/candidate/LLM/cache GET is invoked.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tarfile
import time

LOCK_SHA = "ee033a2d51ef5f7dc51b573285df3c2d78689fc9edcaaf8781420525c1d8d857"
RUNTIME_SHA = "46baef4522e00d5ecfaae7e88e9bc7c1eea68ff95a2c64f2a4f2f4a86bcab565"
LEAN_HASH = "11651562caae0a0b3973811508db2ab8903d3854"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime():
    path = Path("/plan/minif2f_runtime.py")
    if sha(path) != RUNTIME_SHA:
        raise RuntimeError("frozen failed runtime source changed")
    spec = importlib.util.spec_from_file_location("identity_only_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def archive_inputs():
    path = Path("/archives/public-lock.json")
    if sha(path) != LOCK_SHA:
        raise RuntimeError("frozen public lock differs")
    lock = json.loads(path.read_bytes())
    entries = {e["file"]: e for e in lock["entries"]}
    manifest = json.loads(Path("/archives/mathlib-lake-manifest.json").read_bytes())
    selected = ["mathlib-source.tar.gz"]+["package-"+p["name"]+".tar.gz" for p in manifest["packages"]]
    for name in selected+["mathlib-lake-manifest.json"]:
        path = Path("/archives")/name
        if path.stat().st_size != entries[name]["bytes"] or sha(path) != entries[name]["sha256"]:
            raise RuntimeError("fixed copied public input differs: "+name)
    return manifest, entries, selected


def identities(base):
    module = runtime()
    manifest, entries, selected = archive_inputs()
    result = {"mathlib4": module.source_archive_identity(Path("/archives/mathlib-source.tar.gz"), base)}
    for package in manifest["packages"]:
        name = package["name"]
        result[name] = {"revision": package["rev"], **module.source_archive_identity(
            Path("/archives")/("package-"+name+".tar.gz"), base/".lake/packages"/name)}
    return result


def fixture(destination):
    destination = Path(destination)
    if any(destination.iterdir()):
        raise RuntimeError("fixture must be a new empty owned directory")
    manifest, entries, selected = archive_inputs()
    total = 0
    for name in selected:
        with tarfile.open(Path("/archives")/name, "r:gz") as source:
            total += sum(m.size for m in source.getmembers())
    if total > 256*1024**2 or shutil.disk_usage(destination).free-total-32*1024**2 < 1024**3:
        raise RuntimeError("F public fixture cap/reserve would be violated")
    for index, name in enumerate(selected):
        target = destination/"mathlib4" if index == 0 else destination/"mathlib4/.lake/packages"/manifest["packages"][index-1]["name"]
        temporary = destination/("extract-"+str(index))
        temporary.mkdir()
        with tarfile.open(Path("/archives")/name, "r:gz") as source:
            members = source.getmembers()
            prefixes = {m.name.split("/")[0] for m in members}
            if len(prefixes) != 1:
                raise RuntimeError("fixed public archive has unexpected roots")
            source.extractall(temporary, filter="data")
        target.parent.mkdir(parents=True, exist_ok=True)
        (temporary/next(iter(prefixes))).rename(target)
        temporary.rmdir()
    original = identities(destination/"mathlib4")
    # Precreate only the empty metadata mountpoint. Native config compilation
    # gets a tmpfs there; it cannot write any copied original source directory.
    (destination/"mathlib4/.lake/packages/proofwidgets/.lake").mkdir()
    record = {"scope": "public archive copies only, not an original Git checkout", "source_identities": original,
              "copied_logical_source_bytes": total, "candidate_run": False, "e_write": False}
    (destination/"fixture-sources.json").write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps({"fixture_ready": True, "source_bytes": total, "source_packages": 8, "e_write": False,
                      "candidate_run": False}))


def configuration(root, manifest):
    root = Path(root)
    root.mkdir()
    source = Path("/cache/mathlib4/lakefile.lean").read_text()
    requires = re.findall(r'^require\s+"([^"]+)"\s*/\s*"([^"]+)"', source, re.M)
    if {n for _, n in requires} != {p["name"] for p in manifest["packages"] if not p["inherited"]}:
        raise RuntimeError("original seven root dependencies differ")
    dsl = ['import Lake', 'open Lake DSL', '', 'package mathlib where',
           '  manifestFile := some "lake-manifest.json"', '  srcDir := "/cache/mathlib4"',
           '  buildDir := "/cache/mathlib4/.lake/build"', '']
    for scope, name in requires:
        dsl.append(f'require "{scope}" / "{name}" from "/cache/mathlib4/.lake/packages/{name}"')
    for name in ["Mathlib", "Cache", "LongestPole", "MathlibTest", "Archive", "Counterexamples", "docs"]:
        dsl += ['', 'lean_lib '+name]
    (root/"lakefile.lean").write_text("\n".join(dsl)+"\n")
    entries = [{"type": "path", "dir": "/cache/mathlib4/.lake/packages/"+p["name"],
                **{k: p[k] for k in ["name", "scope", "inherited", "configFile", "manifestFile"]}}
               for p in manifest["packages"]]
    path_manifest = {"version": manifest["version"], "name": manifest["name"], "lakeDir": manifest["lakeDir"],
                     "packagesDir": manifest["packagesDir"], "packages": entries}
    (root/"lake-manifest.json").write_text(json.dumps(path_manifest, indent=2)+"\n")
    return path_manifest


def probe():
    base = Path("/cache/mathlib4")
    before = identities(base)
    original_base = Path("/original/mathlib4")
    original_before = identities(original_base)
    if original_before != before:
        raise RuntimeError("current restored E source differs from the fixed public archive fixture")
    manifest, _, _ = archive_inputs()
    root = Path("/tmp/runtime-lake-v2")
    path_manifest = configuration(root, manifest)
    env = dict(os.environ)
    for name in ["LEAN_CC", "LEAN_AR", "LEAN_PATH", "LEAN_SRC_PATH", "LEAN_GITHASH", "LEAN_SYSROOT", "LAKE_HOME", "LAKE_OVERRIDE_LEAN", "ELAN_HOME", "ELAN_TOOLCHAIN"]:
        env.pop(name, None)
    env.update({"PATH": "/cache/toolchain/bin:/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp",
                "XDG_CACHE_HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1"})
    command = ["/cache/toolchain/bin/lake", "-d", str(root), "-f", "lakefile.lean", "env", "python", "-c",
        'import os,json;print(json.dumps({k:os.environ.get(k) for k in ["LEAN_PATH","LEAN_SRC_PATH","LD_LIBRARY_PATH","LEAN_SYSROOT","LEAN_GITHASH","PATH"]}))']
    started = time.monotonic()
    result = subprocess.run(command, env=env, capture_output=True, timeout=600)
    native_elapsed = time.monotonic()-started
    after = identities(base)
    original_after = identities(original_base)
    if after != before or original_after != original_before:
        raise RuntimeError("copied or actual original source identity changed during native probe")
    if result.returncode:
        raise RuntimeError("actual native v2 probe failed: "+result.stderr.decode(errors="replace")[-6000:])
    got = json.loads(result.stdout)
    paths = {str(Path(p).resolve()) for p in got["LEAN_PATH"].split(":") if p}
    expected = {"/cache/mathlib4/.lake/build/lib", "/cache/toolchain/lib/lean"}
    expected |= {"/cache/mathlib4/.lake/packages/"+p["name"]+"/.lake/build/lib" for p in manifest["packages"]}
    if paths != expected or got["LEAN_GITHASH"] != LEAN_HASH or got["LEAN_SYSROOT"] != "/cache/toolchain":
        raise RuntimeError("actual native v2 environment is not the exact ten pinned library roots/toolchain")
    print(json.dumps({"native_v2_probe_passed": True, "actual_environment": got, "library_roots_count": len(paths),
        "native_command": command[:-1], "native_stderr": result.stderr.decode(errors="replace"),
        "native_elapsed_seconds": native_elapsed,
        "native_lake_sha256": sha("/cache/toolchain/bin/lake"),
        "native_lean_sha256": sha("/cache/toolchain/bin/lean"),
        "lean_dsl_sha256": sha(root/"lakefile.lean"), "path_manifest_sha256": sha(root/"lake-manifest.json"),
        "source_identities_before_after_same": True, "source_identities": before,
        "actual_original_source_identities_before_after_same": True,
        "actual_original_source_identities_match_fixture": True,
        "new_runtime_protocol": "reconstructed-lean-dsl-workspace-v2",
        "sources_mount": "read-only copied original public archives", "original_toolchain_mount": "read-only",
        "actual_original_source_mount": "read-only at /original/mathlib4; no nested writable mounts",
        "configuration_and_proofwidgets_config_cache": "tmpfs only", "e_write": False, "public_get": False,
        "candidate_run": False, "not_original_git_checkout": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["fixture", "probe"])
    parser.add_argument("--fixture", default="/fixture")
    args = parser.parse_args()
    fixture(args.fixture) if args.stage == "fixture" else probe()
