"""Independent complete fresh public GET with preserved timeout-prefix evidence.

The v1 name below is the closed data contract consumed by frozen fast/Lean
readers. The executing transport is independently named and source-reviewed.
Unknown partials, unclosed journal operations and stale leases are never repaired.
Opaque Azure ETags are recorded as opaque, not as RFC quoted strong validators.
No old prefix bytes are appended, ranged, or reused in a successful body.
"""
from __future__ import annotations
import argparse
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
TRANSPORT = "same-key-body-timeout-complete-fresh-v3"
V2_TRANSPORT = "same-key-body-timeout-prefix-preserved-v2"
POLICY_MD5 = "known-length-content-md5-complete-fresh-v3"
POLICY_ETAG = "known-length-quoted-etag-complete-fresh-v3"
REVIEW_PROTOCOL = "public-cache-body-v3-source-review-v1"
JOURNAL_REL = "audit/public-cache-body-attempts.jsonl"
EVIDENCE_REL = "downloads/mathlib-cache-failed-prefix"
MAX_GETS, MAX_BODY_RETRIES, MAX_STAGE_RECOVERIES = 3, 1, 8
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
PROTOCOL, ROOT = base.PROTOCOL, base.ROOT
AZURE, MAX_BLOB, BLOCK = base.AZURE, base.MAX_BLOB, base.BLOCK
MAX_RECEIPT_LINE, AUDIT_BUDGET = base.MAX_RECEIPT_LINE, base.AUDIT_BUDGET
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
            serial = self.book.next_get(self.name)
            event = dict(get=self.gets, global_get=serial, response_received=False)
            self.events.append(event)
            try:
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
        super().__init__(initial, reserve=reserve or base.volume_reserves)
        self.recoveries = 0
        self.prefix_bytes = prior_prefix_bytes
        self.gets = 0
        self.get_counts = {}
        self.parts = {}
    def next_get(self, name):
        with self.lock:
            self.gets += 1
            self.get_counts[name]=self.get_counts.get(name,0)+1
            return self.gets
    def allow_prefix(self, size):
        if self.recoveries >= MAX_STAGE_RECOVERIES:
            raise RuntimeError("Stage body recovery budget8 exhausted")
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
                raise RuntimeError("Typed journal exceeds2MiB within16MiB audit budget")
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
        if (transport not in (TRANSPORT,V2_TRANSPORT) or not isinstance(lid,str)
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
                or r.get("body_error_type") not in ("TimeoutError","timeout")
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
        raise RuntimeError("Historical stage exceeds8 prefix recoveries")
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

def validate_resume(root, rows, released=AUTO_RELEASED):
    # Explicit None is the captured absence of a lease before acquiring a new
    # share-deny handle. Never reopen our own active handle in that case.
    released=lease_record(root) if released is AUTO_RELEASED else released
    receipt=Path(root)/"audit/cache-downloads.jsonl"
    if receipt.exists() and receipt.stat().st_size>AUDIT_BUDGET:
        raise RuntimeError("Completed receipts exceed16MiB audit reservation")
    old=base.validate_resume(root,rows)  # Still rejects every unknown canonical part.
    evidence=validate_evidence(root,rows,released)
    unclosed=(released or {}).get("retained_unclosed_owned_parts",[])
    if not isinstance(unclosed,list) or len(unclosed)>4:
        raise RuntimeError("Unknown released owned-artifact footer")
    keys={r["ltar"] for r in rows}
    for artifact in unclosed:
        name=artifact.get("key"); path=Path(artifact.get("path",""))
        lid=(released or {}).get("lease_id")
        allowed={Path(root)/"downloads/mathlib-cache"/str(name),
                 Path(root)/"downloads/mathlib-cache"/(str(name)+".part")}
        if isinstance(lid,str) and re.fullmatch(UUID_RE,lid):
            allowed.add(Path(root)/EVIDENCE_REL/(lid+"-"+str(name)[:16]+"-g1.prefix"))
        if (name not in keys or path.absolute() not in {p.absolute() for p in allowed}
            or type(artifact.get("bytes")) is not int or not 0<=artifact["bytes"]<=MAX_BLOB
            or not isinstance(artifact.get("sha256"),str) or not re.fullmatch(HEX_RE,artifact["sha256"])
            or artifact.get("promoted_to_complete") is not False):
            raise RuntimeError("Released unclosed artifact is not exact typed lease-owned evidence")
        if path.exists():
            raise RuntimeError("Released unclosed owned file still exists; never adopt an unreturned receipt fsync")
    for name,row in old.items():
        transport=row.get("transport_protocol")
        if transport is not None and transport not in (TRANSPORT,V2_TRANSPORT):
            raise RuntimeError("Unknown completed transport protocol")
        if transport in (TRANSPORT,V2_TRANSPORT):
            if (type(row.get("transport_gets")) is not int or not 1<=row["transport_gets"]<=MAX_GETS
                or type(row.get("body_generations")) is not int or row["body_generations"] not in (1,2)):
                raise RuntimeError("Completed V2/V3 transport counters invalid")
            pointer=row.get("failed_prefix_operation")
            if row["body_generations"]==2:
                if (pointer not in evidence["prefixes"] or evidence["prefixes"][pointer]["key"]!=name
                    or evidence["prefixes"][pointer]["transport_protocol"]!=transport):
                    raise RuntimeError("Completed recovered blob lacks matching typed prefix")
            elif pointer is not None: raise RuntimeError("Unrecovered blob has a prefix pointer")
        if transport==TRANSPORT:
            http=row.get("http")
            if not isinstance(http,dict): raise RuntimeError("V3 receipt lacks observed headers")
            expected=content_md5(http.get("content-md5"))
            if (row.get("etag_kind")!=etag_kind(http.get("etag")) or
                row.get("content_md5_verified") is not (expected is not None) or
                row.get("failed_prefix_bytes_reused_in_body")!=0 or
                row.get("fresh_body_complete_from_new_get") is not (row["body_generations"]==2)):
                raise RuntimeError("Completed V3 checksum/fresh provenance flags differ")
            if expected is not None:
                if (row.get("measured_content_md5")!=http["content-md5"] or
                    md5_file(Path(root)/"downloads/mathlib-cache"/name)!=http["content-md5"]):
                    raise RuntimeError("Completed V3 Content-MD5 differs from actual saved bytes")
            elif row.get("measured_content_md5") is not None:
                raise RuntimeError("V3 receipt claims an unadvertised Content-MD5")
            if row["body_generations"]==2:
                prefix=evidence["prefixes"][row["failed_prefix_operation"]]
                if (row.get("fresh_recovery_policy")!=prefix["recovery_policy"] or
                    http.get("etag")!=prefix["etag"] or http.get("content-md5")!=prefix["content_md5"] or
                    int(http.get("content-length","-1"))!=prefix["content_length"]):
                    raise RuntimeError("Completed fresh receipt differs from failed-generation headers")
            elif row.get("fresh_recovery_policy") is not None:
                raise RuntimeError("V3 one-generation receipt claims a fresh recovery policy")
    return old,evidence

def owned_prefix(part, identity, written, digest):
    assert_regular(part)
    before=part.stat()
    if (before.st_dev,before.st_ino)!=identity or before.st_size!=written or sha(part)!=digest:
        raise RuntimeError("This lease's xb prefix identity/bytes/SHA changed")
    after=part.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise RuntimeError("Prefix changed during hash readback")

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
    request=urllib.request.Request(url,headers={"User-Agent":"TgEngin-public-cache-body-v3","Accept-Encoding":"identity"},method="GET")
    attempts=Attempts(name,book); prefix=None
    while True:
        opened,_=attempts.open(opener,request,guard,sleeper)
        timeout_error=None
        with opened as response:
            guard(); length,http=metadata(response,url)
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
            "fresh_recovery_policy":prefix["recovery_policy"] if prefix is not None else None}
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

def validate_review(path, expected_sha):
    path=Path(path)
    if not re.fullmatch(HEX_RE,expected_sha) or sha(path)!=expected_sha:
        raise RuntimeError("Independent source review bytes differ")
    review=json.loads(path.read_bytes())
    if (review.get("protocol")!=REVIEW_PROTOCOL or review.get("validated") is not True
        or review.get("transport_protocol")!=TRANSPORT or review.get("base_helper_sha256")!=BASE_SHA
        or review.get("profile_sha256")!=PROFILE_SHA or review.get("real_acquisition_executed") is not False):
        raise RuntimeError("Independent transport review contract differs")
    source_rows=review.get("new_sources",[])+review.get("protected_sources",[])
    paths={}
    for item in source_rows:
        f=Path(item["path"])
        if f.as_posix().casefold() in paths or sha(f)!=item["sha256"] or f.stat().st_size!=item["bytes"]:
            raise RuntimeError("Independent executing/protected source changed")
        paths[f.as_posix().casefold()]=item
    own=Path(__file__).resolve()
    for f in (own,own.with_suffix(".ps1"),own.with_name("minif2f_public_cache.py"),
              own.parents[2]/"test/fixtures/repair/minif2f-restoration-preflight.json"):
        if f.as_posix().casefold() not in paths: raise RuntimeError("Review omits required source/profile")
    return review

def writer_probe():
    # Preserve the original process/mount check. New stages also hold exactly
    # the same share-deny lease; older stages require root's sole-writer schedule.
    proof=base.writer_probe()
    # Add known newer source names without weakening or changing a02's probe.
    command=r'''$ErrorActionPreference='Stop'; $all=@(Get-CimInstance Win32_Process); $excluded=@(__PID__); $cur=__PID__; while($cur){$p=$all|Where-Object ProcessId -eq $cur;if(-not $p){break};$cur=[int]$p.ParentProcessId;$excluded+=$cur};$hits=@();foreach($p in $all){if($excluded -contains [int]$p.ProcessId){continue};$c=[string]$p.CommandLine;if($c -match '(?i)minif2f_(public_cache_v2|public_cache_v3|fast_unpack|native_v2_stage|native_v2|runtime_v2)\.(py|ps1)["''\s]+[\s\S]*?(acquire|unpack|Bootstrap|Workspace|Controls|PreChecks|RegradeCandidates)(?:["''\s]|$)'){$hits+=[pscustomobject]@{pid=[int]$p.ProcessId;name=$p.Name;stage=$Matches[3]}}};[pscustomobject]@{newer_stage_conflicts=$hits}|ConvertTo-Json -Compress -Depth 4'''.replace("__PID__",str(os.getpid()))
    observed=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",command],
                            capture_output=True,timeout=10)
    if observed.returncode: raise RuntimeError("Newer write-stage observation failed")
    hits=json.loads(observed.stdout.decode("utf-8-sig"))["newer_stage_conflicts"]
    if hits: raise RuntimeError("Another newer writer overlaps owned-root schedule")
    proof["newer_stage_conflicts"]=hits
    return proof

def evidence_closed(root, rows, journal):
    released=dict(body_journal=journal.footer(),prefix_operations_closed=True)
    return validate_evidence(root,rows,released)

def gate(root, public, core_path):
    root=base.exact_root(root); base.allocation_unit()
    free=base.volume_reserves(); rows=base.inputs(root,public,core_path)
    released=lease_record(root)
    old,evidence=validate_resume(root,rows,released)
    probe=writer_probe()
    print(json.dumps(dict(protocol=PROTOCOL,transport_protocol=TRANSPORT,
        old_helper_sha256=BASE_SHA,objects_fixed=base.MANIFEST_COUNT,
        completed_objects=len(old),prefix_evidence=len(evidence["prefixes"]),
        prefix_bytes=evidence["bytes"],writer_probe=probe,**free,
        e_write=False,public_get=False,llm_called=False,candidate_run=False)),flush=True)

def acquire(root, public, core_path, workers, review_path, review_sha):
    # Capture only the hashes validated before execution, never sign a long
    # run with a freshly computed (possibly edited) worker hash at its end.
    review_path=Path(review_path).resolve()
    start_review=validate_review(review_path,review_sha)
    own=Path(__file__).resolve().as_posix().casefold()
    start_worker_sha=next(r["sha256"] for r in start_review["new_sources"]
                          if Path(r["path"]).as_posix().casefold()==own)
    source_started_at=stamp()
    source_final_validated_at=None
    root=base.exact_root(root); base.allocation_unit()
    base.volume_reserves(AUDIT_BUDGET+16384)
    rows=base.inputs(root,public,core_path)
    released=lease_record(root)
    old,prior_evidence=validate_resume(root,rows,released)
    if (root/"audit/cache-download-complete.json").exists():
        raise RuntimeError("Full closed acquisition already exists")
    lease=base.Lease(root/"audit"/base.LEASE_NAME)
    lease.acquire()
    stop=threading.Event(); observer=None; initial=final=book=journal=None
    began=time.monotonic(); completed=dict(old); errors=[]; monitor_errors=[]; probes=0
    receipt=root/"audit/cache-downloads.jsonl"
    old_raw=b""
    old_receipt_sha=hashlib.sha256(old_raw).hexdigest()
    def guard():
        if stop.is_set(): raise RuntimeError("Shared stage stop")
        if time.monotonic()-began>base.WALL_SECONDS:
            stop.set(); raise RuntimeError("Three-hour stage wall budget exhausted")
        book.check()
    def monitor():
        nonlocal probes
        while not stop.wait(10):
            try: guard(); writer_probe(); probes+=1
            except Exception as error:
                monitor_errors.append(type(error).__name__+": "+str(error))
                stop.set(); return
    unclosed_parts=[]; unclosed_parts_error=None
    def footer(closed):
        return dict(transport_protocol=TRANSPORT,
            body_journal=journal.footer() if journal is not None else None,
            prefix_operations_closed=closed,
            transport_gets=book.gets if book is not None else 0,
            registered_body_recoveries=book.recoveries if book is not None else 0,
            retained_registered_prefix_bytes=book.prefix_bytes if book is not None else prior_evidence["bytes"],
            ledger_used_bytes=book.used if book is not None else None,
            ledger_inflight_reservations=dict(book.reservations) if book is not None else {},
            retained_unclosed_owned_parts=unclosed_parts,
            retained_unclosed_owned_parts_error=unclosed_parts_error,
            executing_worker_sha256=start_worker_sha,executing_review_sha256=review_sha,
            executing_review_path=review_path.as_posix(),
            source_review_started_at_utc=source_started_at,
            source_review_final_validated_at_utc=source_final_validated_at,
            guard_source_sha256=BASE_SHA)
    try:
        lease.write(dict(held=True,acquired_at_utc=stamp(),pid=os.getpid(),
            executing_worker_sha256=start_worker_sha,executing_review_sha256=review_sha,
            executing_review_path=review_path.as_posix(),
            source_review_started_at_utc=source_started_at))
        old_raw=receipt.read_bytes() if receipt.exists() else b""
        old_receipt_sha=hashlib.sha256(old_raw).hexdigest()
        start_probe=writer_probe()
        # Lease now held; revalidate exactly the prior released footer captured
        # before claim. The original strict unknown .part rule is unchanged.
        old,prior_evidence=validate_resume(root,rows,released)
        initial=base.full_scan(root)
        book=Book(initial["allocated_envelope_bytes"],prior_evidence["bytes"])
        directory=root/"downloads/mathlib-cache"; directory.mkdir(exist_ok=True)
        if not receipt.exists():
            with receipt.open("xb") as stream: sync_stream(stream)
        journal=Journal(root)
        observer=threading.Thread(target=monitor,name="body-v3-owned-writer-observer",daemon=True)
        observer.start()
        pending=[r for r in rows if r["ltar"] not in old]
        def download(row):
            result=get_one(row,root,lease,book,journal,guard,receipt,completed)
            with book.lock:
                if len(completed)%200==0 or len(completed)==base.MANIFEST_COUNT:
                    print(json.dumps(dict(public_cache_objects=len(completed),total=base.MANIFEST_COUNT,
                        transport_protocol=TRANSPORT,transport_gets=book.gets,
                        body_recoveries=book.recoveries,ledger_forecast_bytes=book.used,
                        candidate_run=False)),flush=True)
            return result
        try:
            with ThreadPoolExecutor(max_workers=workers,thread_name_prefix="public-body-v3") as pool:
                futures={pool.submit(download,row):row["ltar"] for row in pending}
                for future in as_completed(futures):
                    try: future.result()
                    except Exception as error:
                        errors.append(dict(key=futures[future],error=type(error).__name__+": "+str(error),
                                           transport_gets=book.get_counts.get(futures[future],0)))
                        stop.set()
                        for job in futures: job.cancel()
                        break
        finally:
            stop.set()
            observer.join(timeout=35)
            if observer.is_alive(): raise RuntimeError("Writer observer not quiesced")
        if errors or monitor_errors: raise RuntimeError("Public body acquisition aborted: "+json.dumps(dict(objects=errors,observer=monitor_errors)))
        if len(completed)!=base.MANIFEST_COUNT: raise RuntimeError("Fixed5826 keys incomplete")
        if sum(row["transport_gets"] for name,row in completed.items() if name not in old)!=book.gets:
            raise RuntimeError("Final transport GET count does not match new receipts")
        evidence=evidence_closed(root,rows,journal)
        closed_marker=dict(body_journal=journal.footer(),prefix_operations_closed=True)
        validate_resume(root,rows,closed_marker)
        base.inputs(root,public,core_path)
        if hashlib.sha256(receipt.read_bytes()[:len(old_raw)]).hexdigest()!=old_receipt_sha:
            raise RuntimeError("Original completed receipt prefix changed")
        final=base.full_scan(root)
        mutable={"audit/"+base.LEASE_NAME,"audit/cache-downloads.jsonl",
                 "audit/public-cache-acquisition.json","audit/cache-download-complete.json",JOURNAL_REL}
        typed={r["path"] for r in evidence["prefixes"].values()}
        for name,value in initial["files"].items():
            if name not in mutable and final["files"].get(name)!=value:
                raise RuntimeError("Pre-existing file metadata changed: "+name)
        for name in set(final["files"])-set(initial["files"]):
            if (name not in mutable and name not in typed
                and not re.fullmatch(r"downloads/mathlib-cache/[0-9a-f]{16}\.ltar",name)):
                raise RuntimeError("Unregistered file appeared")
        if final["allocated_envelope_bytes"]>book.used or final["allocated_envelope_bytes"]+AUDIT_BUDGET>base.CAP:
            raise RuntimeError("Final allocation exceeds retained ledger/finalization budget")
        end_probe=writer_probe(); downloaded_hash=sha(receipt)
        # No successful proof is written when the review, executing worker/PS,
        # or any protected source differs from the same frozen start review.
        validate_review(review_path,review_sha)
        source_final_validated_at=stamp()
        proof=dict(protocol=PROTOCOL,transport_protocol=TRANSPORT,recorded_at_utc=stamp(),lease_id=lease.id,
            core_sha256=base.CORE_SHA,bootstrap_receipt_sha256=base.BOOTSTRAP_SHA,
            public_lock_sha256=base.LOCK_SHA,module_cache_manifest_sha256=base.MANIFEST_SHA,
            objects=base.MANIFEST_COUNT,workers=workers,
            initial_allocated_envelope_bytes=initial["allocated_envelope_bytes"],
            initial_metadata_fingerprint_sha256=initial["metadata_fingerprint_sha256"],
            final_allocated_envelope_bytes=final["allocated_envelope_bytes"],
            final_metadata_fingerprint_sha256=final["metadata_fingerprint_sha256"],
            fixed_source_links_verified=final["fixed_source_links_verified"],
            ledger_peak_forecast_bytes=book.peak,finalization_reserved_bytes=AUDIT_BUDGET,
            finalization_envelope_upper_bound_bytes=final["allocated_envelope_bytes"]+AUDIT_BUDGET,
            start_writer_probe=start_probe,end_writer_probe=end_probe,periodic_writer_probes=probes,
            pre_existing_files_unchanged_by_metadata=True,all_cache_blob_sha256_rechecked=True,
            original_receipt_prefix_bytes=len(old_raw),original_receipt_prefix_sha256=old_receipt_sha,
            original_receipt_prefix_unchanged=True,download_receipts_sha256=downloaded_hash,
            resumed_objects=len(old),new_transport_gets=book.gets,legacy_transport_gets_not_rewritten=True,
            registered_body_recoveries=book.recoveries,retained_failed_prefixes=len(evidence["prefixes"]),
            retained_failed_prefix_bytes=evidence["bytes"],body_journal=journal.footer(),
            executing_worker_sha256=start_worker_sha,executing_review_sha256=review_sha,
            executing_review_path=review_path.as_posix(),
            source_review_started_at_utc=source_started_at,
            source_review_final_validated_at_utc=source_final_validated_at,
            guard_source_sha256=BASE_SHA,
            elapsed_seconds=round(time.monotonic()-began,3),full_directory_scans=2,
            candidate_run=False,llm_called=False,executable_run=False,
            executable_run_scope="Downloaded Lean/cache executables; host Python transport runs",
            lease_release_protocol="held=false fsynced while share-deny held, then handleclosed")
        base.durable_json(root/"audit/public-cache-acquisition.json",proof)
        complete=dict(recorded_at_utc=stamp(),objects=base.MANIFEST_COUNT,
            module_cache_manifest_sha256=base.MANIFEST_SHA,download_receipts_sha256=downloaded_hash,
            compressed_bytes=sum(r["bytes"] for r in completed.values()),
            owned_envelope_bytes=final["allocated_envelope_bytes"],candidate_run=False,
            acquisition_protocol=PROTOCOL,transport_protocol=TRANSPORT,
            acquisition_proof_sha256=sha(root/"audit/public-cache-acquisition.json"))
        base.durable_json(root/"audit/cache-download-complete.json",complete)
        base.volume_reserves(AUDIT_BUDGET)
        lease.write(dict(held=False,released_at_utc=stamp(),pid=os.getpid(),outcome="complete",
            complete_receipt_sha256=sha(root/"audit/cache-download-complete.json"),**footer(True)))
    except Exception as error:
        stop.set()
        if observer is not None:
            observer.join(timeout=35)
            if observer.is_alive(): raise RuntimeError("Cannot release lease with active observer") from error
        closed=False; evidence_error=None
        if book is not None:
            try: unclosed_parts=book.settle_unclosed_parts()
            except Exception as e: unclosed_parts_error=type(e).__name__+": "+str(e)
        if journal is not None:
            try: evidence_closed(root,rows,journal); closed=True
            except Exception as e: evidence_error=type(e).__name__+": "+str(e)
        scan=None; scan_error=None
        if initial is not None and final is None:
            try: scan=base.full_scan(root)["allocated_envelope_bytes"]
            except Exception as e: scan_error=type(e).__name__+": "+str(e)
        lease.write(dict(held=False,released_at_utc=stamp(),pid=os.getpid(),outcome="aborted",
            completed_objects=len(completed),error=(type(error).__name__+": "+str(error))[:4096],
            failure_post_scan_envelope_bytes=scan,failure_post_scan_error=scan_error,
            evidence_validation_error=evidence_error,unknown_or_partial_requires_review=True,**footer(closed)))
        raise
    finally:
        lease.close()
    print(json.dumps(dict(public_cache_acquisition_complete=True,objects=base.MANIFEST_COUNT,
        protocol=PROTOCOL,transport_protocol=TRANSPORT,lease_handle_closed=True,
        lease_id=lease.id,complete_receipt_sha256=sha(root/"audit/cache-download-complete.json"),
        lease_release_sha256=sha(root/"audit"/base.LEASE_NAME),candidate_run=False)),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=["gate","acquire"])
    parser.add_argument("--root",default=ROOT)
    parser.add_argument("--public",required=True)
    parser.add_argument("--core",required=True)
    parser.add_argument("--workers",type=int,choices=range(1,5),default=4)
    parser.add_argument("--review",required=True)
    parser.add_argument("--review-sha",required=True)
    args=parser.parse_args()
    if args.stage=="gate":
        validate_review(args.review,args.review_sha)
        gate(args.root,args.public,args.core)
    else:
        acquire(args.root,args.public,args.core,args.workers,args.review,args.review_sha)
