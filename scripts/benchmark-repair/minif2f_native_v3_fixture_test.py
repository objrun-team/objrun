"""F-only synthetic schema controls; never an official cache or Lean certificate.

The production COUNT=5826 and original modules are not patched. One fixture has
5826 invented keys and tiny files so the genuine full-count gate is exercised.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import time
import os


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def put(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False)+"\n").encode())


def pin(worker, path, root):
    return {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": worker.sha(path)}


def field_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def rebind_synthetic_history(worker, review, paths, recovery):
    """Rebind synthetic pins so a semantic negative reaches its intended gate."""
    put(paths["cache-fast-prefix0-recovery.json"], recovery)
    digest = worker.sha(paths["cache-fast-prefix0-recovery.json"])
    baseline = json.loads(paths["cache-fast-progress.json"].read_bytes())
    baseline["recovery_receipt_sha256"] = digest
    put(paths["cache-fast-progress.json"], baseline)
    pins = {name: {"path": paths[name].as_posix(), "bytes": paths[name].stat().st_size,
            "sha256": worker.sha(paths[name])} for name in worker.PREFIX0_HISTORY_NAMES}
    closure = json.loads(paths["closure.json"].read_bytes())
    closure["receiptPin"] = pins["cache-fast-prefix0-recovery.json"]
    closure["files"] = [{"original": p, "snapshot": p} for p in pins.values()]
    put(paths["closure.json"], closure)
    pins["closure.json"] = {"path": paths["closure.json"].as_posix(),
        "bytes": paths["closure.json"].stat().st_size, "sha256": worker.sha(paths["closure.json"])}
    review["prefix0_history"] = pins


def fixture(root, worker, project):
    sources = {"fast_python_sha256": root/"unit-fast.py", "recovery_python_sha256": root/"unit-recovery.py"}
    for path in sources.values():
        path.write_bytes(b"synthetic schema source; not production executable\n")
    audit = root/"audit"
    audit.mkdir()
    build = root/"mathlib4/.lake/build/lib"
    build.mkdir(parents=True)
    put(root/"mathlib4/lake-manifest.json", {"packages": []})
    receipts, commits, downloads, keys = [], [], [], []
    offset = 0
    for index in range(worker.COUNT):
        key = f"{index:016x}.ltar"
        target = build/f"Fixture{index}.olean"
        target.write_bytes(b"synthetic schema output")
        source = {"ltar": key, "bytes": 5, "sha256": "0"*64,
                  "url": "https://lakecache.blob.core.windows.net/mathlib4/f/"+key}
        row = {"protocol": worker.FAST_PROTOCOL, "ltar": key, "source_sha256": source["sha256"],
            "source_bytes": 5, "source_url": source["url"], "outputs_fsynced": True,
            "files": [{"path": target.relative_to(root/"mathlib4").as_posix(),
                       "bytes": target.stat().st_size, "sha256": worker.sha(target)}]}
        raw = (json.dumps(row)+"\n").encode()
        receipts.append(raw)
        offset += len(raw)
        commits.append((json.dumps({"protocol": worker.FAST_PROTOCOL, "ltar": key,
            "receipt_line_sha256": hashlib.sha256(raw).hexdigest(), "receipt_end": offset,
            "receipt_fsync_returned": True})+"\n").encode())
        downloads.append((json.dumps(source)+"\n").encode())
        keys.append((json.dumps({"module": f"Fixture{index}", "ltar": key})+"\n").encode())
    for name, rows in [("cache-unpacked.jsonl", receipts), ("cache-fast-commits.jsonl", commits),
                       ("cache-downloads.jsonl", downloads), ("module-cache-manifest.jsonl", keys)]:
        (audit/name).write_bytes(b"".join(rows))
    download_sha = worker.sha(audit/"cache-downloads.jsonl")
    acquisition = {"objects": worker.COUNT, "module_cache_manifest_sha256": worker.KEYS_SHA,
        "bootstrap_receipt_sha256": worker.BOOTSTRAP_SHA, "public_lock_sha256": worker.LOCK_SHA,
        "download_receipts_sha256": download_sha, "all_cache_blob_sha256_rechecked": True,
        "pre_existing_files_unchanged_by_metadata": True, "llm_called": False}
    put(audit/"public-cache-acquisition.json", acquisition)
    download = {"objects": worker.COUNT, "module_cache_manifest_sha256": worker.KEYS_SHA,
        "acquisition_proof_sha256": worker.sha(audit/"public-cache-acquisition.json"),
        "download_receipts_sha256": download_sha, "candidate_run": False}
    put(audit/"cache-download-complete.json", download)
    lease = {"held": False, "stage": worker.FAST_PROTOCOL, "outcome": "batch_closed", "released_at_utc": "fixture"}
    put(audit/"cache-fast-unpack.lock", lease)
    owner = {"protocol": worker.FAST_PROTOCOL, "state": "removed", "container_id": "a"*64, "removed_at_utc": "fixture"}
    put(audit/"cache-fast-container.json", owner)
    provenance = {"download_complete_sha256": worker.sha(audit/"cache-download-complete.json"),
        "acquisition_proof_sha256": worker.sha(audit/"public-cache-acquisition.json"),
        "download_receipts_sha256": download_sha, "bootstrap_sha256": worker.BOOTSTRAP_SHA,
        "keys_sha256": worker.KEYS_SHA, "public_lock_sha256": worker.LOCK_SHA}
    history = root/worker.RECOVERY_HISTORY
    history.mkdir()
    originals = {}
    snapshot = project/"docs/repair-2026-10-08/minif2f-fast-first-failure-readonly-snapshot"
    for name, expected in worker.OLD_FAILED_METADATA.items():
        source = snapshot/name
        assert source.stat().st_size == expected[0] and worker.sha(source) == expected[1]
        shutil.copyfile(source, history/name)
        originals[name] = pin(worker, history/name, root)
    stage = history/"stage"
    stage.mkdir()
    for build in [".lake/build"] + [".lake/packages/"+p+"/.lake/build" for p in
            ["plausible", "LeanSearchClient", "importGraph", "proofwidgets", "aesop", "Qq", "batteries", "Cli"]]:
        (stage/"mathlib4"/build).mkdir(parents=True, exist_ok=True)
    directory_rows = []
    for path in sorted(stage.rglob("*")):
        info = path.lstat()
        directory_rows.append({"relativePath": path.relative_to(stage).as_posix(),
            "device": str(info.st_dev), "fileId": str(info.st_ino), "mtimeNs": str(info.st_mtime_ns)})
    info = stage.lstat()
    root_identity = {"device": str(info.st_dev), "fileId": str(info.st_ino), "mtimeNs": str(info.st_mtime_ns)}
    prefix_history = root/"unit-prefix0-history"
    prefix_history.mkdir()
    recovery = {"protocol": worker.RECOVERY_PROTOCOL, "closed": True, "nativeLeaseHandlesClosed": True,
        "decoded_objects": 0, "cache_unpack_complete": False, "reviewPin": {"fixture": "review"},
        "sourcePins": [{"path": "minif2f_fast_unpack_v2.py", "sha256": worker.sha(sources["fast_python_sha256"])},
                       {"path": "minif2f_fast_prefix0_recovery.py", "sha256": worker.sha(sources["recovery_python_sha256"])}],
        "originalPins": originals, "stageOriginalInventory": directory_rows,
        "stageArchivedInventory": directory_rows, "inputProvenance": provenance,
        "sourceIdentity": {"fixture": "source identity"}, "intentPin": {"fixture": "intent"},
        "freshFastLeasePin": {"fixture": "historical fast lease"}, "recoveryLeasePin": {"fixture": "recovery lease"},
        "history": "fixture history", "actualAbsence": {"pid": {"pid": 107912, "present": False},
            "docker": {"containerId": "21fefd14ab28968506f122d565156232b6419397a3b3bf372b8d17c351586113", "absent": True}},
        "stageRootBefore": root_identity, "stageRootAfter": root_identity}
    put(audit/"cache-fast-prefix0-recovery.json", recovery)
    shutil.copyfile(audit/"cache-fast-prefix0-recovery.json", prefix_history/"cache-fast-prefix0-recovery.json")
    recovery_digest = worker.sha(audit/"cache-fast-prefix0-recovery.json")
    historical_baseline = {"protocol": worker.FAST_PROTOCOL, "state": "recovered_prefix0_not_decoded",
        "validated": True, "processed_prefix": 0, "cache_unpack_complete": False, "decoded_objects": 0,
        "recovery_receipt_sha256": recovery_digest}
    put(prefix_history/"cache-fast-progress.json", historical_baseline)
    for name, field in [("cache-fast-unpack.lock", "freshFastLeasePin"),
                        ("cache-fast-prefix0-recovery.lock", "recoveryLeasePin")]:
        put(prefix_history/name, {"held": False, "fixtureOnly": True})
        recovery[field] = {"sha256": worker.sha(prefix_history/name)}
    # The historical lease hashes belong to the recovery event; final fast
    # producer lease bytes are separate and deliberately differ in the fixture.
    put(audit/"cache-fast-prefix0-recovery.json", recovery)
    shutil.copyfile(audit/"cache-fast-prefix0-recovery.json", prefix_history/"cache-fast-prefix0-recovery.json")
    recovery_digest = worker.sha(audit/"cache-fast-prefix0-recovery.json")
    historical_baseline["recovery_receipt_sha256"] = recovery_digest
    put(prefix_history/"cache-fast-progress.json", historical_baseline)
    put(prefix_history/"cache-fast-prefix0-recovery-partial.json", {"fixtureOnly": True, "closed": False})
    put(prefix_history/"cache-fast-prefix0-transaction-d252083fe94342598ff345f31c96911e.json", {"fixtureOnly": True})
    for name in ["cache-fast-commits.jsonl", "cache-unpacked.jsonl"]:
        (prefix_history/name).write_bytes(b"")
    historical_pins = {name: {"path": (prefix_history/name).as_posix(),
        "bytes": (prefix_history/name).stat().st_size, "sha256": worker.sha(prefix_history/name)}
        for name in worker.PREFIX0_HISTORY_NAMES}
    closure = {"protocol": "root-minif2f-actual-prefix0-closure-archive-v1", "fixtureOnly": True,
        "actualRestoreExitCode": 0, "actualCheckClosedExitCode": 0, "actualNativeShareDenyReopens": 3,
        "decodedObjects": 0, "cacheUnpackComplete": False, "originalFiveFailureMetadataAndStageKept": True,
        "receiptPin": historical_pins["cache-fast-prefix0-recovery.json"],
        "files": [{"original": p, "snapshot": p} for p in historical_pins.values()]}
    put(prefix_history/"closure.json", closure)
    historical_pins["closure.json"] = {"path": (prefix_history/"closure.json").as_posix(),
        "bytes": (prefix_history/"closure.json").stat().st_size, "sha256": worker.sha(prefix_history/"closure.json")}
    progress = {"protocol": worker.FAST_PROTOCOL, "validated": True, "state": "batch_closed",
        "cache_unpack_complete": True, "processed_prefix": worker.COUNT, "controls_executed": False,
        "candidate_run": False, "llm_called": False, "public_get": False, "lease_handle_closed": True,
        "reviewed_script_sha256": worker.sha(sources["fast_python_sha256"]),
        "fast_lease_release_sha256": worker.sha(audit/"cache-fast-unpack.lock"),
        "source_before": {"fixture": "source identity"}, "source_after": {"fixture": "source identity"},
        "worker": {"container_id": "a"*64}, "receipts_sha256": worker.sha(audit/"cache-unpacked.jsonl"),
        "commits_sha256": worker.sha(audit/"cache-fast-commits.jsonl"),
        "input_provenance": provenance}
    put(audit/"cache-fast-progress.json", progress)
    graph = {"protocol": worker.FAST_PROTOCOL, **{role: worker.sha(path) for role, path in sources.items()},
        "pins": {role: pin(worker, root/relative, root) for role, relative in worker.FAST_PIN_PATHS.items()},
        "recovery_field_sha256": {field: field_hash(recovery[field]) for field in worker.RECOVERY_FIELDS}}
    return {"fast_v2_graph": graph, "prefix0_history": historical_pins}, sources, {
        name: prefix_history/name for name in historical_pins}


def native_two_handle_control(project):
    project = Path(project).resolve()
    worker_path = project/"scripts/benchmark-repair/minif2f_runtime_v3.py"
    host_path = project/"scripts/benchmark-repair/minif2f_native_v3_stage.py"
    worker = load(worker_path, "native_v3_handle_worker")
    host = load(host_path, "native_v3_handle_host")
    fast_path = project/"scripts/benchmark-repair/minif2f_fast_unpack_v2.py"
    helper_path = project/"scripts/benchmark-repair/minif2f_public_cache.py"
    assert worker.sha(fast_path) == "ef0ddf5d708f6507d256af7a3c77e68c71a1eb7adda79ab7a7f19e9a246fbc09"
    assert worker.sha(helper_path) == "a02c3519b0ccba8a74e577991fedcf75f0c05fb181cfeb617b7e51b060384c2b"
    fast, helper = load(fast_path, "real_acquisition_guard_F_fixture"), load(helper_path, "real_native_lease_F_fixture")
    root = Path(tempfile.mkdtemp(prefix="minif2f-native-v3-handles-", dir=project/".scratch"))
    lease = None
    try:
        acquisition_path = root/"public-cache-acquisition.lock"
        raw = (json.dumps({"protocol": "public-cache-acquisition-v1", "run_id": host.RUN_ID,
            "held": False, "outcome": "complete", "completed_objects": 5826, "fixtureOnly": True})+"\n").encode()
        acquisition_path.write_bytes(raw)
        before = worker.sha(acquisition_path)
        with fast.AcquisitionGuard(acquisition_path) as guard:
            lease = helper.Lease(root/host.NATIVE_LEASE)
            lease.acquire()
            lease.write({"held": True, "fixtureOnly": True, "execution_protocol": host.PROTOCOL})
            try:
                acquisition_path.open("r+b")
            except PermissionError:
                pass
            else:
                raise RuntimeError("real original acquisition guard did not exclude a writer")
            try:
                second = helper.Lease(root/host.NATIVE_LEASE)
                second.acquire()
            except (PermissionError, OSError, RuntimeError):
                pass
            else:
                second.close()
                raise RuntimeError("second real native lease was not excluded")
            guard.stream.seek(0)
            assert guard.stream.read(16385) == raw and guard.sha256 == before
            lease.write({"held": False, "fixtureOnly": True, "execution_protocol": host.PROTOCOL})
            lease.close()
            lease = None
        assert acquisition_path.read_bytes() == raw and worker.sha(acquisition_path) == before
        assert json.loads((root/host.NATIVE_LEASE).read_bytes())["held"] is False
        with fast.AcquisitionGuard(acquisition_path) as reopened:
            assert reopened.sha256 == before
        print(json.dumps({"protocol": "native-v3-real-F-two-handle-control-v1", "controls_passed": 1,
            "actual_native_handles": 2, "native_lease": host.NATIVE_LEASE, "original_bytes_unchanged": True,
            "original_sha256_before": before, "original_sha256_after": worker.sha(acquisition_path),
            "actual_native_guard_reopen_after_close": True, "E_write": False, "model_calls": 0,
            "network_calls": 0, "docker_calls": 0, "official_decode": False, "Lean_executed": False,
            "fixture_only": True, "worker_sha256": worker.sha(worker_path), "host_sha256": worker.sha(host_path),
            "test_sha256": worker.sha(__file__)}))
    finally:
        if lease:
            lease.close()
        if root.parent.resolve() != (project/".scratch").resolve() or not root.name.startswith("minif2f-native-v3-handles-"):
            raise RuntimeError("refuse unexpected owned two-handle fixture cleanup")
        shutil.rmtree(root)


def run(project):
    project = Path(project).resolve()
    worker_path = project/"scripts/benchmark-repair/minif2f_runtime_v3.py"
    host_path = project/"scripts/benchmark-repair/minif2f_native_v3_stage.py"
    worker = load(worker_path, "synthetic_v3_consumer")
    host = load(host_path, "synthetic_v3_host")
    if worker.COUNT != 5826 or host.CONTAINER_MEMORY != 12*1024**3 or host.HOST_HEADROOM != 1024**3:
        raise RuntimeError("production full-count/resource ABI changed")
    scratch = project/".scratch"
    scratch.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="minif2f-native-v3-schema-", dir=scratch))
    began, outcomes = time.monotonic(), []
    try:
        review, sources, historical_paths = fixture(root, worker, project)
        result = worker.cache_identity(root, review, source_paths=sources, history_paths=historical_paths)
        assert result["objects"] == result["files"] == 5826
        outcomes.append({"case": "synthetic5826_new_protocol_positive", "accepted": True})
        base_review = copy.deepcopy(review)
        original = {role: (root/relative).read_bytes() for role, relative in worker.FAST_PIN_PATHS.items()}
        cases = [
            ("prefix0_is_not_full", "full_progress", lambda v: v.update(processed_prefix=0, cache_unpack_complete=False)),
            ("first2_is_not_full", "full_progress", lambda v: v.update(processed_prefix=2)),
            ("legacy_protocol_rejected", "full_progress", lambda v: v.update(protocol="bounded-official-cache-unpack-v1")),
            ("unclosed_native_handle", "full_progress", lambda v: v.update(lease_handle_closed=False)),
            ("source_identity_drift", "full_progress", lambda v: v.update(source_after={"fixture": "changed"})),
            ("owned_worker_identity_drift", "fast_owner", lambda v: v.update(container_id="b"*64)),
            ("held_fast_lease", "fast_lease", lambda v: v.update(held=True)),
            ("unclosed_prefix0_recovery", "prefix0_recovery", lambda v: v.update(closed=False)),
            ("recovery_cannot_claim_decode", "prefix0_recovery", lambda v: v.update(decoded_objects=2)),
            ("recovery_graph_drift", "prefix0_recovery", lambda v: v.update(sourcePins=[{"fixture": "changed"}])),
            ("source_revision_drift", "full_progress", lambda v: v.update(reviewed_script_sha256="f"*64)),
        ]
        for label, role, mutate in cases:
            for name, raw in original.items():
                (root/worker.FAST_PIN_PATHS[name]).write_bytes(raw)
            changed_review = copy.deepcopy(base_review)
            path = root/worker.FAST_PIN_PATHS[role]
            value = json.loads(path.read_bytes())
            mutate(value)
            put(path, value)
            changed_review["fast_v2_graph"]["pins"][role] = pin(worker, path, root)
            try:
                worker.fast_graph_gate(root, changed_review, source_paths=sources, history_paths=historical_paths)
            except RuntimeError:
                outcomes.append({"case": label, "rejected": True})
            else:
                raise RuntimeError("negative graph accepted: "+label)
        for name, raw in original.items():
            (root/worker.FAST_PIN_PATHS[name]).write_bytes(raw)
        changed_review = copy.deepcopy(base_review)
        recovery_path = root/worker.FAST_PIN_PATHS["prefix0_recovery"]
        value = json.loads(recovery_path.read_bytes())
        value["stageRootAfter"]["fileId"] = "changed fixture root"
        put(recovery_path, value)
        changed_review["fast_v2_graph"]["pins"]["prefix0_recovery"] = pin(worker, recovery_path, root)
        changed_review["fast_v2_graph"]["recovery_field_sha256"]["stageRootAfter"] = field_hash(value["stageRootAfter"])
        history_original = {name: path.read_bytes() for name, path in historical_paths.items()}
        rebind_synthetic_history(worker, changed_review, historical_paths, value)
        try:
            worker.fast_graph_gate(root, changed_review, source_paths=sources, history_paths=historical_paths)
        except RuntimeError:
            outcomes.append({"case": "same_E_stage_root_identity_drift", "rejected": True})
        else:
            raise RuntimeError("same-E root identity drift accepted")
        for name, raw in original.items():
            (root/worker.FAST_PIN_PATHS[name]).write_bytes(raw)
        for name, raw in history_original.items():
            historical_paths[name].write_bytes(raw)
        historical_paths["cache-fast-progress.json"].write_bytes(b'{"fixtureDrift":true}\n')
        try:
            worker.fast_graph_gate(root, base_review, source_paths=sources, history_paths=historical_paths)
        except RuntimeError:
            outcomes.append({"case": "immutable_historical_snapshot_drift", "rejected": True})
        else:
            raise RuntimeError("historical baseline drift accepted")
        for name, raw in history_original.items():
            historical_paths[name].write_bytes(raw)
        target = root/"mathlib4/.lake/build/lib/Fixture0.olean"
        target.write_bytes(b"X"*target.stat().st_size)
        try:
            worker.cache_identity(root, base_review, source_paths=sources, history_paths=historical_paths)
        except RuntimeError:
            outcomes.append({"case": "actual_same_size_output_tamper", "rejected": True})
        else:
            raise RuntimeError("same-size output tamper accepted")
        for available, accepted in [(13*1024**3-1, False), (13*1024**3, True)]:
            try:
                value = host.memory_policy_record(available, 32*1024**3)
            except RuntimeError:
                if accepted:
                    raise
                outcomes.append({"case": "synthetic_memory_below_frozen_budget_plus_headroom", "rejected": True})
            else:
                if not accepted or value["required_available_bytes"] != 13*1024**3:
                    raise RuntimeError("memory admission boundary changed")
                outcomes.append({"case": "synthetic_memory_frozen_budget_plus_headroom", "accepted": True})
        data = {"protocol": "native-v3-synthetic-schema-controls-v1", "cases_passed": len(outcomes), "cases": outcomes,
            "production_objects_constant": 5826, "invented_fixture_objects": 5826, "official_objects_decoded": 0,
            "actual_lean_executed": False, "official_cache_certified": False, "E_write": False,
            "docker_calls": 0, "network_calls": 0, "model_calls": 0, "candidate_run": False,
            "worker_sha256": worker.sha(worker_path), "host_sha256": worker.sha(host_path),
            "test_sha256": worker.sha(__file__), "elapsed_seconds": time.monotonic()-began}
        data["actual_fresh_win32_memory_queries"] = 0
        print(json.dumps(data, ensure_ascii=False))
    finally:
        if root.parent.resolve() != scratch or not root.name.startswith("minif2f-native-v3-schema-") or root.is_symlink():
            raise RuntimeError("refuse unexpected owned synthetic fixture cleanup")
        shutil.rmtree(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--lease-only", action="store_true")
    args = parser.parse_args()
    native_two_handle_control(args.project) if args.lease_only else run(args.project)
