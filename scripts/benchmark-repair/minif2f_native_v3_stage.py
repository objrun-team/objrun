"""Host coordinator for independently reviewed native v3 / fast-unpack v2.

No stage executes on import. The parent schedules all E writers serially.
An independent native lease is used as a cooperative mutex. The full public
acquisition marker is held read-only share-deny and never overwritten.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time

PROTOCOL = "reconstructed-lean-dsl-workspace-v3-fast-v2"
ROOT = Path("E:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/minif2f-v415")
PROJECT = Path("F:/git/TgEngin-handoff-2026-10-07/TgEngin")
IMAGE = "sha256:adccbc2412fe240d3bba28a81e136d2e816a28b003263a2f1738098a67cbfbba"
RUN_ID = "01a119ed-fdf7-7c32-b323-de9bab1290b6"
HELPER_SHA = "a02c3519b0ccba8a74e577991fedcf75f0c05fb181cfeb617b7e51b060384c2b"
META_BUDGET = 64*1024**2
OUT_BUDGET = 16*1024**2
CONTAINER_MEMORY = 12*1024**3
HOST_HEADROOM = 1024**3
STAGES = {"Workspace": "workspace", "Controls": "controls", "Candidates": "candidates"}
NATIVE_LEASE = "cache-native-v3.lock"


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def module(path, expected, name):
    if sha(path) != expected:
        raise RuntimeError("reviewed execution source changed: "+str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def checked_review(path):
    review = json.loads(Path(path).read_bytes())
    if review["protocol"] != PROTOCOL or review["public_helper_sha256"] != HELPER_SHA:
        raise RuntimeError("independent v3 review protocol/helper differs")
    for entry in review["files"]:
        target = Path(entry["path"])
        if not target.is_relative_to(PROJECT) or target.stat().st_size != entry["bytes"] or sha(target) != entry["sha256"]:
            raise RuntimeError("independent reviewed file bytes differ: "+str(target))
    if sha(__file__) != review["host_sha256"]:
        raise RuntimeError("unreviewed native v3 host coordinator")
    public = PROJECT/".phase1-data/minif2f-restoration-public"
    if sha(public/"public-lock.json") != review["public_lock_sha256"]:
        raise RuntimeError("frozen public material lock differs")
    graph = review.get("fast_v2_graph")
    if not isinstance(graph, dict) or graph.get("protocol") != "bounded-official-cache-unpack-v2-archive-dot-prefix":
        raise RuntimeError("actual root-reviewed full fast v2/recovery graph required")
    for role, name in [("fast_python_sha256", "minif2f_fast_unpack_v2.py"),
                       ("recovery_python_sha256", "minif2f_fast_prefix0_recovery.py")]:
        if sha(PROJECT/"scripts/benchmark-repair"/name) != graph.get(role):
            raise RuntimeError("reviewed final fast/recovery source changed")
    history = review.get("prefix0_history")
    worker = module(PROJECT/"scripts/benchmark-repair/minif2f_runtime_v3.py", review["worker_sha256"], "v3_history_shape")
    if not isinstance(history, dict) or set(history) != worker.PREFIX0_HISTORY_NAMES | {"closure.json"}:
        raise RuntimeError("exact immutable pre-first2 snapshot pins required")
    for name, entry in history.items():
        expected = PROJECT/"docs/repair-2026-10-08/minif2f-prefix0-actual-closure"/name
        if Path(entry.get("path", "")).resolve() != expected.resolve() or sha(expected) != entry.get("sha256"):
            raise RuntimeError("historical source path/bytes changed")
    return review


def memory_policy_record(available, total):
    if type(available) is not int or type(total) is not int or not 0 <= available <= total:
        raise RuntimeError("native physical memory observation is unavailable/invalid")
    result = {"observed_at_utc": stamp(), "method": "Win32 GlobalMemoryStatusEx",
        "total_physical_bytes": total, "available_physical_bytes": available,
        "container_limit_bytes": CONTAINER_MEMORY, "additional_host_headroom_bytes": HOST_HEADROOM,
        "required_available_bytes": CONTAINER_MEMORY+HOST_HEADROOM}
    if available < result["required_available_bytes"]:
        raise RuntimeError("typed resource prerequisite: native 12GiB plus 1GiB host headroom unavailable: "+json.dumps(result))
    return result


def host_memory_gate():
    """Fresh native Windows physical memory; no model, Docker or subprocess."""
    if os.name != "nt":
        raise RuntimeError("fresh native Windows memory observation required")
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
            (name, ctypes.c_uint64) for name in ["total_physical", "available_physical",
                "total_page", "available_page", "total_virtual", "available_virtual", "available_extended"]]
    value = MemoryStatus()
    value.length = ctypes.sizeof(value)
    function = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
    function.argtypes, function.restype = [ctypes.POINTER(MemoryStatus)], ctypes.c_int
    if not function(ctypes.byref(value)):
        raise RuntimeError("native physical-memory query failed: "+str(ctypes.get_last_error()))
    return memory_policy_record(value.available_physical, value.total_physical)


def run(command, timeout=30):
    result = subprocess.run(command, capture_output=True, timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise RuntimeError("local subprocess failed: "+result.stderr.decode(errors="replace")[-4000:])
    return result.stdout.decode("utf-8-sig").strip()


def ordinary_directory(path):
    cursor = Path(path)
    while cursor != ROOT.parent:
        info = cursor.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise RuntimeError("runtime path has a nonordinary/reparse ancestor: "+str(cursor))
        cursor = cursor.parent


def metadata_envelope(paths):
    total = 0
    for base in paths:
        if not base.exists():
            continue
        for directory, dirs, files in os.walk(base, followlinks=False):
            info = Path(directory).lstat()
            if getattr(info, "st_file_attributes", 0) & 0x400:
                raise RuntimeError("unexpected runtime metadata reparse directory")
            total += 4096
            for name in dirs+files:
                target = Path(directory)/name
                info = target.lstat()
                if getattr(info, "st_file_attributes", 0) & 0x400:
                    raise RuntimeError("unexpected runtime metadata reparse point")
                if name in files:
                    if not stat.S_ISREG(info.st_mode):
                        raise RuntimeError("unexpected nonregular runtime metadata file")
                    total += ((info.st_size+4095)//4096)*4096+4096
    if total > META_BUDGET:
        raise RuntimeError("runtime metadata/output exceeded the reserved 64 MiB")
    return total


def foreign_container_probe(helper, owned_id):
    listed = run(["docker", "ps", "--no-trunc", "--format", "{{.ID}}"]).split()
    foreign = [cid for cid in listed if cid != owned_id]
    conflicts = []
    if foreign:
        objects = json.loads(run(["docker", "inspect", *foreign]))
        root = helper.normalize_mount(str(ROOT))
        for container in objects:
            for mount in container.get("Mounts", []):
                source = helper.normalize_mount(mount.get("Source", ""))
                overlaps = source and (source == root or source.startswith(root+"/") or root.startswith(source+"/"))
                if overlaps and mount.get("RW"):
                    conflicts.append({"container_id": container["Id"], "source": source})
    if conflicts:
        raise RuntimeError("another observed Docker writer overlaps E owned root: "+json.dumps(conflicts))
    return {"foreign_running_containers_checked": foreign, "writable_mount_conflicts": []}


def fast_prerequisite(review):
    worker = module(PROJECT/"scripts/benchmark-repair/minif2f_runtime_v3.py",
                    review["worker_sha256"], "v3_fast_graph_gate")
    graph = worker.fast_graph_gate(ROOT, review, {
        "fast_python_sha256": PROJECT/"scripts/benchmark-repair/minif2f_fast_unpack_v2.py",
        "recovery_python_sha256": PROJECT/"scripts/benchmark-repair/minif2f_fast_prefix0_recovery.py",
    }, history_paths={name: Path(p["path"]) for name, p in review["prefix0_history"].items()})
    path = ROOT/"audit/cache-fast-progress.json"
    if not path.is_file():
        raise RuntimeError("typed prerequisite: complete official controlled unpack is unavailable")
    value = json.loads(path.read_bytes())
    if (value.get("protocol") != "bounded-official-cache-unpack-v2-archive-dot-prefix" or value.get("validated") is not True
            or value.get("state") != "batch_closed" or value.get("cache_unpack_complete") is not True
            or value.get("processed_prefix") != 5826 or value.get("controls_executed") is not False):
        raise RuntimeError("typed prerequisite: controlled unpack is not closed for all 5826 objects")
    for relative in ["mathlib4/.lake/packages/proofwidgets/.lake",
                     "mathlib4/.lake/packages/proofwidgets/.lake/build"]:
        ordinary_directory(ROOT/relative)
    return graph


def container_args(stage, review_path, review_sha, output, review):
    runtime = ROOT/"runtime-lake-v3"
    metadata = runtime/"proofwidgets-metadata"
    original_build = ROOT/"mathlib4/.lake/packages/proofwidgets/.lake/build"
    readonly = stage != "Workspace"
    name = "minif2f-native-v3-"+STAGES[stage]+"-"+RUN_ID[:8]
    args = ["docker", "create", "--name", name, "--pull", "never", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
        "--cpus", "2", "--memory", "12g", "--memory-swap", "12g", "--pids-limit", "128",
        "--log-driver", "none", "--shm-size", "16m",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=117440512,mode=1777",
        "--label", "tgengin.minif2f-owned="+RUN_ID, "--label", "tgengin.minif2f.stage=native-v3-"+STAGES[stage],
        "--env", "PYTHONDONTWRITEBYTECODE=1"]
    mounts = [(ROOT, "/cache", True), (runtime, "/cache/runtime-lake-v3", readonly),
        (metadata, "/cache/mathlib4/.lake/packages/proofwidgets/.lake", readonly),
        (original_build, "/cache/mathlib4/.lake/packages/proofwidgets/.lake/build", True),
        (output, "/out", False), (Path(review_path), "/review/v3.json", True)]
    plan = PROJECT/"scripts/benchmark-repair"
    for filename in ["minif2f_runtime_v3.py", "minif2f_restore.py", "minif2f_runtime.py",
                     "minif2f_native_v2_probe.py", "minif2f_legacy_regrade.py",
                     "minif2f_fast_unpack_v2.py", "minif2f_fast_prefix0_recovery.py"]:
        mounts.append((plan/filename, "/plan/"+filename, True))
    mounts.append((PROJECT/"examples/benchmark/minif2f/stand.py", "/plan/stand.py", True))
    mounts.extend((Path(p["path"]), "/history-prefix0/"+name, True)
                  for name, p in review["prefix0_history"].items())
    public = PROJECT/".phase1-data/minif2f-restoration-public"
    names = ["public-lock.json", "mathlib-lake-manifest.json", "mathlib-lakefile.lean", "mathlib-lean-toolchain",
        "mathlib-source.tar.gz"]+["package-"+name+".tar.gz" for name in
        ["plausible", "LeanSearchClient", "importGraph", "proofwidgets", "aesop", "Qq", "batteries", "Cli"]]
    mounts.extend((public/name, "/archives/"+name, True) for name in names)
    if stage == "Candidates":
        mounts.append((PROJECT/".phase1-data/minif2f-restoration-private/legacy-final-3.json",
                       "/private/legacy-final-3.json", True))
    for source, destination, ro in mounts:
        args += ["--mount", "type=bind,source="+source.as_posix()+",target="+destination+(",readonly" if ro else "")]
    args += [IMAGE, "python", "/plan/minif2f_runtime_v3.py", STAGES[stage], "--review-sha", review_sha]
    return args, mounts


def inspect_owned(cid, mounts, stage):
    obj = json.loads(run(["docker", "inspect", "--size", cid]))[0]
    helper = module(PROJECT/"scripts/benchmark-repair/minif2f_public_cache.py", HELPER_SHA, "v2_mount_helper")
    expected = {(helper.normalize_mount(source.as_posix()), destination): not readonly
                for source, destination, readonly in mounts}
    actual = {(helper.normalize_mount(m["Source"]), m["Destination"]): bool(m["RW"]) for m in obj["Mounts"]}
    config = obj["HostConfig"]
    if (actual != expected or obj["Id"] != cid
            or obj["Name"] != "/minif2f-native-v3-"+STAGES[stage]+"-"+RUN_ID[:8]
            or obj["Config"]["Labels"].get("tgengin.minif2f-owned") != RUN_ID
            or obj["Config"]["Labels"].get("tgengin.minif2f.stage") != "native-v3-"+STAGES[stage]
            or obj["Config"]["User"] != "65534:65534"
            or obj["Image"] != IMAGE or config["NetworkMode"] != "none"
            or not obj["HostConfig"]["ReadonlyRootfs"] or obj["SizeRw"] > 128*1024**2
            or config["ShmSize"]+117440512 != 128*1024**2
            or config["Memory"] != 12*1024**3 or config["MemorySwap"] != 12*1024**3
            or config["PidsLimit"] != 128 or config["CapDrop"] != ["ALL"]
            or config["SecurityOpt"] != ["no-new-privileges"]
            or config["Tmpfs"] != {"/tmp": "rw,nosuid,nodev,size=117440512,mode=1777"}):
        raise RuntimeError("owned runtime container restrictions/mounts differ")
    return obj


def historical_snapshot(review):
    selection = module(PROJECT/"scripts/benchmark-repair/minif2f_legacy_regrade.py",
                       review["legacy_selection_sha256"], "v2_historical_selection")
    path = PROJECT/".phase1-data/minif2f-restoration-private/legacy-final-3.json"
    if sha(path) != review["private_bundle_sha256"]:
        raise RuntimeError("fixed private input bundle differs")
    bundle = json.loads(path.read_bytes())
    selection.selected(bundle)
    return selection.source_snapshot(bundle["source_files"])


def execute(stage, review_path, expected_review_sha):
    if expected_review_sha is None or sha(review_path) != expected_review_sha:
        raise RuntimeError("exact root-reviewed v3 review SHA required for any E stage")
    review = checked_review(review_path)
    review_sha = sha(review_path)
    helper = module(PROJECT/"scripts/benchmark-repair/minif2f_public_cache.py", HELPER_SHA, "v2_host_guard")
    helper.exact_root(ROOT)
    helper.allocation_unit()
    helper.volume_reserves(META_BUDGET+65536)
    helper.inputs(ROOT, PROJECT/".phase1-data/minif2f-restoration-public",
                  PROJECT/"scripts/benchmark-repair/minif2f_restore.py")
    fast = fast_prerequisite(review)  # Complete5826 graph before any E mutation/lease.
    memory = host_memory_gate()  # The frozen 12GiB limit is not lowered to fit pressure.
    runtime = ROOT/"runtime-lake-v3"
    output = ROOT/"audit"/("runtime-v3-"+STAGES[stage])
    if output.exists() or (stage == "Workspace" and runtime.exists()):
        raise RuntimeError("typed prerequisite: existing stage artifacts require review; no automatic rerun")
    if stage != "Workspace":
        ordinary_directory(runtime)
    historical_before = historical_snapshot(review) if stage == "Candidates" else None
    lease = helper.Lease(ROOT/"audit"/NATIVE_LEASE)
    producer = module(PROJECT/"scripts/benchmark-repair/minif2f_fast_unpack_v2.py",
                      review["fast_v2_graph"]["fast_python_sha256"], "v3_original_acquisition_guard")
    acquisition = producer.AcquisitionGuard(ROOT/"audit"/helper.LEASE_NAME)
    cid, process, initial, final, status = None, None, None, None, "aborted"
    leased, acquisition_held = False, False
    began = time.monotonic()
    result = {"protocol": PROTOCOL, "stage": stage, "review_sha256": review_sha, "began_at_utc": stamp(),
              "metadata_reservation_bytes": META_BUDGET, "public_get": False, "llm_called": False,
              "execution_protocol_note": "old native v2 and failed v1 are preserved; independent fast-v2 consumer",
              "initial_host_memory_gate": memory, "actual_fast_graph_sha256": fast["graph_sha256"]}
    try:
        acquisition.__enter__()
        acquisition_held = True
        if acquisition.sha256 != fast["full_progress"]["original_acquisition_lease_sha256"]:
            raise RuntimeError("original complete acquisition marker differs from the full decode proof")
        result["original_acquisition_marker_sha256"] = acquisition.sha256
        lease.acquire()
        leased = True
        lease.write({"held": True, "acquired_at_utc": stamp(), "pid": os.getpid(),
                     "execution_protocol": PROTOCOL, "stage": stage})
        result["initial_writer_probe"] = helper.writer_probe()
        initial = helper.full_scan(ROOT)
        if initial["allocated_envelope_bytes"]+META_BUDGET+65536 > helper.CAP:
            raise RuntimeError("initial owned allocation plus reserved metadata crosses 14 GiB")
        result["initial_envelope"] = initial
        result["pre_create_host_memory_gate"] = host_memory_gate()
        if stage == "Workspace":
            runtime.mkdir()
            (runtime/"proofwidgets-metadata/build").mkdir(parents=True)
        output.mkdir()
        args, mounts = container_args(stage, review_path, review_sha, output, review)
        cid = run(args)
        if len(cid) != 64 or any(c not in "0123456789abcdef" for c in cid):
            raise RuntimeError("owned Docker create returned an unknown identity")
        inspection = inspect_owned(cid, mounts, stage)
        helper.durable_json(output/"container-initial.json", inspection)
        stdout, stderr = output/"stdout.log", output/"stderr.log"
        with stdout.open("xb") as out, stderr.open("xb") as err:
            result["pre_start_host_memory_gate"] = host_memory_gate()
            process = subprocess.Popen(["docker", "start", "--attach", cid], stdout=out, stderr=err,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            checks, peak = 0, 0
            while process.poll() is None:
                time.sleep(2)
                metadata = metadata_envelope([runtime, output])
                peak = max(peak, metadata)
                helper.volume_reserves(META_BUDGET)
                if stdout.stat().st_size+stderr.stat().st_size > OUT_BUDGET:
                    raise RuntimeError("runtime logs exceeded the 16 MiB output budget")
                if time.monotonic()-began > 3*3600:
                    raise RuntimeError("native v3 stage exceeded three-hour wall budget")
                if checks % 5 == 0:
                    foreign_container_probe(helper, cid)
                    inspect_owned(cid, mounts, stage)
                if checks % 15 == 0:
                    print(json.dumps({"native_v3_stage": stage, "elapsed_seconds": time.monotonic()-began,
                                      "metadata_envelope_bytes": metadata, "candidate_stage": stage == "Candidates"}), flush=True)
                checks += 1
            process.wait()
            out.flush()
            err.flush()
            os.fsync(out.fileno())
            os.fsync(err.fileno())
        state = inspect_owned(cid, mounts, stage)
        helper.durable_json(output/"container-final.json", state)
        if process.returncode != 0 or state["State"]["ExitCode"] != 0:
            raise RuntimeError("native v2 worker failed; original stage logs retained at "+str(output))
        final = helper.full_scan(ROOT)
        if final["allocated_envelope_bytes"] > helper.CAP:
            raise RuntimeError("final owned allocation crosses 14 GiB")
        helper.volume_reserves()
        if sha(review_path) != review_sha:
            raise RuntimeError("independently reviewed native v3 authorization changed during stage")
        checked_review(review_path)
        result["reviewed_execution_sources_unchanged_at_end"] = True
        if stage == "Candidates":
            historical_after = historical_snapshot(review)
            if historical_after != historical_before:
                raise RuntimeError("historical files changed during read-only candidate diagnosis")
            result["historical_sources_before"] = historical_before
            result["historical_sources_after"] = historical_after
        result.update({"final_envelope": final, "metadata_envelope_peak_bytes": peak,
            "observed_process_checks": checks, "worker_exit_code": state["State"]["ExitCode"],
            "source_and_cache_mounts": "read-only; isolated config metadata overlay only",
            "fixed_prerequisite_sha256": sha(ROOT/"audit/cache-fast-progress.json"),
            "sole_writer_requirement": "root serial scheduling plus cooperative Windows lease; host regex is not exhaustive"})
        status = "complete"
    except Exception as error:
        result["error_type"], result["error"] = type(error).__name__, str(error)
        raise
    finally:
        cleanup_ok = True
        if cid is not None:
            # Only this exact successfully created owned CID is removed.
            removed = subprocess.run(["docker", "rm", "--force", cid], capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            result["owned_container_removal_exit_code"] = removed.returncode
            gone = subprocess.run(["docker", "inspect", cid], capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            cleanup_ok = removed.returncode == 0 and gone.returncode != 0 and b"No such" in gone.stderr
            result["owned_container_absent_after_exact_removal"] = cleanup_ok
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                cleanup_ok = False
        if not cleanup_ok:
            status = "cleanup_failed"
        result.update({"state": status, "finished_at_utc": stamp(), "elapsed_seconds": time.monotonic()-began})
        try:
            if acquisition_held:
                acquisition.stream.seek(0)
                if hashlib.sha256(acquisition.stream.read(16385)).hexdigest() != acquisition.sha256:
                    raise RuntimeError("original read-only acquisition marker changed during native stage")
                result["original_acquisition_marker_bytes_unchanged"] = True
            if leased:
                lease.write({"held": not cleanup_ok, "result": status, "released_at_utc": stamp() if cleanup_ok else None,
                             "execution_protocol": PROTOCOL, "stage": stage})
        finally:
            try:
                lease.close()  # Also closes an acquired handle if its first write failed.
            finally:
                if acquisition_held:
                    acquisition.__exit__(None, None, None)
        result["native_lease_handles_closed"] = True
        if output.exists():
            helper.durable_json(output/"host-stage-proof.json", result)
        # Retain and hash the exact new stage artifacts in an independent F directory.
        if output.exists():
            archive = PROJECT/"docs/repair-2026-10-08/minif2f-native-v3-stages"/STAGES[stage]
            if archive.exists():
                raise RuntimeError("refuse overwriting an existing F v3 stage archive")
            shutil.copytree(output, archive, symlinks=True)
            fingerprints = []
            for original in sorted(output.rglob("*")):
                if original.is_file():
                    copied = archive/original.relative_to(output)
                    if copied.stat().st_size != original.stat().st_size or sha(copied) != sha(original):
                        raise RuntimeError("F archive differs from original new-stage evidence")
                    fingerprints.append({"path": original.relative_to(output).as_posix(),
                                         "bytes": original.stat().st_size, "sha256": sha(original)})
            lease_path = ROOT/"audit"/NATIVE_LEASE
            shutil.copyfile(lease_path, archive/"lease-after-stage.json")
            if sha(archive/"lease-after-stage.json") != sha(lease_path):
                raise RuntimeError("F lease snapshot differs")
            helper.durable_json(archive/"archive-file-manifest.json", {"files": fingerprints,
                "lease_release_sha256": sha(lease_path), "owned_cleanup_verified": cleanup_ok})
            result["f_archive"] = str(archive)
        if not cleanup_ok:
            raise RuntimeError("exact owned container cleanup not proven; held marker preserved for root review")
    print(json.dumps({"native_v3_stage": stage, "state": status, "f_archive": result["f_archive"]}), flush=True)


def gate(review_path):
    review = checked_review(review_path)
    probe = json.loads((PROJECT/"docs/repair-2026-10-08/minif2f-native-v2-probe.json").read_bytes())
    if not probe.get("native_v2_probe_passed") or probe["library_roots_count"] != 10:
        raise RuntimeError("actual native positive probe is absent")
    fast = fast_prerequisite(review)
    memory = host_memory_gate()
    print(json.dumps({"protocol": PROTOCOL, "review_sha256": sha(review_path),
        "frozen_execution_files": len(review["files"]), "inherited_native_v2_configuration_probe_passed": True,
        "actual_native_v3_execution_passed": None, "actual_full_fast_graph_sha256": fast["graph_sha256"],
        "fresh_host_memory_gate": memory,
        "native_fixture_scope": probe["sources_mount"], "e_write": False, "candidate_run": False,
        "executing_stages_require": "root serial review, full5826 fast-v2 outputs rechecked by worker, fresh13GiB physical memory, exact same-code gate"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["Gate", *STAGES], default="Gate")
    parser.add_argument("--review", required=True)
    parser.add_argument("--review-sha")
    args = parser.parse_args()
    gate(args.review) if args.stage == "Gate" else execute(args.stage, args.review, args.review_sha)
