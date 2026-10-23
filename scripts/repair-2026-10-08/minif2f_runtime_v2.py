"""Genuine Lean DSL workspace v2, public controls, and exactly three old submits.

This is a new reconstruction protocol. Original Git checkouts are not claimed.
Workers receive original sources/cache/toolchain read-only. Only the explicitly
mounted v2 configuration metadata (workspace stage) and /out can be written.
The old failed runtime, old core, public pins and historical files are untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time

PROTOCOL = "reconstructed-lean-dsl-workspace-v2"
FAST_PROTOCOL = "bounded-official-cache-unpack-v1"
LOCK_SHA = "ee033a2d51ef5f7dc51b573285df3c2d78689fc9edcaaf8781420525c1d8d857"
BOOTSTRAP_SHA = "cf84863b8c93839a35ca7989cc7c83fad94d09444269d563a14b28324bc76a77"
KEYS_SHA = "bc7f8caa504054de03a3ec6a945de4a4ab7bdb12918029763c46bbb817d6dda9"
CORE_SHA = "8c8b77f6bf64ec6b07f82419dab8d0d5ee24bad3157cd51cfe2a942b8a28cd98"
IDENTITY_SHA = "46baef4522e00d5ecfaae7e88e9bc7c1eea68ff95a2c64f2a4f2f4a86bcab565"
GENERATOR_SHA = "1b455ba92d6c8af66508d9805bb011feaad55fcc5f12df7cfde455197081e58c"
SELECTION_SHA = "a11c23b29b2480ab7972a7059e8ca761cdf5032002e99bb7a9c69a4fc44430a7"
LEAN_HASH = "11651562caae0a0b3973811508db2ab8903d3854"
LAKE_SHA = "cbc8c15c933308a931dd3cdde188fd705130f4b4db9ef838e70e9d2e28e8a1b1"
LEAN_SHA = "eacf754d25ae86ea076882a34b9444f2485659d9df4266b821443b28ca95a215"
MAX_FILE = 64*1024**2
MAX_OUT = 16*1024**2
COUNT = 5826
CANDIDATE_INVOCATIONS = 0


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked_module(path, expected, name):
    if sha(path) != expected:
        raise RuntimeError("reviewed execution input changed: "+str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def durable_json(path, value):
    path = Path(path)
    data = (json.dumps(value, ensure_ascii=False, indent=2)+"\n").encode()
    if len(data) > MAX_OUT:
        raise RuntimeError("new receipt exceeds its 16 MiB output budget")
    temporary = path.with_name(path.name+".new")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def ordinary(path, directory=False):
    info = Path(path).lstat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise RuntimeError("unexpected nonregular execution input: "+str(path))
    return info


def read_review(path, expected):
    if sha(path) != expected:
        raise RuntimeError("independent v2 review changed")
    review = json.loads(Path(path).read_bytes())
    if review["protocol"] != PROTOCOL or review["public_lock_sha256"] != LOCK_SHA:
        raise RuntimeError("independent v2 review protocol/lock differs")
    if sha(__file__) != review["worker_sha256"]:
        raise RuntimeError("reviewed v2 worker changed")
    return review


def source_gate(root, full_toolchain=False):
    root = Path(root)
    if str(root) != "/cache":
        raise RuntimeError("fixed Linux cache mapping required")
    core = checked_module("/plan/minif2f_restore.py", CORE_SHA, "v2_core_identity")
    core.owner(root)  # Owner marker check only; no mutation or repeated tree scan.
    identity = checked_module("/plan/minif2f_runtime.py", IDENTITY_SHA, "v2_archive_identity")
    generator = checked_module("/plan/minif2f_native_v2_probe.py", GENERATOR_SHA, "v2_configuration")
    manifest, locked, _ = generator.archive_inputs()
    if sha(root/"audit/bootstrap.json") != BOOTSTRAP_SHA:
        raise RuntimeError("actual successful Bootstrap receipt differs")
    bootstrap = json.loads((root/"audit/bootstrap.json").read_bytes())
    if bootstrap["pins"] != core.PINS or bootstrap["public_lock_sha256"] != LOCK_SHA:
        raise RuntimeError("successful Bootstrap pins differ")
    if sha(root/"audit/module-cache-manifest.jsonl") != KEYS_SHA:
        raise RuntimeError("fixed official cache-key manifest differs")
    originals = identity.original_inputs(root)
    public = {n: sha(Path("/archives")/("mathlib-"+n)) for n in originals}
    for name, digest in public.items():
        entry = locked["mathlib-"+name]
        if digest != entry["sha256"] or (Path("/archives")/("mathlib-"+name)).stat().st_size != entry["bytes"]:
            raise RuntimeError("public original Mathlib hash-input bytes differ from frozen lock")
    if originals != public:
        raise RuntimeError("an original Mathlib hash input differs")
    sources = generator.identities(root/"mathlib4")
    expected = {
        root/"problems.jsonl": bootstrap["problems_sha256"],
        root/"repl/.lake/build/bin/repl": bootstrap["repl_binary_sha256"],
        root/"vendor/kimina-lean-server/client/kimina_client/models.py": bootstrap["models_sha256"],
        root/"toolchain/bin/lake": LAKE_SHA,
        root/"toolchain/bin/lean": LEAN_SHA,
    }
    for path, digest in expected.items():
        if sha(path) != digest:
            raise RuntimeError("fixed public executable/book/predicate differs: "+str(path))
    chain = identity.toolchain_identity(root) if full_toolchain else None
    return {"original_mathlib_inputs": originals, "source_identities": sources,
            "bootstrap": bootstrap, "manifest": manifest, "toolchain_manifest": chain}


def cache_identity(root):
    root = Path(root)
    complete_path = root/"audit/cache-fast-progress.json"
    complete = json.loads(complete_path.read_bytes())
    if (complete.get("protocol") != FAST_PROTOCOL or complete.get("validated") is not True
            or complete.get("state") != "batch_closed" or complete.get("cache_unpack_complete") is not True
            or complete.get("processed_prefix") != COUNT or complete.get("controls_executed") is not False):
        raise RuntimeError("full controlled official unpack prerequisite unavailable")
    receipt = root/"audit/cache-unpacked.jsonl"
    commits = root/"audit/cache-fast-commits.jsonl"
    if sha(receipt) != complete["receipts_sha256"] or sha(commits) != complete["commits_sha256"]:
        raise RuntimeError("closed controlled-unpack receipts changed")
    download_complete = json.loads((root/"audit/cache-download-complete.json").read_bytes())
    downloads_path = root/"audit/cache-downloads.jsonl"
    if sha(downloads_path) != download_complete["download_receipts_sha256"]:
        raise RuntimeError("original closed download receipts changed")
    download_rows = [json.loads(line) for line in downloads_path.read_text().splitlines()]
    downloaded = {r["ltar"]: r for r in download_rows}
    keys = [json.loads(line) for line in (root/"audit/module-cache-manifest.jsonl").read_text().splitlines()]
    names = {k["ltar"] for k in keys}
    if len(keys) != COUNT or len(names) != COUNT or len(download_rows) != COUNT or set(downloaded) != names:
        raise RuntimeError("official 5826 cache objects differ")
    for row in download_rows:
        if (row["url"] != "https://lakecache.blob.core.windows.net/mathlib4/f/"+row["ltar"]
                or not 0 < row["bytes"] <= MAX_FILE
                or len(row["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in row["sha256"])):
            raise RuntimeError("original public download URI/hash/size differs")
    package_manifest = json.loads((root/"mathlib4/lake-manifest.json").read_bytes())
    prefixes = [(".lake", "build")] + [
        (".lake", "packages", p["name"], ".lake", "build") for p in package_manifest["packages"]]
    raw_lines = receipt.read_bytes().splitlines(keepends=True)
    commit_rows = [json.loads(line) for line in commits.read_text().splitlines()]
    if len(raw_lines) != COUNT or len(commit_rows) != COUNT:
        raise RuntimeError("controlled unpack receipt/commit count differs")
    outputs, seen_keys, seen_paths, end = [], set(), set(), 0
    for raw, committed in zip(raw_lines, commit_rows):
        if not raw.endswith(b"\n"):
            raise RuntimeError("uncommitted receipt tail")
        record = json.loads(raw)
        name = record["ltar"]
        source = downloaded.get(name)
        if (name in seen_keys or source is None or record.get("protocol") != FAST_PROTOCOL
                or record["source_sha256"] != source["sha256"]
                or record["source_bytes"] != source["bytes"] or record["source_url"] != source["url"]
                or record.get("outputs_fsynced") is not True):
            raise RuntimeError("official unpack input/fsync provenance differs")
        seen_keys.add(name)
        end += len(raw)
        if (committed.get("protocol") != FAST_PROTOCOL or committed["ltar"] != name
                or committed["receipt_line_sha256"] != hashlib.sha256(raw).hexdigest()
                or committed["receipt_end"] != end or committed.get("receipt_fsync_returned") is not True):
            raise RuntimeError("durable controlled-unpack commit chain differs")
        files = record["files"]
        if not 1 <= len(files) <= 8:
            raise RuntimeError("official unpack per-object path count differs")
        for entry in files:
            path = PurePosixPath(entry["path"])
            if (path.is_absolute() or ".." in path.parts or str(path) != entry["path"]
                    or path.parts in seen_paths
                    or not any(path.parts[:len(prefix)] == prefix and len(path.parts) > len(prefix) for prefix in prefixes)):
                raise RuntimeError("official cached output path is ambiguous or outside native build roots")
            seen_paths.add(path.parts)
            target = root/"mathlib4"/path
            cursor = target.parent
            while cursor != root/"mathlib4":
                ordinary(cursor, directory=True)
                cursor = cursor.parent
            info = ordinary(target)
            if not 0 <= info.st_size <= MAX_FILE or info.st_size != entry["bytes"] or sha(target) != entry["sha256"]:
                raise RuntimeError("official cached output bytes changed: "+str(path))
            outputs.append(entry)
    if seen_keys != names:
        raise RuntimeError("missing official unpack cache objects")
    return {"protocol": FAST_PROTOCOL, "objects": COUNT, "files": len(outputs),
        "bytes": sum(e["bytes"] for e in outputs),
        "unpacked_receipts_sha256": sha(receipt), "commits_sha256": sha(commits),
        "full_unpacked_proof_sha256": sha(complete_path),
        "file_manifest_sha256": hashlib.sha256(json.dumps(outputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def native_environment(root):
    env = dict(os.environ)
    for name in ["LEAN_CC", "LEAN_AR", "LEAN_PATH", "LEAN_SRC_PATH", "LEAN_GITHASH", "LEAN_SYSROOT",
                 "LAKE_HOME", "LAKE_OVERRIDE_LEAN", "ELAN_HOME", "ELAN_TOOLCHAIN"]:
        env.pop(name, None)
    env.update({"PATH": str(root/"runtime-lake-v2/bin")+":"+str(root/"toolchain/bin")+":/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp", "XDG_CACHE_HOME": "/tmp", "TMPDIR": "/tmp", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(root/"python-support"), "TGENGIN_MF2F_HOME": str(root),
        "TGENGIN_MF2F_BACKEND": "repl", "TGENGIN_MF2F_REPLS": "1", "TGENGIN_MF2F_MEM_GB": "12",
        "TGENGIN_MF2F_TIMEOUT": "300", "TGENGIN_MF2F_MAX_USES": "4", "TGENGIN_MF2F_STRICT_AXIOMS": "0"})
    return env


def actual_native_probe(root, manifest):
    command = [str(root/"toolchain/bin/lake"), "-d", str(root/"runtime-lake-v2"), "-f", "lakefile.lean",
        "env", "python", "-c",
        'import os,json;print(json.dumps({k:os.environ.get(k) for k in ["LEAN_PATH","LEAN_SRC_PATH","LD_LIBRARY_PATH","LEAN_SYSROOT","LEAN_GITHASH","PATH"]}))']
    started = time.monotonic()
    result = subprocess.run(command, env=native_environment(root), capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError("actual native Lean DSL v2 failed: "+result.stderr.decode(errors="replace")[-6000:])
    actual = json.loads(result.stdout)
    paths = {str(Path(p).resolve()) for p in actual["LEAN_PATH"].split(":") if p}
    expected = {str(root/"mathlib4/.lake/build/lib"), str(root/"toolchain/lib/lean")} | {
        str(root/"mathlib4/.lake/packages"/p["name"]/".lake/build/lib") for p in manifest["packages"]}
    if paths != expected or actual["LEAN_GITHASH"] != LEAN_HASH or actual["LEAN_SYSROOT"] != str(root/"toolchain"):
        raise RuntimeError("actual native environment is not the exact ten pinned library roots/toolchain")
    return {"environment": actual, "command": command[:-1], "stderr": result.stderr.decode(errors="replace"),
            "elapsed_seconds": time.monotonic()-started, "library_roots_count": len(paths)}


def config_cache_identity(root, flush=False):
    paths = []
    for base in [root/"runtime-lake-v2/.lake", root/"runtime-lake-v2/proofwidgets-metadata"]:
        ordinary(base, directory=True)
        for path in sorted(base.iterdir()):
            if path.name == "build" and base.name == "proofwidgets-metadata":
                ordinary(path, directory=True)  # Empty host mountpoint; actual official build is mounted RO.
                continue
            if path.name not in {"lakefile.olean", "lakefile.olean.trace", "lakefile.olean.lock"}:
                raise RuntimeError("unexpected native configuration cache metadata: "+str(path))
            info = ordinary(path)
            if info.st_size > 32*1024**2:
                raise RuntimeError("native configuration cache exceeds its fixed file budget")
            if flush:
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
            paths.append({"path": path.relative_to(root/"runtime-lake-v2").as_posix(),
                          "bytes": info.st_size, "sha256": sha(path)})
        if not (base/"lakefile.olean").is_file() or not (base/"lakefile.olean.trace").is_file():
            raise RuntimeError("native configuration cache is incomplete")
    return paths


def workspace(root, output, review, review_sha):
    before = source_gate(root, full_toolchain=True)
    cached_before = cache_identity(root)
    directory = root/"runtime-lake-v2"
    if any(directory.iterdir()):
        # The host creates only the isolated metadata overlay/mountpoint.
        if {p.name for p in directory.iterdir()} != {"proofwidgets-metadata"}:
            raise RuntimeError("refuse existing v2 runtime configuration")
    generator = checked_module("/plan/minif2f_native_v2_probe.py", GENERATOR_SHA, "v2_dsl_generator")
    # The positive genuine native probe used an empty freshly created root.
    # Generate in tmpfs, then durably copy its exact configuration to new v2.
    temporary = Path("/tmp/v2-configuration")
    generator.configuration(temporary, before["manifest"])
    for name in ["lakefile.lean", "lake-manifest.json"]:
        with (directory/name).open("xb") as stream:
            stream.write((temporary/name).read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
    launcher = directory/"bin/lake"
    launcher.parent.mkdir()
    text = '''#!/bin/sh
set -eu
if [ "$#" -ne 2 ] || [ "$1" != env ] || [ "$2" != "/cache/repl/.lake/build/bin/repl" ]; then
  echo "reconstructed-lean-dsl-workspace-v2: only the fixed REPL lake env invocation is allowed" >&2
  exit 2
fi
exec "/cache/toolchain/bin/lake" -d "/cache/runtime-lake-v2" -f lakefile.lean env "$2"
'''
    with launcher.open("xb") as stream:
        stream.write(text.encode())
        stream.flush()
        os.fsync(stream.fileno())
    launcher.chmod(0o755)
    native = actual_native_probe(root, before["manifest"])
    caches = config_cache_identity(root, flush=True)
    after = source_gate(root)
    cached_after = cache_identity(root)
    if before["source_identities"] != after["source_identities"] or cached_before != cached_after:
        raise RuntimeError("original source or official cached bytes changed during v2 Workspace")
    durable_json(directory/"toolchain-files.json", before["toolchain_manifest"])
    files = {name: sha(directory/name) for name in ["lakefile.lean", "lake-manifest.json", "bin/lake", "toolchain-files.json"]}
    result = {"protocol": PROTOCOL, "completed": True, "recorded_at_utc": stamp(),
        "review_sha256": review_sha, "worker_sha256": review["worker_sha256"],
        "runtime_files": files, "config_cache_files": caches, "native_lake_probe": native,
        "source_identities": after["source_identities"], "original_mathlib_inputs": after["original_mathlib_inputs"],
        "official_cache_identity": cached_after, "bootstrap_receipt_sha256": BOOTSTRAP_SHA,
        "module_cache_manifest_sha256": KEYS_SHA, "public_lock_sha256": LOCK_SHA,
        "native_lake_sha256": LAKE_SHA, "native_lean_sha256": LEAN_SHA,
        "repl_sha256": before["bootstrap"]["repl_binary_sha256"],
        "stand_sha256": review["stand_sha256"], "new_runtime_protocol": True,
        "original_git_checkout_claimed": False, "old_failed_runtime_modified": False,
        "source_and_official_cache_mounts": "read-only; isolated proofwidgets config metadata overlay",
        "candidate_run": False, "llm_called": False, "public_get": False}
    durable_json(output/"runtime-workspace-v2.json", result)
    print(json.dumps({"workspace_v2_passed": True, "library_roots_count": 10, "candidate_run": False}))


def runtime_environment(root, workspace_receipt=None):
    root = Path(root)
    path = workspace_receipt or root/"audit/runtime-v2-workspace/runtime-workspace-v2.json"
    record = json.loads(path.read_bytes())
    if record["protocol"] != PROTOCOL or record.get("completed") is not True:
        raise RuntimeError("completed genuine v2 Workspace unavailable")
    identity = checked_module("/plan/minif2f_runtime.py", IDENTITY_SHA, "v2_original_input_identity")
    if identity.original_inputs(root) != record["original_mathlib_inputs"]:
        raise RuntimeError("original Mathlib hash inputs changed")
    for name, digest in record["runtime_files"].items():
        if sha(root/"runtime-lake-v2"/name) != digest:
            raise RuntimeError("isolated v2 runtime files changed")
    if config_cache_identity(root) != record["config_cache_files"]:
        raise RuntimeError("native Lean configuration cache changed")
    for path, digest in [(root/"toolchain/bin/lake", LAKE_SHA), (root/"toolchain/bin/lean", LEAN_SHA),
                         (root/"repl/.lake/build/bin/repl", record["repl_sha256"])]:
        if sha(path) != digest:
            raise RuntimeError("fixed executable changed")
    return native_environment(root)


def original_stand(root, review):
    if sha("/plan/stand.py") != review["stand_sha256"]:
        raise RuntimeError("original reviewed stand.py changed")
    env = runtime_environment(root)
    os.environ.clear()
    os.environ.update(env)
    sys.path.insert(0, str(root/"python-support"))
    spec = importlib.util.spec_from_file_location("mf2f_original_stand_v2", "/plan/stand.py")
    stand = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stand)
    if len(stand.BOOK) != 488:
        raise RuntimeError("exact original 488-problem book unavailable")
    return stand


def kill_idle(stand):
    for repl in stand.LEAN.idle:
        repl.kill()


def controls(root, output, review, review_sha):
    before = source_gate(root)
    cache_before = cache_identity(root)
    workspace_path = root/"audit/runtime-v2-workspace/runtime-workspace-v2.json"
    workspace_record = json.loads(workspace_path.read_bytes())
    if cache_before != workspace_record["official_cache_identity"]:
        raise RuntimeError("official cached bytes differ from v2 Workspace")
    stand = original_stand(root, review)
    header = "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n\n"
    results = {}
    try:
        for label, prop, tactic in [("good", "True", "trivial"), ("sorry", "True", "sorry"), ("wrong", "False", "trivial")]:
            name = "tgengin_restore_control_"+label
            item = {"name": name, "header": header, "statement": "theorem "+name+" : "+prop+" := by\n"}
            began = time.perf_counter()
            results[label] = {**stand.judge(item, header+item["statement"]+"  "+tactic),
                              "grading_wall_seconds": time.perf_counter()-began}
    finally:
        kill_idle(stand)
    wanted = {"good": [True, True, True], "sorry": [True, True, False], "wrong": [True, False, False]}
    passed = all([results[k][x] for x in ["stated", "compiles", "sound"]] == v
                 and not results[k].get("backend_error") for k, v in wanted.items())
    after = source_gate(root)
    cache_after = cache_identity(root)
    intact = before["source_identities"] == after["source_identities"] and cache_before == cache_after
    result = {"protocol": PROTOCOL, "recorded_at_utc": stamp(), "review_sha256": review_sha,
        "public_controls": results, "controls_passed": bool(passed and intact), "book_count": len(stand.BOOK),
        "runtime_workspace_sha256": sha(workspace_path), "official_cache_identity": cache_after,
        "source_identities_unchanged": intact, "candidate_run": False, "llm_called": False}
    durable_json(output/"public-controls-v2.json", result)
    if not result["controls_passed"]:
        raise RuntimeError("public dependency control failure; no historical candidate may be measured")
    durable_json(output/"runtime-prechecks-v2.json", {**result,
        "public_controls_sha256": sha(output/"public-controls-v2.json"),
        "original_mathlib_inputs": after["original_mathlib_inputs"], "source_identities": after["source_identities"]})
    print(json.dumps({"public_controls_v2_passed": True, "book_count": 488, "candidate_run": False}))


def candidates(root, output, review, review_sha):
    global CANDIDATE_INVOCATIONS
    bundle_path = Path("/private/legacy-final-3.json")
    if sha(bundle_path) != review["private_bundle_sha256"]:
        raise RuntimeError("frozen private last-submit bundle changed")
    selection = checked_module("/plan/minif2f_legacy_regrade.py", SELECTION_SHA, "v2_last_submit_selection")
    bundle = json.loads(bundle_path.read_bytes())
    records = selection.selected(bundle)  # Exact original three fingerprints/selection/deadlines.
    prechecks_path = root/"audit/runtime-v2-controls/runtime-prechecks-v2.json"
    prechecks = json.loads(prechecks_path.read_bytes())
    if (prechecks["protocol"] != PROTOCOL or prechecks.get("controls_passed") is not True
            or prechecks.get("source_identities_unchanged") is not True or prechecks.get("candidate_run") is not False):
        raise RuntimeError("genuine v2 True/sorry/False prechecks unavailable")
    workspace_path = root/"audit/runtime-v2-workspace/runtime-workspace-v2.json"
    controls_path = root/"audit/runtime-v2-controls/public-controls-v2.json"
    if sha(workspace_path) != prechecks["runtime_workspace_sha256"] or sha(controls_path) != prechecks["public_controls_sha256"]:
        raise RuntimeError("v2 Workspace or public control receipt changed")
    before = source_gate(root)
    began = time.perf_counter()
    cache_before = cache_identity(root)
    audit_seconds = time.perf_counter()-began
    if cache_before != prechecks["official_cache_identity"] or before["source_identities"] != prechecks["source_identities"]:
        raise RuntimeError("candidate input source/cache identity differs from prechecks")
    stand = original_stand(root, review)
    result = {"protocol": PROTOCOL, "classification": "post-hoc local diagnosis, not a new formal F run or historical score rewrite",
        "recorded_at_utc": stamp(), "review_sha256": review_sha,
        "bundle_sha256": sha(bundle_path), "runtime_harness_sha256": review["worker_sha256"],
        "stand_sha256": review["stand_sha256"], "runtime_prechecks_sha256": sha(prechecks_path),
        "workspace_receipt_sha256": sha(workspace_path), "bootstrap_receipt_sha256": BOOTSTRAP_SHA,
        "official_cache_identity_before": cache_before, "input_cache_audit_seconds": audit_seconds,
        "original_mathlib_inputs": before["original_mathlib_inputs"], "source_pins": before["bootstrap"]["pins"],
        "image_id": before["bootstrap"]["image_id"], "new_runtime_protocol": True, "network": "none",
        "cache_mount": "read-only", "llm_called": False, "candidate_or_private_gt_sent_externally": False,
        "timeout_seconds": 300, "cold_header_timeout_seconds": 600, "memory_gib": 12, "repl_pool_size": 1, "records": []}
    try:
        for record in records:
            began = time.perf_counter()
            started = stamp()
            try:
                CANDIDATE_INVOCATIONS += 1
                got = stand.judge(stand.BOOK[record["task"]], record["candidate"])
                unavailable = bool(got.get("backend_error"))
                value = None if unavailable else int(bool(got["stated"] and got["compiles"] and got["sound"]))
            except Exception as error:
                got = {"backend_error": type(error).__name__+": "+str(error)}
                unavailable, value = True, None
            result["records"].append({
                **{k: record[k] for k in ["run", "task", "candidate_sha256", "candidate_bytes", "description_sha256",
                    "call_id", "instance", "unit", "seq", "call_index", "at", "created_at", "solve_seconds",
                    "declared_deadline_at", "selection_rule", "stored_pass", "original_final_grading_candidate_digest_available"]},
                "deadline_eligible": record["at"] <= record["declared_deadline_at"], "started_at_utc": started,
                "grading_wall_seconds": time.perf_counter()-began, "pass": value, "valid": not unavailable,
                "outcome": "grader_error" if unavailable else "candidate_result",
                "measurement_unavailable": unavailable, "raw_local_lean_receipt": got})
            durable_json(output/"legacy-regrade-minif2f-v2.json", result)
    finally:
        kill_idle(stand)
    began = time.perf_counter()
    integrity_detail = None
    try:
        after = source_gate(root)
        cache_after = cache_identity(root)
        intact = before["source_identities"] == after["source_identities"] and cache_before == cache_after
    except Exception as error:
        cache_after, intact = None, False
        integrity_detail = type(error).__name__+": "+str(error)
    result.update({"output_cache_audit_seconds": time.perf_counter()-began,
        "official_cache_identity_after": cache_after, "cache_and_original_inputs_unchanged": intact})
    if not intact:
        result["environment_integrity_error"] = integrity_detail or "read-only original input fingerprint mismatch"
        for row in result["records"]:
            row.update({"valid": False, "pass": None, "outcome": "grader_error", "measurement_unavailable": True})
    result["summary"] = {"fixed_candidates": 3, "valid_measurements": sum(r["valid"] for r in result["records"]),
        "passed": sum(r["pass"] == 1 for r in result["records"]), "rejected": sum(r["pass"] == 0 for r in result["records"]),
        "unavailable": sum(r["measurement_unavailable"] for r in result["records"])}
    result["candidate_run"] = CANDIDATE_INVOCATIONS > 0
    durable_json(output/"legacy-regrade-minif2f-v2.json", result)
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["workspace", "controls", "candidates"])
    parser.add_argument("--review", default="/review/v2.json")
    parser.add_argument("--review-sha", required=True)
    args = parser.parse_args()
    reviewed = read_review(args.review, args.review_sha)
    root, output = Path("/cache"), Path("/out")
    ordinary(output, directory=True)
    try:
        {"workspace": workspace, "controls": controls, "candidates": candidates}[args.stage](
            root, output, reviewed, args.review_sha)
    except Exception as error:
        durable_json(output/"worker-failure.json", {"protocol": PROTOCOL, "stage": args.stage,
            "recorded_at_utc": stamp(), "error_type": type(error).__name__, "error": str(error),
            "measurement_unavailable": True, "candidate_run": CANDIDATE_INVOCATIONS > 0,
            "candidate_invocations": CANDIDATE_INVOCATIONS, "llm_called": False})
        raise
