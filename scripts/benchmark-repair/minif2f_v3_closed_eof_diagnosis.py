"""Read only the released V3 EOF evidence; write a new F-only diagnosis.

This does not import acquisition helpers, run validation stages, open a lease,
read executable environments, send GETs, or promote public objects.
"""
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
ROOT = Path("E:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/minif2f-v415")
OUT = PROJECT / "docs/repair-2026-10-08/minif2f-v3-closed-eof-diagnosis.json"
LEASE_ID = "bc9808c7-4940-48dd-bff8-dbb170cdabb6"
FATAL = "6bf7eeaf1784efec.ltar"
STOPPED = "a054c375d3391ae4.ltar"
V3_SHA = "23e760d9236037e8c5d14ef686b00fcbe9659d34cf28d7c03624a7775573af83"
REVIEW_SHA = "21ce70fcd2c9665f00981b9c2b2aa47a950a5130f02b866484e1f2ba41672815"
BASE_SHA = "a02c3519b0ccba8a74e577991fedcf75f0c05fb181cfeb617b7e51b060384c2b"
JOURNAL_SHA = "87d966cdc2ea16755a267a9872cce06f7b26e3e618fbd4eba9d6d4fb78e2466a"
KEY_SHA = "bc7f8caa504054de03a3ec6a945de4a4ab7bdb12918029763c46bbb817d6dda9"
TRANSPORT = "same-key-body-timeout-complete-fresh-v3"
IDENTITIES = {}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    path = Path(path)
    before = path.lstat()
    if not path.is_file() or getattr(before, "st_file_attributes", 0) & 0x400:
        raise RuntimeError("Refuse nonregular or reparse input: " + str(path))
    raw = path.read_bytes()
    after = path.stat()
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise RuntimeError("Input changed during read: " + str(path))
    IDENTITIES[str(path)] = dict(bytes=len(raw), sha256=digest(raw), mtime_ns=before.st_mtime_ns,
                                 device=before.st_dev, inode=before.st_ino)
    return raw


def rows(raw):
    if raw and not raw.endswith(b"\n"):
        raise RuntimeError("Truncated JSONL")
    return [json.loads(line) for line in raw.splitlines() if line]


def main():
    if OUT.exists():
        raise RuntimeError("Diagnosis already exists; never overwrite original read evidence")
    lease_path = ROOT / "audit/public-cache-acquisition.lock"
    lease = json.loads(read(lease_path))
    assert lease["held"] is False and lease["outcome"] == "aborted"
    assert lease["lease_id"] == LEASE_ID and lease["pid"] == 33428
    assert lease["completed_objects"] == 3554 and lease["transport_gets"] == 1505
    assert lease["executing_worker_sha256"] == V3_SHA
    assert lease["executing_review_sha256"] == REVIEW_SHA and lease["guard_source_sha256"] == BASE_SHA
    assert lease["prefix_operations_closed"] is True
    for relative, expected in (
        ("scripts/benchmark-repair/minif2f_public_cache_v3.py", V3_SHA),
        ("scripts/benchmark-repair/minif2f_public_cache.py", BASE_SHA),
        ("docs/repair-2026-10-08/minif2f-public-cache-v3-review.json", REVIEW_SHA),
    ):
        assert digest(read(PROJECT / relative)) == expected
    key_raw = read(ROOT / "audit/module-cache-manifest.jsonl")
    assert digest(key_raw) == KEY_SHA
    keys = {r["ltar"] for r in rows(key_raw)}
    assert len(keys) == 5826
    receipt_raw = read(ROOT / "audit/cache-downloads.jsonl")
    completed = rows(receipt_raw)
    by_key = {r["ltar"]: r for r in completed}
    assert len(by_key) == len(completed) == 3554 and set(by_key).issubset(keys)
    assert FATAL not in by_key and STOPPED not in by_key
    prior = read(PROJECT / "docs/repair-2026-10-08/minif2f-dependency-failures/public-cache-body-v2-first-attempt/original-2066-cache-downloads.jsonl")
    assert len(rows(prior)) == 2066 and receipt_raw.startswith(prior)
    journal_raw = read(ROOT / "audit/public-cache-body-attempts.jsonl")
    assert len(journal_raw) == 6751 and digest(journal_raw) == JOURNAL_SHA
    assert lease["body_journal"]["synced_sha256"] == JOURNAL_SHA
    events = rows(journal_raw)
    prepared, commits, prepared_line_sha = {}, {}, {}
    for line in journal_raw.splitlines(keepends=True):
        event = json.loads(line)
        assert event["lease_id"] == LEASE_ID and event["transport_protocol"] == TRANSPORT
        operation = event["operation"]
        if event["event"] == "prepared":
            assert operation not in prepared
            prepared[operation] = event
            prepared_line_sha[operation] = digest(line)
        else:
            assert event["event"] == "committed" and operation not in commits
            assert event["prepared_row_sha256"] == prepared_line_sha[operation]
            assert event["prepared_journal_fsync_returned"] is True
            commits[operation] = event
    assert set(prepared) == set(commits) and len(prepared) == 4
    prefixes = {}
    for operation, event in prepared.items():
        expected_rel = "downloads/mathlib-cache-failed-prefix/" + LEASE_ID + "-" + event["key"][:16] + "-g1.prefix"
        assert event["path"] == expected_rel and event["generation"] == 1
        assert event["prefix_flush_returned"] is True and event["prefix_fsync_returned"] is True
        raw = read(ROOT / expected_rel)
        assert len(raw) == event["bytes"] and digest(raw) == event["sha256"]
        prefixes[event["key"]] = dict(event=event, commit=commits[operation], completed_receipt=by_key.get(event["key"]))
    assert sum(p["event"]["bytes"] for p in prefixes.values()) == lease["retained_registered_prefix_bytes"] == 145700
    parts = {}
    for part in lease["retained_unclosed_owned_parts"]:
        name = part["key"]
        assert name in (FATAL, STOPPED) and part["promoted_to_complete"] is False
        path = ROOT / "downloads/mathlib-cache" / (name + ".part")
        assert os.path.normcase(os.path.abspath(part["path"])) == os.path.normcase(os.path.abspath(path))
        raw = read(path)
        assert len(raw) == part["bytes"] and digest(raw) == part["sha256"]
        item = dict(lease_artifact=part, actual_bytes=len(raw), actual_sha256=digest(raw),
                    actual_content_md5=base64.b64encode(hashlib.md5(raw, usedforsecurity=False).digest()).decode("ascii"))
        if name == FATAL:
            original = prefixes[name]["event"]
            item["first_generation_prefix_sha256_of_fresh_bytes"] = digest(raw[:original["bytes"]])
            item["first_generation_prefix_drift"] = item["first_generation_prefix_sha256_of_fresh_bytes"] != original["sha256"]
            assert item["first_generation_prefix_drift"] is False
        parts[name] = item
    assert set(parts) == {FATAL, STOPPED}
    newer = [r for r in completed if r.get("lease_id") == LEASE_ID]
    recovered = [r for r in newer if r.get("body_generations") == 2]
    metadata = dict(protocol="released-v3-eof-readonly-diagnosis-v1", observed_at_utc=datetime.now(timezone.utc).isoformat(),
                    source_lease=lease, fixed_manifest_count=5826, completed_receipt_count=3554,
                    missing_receipt_count=2272, fatal_and_stopped_promoted=False,
                    preserved_prior_2066_receipt_prefix=True, prior_receipt_sha256=digest(prior),
                    new_completed_this_lease=len(newer), new_completed_transport_gets_sum=sum(r["transport_gets"] for r in newer),
                    completed_two_generation_count=len(recovered), recovered_receipts=recovered,
                    registered_prefixes=prefixes, retained_unclosed_parts=parts,
                    process_fresh_absence_verified=False, process_fresh_absence_owned_by_root=True,
                    body_generation_2_fsync="Inferred from exact frozen source EOF branch after sync_stream returned; no separate per-part fsync receipt.",
                    stopped_part_fsync="Not guaranteed by this fault path; measured stable readback is separate from flush/fsync provenance.",
                    original_generation_2_global_get="Not recorded individually; do not invent it from total1505 or generation1global1485.",
                    failure_classification="Response body read returned EOF below the observed declared length. Complete headers were observed; root cause of truncation is not established.",
                    downstream_stopped_part_classification="Only released-footer observed headers and bytes are established; shared-stop origin is source/run inference, not an independently recorded read error.",
                    boundaries=dict(network_gets=0, model_calls=0, candidate_runs=0, lean_runs=0, docker_calls=0,
                                    e_writes=0, existing_source_edits=0, completion_promotions=0,
                                    full_e_directory_scans=0, process_operations=0))
    original = dict(IDENTITIES)
    for filename, before in original.items():
        read(Path(filename))
        assert IDENTITIES[filename] == before
    metadata["inputs"] = [dict(path=filename, **identity) for filename, identity in original.items()]
    metadata["input_hash_size_mtime_identity_unchanged"] = True
    raw = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with OUT.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(dict(path=str(OUT), bytes=len(raw), sha256=digest(raw), completed=3554,
                          new_completed=len(newer), two_generation_successes=len(recovered), e_writes=0)))


if __name__ == "__main__":
    main()
