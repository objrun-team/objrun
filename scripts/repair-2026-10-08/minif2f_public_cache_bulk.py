"""Explicit new2270-key budget after closed3556 carry; complete fresh GET only.

The v1 name below is the closed data contract consumed by frozen fast/Lean
readers. The executing transport is independently named and source-reviewed.
Unknown partials, unclosed journal operations and stale leases are never repaired.
Opaque Azure ETags are recorded as opaque, not as RFC quoted strong validators.
No old prefix bytes are appended, ranged, or reused in a successful body.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import base64
import binascii
from concurrent.futures import ThreadPoolExecutor, as_completed
import errno
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request

BASE_SHA = "a02c3519b0ccba8a74e577991fedcf75f0c05fb181cfeb617b7e51b060384c2b"
PROFILE_SHA = "f23ebc252a02cf9a407db4fb2045f6c8dba064e1706e97d28fc6ff96ac2a5fd3"
TRANSPORT = "explicit-root-new-key-complete-bulk-v1"
V3_TRANSPORT = "same-key-body-timeout-complete-fresh-v3"
V2_TRANSPORT = "same-key-body-timeout-prefix-preserved-v2"
POLICY_MD5 = "known-length-content-md5-complete-fresh-bulk-v1"
POLICY_ETAG = "known-length-quoted-etag-complete-fresh-bulk-v1"
REVIEW_PROTOCOL = "public-cache-explicit-bulk-source-review-v1"
JOURNAL_REL = "audit/public-cache-bulk-body-attempts.jsonl"
EVIDENCE_REL = "downloads/mathlib-cache-bulk-failed-prefix"
DISPATCH_REL = "audit/public-cache-bulk-get-intents.jsonl"
INPUT_REL = "audit/public-cache-bulk-inputs.json"
PHASE_REL = "audit/public-cache-bulk-phase.json"
MAX_GETS, MAX_BODY_RETRIES, MAX_STAGE_RECOVERIES = 3, 1, 4
PREFIX_CAP, JOURNAL_CAP = 256*1024**2, 2*1024**2
UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
HEX_RE = r"[0-9a-f]{64}"
AUTO_RELEASED = object()

def load_base():
    path = Path(__file__).with_name("minif2f_public_cache.py")
    if hashlib.sha256(path.read_bytes()).hexdigest() != BASE_SHA:
        raise RuntimeError("Frozen a02 guard source changed")
    spec = importlib.util.spec_from_file_location("public_cache_a02_guards", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

base = load_base()
def load_carry():
    path=Path(__file__).with_name("minif2f_public_cache_root_carry.py")
    if hashlib.sha256(path.read_bytes()).hexdigest()!="8e199889ef3eff84747383ce2196e9a46e439637c53d9a1471d2df6319236ba3":
        raise RuntimeError("Frozen actual carry source changed")
    spec=importlib.util.spec_from_file_location("bulk_prior_carry",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
carry=load_carry()
CARRY_REVIEW_SHA="1a4ce79743fe80e89c673b79f934399d1663ae7a0066d52c4c5e5964cb168bc4"
CARRY_PHASE_SHA="6b1f63ad1f78331d60254dc2b48ec2da3e66f3ce645ab0fbbd27d43342265c2b"
CARRY_RECEIPTS_SHA="0a1341f62fd894701915886aec9e4f4258a686e73e54c644bab7a289a9b48713"
CARRY_LEASE_SHA="eae8be6693a60271d4378981b8f33422619a3005ef962afa0b0e5d2cff8b4c63"
PROTOCOL, ROOT = base.PROTOCOL, base.ROOT
AZURE, MAX_BLOB, BLOCK = base.AZURE, base.MAX_BLOB, base.BLOCK
MAX_RECEIPT_LINE, AUDIT_BUDGET = base.MAX_RECEIPT_LINE, 64*1024**2
stamp, sha, rounded, assert_regular = base.stamp, base.sha, base.rounded, base.assert_regular

def strong_etag(value):
    return (isinstance(value, str) and 2 <= len(value) <= 256 and
            value.startswith('"') and value.endswith('"') and
            all(0x21 <= ord(c) <= 0x7e and c != '"' for c in value[1:-1]))

def etag_kind(value):
    if value is None: return None
    if (not isinstance(value,str) or not 0 < len(value) <= 256 or
        not all(0x21 <= ord(c) <= 0x7e for c in value)):
        raise RuntimeError("Invalid bounded opaque ETag")
    return ("quoted_strong" if strong_etag(value) else
            "weak" if value.startswith("W/") else "opaque_unquoted")

def content_md5(value):
    if value is None: return None
    if not isinstance(value,str) or len(value)!=24:
        raise RuntimeError("Content-MD5 is not canonical16-byte base64")
    try: raw=base64.b64decode(value,validate=True)
    except (ValueError,binascii.Error) as error:
        raise RuntimeError("Invalid Content-MD5 base64") from error
    if len(raw)!=16 or base64.b64encode(raw).decode("ascii")!=value:
        raise RuntimeError("Content-MD5 is not canonical16-byte base64")
    return raw

def recovery_policy(length, http):
    if type(length) is not int or not 0 < length <= MAX_BLOB:
        raise RuntimeError("Fresh body recovery requires a known bounded length")
    etag_kind(http.get("etag"))
    if content_md5(http.get("content-md5")) is not None:
        return POLICY_MD5
    if strong_etag(http.get("etag")):
        return POLICY_ETAG
    raise RuntimeError("Fresh body recovery has no accepted MD5/quoted-ETag validator")

def md5_file(path):
    assert_regular(path)
    h=hashlib.md5(usedforsecurity=False)
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda:stream.read(BLOCK),b""): h.update(chunk)
    return base64.b64encode(h.digest()).decode("ascii")

def validate_recovery_record(row, transport):
    if transport==V2_TRANSPORT:
        if not strong_etag(row.get("etag")):
            raise RuntimeError("Historical V2 prefix lacks its original quoted strong ETag")
        return
    policy=recovery_policy(row.get("content_length"),
                           {"etag":row.get("etag"),"content-md5":row.get("content_md5")})
    if row.get("recovery_policy")!=policy or row.get("etag_kind")!=etag_kind(row.get("etag")):
        raise RuntimeError("V3 prefix policy/opaque header classification changed")

def metadata(response, url):
    if response.status != 200 or response.geturl() != url:
        raise RuntimeError("Public GET must return200 at the exact fixed URL")
    seen=set()
    for key,value in response.headers.items():
        key=key.lower()
        if key in {"content-length","content-md5","etag","content-encoding"}:
            if key in seen: raise RuntimeError("Ambiguous duplicate integrity header")
            seen.add(key)
    raw = response.headers.get("Content-Length")
    if raw is not None and (not re.fullmatch(r"[0-9]{1,12}", raw)):
        raise RuntimeError("Invalid Content-Length")
    length = int(raw) if raw is not None else None
    if length is not None and not 0 < length <= MAX_BLOB:
        raise RuntimeError("Public Content-Length outside64MiB")
    encoding = response.headers.get("Content-Encoding")
    if encoding is not None and encoding.lower() != "identity":
        raise RuntimeError("Public response is not identity encoding")
    http = {k.lower():v for k,v in response.headers.items()
            if k.lower() in {"etag","content-md5","last-modified","content-length"}}
    if any(not isinstance(v,str) or len(v.encode()) > 256 for v in http.values()):
        raise RuntimeError("HTTP metadata exceeds the fixed row budget")
    content_md5(http.get("content-md5"))
    etag_kind(http.get("etag"))
    return length, http

def retryable_open(error):
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    return (not isinstance(error, (urllib.error.HTTPError, http.client.HTTPException, ssl.SSLError, EOFError))
            and not isinstance(reason, (http.client.HTTPException, ssl.SSLError, EOFError))
            and (isinstance(reason, (TimeoutError, socket.timeout)) or
                 isinstance(reason, OSError) and
                 (getattr(reason,"winerror",None) in {10053,10054,10060}
                  or getattr(reason,"errno",None) in {errno.ETIMEDOUT,errno.ECONNRESET,errno.ECONNABORTED})))

class Attempts:
    def __init__(self, name, book):
        self.name, self.book = name, book
        self.gets, self.generations, self.events = 0, 0, []
    def open(self, opener, request, guard, sleeper=time.sleep):
        while self.gets < MAX_GETS:
            guard()
            self.gets += 1
            with self.book.lock:
                serial = self.book.next_get(self.name)
                # Atomic ordinal plus durable intent; concurrent workers cannot
                # record ordinal2 before ordinal1. An ambiguous intent is used.
                self.book.dispatch(self.name,self.gets,serial)
            event = dict(get=self.gets, global_get=serial, response_received=False)
            self.events.append(event)
            try:
                with self.book.lock:self.book.open_calls+=1
                response = opener.open(request, timeout=60)
            except Exception as error:
                event.update(error_type=type(error).__name__, retryable=retryable_open(error))
                if not event["retryable"] or self.gets >= MAX_GETS:
                    raise
                guard(); sleeper((.5,2)[min(self.gets-1,1)]); guard()
            else:
                self.generations += 1
                if self.generations > MAX_BODY_RETRIES+1:
                    response.close()
                    raise RuntimeError("More than two opened body generations")
                event.update(response_received=True, generation=self.generations)
                return response, event
        raise RuntimeError("Shared opening/body GET budget exhausted")

class Book(base.Ledger):
    def __init__(self, initial, prior_prefix_bytes=0, reserve=None):
        self.dispatch_journal=None
        super().__init__(initial, reserve=reserve or (lambda addition:base.volume_reserves(addition+48*1024**2)))
        self.used+=48*1024**2
        self.check()
        self.recoveries = 0
        self.prefix_bytes = prior_prefix_bytes
        self.gets = 0
        self.get_counts = {}
        self.parts = {}
        self.open_calls=0
    def begin(self,name,limit):
        with self.lock:
            super().begin(name,limit)
            # Reserve worst-case retention of every inflight body. Any abort
            # keeps bytes; the 256MiB cap is never enforced by deleting proof.
            if self.prefix_bytes+sum(self.reservations.values())>PREFIX_CAP:
                del self.reservations[name]
                raise RuntimeError("Failed-prefix plus all inflight retention forecast exceeds256MiB")
    def dispatch(self,name,key_get,serial):
        if key_get>3 or serial>6810:raise RuntimeError("Explicit new bulk GET allowance exhausted")
        if self.dispatch_journal is None:raise RuntimeError("No durable new-budget dispatch journal")
        self.dispatch_journal.append(dict(event="dispatch",key=name,new_key_get=key_get,
            new_global_get=serial,v3_window_gets_before=1507,v3_window_consumed_allowance=1507+serial,
            old_v3_key_interval=[0,3],v3_plus_bulk_key_interval=[key_get,key_get+3],
            all_history_key_gets=None,all_history_global_gets=None))
    def next_get(self, name):
        with self.lock:
            self.gets += 1
            self.get_counts[name]=self.get_counts.get(name,0)+1
            return self.gets
    def allow_prefix(self, size):
        if self.recoveries >= MAX_STAGE_RECOVERIES:
            raise RuntimeError("Stage new body recovery budget4 exhausted")
        if self.prefix_bytes+size > PREFIX_CAP:
            raise RuntimeError("Registered failed-prefix budget256MiB exhausted")
    def retain(self, name, size):
        # The bytes already exist. No rollback/deletion on a later guard failure.
        self.allow_prefix(size)
        self.used += rounded(size)+base.META_PER_BLOB
        del self.reservations[name]
        self.recoveries += 1
        self.prefix_bytes += size
        if name in self.parts: self.parts[name]["retained_in_used"]=True
        self.check()
    def observe_part(self, name, path, identity, observed_http=None):
        with self.lock:
            self.parts[name]=dict(path=str(path),identity=identity,retained_in_used=False,
                                 observed_http=observed_http)
    def settle_unclosed_parts(self):
        """Called after all workers stop; retain each exact own file in used.

        No unknown path adoption, deletion or repair. A torn IO operation is
        reported as an unclosed artifact, not promoted to a completed object.
        """
        result=[]
        with self.lock:
            for name,owned in self.parts.items():
                path=Path(owned["path"])
                assert_regular(path); info=path.stat()
                if (info.st_dev,info.st_ino)!=owned["identity"] or info.st_size>MAX_BLOB:
                    raise RuntimeError("Unclosed owned part changed identity/size")
                allocation=rounded(info.st_size)+base.META_PER_BLOB
                if not owned["retained_in_used"]:
                    self.used+=allocation
                    self.reservations.pop(name,None)
                    owned["retained_in_used"]=True
                result.append(dict(key=name,path=str(path),bytes=info.st_size,
                    sha256=sha(path),allocated_plus_metadata_bytes=allocation,
                    promoted_to_complete=False,observed_http=owned.get("observed_http")))
            self.peak=max(self.peak,self.used+sum(self.reservations.values()))
        return result

def encode_row(row):
    value=(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n").encode()
    if len(value)>MAX_RECEIPT_LINE:
        raise RuntimeError("Typed journal/receipt row exceeds2048bytes")
    return value

def sync_stream(stream):
    stream.flush()
    os.fsync(stream.fileno())

class Journal:
    def __init__(self, root):
        self.root, self.path = Path(root), Path(root)/JOURNAL_REL
        self.lock = threading.RLock()
        if not self.path.exists():
            with self.path.open("xb") as stream: sync_stream(stream)
        assert_regular(self.path)
        self.synced_bytes=self.path.stat().st_size
        self.synced_sha=sha(self.path)
    def append(self, row):
        encoded=encode_row(row)
        with self.lock:
            assert_regular(self.path)
            if self.path.stat().st_size+len(encoded)>JOURNAL_CAP:
                raise RuntimeError("Typed journal exceeds2MiB within64MiB audit budget")
            with self.path.open("ab") as stream:
                if stream.write(encoded)!=len(encoded):
                    raise RuntimeError("Short journal write")
                sync_stream(stream)
            # Set only after flush/fsync/close all returned. A failed tail does
            # not match this digest; lease footer makes resume reject it.
            self.synced_bytes=self.path.stat().st_size
            self.synced_sha=sha(self.path)
        return hashlib.sha256(encoded).hexdigest()
    def footer(self):
        return dict(path=JOURNAL_REL, synced_bytes=self.synced_bytes,
                    synced_sha256=self.synced_sha)

def lease_record(root):
    path=Path(root)/"audit"/base.LEASE_NAME
    if not path.exists(): return None
    assert_regular(path)
    if path.stat().st_size>16384: raise RuntimeError("Oversized prior lease")
    value=json.loads(path.read_bytes())
    if value.get("held") is not False or value.get("protocol")!=PROTOCOL or value.get("run_id")!=base.RUN_ID:
        raise RuntimeError("Active/stale/unknown acquisition lease")
    return value

def validate_evidence(root, rows, released=None):
    root=Path(root); path=root/JOURNAL_REL; directory=root/EVIDENCE_REL
    keys={r["ltar"] for r in rows}
    if path.with_name(path.name+".new").exists():
        raise RuntimeError("Unknown typed audit partial")
    if not path.exists():
        if directory.exists(): raise RuntimeError("Orphan prefix evidence directory")
        return dict(prefixes={},bytes=0,journal_sha256=None)
    assert_regular(path)
    if path.stat().st_size>JOURNAL_CAP:
        raise RuntimeError("Typed journal exceeds2MiB")
    raw=path.read_bytes()
    if len(raw)>JOURNAL_CAP or raw and not raw.endswith(b"\n"):
        raise RuntimeError("Oversized/truncated typed journal")
    released=released if released is not None else lease_record(root)
    footer=(released or {}).get("body_journal")
    if (not isinstance(footer,dict) or footer.get("path")!=JOURNAL_REL
        or footer.get("synced_bytes")!=len(raw) or footer.get("synced_sha256")!=hashlib.sha256(raw).hexdigest()
        or (released or {}).get("prefix_operations_closed") is not True):
        raise RuntimeError("Journal lacks matching returned-fsync/closed lease footer")
    prepared, committed, counts, global_gets={}, {}, {}, set()
    for line in raw.splitlines(keepends=True):
        if not line.strip() or len(line)>MAX_RECEIPT_LINE:
            raise RuntimeError("Invalid typed journal row")
        r=json.loads(line)
        lid,name,generation=r.get("lease_id"),r.get("key"),r.get("generation")
        transport=r.get("transport_protocol")
        if (transport!=TRANSPORT or not isinstance(lid,str)
            or not re.fullmatch(UUID_RE,lid) or name not in keys or type(generation) is not int or generation!=1):
            raise RuntimeError("Journal key/lease/generation differs from fixed typed schema")
        op=lid+":"+name+":1"
        expected=EVIDENCE_REL+"/"+lid+"-"+name[:16]+"-g1.prefix"
        if (r.get("operation")!=op or r.get("path")!=expected or type(r.get("bytes")) is not int
            or not 0<=r["bytes"]<=MAX_BLOB or not isinstance(r.get("sha256"),str) or not re.fullmatch(HEX_RE,r["sha256"])):
            raise RuntimeError("Wrong prefix path/bytes/SHA")
        event=r.get("event")
        if event=="prepared":
            if op in prepared or op in committed: raise RuntimeError("Duplicate prefix intent")
            if (r.get("prefix_flush_returned") is not True or r.get("prefix_fsync_returned") is not True
                or r.get("created_xb_this_lease") is not True or type(r.get("content_length")) is not int
                or not r["bytes"]<=r["content_length"]<=MAX_BLOB
                or r.get("url")!=AZURE+name or r.get("http_status")!=200
                or r.get("body_error_type") not in ("TimeoutError","timeout","ShortBodyEOF")
                or type(r.get("get")) is not int or not 1<=r["get"]<MAX_GETS
                or type(r.get("global_get")) is not int or r["global_get"]<r["get"]
                or type(r.get("created_device")) is not int or type(r.get("created_inode")) is not int
                or r.get("allocated_prefix_plus_metadata_bytes")!=rounded(r["bytes"])+base.META_PER_BLOB):
                raise RuntimeError("Prefix intent has no exact identity/returned durability")
            validate_recovery_record(r,transport)
            if (lid,r["global_get"]) in global_gets: raise RuntimeError("Duplicate global GET identity")
            global_gets.add((lid,r["global_get"]))
            prepared[op]=(r,hashlib.sha256(line).hexdigest())
        elif event=="committed":
            if op not in prepared or op in committed: raise RuntimeError("Orphan/duplicate prefix commit")
            prev,digest=prepared[op]
            if (r.get("prepared_journal_fsync_returned") is not True or r.get("prepared_row_sha256")!=digest
                or any(r[k]!=prev[k] for k in ("path","bytes","sha256","lease_id","key","generation",
                                              "transport_protocol"))):
                raise RuntimeError("Commit differs from fsynced intent")
            committed[op]=prev
            counts[lid]=counts.get(lid,0)+1
        else: raise RuntimeError("Unknown typed journal state")
    if set(prepared)!=set(committed):
        raise RuntimeError("Unclosed prepared prefix; no automatic crash-gap repair")
    if any(n>MAX_STAGE_RECOVERIES for n in counts.values()):
        raise RuntimeError("New stage exceeds4 prefix recoveries")
    total=sum(r["bytes"] for r in committed.values())
    if total>PREFIX_CAP: raise RuntimeError("Retained registered prefixes exceed256MiB")
    allowed={r["path"]:r for r in committed.values()}
    actual=set()
    if directory.exists():
        st=directory.lstat()
        if not directory.is_dir() or getattr(st,"st_file_attributes",0)&0x400:
            raise RuntimeError("Unknown prefix directory/reparse")
        for p in directory.iterdir():
            assert_regular(p)
            rel=p.relative_to(root).as_posix(); actual.add(rel)
            if rel not in allowed or p.stat().st_size!=allowed[rel]["bytes"] or sha(p)!=allowed[rel]["sha256"]:
                raise RuntimeError("Orphan/modified prefix artifact")
    if actual!=set(allowed): raise RuntimeError("Registered prefix is missing")
    return dict(prefixes=committed,bytes=total,journal_sha256=hashlib.sha256(raw).hexdigest())


def owned_prefix(part, identity, written, digest):
    assert_regular(part)
    before=part.stat()
    if (before.st_dev,before.st_ino)!=identity or before.st_size!=written or sha(part)!=digest:
        raise RuntimeError("This lease's xb prefix identity/bytes/SHA changed")
    after=part.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise RuntimeError("Prefix changed during hash readback")

class ShortBodyEOF(RuntimeError):pass

def preserve_prefix(root, part, identity, written, digest, length, http, attempt, lease, book, journal, guard, error):
    policy=recovery_policy(length,http)
    if attempt.gets>=MAX_GETS or attempt.generations!=1:
        raise RuntimeError("No shared GET or one-body retry allowance remains")
    owned_prefix(part,identity,written,digest)
    op=lease.id+":"+attempt.name+":1"
    rel=EVIDENCE_REL+"/"+lease.id+"-"+attempt.name[:16]+"-g1.prefix"
    target=Path(root)/rel
    with book.lock:
        guard(); book.allow_prefix(written)
        # Retain actual allocated prefix+metadata before reserving a fresh body.
        book.retain(attempt.name,written)
        target.parent.mkdir(exist_ok=True)
        if target.parent.stat().st_dev!=part.stat().st_dev or target.exists():
            raise RuntimeError("Prefix rename must be same-volume and no-replace")
        intent=dict(transport_protocol=TRANSPORT,event="prepared",operation=op,
            lease_id=lease.id,key=attempt.name,generation=1,path=rel,bytes=written,sha256=digest,
            created_xb_this_lease=True,prefix_flush_returned=True,prefix_fsync_returned=True,
            created_device=identity[0],created_inode=identity[1],
            allocated_prefix_plus_metadata_bytes=rounded(written)+base.META_PER_BLOB,
            content_length=length,etag=http.get("etag"),etag_kind=etag_kind(http.get("etag")),
            content_md5=http.get("content-md5"),recovery_policy=policy,
            url=AZURE+attempt.name,http_status=200,
            get=attempt.gets,global_get=attempt.events[-1]["global_get"],
            body_error_type=type(error).__name__,recorded_at_utc=stamp())
        intent_sha=journal.append(intent)
        owned_prefix(part,identity,written,digest)
        part.rename(target)  # Windows rename refuses an existing target.
        book.parts[attempt.name]["path"]=str(target)
        owned_prefix(target,identity,written,digest)
        journal.append(dict(transport_protocol=TRANSPORT,event="committed",operation=op,
            lease_id=lease.id,key=attempt.name,generation=1,path=rel,bytes=written,sha256=digest,
            prepared_journal_fsync_returned=True,prepared_row_sha256=intent_sha,recorded_at_utc=stamp()))
        book.parts.pop(attempt.name)
        book.begin(attempt.name,length)
        guard()
    return intent

def get_one(row, root, lease, book, journal, guard, receipt, completed,
            opener=None, sleeper=time.sleep):
    name,url=row["ltar"],AZURE+row["ltar"]
    if not re.fullmatch(r"[0-9a-f]{16}\.ltar",name):
        raise RuntimeError("Only a fixed public16hex key is allowed")
    guard()
    opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),base.NoRedirect())
    request=urllib.request.Request(url,headers={"User-Agent":"TgEngin-explicit-public-bulk-v1","Accept-Encoding":"identity"},method="GET")
    attempts=Attempts(name,book); prefix=None
    while True:
        opened,_=attempts.open(opener,request,guard,sleeper)
        timeout_error=None
        with opened as response:
            guard(); length,http=metadata(response,url)
            if length is None or content_md5(http.get("content-md5"))is None:
                raise RuntimeError("Explicit bulk requires known length and complete-body Content-MD5")
            if prefix is not None:
                if (length!=prefix["content_length"] or http.get("etag")!=prefix["etag"] or
                    http.get("content-md5")!=prefix["content_md5"] or
                    recovery_policy(length,http)!=prefix["recovery_policy"]):
                    raise RuntimeError("Fresh same-key observed ETag/MD5/length/policy changed")
            else: book.begin(name,length or MAX_BLOB)
            part=Path(root)/"downloads/mathlib-cache"/(name+".part")
            digest=hashlib.sha256(); prefix_digest=hashlib.sha256(); compared=0; written=0
            body_md5=hashlib.md5(usedforsecurity=False)
            with part.open("xb") as stream:
                identity=(os.fstat(stream.fileno()).st_dev,os.fstat(stream.fileno()).st_ino)
                book.observe_part(name,part,identity,
                                  dict(url=url,status=200,content_length=length,headers=http))
                while True:
                    guard()
                    # The sole body timeout catch is the actual read1 call.
                    try: chunk=response.read1(BLOCK)
                    except (TimeoutError,socket.timeout) as error:
                        timeout_error=error
                        sync_stream(stream)
                        break
                    if not chunk: break
                    guard()
                    written+=len(chunk)
                    if written>MAX_BLOB or length is not None and written>length:
                        raise RuntimeError("Public body exceeds bounded/declared length")
                    if stream.write(chunk)!=len(chunk): raise RuntimeError("Short owned body write")
                    digest.update(chunk)
                    body_md5.update(chunk)
                    if prefix is not None and compared<prefix["bytes"]:
                        amount=min(len(chunk),prefix["bytes"]-compared)
                        prefix_digest.update(chunk[:amount]); compared+=amount
                        if compared==prefix["bytes"] and prefix_digest.hexdigest()!=prefix["sha256"]:
                            raise RuntimeError("Fresh body prefix SHA changed")
                    book.check()
                if timeout_error is None: sync_stream(stream)
        # Failed response is now closed before any preservation/new GET.
        if timeout_error is None and length is not None and written<length:
            timeout_error=ShortBodyEOF("Observed body EOF below declared length")
        if timeout_error is not None:
            if prefix is not None: raise timeout_error  # No third body generation.
            prefix=preserve_prefix(root,part,identity,written,digest.hexdigest(),length,http,
                                   attempts,lease,book,journal,guard,timeout_error)
            continue
        if not written or length is not None and written!=length:
            raise RuntimeError("Public body EOF/length mismatch")
        if prefix is not None and (compared!=prefix["bytes"] or prefix_digest.hexdigest()!=prefix["sha256"]):
            raise RuntimeError("Fresh body did not match all retained prefix bytes")
        expected_md5=content_md5(http.get("content-md5"))
        if expected_md5 is not None and body_md5.digest()!=expected_md5:
            raise RuntimeError("Complete fresh/public body Content-MD5 mismatch; no retry")
        owned_prefix(part,identity,written,digest.hexdigest())
        result={**row,"url":url,"bytes":written,"sha256":digest.hexdigest(),"http":http,
            "recorded_at_utc":stamp(),"acquisition_protocol":PROTOCOL,"lease_id":lease.id,
            "http_status":200,"hash_assurance":"official public key/URL; local SHA measured after GET",
            "transport_protocol":TRANSPORT,"transport_gets":attempts.gets,"body_generations":attempts.generations,
            "etag_kind":etag_kind(http.get("etag")),"content_md5_verified":expected_md5 is not None,
            "measured_content_md5":base64.b64encode(body_md5.digest()).decode("ascii") if expected_md5 is not None else None,
            "fresh_body_complete_from_new_get":prefix is not None,"failed_prefix_bytes_reused_in_body":0,
            "fresh_recovery_policy":prefix["recovery_policy"] if prefix is not None else None,
            "new_budget_namespace":lease.id,"old_v3_key_interval":[0,3],
            "v3_plus_bulk_key_interval":[attempts.gets,attempts.gets+3],
            "all_history_key_gets":None,"all_history_global_gets":None}
        if prefix is not None: result["failed_prefix_operation"]=prefix["operation"]
        encoded=encode_row(result); guard()
        with book.lock:
            destination=part.with_name(name)
            if destination.exists(): raise RuntimeError("Never replace an existing final object")
            part.rename(destination)
            book.parts[name]["path"]=str(destination)
            with Path(receipt).open("ab") as stream:
                if stream.write(encoded)!=len(encoded): raise RuntimeError("Short completed receipt write")
                sync_stream(stream)
            completed[name]=result
            book.parts.pop(name)
            book.committed(name,written)
        return result








def validate_new_rows(root,rows,evidence):
    for name,row in rows.items():
        gets=row.get("transport_gets");generations=row.get("body_generations")
        if (row.get("transport_protocol")!=TRANSPORT or type(gets)is not int or not 1<=gets<=3 or
            type(generations)is not int or generations not in (1,2)):
            raise RuntimeError("New bulk counters/protocol differ")
        http=row.get("http")
        if not isinstance(http,dict):raise RuntimeError("Bulk receipt lacks observed headers")
        expected=content_md5(http.get("content-md5"))
        if (expected is None or http.get("content-length")!=str(row["bytes"]) or
            row.get("content_md5_verified")is not True or row.get("measured_content_md5")!=http["content-md5"] or
            md5_file(Path(root)/"downloads/mathlib-cache"/name)!=http["content-md5"] or
            row.get("etag_kind")!=etag_kind(http.get("etag")) or row.get("failed_prefix_bytes_reused_in_body")!=0 or
            row.get("fresh_body_complete_from_new_get")is not (generations==2)):
            raise RuntimeError("Bulk actual full MD5/length/header/fresh provenance differ")
        pointer=row.get("failed_prefix_operation")
        if generations==2:
            prefix=evidence["prefixes"].get(pointer)
            if (not prefix or prefix["key"]!=name or prefix["lease_id"]!=row["lease_id"] or
                prefix["transport_protocol"]!=TRANSPORT or row.get("fresh_recovery_policy")!=prefix["recovery_policy"] or
                http.get("etag")!=prefix["etag"] or http.get("content-md5")!=prefix["content_md5"] or
                int(http["content-length"])!=prefix["content_length"]):
                raise RuntimeError("Bulk recovered row lacks exact typed prefix/headers")
        elif pointer is not None or row.get("fresh_recovery_policy")is not None:
            raise RuntimeError("One-generation bulk row claims prefix recovery")
    return rows
