"""F/tmpfs-only tests. Artificial one-object schema fixtures are not cache proof."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value)+"\n")


def build_fixture(root, worker, alter=None):
    key = "0123456789abcdef.ltar"
    source = {"ltar": key, "bytes": 5, "sha256": "0"*64,
              "url": "https://lakecache.blob.core.windows.net/mathlib4/f/"+key}
    target = root/"mathlib4/.lake/build/lib/Fixture.olean"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"artificial unit fixture")
    put(root/"mathlib4/lake-manifest.json", {"packages": []})
    put(root/"audit/module-cache-manifest.jsonl", {"module": "Fixture", "ltar": key})
    put(root/"audit/cache-downloads.jsonl", source)
    put(root/"audit/cache-download-complete.json", {
        "download_receipts_sha256": worker.sha(root/"audit/cache-downloads.jsonl")})
    row = {"protocol": worker.FAST_PROTOCOL, "ltar": key, "source_bytes": 5,
        "source_sha256": source["sha256"], "source_url": source["url"], "outputs_fsynced": True,
        "files": [{"path": ".lake/build/lib/Fixture.olean", "bytes": target.stat().st_size, "sha256": worker.sha(target)}]}
    if alter:
        alter(row, target)
    raw = (json.dumps(row)+"\n").encode()
    (root/"audit/cache-unpacked.jsonl").write_bytes(raw)
    commit = {"protocol": worker.FAST_PROTOCOL, "ltar": key, "receipt_end": len(raw),
              "receipt_line_sha256": hashlib.sha256(raw).hexdigest(), "receipt_fsync_returned": True}
    put(root/"audit/cache-fast-commits.jsonl", commit)
    complete = {"protocol": worker.FAST_PROTOCOL, "validated": True, "state": "batch_closed",
        "cache_unpack_complete": True, "processed_prefix": 1, "controls_executed": False,
        "receipts_sha256": worker.sha(root/"audit/cache-unpacked.jsonl"),
        "commits_sha256": worker.sha(root/"audit/cache-fast-commits.jsonl")}
    put(root/"audit/cache-fast-progress.json", complete)
    return target, commit, complete


def schema_tests(project):
    project = Path(project)
    worker = load(project/"scripts/benchmark-repair/minif2f_runtime_v2.py", "unit_only_v2")
    # Only this in-memory unit fixture instance uses one object. The actual
    # source file remains COUNT=5826 and is hash-bound by the independent review.
    worker.COUNT = 1
    outcomes = []
    directory = Path(tempfile.mkdtemp(prefix="native-v2-schema-", dir=project/".phase1-data"))
    try:
        for label, mutate in [
            ("same_size_output_tamper", lambda r, p: p.write_bytes(b"X"*p.stat().st_size)),
            ("missing_output_fsync", lambda r, p: r.update(outputs_fsynced=False)),
            ("traversal_path", lambda r, p: r["files"][0].update(path="../outside.olean")),
            ("source_tree_path", lambda r, p: r["files"][0].update(path="Mathlib/Fixture.lean")),
            ("duplicate_output_path", lambda r, p: r["files"].append(dict(r["files"][0]))),
            ("source_sha_mismatch", lambda r, p: r.update(source_sha256="1"*64)),
        ]:
            root = directory/label
            build_fixture(root, worker, mutate)
            try:
                worker.cache_identity(root)
            except RuntimeError as error:
                outcomes.append({"case": label, "rejected": True, "error": str(error)})
            else:
                raise RuntimeError("negative actual input was accepted: "+label)
        for label in ["missing_commit_fsync", "wrong_commit_line_sha", "unclosed_full_prefix"]:
            root = directory/label
            _, commit, complete = build_fixture(root, worker)
            if label == "missing_commit_fsync":
                commit["receipt_fsync_returned"] = False
            elif label == "wrong_commit_line_sha":
                commit["receipt_line_sha256"] = "2"*64
            else:
                complete["cache_unpack_complete"] = False
            put(root/"audit/cache-fast-commits.jsonl", commit)
            complete["commits_sha256"] = worker.sha(root/"audit/cache-fast-commits.jsonl")
            put(root/"audit/cache-fast-progress.json", complete)
            try:
                worker.cache_identity(root)
            except RuntimeError as error:
                outcomes.append({"case": label, "rejected": True, "error": str(error)})
            else:
                raise RuntimeError("negative actual chain was accepted: "+label)
        root = directory/"positive"
        build_fixture(root, worker)
        value = worker.cache_identity(root)
        if value["objects"] != 1 or value["files"] != 1:
            raise RuntimeError("valid artificial one-object schema fixture was rejected")
        outcomes.append({"case": "artificial_schema_positive", "accepted": True})
    finally:
        # The only recursive cleanup is the exact newly created F test fixture.
        if directory.parent.resolve() != (project/".phase1-data").resolve() or not directory.name.startswith("native-v2-schema-"):
            raise RuntimeError("refuse unexpected fixture cleanup target")
        shutil.rmtree(directory)
    print(json.dumps({"unit_schema_cases_passed": len(outcomes), "cases": outcomes,
        "artificial_object_count": 1, "official_cache_certified": False, "e_write": False,
        "candidate_run": False, "llm_called": False}))


def native_test():
    worker = load("/plan/minif2f_runtime_v2.py", "actual_new_v2_worker")
    generator = load("/plan/minif2f_native_v2_probe.py", "frozen_v2_configuration_generator")
    manifest, _, _ = generator.archive_inputs()
    temp = Path("/tmp/new-v2-generated")
    generator.configuration(temp, manifest)
    root = Path("/cache/runtime-lake-v2")
    for name in ["lakefile.lean", "lake-manifest.json"]:
        shutil.copyfile(temp/name, root/name)
    native = worker.actual_native_probe(Path("/cache"), manifest)
    print(json.dumps({"new_worker_native_environment_passed": True, "native": native,
        "worker_sha256": worker.sha("/plan/minif2f_runtime_v2.py"),
        "lean_dsl_sha256": worker.sha(root/"lakefile.lean"),
        "path_manifest_sha256": worker.sha(root/"lake-manifest.json"),
        "scope": "same pinned public archive fixture and actual fixed native toolchain; metadata tmpfs",
        "e_write": False, "candidate_run": False, "llm_called": False, "public_get": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["schema", "native"])
    parser.add_argument("--project")
    args = parser.parse_args()
    schema_tests(args.project) if args.stage == "schema" else native_test()
