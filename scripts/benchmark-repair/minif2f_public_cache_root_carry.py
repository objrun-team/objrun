"""Two explicitly reviewed complete GETs; no implicit retry or bulk acquisition.

Frozen V2/V3/Profile/fast/native sources are imported read-only. The distinct
transport records a fatal GET3/body3 and a separately authorized additional GET
with unknown old count. It never publishes a5826 download-complete certificate.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import urllib.request

PROJECT = Path(__file__).resolve().parents[2]
V3_SHA = "23e760d9236037e8c5d14ef686b00fcbe9659d34cf28d7c03624a7775573af83"
AUTH_SHA = "754e410406ed2d310976435d70774a35bf6f85d462f4f492e1c2ffd84a480771"
ARCHIVE_SHA = "0a36195c10a6371d1badd1c59f9e9f33210eb8bc7ced51260c8741bd25e9d596"
AUTH_REL = ".local-evidence/repository/test/fixtures/repair/minif2f-public-cache-root-carry-authorization.json"
REVIEW_REL = ".local-evidence/repository/test/fixtures/repair/minif2f-public-cache-root-carry-review.json"
TRANSPORT = "same-key-root-reviewed-complete-carry-v1"
REVIEW_PROTOCOL = "public-cache-root-carry-source-review-v1"
EVENTS_REL = "audit/public-cache-root-carry-events.jsonl"
PHASE_REL = "audit/public-cache-root-carry-phase.json"
KEYS = ("6bf7eeaf1784efec.ltar", "a054c375d3391ae4.ltar")
DEADLINE = datetime.fromisoformat("2026-10-08T18:16:26.118992+00:00").timestamp()
ARCHIVE_WALL_FLOOR = datetime.fromisoformat("2026-10-08T16:05:04.895559+00:00").timestamp()


def load_v3():
    path = Path(__file__).with_name("minif2f_public_cache_v3.py")
    if hashlib.sha256(path.read_bytes()).hexdigest() != V3_SHA:
        raise RuntimeError("Frozen V3 source changed")
    spec = importlib.util.spec_from_file_location("root_carry_frozen_v3", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v3 = load_v3()
base = v3.base
sha, stamp, regular, sync = v3.sha, v3.stamp, v3.assert_regular, v3.sync_stream


def pinned(path, expected, size=None):
    path = Path(path)
    regular(path)
    before = path.stat()
    if (size is not None and before.st_size != size) or sha(path) != expected:
        raise RuntimeError("Pinned bytes changed: " + path.name)
    raw = path.read_bytes()
    after = path.stat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or
            hashlib.sha256(raw).hexdigest() != expected):
        raise RuntimeError("Pinned bytes changed during read")
    return raw


def load_authorization():
    auth = json.loads(pinned(PROJECT/AUTH_REL, AUTH_SHA))
    if (auth["protocol"] != "root-reviewed-two-key-carry-authorization-v1" or
            auth["rootPreparationApproved"] is not True or auth["automaticLaunchAuthorized"] is not False or
            auth["actualEPhaseExecuted"] is not False or tuple(x["key"] for x in auth["keys"]) != KEYS or
            auth["budget"]["maxNewGets"] != 2 or auth["budget"]["priorStageGets"] != 1505 or
            auth["budget"]["maximumFinalObjects"] != 3556 or
            auth["budget"]["mayEmit5826CompletionCertificate"] is not False):
        raise RuntimeError("Unknown or widened two-key authorization")
    directory = PROJECT/auth["archiveDirectory"]
    if directory.resolve() != (PROJECT/"docs/repair-2026-10-08/minif2f-dependency-failures/public-cache-body-v3-first-attempt-verified-v2").resolve():
        raise RuntimeError("Different root failure archive")
    receipt = json.loads(pinned(directory/auth["archiveReceipt"]["file"], ARCHIVE_SHA, 12122))
    if (receipt["originalProcessAbsent"] is not True or receipt["originalLeaseHeld"] is not False or
            receipt["completedObjects"] != 3554 or receipt["partialPromoted"] is not False):
        raise RuntimeError("Root archive is not exact released failure")
    for entry in receipt["parts"] + receipt["copiedInputs"]:
        path = Path(entry["archive"])
        if path.resolve().parent != directory.resolve() or entry["flushToDiskReturned"] is not True:
            raise RuntimeError("Archive path/durability differs")
        pinned(path, entry["sha256"], entry["bytes"])
    for name in ("archiveBinding", "diagnosis", "design"):
        pin = auth[name]
        pinned(PROJECT/pin["path"], pin["sha256"], pin["bytes"])
    prior_lease = json.loads(pinned(directory/auth["priorLease"]["file"],
                                  auth["priorLease"]["sha256"], auth["priorLease"]["bytes"]))
    for policy in auth["keys"]:
        if (policy["newAuthorizedGets"] != 1 or policy["url"] != base.AZURE+policy["key"] or
                v3.etag_kind(policy["etag"]) != "opaque_unquoted" or
                v3.content_md5(policy["contentMd5"]) is None):
            raise RuntimeError("Invalid fixed one-GET policy")
        for prefix in policy["prefixes"]:
            pinned(directory/prefix["file"], prefix["sha256"], prefix["bytes"])
    return auth, directory, prior_lease


def validate_review(expected_sha):
    path = PROJECT/REVIEW_REL
    review = json.loads(pinned(path, expected_sha))
    if (review.get("protocol") != REVIEW_PROTOCOL or review.get("validated") is not True or
            review.get("transport_protocol") != TRANSPORT or review.get("authorization_sha256") != AUTH_SHA or
            review.get("real_acquisition_executed") is not False):
        raise RuntimeError("Different independent carry review")
    paths = set()
    for entry in review["new_sources"] + review["protected_sources"]:
        path = Path(entry["path"])
        key = str(path.resolve()).casefold()
        if key in paths:
            raise RuntimeError("Duplicate source pin")
        paths.add(key)
        pinned(path, entry["sha256"], entry["bytes"])
    required = (Path(__file__).resolve(), Path(__file__).with_suffix(".ps1").resolve(),
                PROJECT/AUTH_REL, Path(__file__).with_name("minif2f_public_cache_v3.py"),
                Path(__file__).with_name("minif2f_public_cache.py"),
                PROJECT/".local-evidence/repository/test/fixtures/repair/minif2f-restoration-preflight.json")
    if any(str(path.resolve()).casefold() not in paths for path in required):
        raise RuntimeError("Review omits required executing source/auth/profile")
    return review


class Deadline:
    def __init__(self, wall=time.time, monotonic=time.monotonic):
        self.wall, self.monotonic = wall, monotonic
        self.last_wall, self.start_mono = wall(), monotonic()
        self.last_mono = self.start_mono
        self.remaining = DEADLINE-self.last_wall
        if not 0 < self.remaining <= 3*3600 or self.last_wall < ARCHIVE_WALL_FLOOR:
            raise RuntimeError("Original V3 deadline expired or clock evidence invalid")

    def check(self):
        now, mono = self.wall(), self.monotonic()
        if (now < self.last_wall or mono < self.last_mono or now >= DEADLINE or
                mono-self.start_mono >= self.remaining):
            raise RuntimeError("Original carried deadline/clock guard failed")
        self.last_wall, self.last_mono = now, mono


class OwnedLease(base.Lease):
    def write(self, values):
        super().write(values)
        self.expected = dict(protocol=base.PROTOCOL, run_id=base.RUN_ID, lease_id=self.id, **values)
        self.assert_owned()

    def assert_owned(self):
        if self.stream is None:
            raise RuntimeError("Owned share-deny lease handle closed")
        self.stream.seek(0)
        value = json.loads(self.stream.read(16385))
        if value != self.expected or value.get("pid") != os.getpid():
            raise RuntimeError("Owned lease identity changed")


class AttemptJournal:
    """No existing intent is ever automatically retried, including an empty file."""
    def __init__(self, path, lease_id, review_sha):
        self.path = Path(path)
        self.lease_id, self.review_sha = lease_id, review_sha
        self.bytes, self.last_sha, self.count = 0, AUTH_SHA, 0
        self.used, self.open_calls, self.committed, self.failed = set(), set(), set(), False
        with self.path.open("xb") as stream:
            sync(stream)

    def append(self, event):
        if self.failed:
            raise RuntimeError("Unacknowledged carry journal tail")
        row = dict(protocol=TRANSPORT, event_seq=self.count, previous_sha256=self.last_sha,
                   lease_id=self.lease_id, authorization_sha256=AUTH_SHA, review_sha256=self.review_sha,
                   recorded_at_utc=stamp(), **event)
        raw = v3.encode_row(row)
        try:
            regular(self.path)
            if self.path.stat().st_size != self.bytes or self.bytes+len(raw) > 65536:
                raise RuntimeError("Carry journal mutated or outside fixed64KiB")
            with self.path.open("ab") as stream:
                if stream.write(raw) != len(raw):
                    raise RuntimeError("Short carry journal write")
                sync(stream)
            if self.path.read_bytes()[self.bytes:] != raw:
                raise RuntimeError("Carry journal readback differs")
        except Exception:
            self.failed = True
            raise
        self.bytes += len(raw)
        self.count += 1
        self.last_sha = hashlib.sha256(raw).hexdigest()
        if event.get("event") == "committed":
            self.committed.add(event["key"])
        return self.last_sha

    def dispatch(self, policy):
        key = policy["key"]
        if key not in KEYS or key in self.used or len(self.used) >= 2:
            raise RuntimeError("One authorized GET already consumed or unknown key")
        # Mark before any IO: an ambiguous failed intent is never reclaimed.
        self.used.add(key)
        ordinal = len(self.used)
        self.append(dict(event="dispatch", key=key, policy=policy["policy"],
                         new_ordinal=ordinal, prior_stage_gets=1505, aggregate_consumed_get_allowance=1505+ordinal,
                         prior_key_gets_exact=policy["priorLogicalGetsExact"],
                         prior_key_gets_interval=policy["priorLogicalGetsInterval"],
                         cumulative_key_gets_exact=policy["cumulativeLogicalGetsExact"],
                         cumulative_key_gets_interval=policy["cumulativeLogicalGetsInterval"],
                         opened_body_generation=policy["newOpenedBodyGeneration"], url=policy["url"],
                         reservation_bytes=base.rounded(policy["contentLength"])+base.META_PER_BLOB))
        return ordinal

    def footer(self):
        return dict(path=EVENTS_REL, acknowledged_bytes=self.bytes, event_count=self.count,
                    last_line_sha256=self.last_sha, actual_sha256=sha(self.path),
                    exact_acknowledged_tail=self.path.stat().st_size == self.bytes and not self.failed,
                    consumed_keys=sorted(self.used), new_get_intents=len(self.used),
                    opener_calls=len(self.open_calls), acknowledged_committed_keys=sorted(self.committed))


def fresh_one(policy, row, root, lease, book, journal, guard, receipt, opener=None):
    """Kernel also used with synthetic F-only responses in offline controls."""
    key = policy["key"]
    if key not in KEYS or row["ltar"] != key or policy["newAuthorizedGets"] != 1:
        raise RuntimeError("Only the two exact one-GET authorizations are supported")
    guard()
    book.begin(key, policy["contentLength"])
    ordinal = journal.dispatch(policy)  # Durability returns before any socket open.
    guard()
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), base.NoRedirect())
    request = urllib.request.Request(policy["url"], headers={"User-Agent": "TgEngin-public-cache-root-carry-v1",
                                                           "Accept-Encoding": "identity"}, method="GET")
    journal.open_calls.add(key)
    with opener.open(request, timeout=60) as response:
        length, http = v3.metadata(response, policy["url"])
        if (length != policy["contentLength"] or http.get("content-md5") != policy["contentMd5"] or
                http.get("etag") != policy["etag"]):
            raise RuntimeError("Carried fixed headers changed")
        journal.append(dict(event="headers", key=key, new_ordinal=ordinal, http_status=200, http=http))
        part = Path(root)/"downloads/mathlib-cache"/(key+".part")
        digest, body_md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)
        windows = [(p, hashlib.sha256()) for p in policy["prefixes"]]
        written = 0
        with part.open("xb") as stream:
            info = os.fstat(stream.fileno())
            identity = (info.st_dev, info.st_ino)
            book.observe_part(key, part, identity, dict(url=policy["url"], status=200,
                                                       content_length=length, headers=http))
            try:
                while True:
                    guard()
                    chunk = response.read1(base.BLOCK)
                    if not chunk:
                        break
                    guard()
                    before = written
                    written += len(chunk)
                    if written > length or written > base.MAX_BLOB:
                        raise RuntimeError("Carry body exceeds length64MiB bound")
                    if stream.write(chunk) != len(chunk):
                        raise RuntimeError("Short carry body write")
                    digest.update(chunk)
                    body_md5.update(chunk)
                    for prefix, window in windows:
                        amount = max(0, min(len(chunk), prefix["bytes"]-before))
                        if amount:
                            window.update(chunk[:amount])
                    book.check()
            finally:
                # Failures get their own actual returned-fsync provenance too.
                # If this fails, the exception denies all receipt promotion.
                sync(stream)
    if written != length:
        raise RuntimeError("Carry body EOF/length mismatch; allowance consumed")
    if any(written < p["bytes"] or h.hexdigest() != p["sha256"] for p, h in windows):
        raise RuntimeError("Carry fresh prefix window SHA drift")
    if body_md5.digest() != v3.content_md5(policy["contentMd5"]):
        raise RuntimeError("Carry complete body Content-MD5 mismatch")
    v3.owned_prefix(part, identity, written, digest.hexdigest())
    guard()
    result = dict(**row, acquisition_protocol=base.PROTOCOL, transport_protocol=TRANSPORT,
                  url=policy["url"], http_status=200, http=http, bytes=written, sha256=digest.hexdigest(),
                  lease_id=lease.id, recorded_at_utc=stamp(), authorization_sha256=AUTH_SHA,
                  transport_gets=1, cumulative_key_gets_exact=policy["cumulativeLogicalGetsExact"],
                  cumulative_key_gets_interval=policy["cumulativeLogicalGetsInterval"],
                  body_generations=policy["newOpenedBodyGeneration"], new_get_ordinal=ordinal,
                  content_md5_verified=True, measured_content_md5=policy["contentMd5"],
                  etag_kind="opaque_unquoted", all_failed_prefix_windows_verified=True,
                  failed_prefix_bytes_reused_in_body=0, fresh_body_complete_from_new_get=True,
                  hash_assurance="official URL; complete Content-MD5; local SHA measured, no published SHA")
    encoded = v3.encode_row(result)
    target = part.with_name(key)
    if target.exists():
        raise RuntimeError("Never overwrite an existing complete cache object")
    part.rename(target)
    book.parts[key]["path"] = str(target)
    with Path(receipt).open("ab") as stream:
        if stream.write(encoded) != len(encoded):
            raise RuntimeError("Short carry completed receipt")
        sync(stream)
    end = Path(receipt).stat().st_size
    if Path(receipt).read_bytes()[end-len(encoded):] != encoded:
        raise RuntimeError("Carry completed receipt readback differs")
    journal.append(dict(event="committed", key=key, new_ordinal=ordinal,
                        completed_receipt_line_sha256=hashlib.sha256(encoded).hexdigest(),
                        receipt_end=end, receipt_fsync_returned=True, body_fsync_returned=True,
                        bytes=written, sha256=digest.hexdigest()))
    book.committed(key, written)
    book.parts.pop(key)
    return result


def legacy_rows_valid(root, rows, evidence):
    # Preserve the exact frozen V2/V3 row rules; public bytes are checked by base.
    for name, row in rows.items():
        transport = row.get("transport_protocol")
        if transport is None:
            continue
        if transport not in (v3.TRANSPORT, v3.V2_TRANSPORT):
            raise RuntimeError("Unexpected protocol in immutable legacy prefix")
        count, generations = row.get("transport_gets"), row.get("body_generations")
        if type(count) is not int or not 1 <= count <= 3 or type(generations) is not int or generations not in (1, 2):
            raise RuntimeError("Frozen legacy transport counters differ")
        pointer = row.get("failed_prefix_operation")
        if generations == 2:
            prefix = evidence["prefixes"].get(pointer)
            if not prefix or prefix["key"] != name or prefix["transport_protocol"] != transport:
                raise RuntimeError("Legacy recovered prefix lacks its typed operation")
        elif pointer is not None:
            raise RuntimeError("Legacy unrecovered row carries a prefix pointer")
        if transport == v3.TRANSPORT:
            http = row.get("http")
            if not isinstance(http, dict):
                raise RuntimeError("Legacy V3 observed headers missing")
            expected = v3.content_md5(http.get("content-md5"))
            if (row.get("etag_kind") != v3.etag_kind(http.get("etag")) or
                    row.get("content_md5_verified") is not (expected is not None) or
                    row.get("failed_prefix_bytes_reused_in_body") != 0 or
                    row.get("fresh_body_complete_from_new_get") is not (generations == 2)):
                raise RuntimeError("Legacy V3 provenance flags differ")
            if expected is not None:
                if row.get("measured_content_md5") != http["content-md5"] or v3.md5_file(Path(root)/"downloads/mathlib-cache"/name) != http["content-md5"]:
                    raise RuntimeError("Legacy V3 actual body MD5 differs")
            elif row.get("measured_content_md5") is not None:
                raise RuntimeError("Legacy V3 claims unadvertised MD5")
            if generations == 2:
                if (row.get("fresh_recovery_policy") != prefix["recovery_policy"] or
                        http.get("etag") != prefix["etag"] or http.get("content-md5") != prefix["content_md5"] or
                        int(http.get("content-length", "-1")) != prefix["content_length"]):
                    raise RuntimeError("Legacy V3 fresh headers differ")
            elif row.get("fresh_recovery_policy") is not None:
                raise RuntimeError("Legacy V3 one body claims recovery")


def validate_typed_rows(root, manifest, auth, prior_lease, raw=None):
    """A distinct validator accepts carry rows; no masquerading as frozen V3."""
    all_rows = base.validate_resume(Path(root), manifest)
    archive = PROJECT/auth["archiveDirectory"]
    original = pinned(archive/auth["priorCompleted"]["file"], auth["priorCompleted"]["sha256"], auth["priorCompleted"]["bytes"])
    raw = raw if raw is not None else (Path(root)/"audit/cache-downloads.jsonl").read_bytes()
    if not raw.startswith(original) or not raw.endswith(b"\n"):
        raise RuntimeError("Original3554 receipt prefix changed or tail truncated")
    evidence = v3.validate_evidence(root, manifest, prior_lease)
    legacy = {r["ltar"]: r for r in (json.loads(line) for line in original.splitlines())}
    if len(legacy) != 3554:
        raise RuntimeError("Wrong fixed legacy prefix count")
    legacy_rows_valid(root, legacy, evidence)
    tail = [json.loads(line) for line in raw[len(original):].splitlines()]
    if len(tail) > 2 or set(all_rows) != set(legacy) | {r["ltar"] for r in tail}:
        raise RuntimeError("Unauthorized carry tail/count")
    for record in tail:
        policy = next((p for p in auth["keys"] if p["key"] == record["ltar"]), None)
        if not policy or (record.get("transport_protocol") != TRANSPORT or record.get("authorization_sha256") != AUTH_SHA or
                record.get("acquisition_protocol") != base.PROTOCOL or record.get("transport_gets") != 1 or
                record.get("body_generations") != policy["newOpenedBodyGeneration"] or
                record.get("cumulative_key_gets_exact") != policy["cumulativeLogicalGetsExact"] or
                record.get("cumulative_key_gets_interval") != policy["cumulativeLogicalGetsInterval"] or
                record.get("http_status") != 200 or record.get("bytes") != policy["contentLength"] or
                record.get("content_md5_verified") is not True or record.get("all_failed_prefix_windows_verified") is not True or
                record.get("failed_prefix_bytes_reused_in_body") != 0 or record.get("fresh_body_complete_from_new_get") is not True or
                record.get("measured_content_md5") != policy["contentMd5"] or record.get("etag_kind") != "opaque_unquoted"):
            raise RuntimeError("New carry row does not match its exact root policy")
        http = record["http"]
        if (http.get("content-length") != str(policy["contentLength"]) or http.get("content-md5") != policy["contentMd5"] or http.get("etag") != policy["etag"]):
            raise RuntimeError("Carry actual recorded headers differ")
        path = Path(root)/"downloads/mathlib-cache"/record["ltar"]
        if v3.md5_file(path) != policy["contentMd5"]:
            raise RuntimeError("Carry actual complete body MD5 differs")
        with path.open("rb") as stream:
            data = stream.read(policy["contentLength"]+1)
        if any(hashlib.sha256(data[:p["bytes"]]).hexdigest() != p["sha256"] for p in policy["prefixes"]):
            raise RuntimeError("Carry actual saved prefix windows drifted")
    return all_rows, tail


def inspect_attempts(path, lease_id, review_sha, auth, raw_receipts):
    raw = Path(path).read_bytes()
    if len(raw) > 65536 or raw and not raw.endswith(b"\n"):
        raise RuntimeError("Carry attempts oversized/truncated")
    previous, dispatched, commits, headers = AUTH_SHA, {}, {}, set()
    for seq, line in enumerate(raw.splitlines(keepends=True)):
        row = json.loads(line)
        if (row["protocol"] != TRANSPORT or row["event_seq"] != seq or row["previous_sha256"] != previous or
                row["lease_id"] != lease_id or row["authorization_sha256"] != AUTH_SHA or row["review_sha256"] != review_sha):
            raise RuntimeError("Carry attempt chain/bindings differ")
        key = row.get("key")
        policy = next((p for p in auth["keys"] if p["key"] == key), None)
        if not policy:
            raise RuntimeError("Attempt outside authorized keys")
        if row["event"] == "dispatch":
            if key in dispatched or row["new_ordinal"] != len(dispatched)+1 or row["aggregate_consumed_get_allowance"] != 1506+len(dispatched):
                raise RuntimeError("Duplicate/reset carry GET intent")
            if (row["prior_stage_gets"] != 1505 or row["policy"] != policy["policy"] or row["url"] != policy["url"] or
                    row["prior_key_gets_exact"] != policy["priorLogicalGetsExact"] or
                    row["prior_key_gets_interval"] != policy["priorLogicalGetsInterval"] or
                    row["cumulative_key_gets_exact"] != policy["cumulativeLogicalGetsExact"] or
                    row["cumulative_key_gets_interval"] != policy["cumulativeLogicalGetsInterval"] or
                    row["opened_body_generation"] != policy["newOpenedBodyGeneration"]):
                raise RuntimeError("Intent does not carry the authorized original budget")
            dispatched[key] = row
        elif row["event"] == "headers":
            http = row.get("http", {})
            if (key not in dispatched or key in headers or row["new_ordinal"] != dispatched[key]["new_ordinal"] or
                    row.get("http_status") != 200 or http.get("content-length") != str(policy["contentLength"]) or
                    http.get("content-md5") != policy["contentMd5"] or http.get("etag") != policy["etag"]):
                raise RuntimeError("Unknown/duplicate header event")
            headers.add(key)
        elif row["event"] == "committed":
            if (key not in headers or key in commits or row["new_ordinal"] != dispatched[key]["new_ordinal"] or
                    row["receipt_fsync_returned"] is not True or row["body_fsync_returned"] is not True):
                raise RuntimeError("Unreturned or duplicate completed carry event")
            end = row["receipt_end"]
            start = raw_receipts.rfind(b"\n", 0, end-1)+1
            if (not 0 < end <= len(raw_receipts) or hashlib.sha256(raw_receipts[start:end]).hexdigest() != row["completed_receipt_line_sha256"]):
                raise RuntimeError("Committed receipt offset/hash differs")
            record = json.loads(raw_receipts[start:end])
            if (record["ltar"] != key or record["lease_id"] != lease_id or record["new_get_ordinal"] != dispatched[key]["new_ordinal"] or
                    record["bytes"] != row["bytes"] or record["sha256"] != row["sha256"]):
                raise RuntimeError("Committed carry bytes/receipt identity differs")
            commits[key] = row
        else:
            raise RuntimeError("Unknown carry event")
        previous = hashlib.sha256(line).hexdigest()
    return dict(dispatched=dispatched, commits=commits, raw_sha256=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw), events=len(raw.splitlines()), last_sha256=previous)


def writer_probe():
    proof = v3.writer_probe()
    command = r'''$ErrorActionPreference='Stop';$all=@(Get-CimInstance Win32_Process);$excluded=@(__PID__);$cur=__PID__;while($cur){$p=$all|Where-Object ProcessId -eq $cur;if(-not $p){break};$cur=[int]$p.ParentProcessId;$excluded+=$cur};$hits=@();foreach($p in $all){if($excluded -contains [int]$p.ProcessId){continue};if([string]$p.CommandLine -match '(?i)minif2f_public_cache_root_carry\.(py|ps1)["''\s]+[\s\S]*?acquire(?:["''\s]|$)'){$hits+=[pscustomobject]@{pid=[int]$p.ProcessId;name=$p.Name;stage='Acquire'}}};$prior=@($all|Where-Object ProcessId -eq 33428);[pscustomobject]@{carry_writers=$hits;prior_pid_present=($prior.Count -gt 0)}|ConvertTo-Json -Depth 4 -Compress'''.replace("__PID__", str(os.getpid()))
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, timeout=10)
    if result.returncode:
        raise RuntimeError("Carry original PID/writer metadata observation failed")
    observed = json.loads(result.stdout.decode("utf-8-sig"))
    if observed["carry_writers"] or observed["prior_pid_present"]:
        raise RuntimeError("Prior actor PID or another carry writer still present")
    proof["carry_probe"] = observed
    return proof


def preflight(root, public, core, review_sha, allow_closed=False):
    review = validate_review(review_sha)
    auth, directory, prior = load_authorization()
    root = base.exact_root(root)
    base.allocation_unit()
    base.volume_reserves(base.AUDIT_BUDGET)
    manifest = base.inputs(root, public, core)
    if (root/"audit/cache-download-complete.json").exists():
        raise RuntimeError("This narrow stage cannot replace a full5826 closure")
    if (root/PHASE_REL).exists() or (root/EVENTS_REL).exists():
        if not allow_closed:
            raise RuntimeError("Prior carry intent exists; no automatic retry or new budget")
        return root, auth, prior, manifest, review, inspect_closed(root, auth, prior, manifest, review_sha)
    pinned(root/"audit"/base.LEASE_NAME, auth["priorLease"]["sha256"], auth["priorLease"]["bytes"])
    pinned(root/"audit/cache-downloads.jsonl", auth["priorCompleted"]["sha256"], auth["priorCompleted"]["bytes"])
    pinned(root/v3.JOURNAL_REL, auth["priorBodyJournal"]["sha256"], auth["priorBodyJournal"]["bytes"])
    old, evidence = v3.validate_resume(root, manifest, prior)
    if len(old) != 3554 or any(key in old for key in KEYS):
        raise RuntimeError("Different3554 prior prefix or carry key already complete")
    Deadline().check()
    return root, auth, prior, manifest, review, dict(writer_probe=writer_probe(), completed_objects=3554,
                                                   deadline_utc=auth["budget"]["deadlineUtc"], e_write=False,
                                                   public_get=False, candidate_run=False, llm_called=False)


def inspect_closed(root, auth, prior, manifest, review_sha):
    phase = json.loads((root/PHASE_REL).read_bytes())
    if (phase.get("protocol") != TRANSPORT or phase.get("validated") is not True or phase.get("state") != "two_key_phase_closed" or
            phase.get("full5826_complete") is not False or phase.get("completed_objects") != 3556 or
            phase.get("lease_handle_closed") is not True or phase.get("review_sha256") != review_sha or
            phase.get("authorization_sha256") != AUTH_SHA):
        raise RuntimeError("Unclosed/unknown carry phase; no automatic recovery")
    marker = json.loads(pinned(root/"audit"/base.LEASE_NAME, phase["released_lease_sha256"]))
    if marker.get("held") is not False or marker.get("outcome") != "carry_phase_closed" or marker.get("lease_id") != phase["lease_id"]:
        raise RuntimeError("Carry lease has not closed under exact identity")
    all_rows, tail = validate_typed_rows(root, manifest, auth, prior)
    raw = (root/"audit/cache-downloads.jsonl").read_bytes()
    attempts = inspect_attempts(root/EVENTS_REL, phase["lease_id"], review_sha, auth, raw)
    if (len(all_rows) != 3556 or {r["ltar"] for r in tail} != set(KEYS) or
            set(attempts["dispatched"]) != set(KEYS) or set(attempts["commits"]) != set(KEYS) or
            phase["download_receipts_sha256"] != hashlib.sha256(raw).hexdigest() or
            phase["attempts_sha256"] != attempts["raw_sha256"] or phase["new_gets"] != 2 or phase["aggregate_known_gets"] != 1507):
        raise RuntimeError("Closed carry counts/hash/commits differ")
    validate_review(review_sha)
    return dict(phase_closed=True, completed_objects=3556, missing_objects=2270, full5826_complete=False,
                public_get=False, e_write=False, llm_called=False, candidate_run=False)


def acquire(root, public, core, review_sha):
    root, auth, prior, manifest, review, gate = preflight(root, public, core, review_sha)
    start_worker_sha = sha(__file__)
    clock = Deadline()
    lease = OwnedLease(root/"audit"/base.LEASE_NAME)
    stop, observer, book, journal = threading.Event(), None, None, None
    errors, initial, final = [], None, None
    receipt = root/"audit/cache-downloads.jsonl"
    original_raw = b""
    def guard():
        if stop.is_set():
            raise RuntimeError("Shared carry stop")
        clock.check()
        lease.assert_owned()
        book.check()
    def observe():
        while not stop.wait(10):
            try:
                guard()
                writer_probe()
            except Exception as error:
                errors.append(type(error).__name__+": "+str(error))
                stop.set()
    def footer(outcome, **extra):
        return dict(held=False, pid=os.getpid(), released_at_utc=stamp(), outcome=outcome,
                    transport_protocol=TRANSPORT, authorization_sha256=AUTH_SHA, executing_review_sha256=review_sha,
                    executing_worker_sha256=start_worker_sha, body_journal=prior["body_journal"],
                    prefix_operations_closed=True, prior_stage_gets=1505,
                    new_get_intents=len(journal.used) if journal else 0,
                    aggregate_consumed_get_allowance=1505+(len(journal.used) if journal else 0),
                    actual_opener_calls=len(journal.open_calls) if journal else 0,
                    aggregate_known_transport_attempts=1505+(len(journal.open_calls) if journal else 0),
                    attempt_journal=journal.footer() if journal else None,
                    deadline_utc=auth["budget"]["deadlineUtc"], **extra)
    try:
        lease.acquire()
        lease.write(dict(held=True, pid=os.getpid(), acquired_at_utc=stamp(), transport_protocol=TRANSPORT,
                         authorization_sha256=AUTH_SHA, executing_review_sha256=review_sha,
                         executing_worker_sha256=start_worker_sha))
        # After share-deny claim, check captured prior evidence without reopening own lease.
        v3.validate_resume(root, manifest, prior)
        original_raw = pinned(receipt, auth["priorCompleted"]["sha256"], auth["priorCompleted"]["bytes"])
        load_authorization()
        validate_review(review_sha)
        start_probe = writer_probe()
        initial = base.full_scan(root)
        book = v3.Book(initial["allocated_envelope_bytes"], 292278)
        book.recoveries = 6
        journal = AttemptJournal(root/EVENTS_REL, lease.id, review_sha)
        observer = threading.Thread(target=observe, name="root-carry-writer-observer", daemon=True)
        observer.start()
        by_key = {r["ltar"]: r for r in manifest}
        for policy in auth["keys"]:
            guard()
            validate_review(review_sha)
            fresh_one(policy, by_key[policy["key"]], root, lease, book, journal, guard, receipt)
        stop.set()
        observer.join(timeout=35)
        if observer.is_alive() or errors:
            raise RuntimeError("Carry observer did not close cleanly: "+str(errors))
        all_rows, tail = validate_typed_rows(root, manifest, auth, prior)
        raw = receipt.read_bytes()
        attempts = inspect_attempts(root/EVENTS_REL, lease.id, review_sha, auth, raw)
        if (len(all_rows) != 3556 or len(tail) != 2 or not raw.startswith(original_raw) or
                set(attempts["commits"]) != set(KEYS) or len(journal.used) != 2):
            raise RuntimeError("Two-key closure is not exactly3556/2")
        final = base.full_scan(root)
        mutable = {"audit/"+base.LEASE_NAME, "audit/cache-downloads.jsonl", EVENTS_REL, PHASE_REL}
        for name, metadata in initial["files"].items():
            if name not in mutable and final["files"].get(name) != metadata:
                raise RuntimeError("Existing source/cache metadata changed: "+name)
        allowed_new = {EVENTS_REL, PHASE_REL, *("downloads/mathlib-cache/"+key for key in KEYS)}
        if set(final["files"])-set(initial["files"])-allowed_new:
            raise RuntimeError("Unknown new owned file")
        if final["allocated_envelope_bytes"] > book.used or final["allocated_envelope_bytes"]+base.AUDIT_BUDGET > base.CAP:
            raise RuntimeError("Final directory exceeds conservative ledger")
        validate_review(review_sha)
        load_authorization()
        end_probe = writer_probe()
        clock.check()
        phase = dict(protocol=TRANSPORT, state="awaiting_lease_release", validated=False, lease_id=lease.id,
                     authorization_sha256=AUTH_SHA, archive_receipt_sha256=ARCHIVE_SHA, review_sha256=review_sha,
                     executing_worker_sha256=start_worker_sha, source_start_sha256=start_worker_sha,
                     source_end_sha256=sha(__file__), completed_objects=3556, missing_objects=2270,
                     full5826_complete=False, new_gets=2, prior_stage_gets=1505, aggregate_known_gets=1507,
                     carried_preservation_operations=6, carried_failed_prefix_bytes=292278,
                     original3554_prefix_sha256=hashlib.sha256(original_raw).hexdigest(), original3554_prefix_unchanged=True,
                     download_receipts_sha256=hashlib.sha256(raw).hexdigest(), attempts_sha256=attempts["raw_sha256"],
                     initial_envelope=initial["allocated_envelope_bytes"], final_envelope=final["allocated_envelope_bytes"],
                     ledger_peak=book.peak, full_directory_scans=2, start_writer_probe=start_probe, end_writer_probe=end_probe,
                     deadline_utc=auth["budget"]["deadlineUtc"], original_body_journal_unchanged=True,
                     candidate_run=False, llm_called=False, lean_executed=False, lease_handle_closed=False)
        base.durable_json(root/PHASE_REL, phase)
        lease.write(footer("carry_phase_closed", completed_objects=3556, retained_unclosed_owned_parts=[]))
        lease.close()
        phase.update(state="two_key_phase_closed", validated=True, lease_handle_closed=True,
                     released_lease_sha256=sha(root/"audit"/base.LEASE_NAME), closed_at_utc=stamp())
        validate_review(review_sha)
        clock.check()
        writer_probe()
        base.volume_reserves(base.AUDIT_BUDGET)
        base.durable_json(root/PHASE_REL, phase)
        inspect_closed(root, auth, prior, manifest, review_sha)
        print(json.dumps(dict(phase=PHASE_REL, sha256=sha(root/PHASE_REL), completed_objects=3556,
                              full5826_complete=False, candidate_run=False, llm_called=False)), flush=True)
    except Exception as error:
        stop.set()
        if observer:
            observer.join(timeout=35)
            if observer.is_alive():
                raise RuntimeError("Cannot close lease while owned observer still runs") from error
        if lease.stream is not None:
            artifacts, settle_error = [], None
            try:
                if book:
                    artifacts = book.settle_unclosed_parts()
            except Exception as secondary:
                settle_error = type(secondary).__name__+": "+str(secondary)
            retained = 292278+sum(p["bytes"] for p in artifacts)
            phase_error = (type(error).__name__+": "+str(error))[:4096]
            lease.write(footer("carry_aborted", error=phase_error, observer=errors,
                               completed_objects_established_by_acknowledged_events=3554+(len(journal.committed) if journal else 0),
                               retained_unclosed_owned_parts=artifacts, settle_error=settle_error,
                               conservative_preservation_operations=6+len(artifacts),
                               conservative_failed_prefix_bytes=retained))
        raise
    finally:
        lease.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("gate", "acquire"))
    parser.add_argument("--review-sha", required=True)
    args = parser.parse_args()
    public = PROJECT/".phase1-data/minif2f-restoration-public"
    core = Path(__file__).with_name("minif2f_restore.py")
    root = Path(base.ROOT)
    if args.stage == "gate":
        print(json.dumps(preflight(root, public, core, args.review_sha, allow_closed=True)[-1]), flush=True)
    else:
        acquire(root, public, core, args.review_sha)


if __name__ == "__main__":
    main()
