"""Owned F-only offline transport controls, never real GET/Lean/model/Docker."""
import hashlib
import errno
from concurrent.futures import ThreadPoolExecutor
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import ssl
import sys
import unittest
from unittest.mock import patch
import uuid

PROJECT = Path(__file__).resolve().parents[2]
SCRIPTS = PROJECT / "scripts/benchmark-repair"
FIXTURES = PROJECT / ".scratch" / ("minif-body-v2-" + uuid.uuid4().hex[:12])
FIXTURES.mkdir(parents=True)
EVIDENCE = dict(fixture_root=str(FIXTURES), e_write=False, c_write=False,
                d_write=False, network=False, docker=False, llm_called=False,
                candidate_run=False, controls=[])
NAME = "0000000000000001.ltar"
ROW = dict(module="Mathlib/Fixture.lean", ltar=NAME)

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class Response:
    status = 200
    def __init__(self, events, length=10, etag='"fixed-public-fixture"', name=NAME):
        self.events = list(events)
        self.headers = {"Content-Length": str(length), "ETag": etag}
        self.closed = False
        self.reads = 0
        self.name = name
    def geturl(self):
        return "https://lakecache.blob.core.windows.net/mathlib4/f/" + self.name
    def read1(self, block):
        assert not self.closed, "timed-out response reused after close"
        self.reads += 1
        event = self.events.pop(0) if self.events else b""
        if isinstance(event, BaseException): raise event
        return event
    def close(self): self.closed = True
    def __enter__(self): return self
    def __exit__(self, *args): self.close()

class Opener:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
    def open(self, request, timeout):
        self.calls.append(dict(url=request.full_url, method=request.method,
                               timeout=timeout, headers=dict(request.header_items())))
        event = self.results.pop(0)
        if isinstance(event, BaseException): raise event
        return event

def root():
    p = FIXTURES / uuid.uuid4().hex
    p.mkdir(); (p/"audit").mkdir(); (p/"downloads").mkdir()
    return p

def fixed_free(addition=0):
    # Only fixture F is observed; this does not certify real E reserves.
    value = shutil.disk_usage(FIXTURES).free
    if value - addition < 1024**3:
        raise RuntimeError("fixture F reserve")
    return dict(e_free_bytes=10*1024**3, f_free_bytes=value)

def baseline_reproduction():
    old = load("a02_body_baseline", "minif2f_public_cache.py")
    p = root()
    first = Response([b"abc", TimeoutError("socket body read1 timed out")])
    fresh = Response([b"abcdefghij", b""])
    opener = Opener([first, fresh])
    original_ledger = old.Ledger
    error = None
    with patch.object(old, "exact_root", return_value=p), \
         patch.object(old, "allocation_unit"), patch.object(old, "volume_reserves", fixed_free), \
         patch.object(old, "inputs", return_value=[ROW]), \
         patch.object(old, "writer_probe", return_value=dict(fixture=True)), \
         patch.object(old, "MANIFEST_COUNT", 1), \
         patch.object(old, "Ledger", side_effect=lambda initial:original_ledger(initial,reserve=fixed_free)), \
         patch.object(old.urllib.request, "build_opener", return_value=opener):
        try: old.acquire(p, p, p, 1)
        except Exception as exc: error = type(exc).__name__ + ": " + str(exc)
    result = dict(label="old_a02_body_timeout_does_not_fresh_retry",
                  exact_old_sha256=hashlib.sha256((SCRIPTS/"minif2f_public_cache.py").read_bytes()).hexdigest(),
                  symptom=error, get_count=len(opener.calls), first_response_closed=first.closed,
                  partial_bytes=(p/"downloads/mathlib-cache"/(NAME+".part")).stat().st_size,
                  new_body_read_count=fresh.reads, desired_recovery_success=error is None,
                  fixture=str(p))
    EVIDENCE["controls"].append(result)
    print(json.dumps(result), flush=True)
    # Desired behavior: bounded fresh same-key response completes the object.
    assert error is None, "RED: a02 aborts on response.read1 TimeoutError; fresh complete response unused"

new = load("public_body_v2_controls","minif2f_public_cache_v2.py") if "--baseline-red" not in sys.argv else None

def fixture_review(module, extra=()):
    own=Path(module.__file__).resolve()
    files=[own,own.with_suffix(".ps1"),own.with_name("minif2f_public_cache.py"),
           own.parents[2]/".local-evidence/repository/test/fixtures/repair/minif2f-restoration-preflight.json",*extra]
    rows=[dict(path=f.as_posix(),bytes=f.stat().st_size,
               sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in files]
    document=dict(protocol=module.REVIEW_PROTOCOL,validated=True,
                  transport_protocol=module.TRANSPORT,base_helper_sha256=module.BASE_SHA,
                  profile_sha256=module.PROFILE_SHA,real_acquisition_executed=False,
                  new_sources=rows[:2],protected_sources=rows[2:])
    path=FIXTURES/("fixture-review-"+uuid.uuid4().hex+".json")
    path.write_bytes((json.dumps(document)+"\n").encode())
    return path,hashlib.sha256(path.read_bytes()).hexdigest(),rows[0]["sha256"]

class Fixture:
    def __init__(self):
        self.root=root(); (self.root/"downloads/mathlib-cache").mkdir()
        self.lease=new.base.Lease(self.root/"audit"/new.base.LEASE_NAME)
        self.lease.acquire()
        self.book=new.Book(128*1024,reserve=fixed_free)
        self.journal=new.Journal(self.root)
        self.receipt=self.root/"audit/cache-downloads.jsonl"
        with self.receipt.open("xb") as stream:
            stream.flush(); os.fsync(stream.fileno())
        self.completed={}
    def get(self, opener, row=ROW, guard=lambda:None):
        return new.get_one(row,self.root,self.lease,self.book,self.journal,guard,
                           self.receipt,self.completed,opener=opener,sleeper=lambda _:None)
    def close(self, rows=(ROW,)):
        closed=True
        try:new.evidence_closed(self.root,rows,self.journal)
        except Exception:closed=False
        self.lease.write(dict(held=False,outcome="fixture_closed",body_journal=self.journal.footer(),
                              prefix_operations_closed=closed))
        self.lease.close()
    def marker(self):
        return dict(body_journal=self.journal.footer(),prefix_operations_closed=True)

class ProtocolTests(unittest.TestCase):
    def setUp(self):self.f=Fixture()
    def tearDown(self):
        self.f.close(getattr(self,"rows",(ROW,)))
        EVIDENCE["controls"].append(dict(label=self._testMethodName,fixture=str(self.f.root),
                                        real_F_file_io=True))
    def success(self):
        first=Response([b"abc",TimeoutError("body timeout")])
        fresh=Response([b"abcdefghij",b""])
        opener=Opener([first,fresh])
        result=self.f.get(opener)
        return result,opener,first,fresh
    def test_body_timeout_fresh_success_exact_prefix_durable(self):
        native=os.fsync; calls=[]
        def observed(fd):
            native(fd); calls.append("returned")
        with patch.object(new.os,"fsync",side_effect=observed):
            result,opener,first,fresh=self.success()
        self.assertEqual(len(opener.calls),2); self.assertTrue(first.closed and fresh.closed)
        self.assertEqual(calls,["returned"]*5) # prefix, intent, commit, full, receipt
        self.assertEqual(result["body_generations"],2)
        self.assertEqual((self.f.root/"downloads/mathlib-cache"/NAME).read_bytes(),b"abcdefghij")
        evidence=new.evidence_closed(self.f.root,[ROW],self.f.journal)
        self.assertEqual(evidence["bytes"],3); self.assertEqual(len(evidence["prefixes"]),1)
        self.assertEqual(self.f.book.prefix_bytes,3)
        self.assertGreaterEqual(self.f.book.used,128*1024+new.AUDIT_BUDGET+2*new.base.META_PER_BLOB)
        self.assertLessEqual(max(len(z) for z in self.f.journal.path.read_bytes().splitlines(keepends=True)),2048)
    def test_original_fsync_fault_preserves_part_and_no_fresh_get(self):
        first=Response([b"abc",TimeoutError("body")]); opener=Opener([first,Response([b"abcdefghij"])])
        with patch.object(new.os,"fsync",side_effect=OSError(errno.EIO,"injected at real file fsync")):
            with self.assertRaises(OSError):self.f.get(opener)
        self.assertEqual(len(opener.calls),1)
        self.assertEqual((self.f.root/"downloads/mathlib-cache"/(NAME+".part")).read_bytes(),b"abc")
        self.assertEqual(self.f.journal.path.stat().st_size,0)
    def test_real_write_then_writefault_no_retry(self):
        native=Path.open
        class Writer:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):return self.stream.__exit__(*args)
            def fileno(self):return self.stream.fileno()
            def flush(self):return self.stream.flush()
            def write(self,value):
                self.stream.write(value[:1]); self.stream.flush()
                raise OSError(errno.EIO,"injected after real owned write")
        def opened(path,mode="r",*a,**kw):
            s=native(path,mode,*a,**kw)
            return Writer(s) if mode=="xb" and path.name.endswith(".part") else s
        opener=Opener([Response([b"abc",TimeoutError("body")]),Response([b"abcdefghij"])])
        with patch.object(Path,"open",opened):
            with self.assertRaises(OSError):self.f.get(opener)
        self.assertEqual(len(opener.calls),1)
        self.assertEqual((self.f.root/"downloads/mathlib-cache"/(NAME+".part")).read_bytes(),b"a")
    def test_second_body_timeout_never_third_generation(self):
        opener=Opener([Response([b"abc",TimeoutError("first")]),
                       Response([b"abc",TimeoutError("second")]),Response([b"abcdefghij"])])
        with self.assertRaises(TimeoutError):self.f.get(opener)
        self.assertEqual(len(opener.calls),2); self.assertEqual(self.f.book.recoveries,1)
        self.assertTrue((self.f.root/"downloads/mathlib-cache"/(NAME+".part")).exists())
    def test_opening_and_body_share_three_gets(self):
        opener=Opener([TimeoutError("opening"),Response([b"abc",TimeoutError("body")]),
                       Response([b"abcdefghij",b""])])
        result=self.f.get(opener)
        self.assertEqual(result["transport_gets"],3); self.assertEqual(len(opener.calls),3)
        self.assertEqual(len({z["url"] for z in opener.calls}),1)
        self.assertTrue(all(z["method"]=="GET" and z["timeout"]==60 for z in opener.calls))
        self.assertTrue(all("Range" not in z["headers"] for z in opener.calls))
    def test_three_open_attempts_leave_no_body_retry_budget(self):
        opener=Opener([TimeoutError("open1"),TimeoutError("open2"),
                       Response([b"abc",TimeoutError("body3")]),Response([b"abcdefghij"])])
        with self.assertRaises(RuntimeError):self.f.get(opener)
        self.assertEqual(len(opener.calls),3); self.assertEqual(self.f.book.recoveries,0)
        self.assertTrue((self.f.root/"downloads/mathlib-cache"/(NAME+".part")).exists())
    def test_fresh_prefix_etag_length_mismatch_reject(self):
        for kind in ("prefix","etag","length"):
            f=Fixture()
            try:
                fresh=Response([b"xyzdefghij"],etag='"changed"' if kind=="etag" else '"fixed-public-fixture"',
                               length=9 if kind=="length" else 10)
                if kind!="prefix":fresh.events=[b"abcdefghij"]
                opener=Opener([Response([b"abc",TimeoutError("first")]),fresh])
                with self.assertRaises(RuntimeError):f.get(opener)
                self.assertEqual(len(opener.calls),2); self.assertEqual(f.book.recoveries,1)
                self.assertEqual(len(new.evidence_closed(f.root,[ROW],f.journal)["prefixes"]),1)
                self.assertFalse((f.root/"downloads/mathlib-cache"/NAME).exists())
            finally:f.close()
    def test_weak_etag_or_unknown_length_no_recovery(self):
        for kind in ("weak","length"):
            f=Fixture()
            try:
                response=Response([b"abc",TimeoutError("body")],etag='W/"weak"' if kind=="weak" else '"fixed"')
                if kind=="length":response.headers.pop("Content-Length")
                opener=Opener([response,Response([b"abcdefghij"])])
                with self.assertRaises(RuntimeError):f.get(opener)
                self.assertEqual(len(opener.calls),1);self.assertEqual(f.book.recoveries,0)
            finally:f.close()
    def test_body_http_tls_eof_and_guard_timeout_never_retry(self):
        for error in (ssl.SSLError("TLS"),http.client.RemoteDisconnected("HTTP"),None):
            f=Fixture()
            try:
                events=[b"abc",error] if error is not None else [b"abc",b""]
                opener=Opener([Response(events),Response([b"abcdefghij"])])
                with self.assertRaises(Exception):f.get(opener)
                self.assertEqual(len(opener.calls),1);self.assertEqual(f.book.recoveries,0)
            finally:f.close()
        n=[0]
        def guard():
            n[0]+=1
            if n[0]==5:raise TimeoutError("guard is not read1")
        opener=Opener([Response([b"abc"]),Response([b"abcdefghij"])])
        with self.assertRaises(TimeoutError):self.f.get(opener,guard=guard)
        self.assertEqual(len(opener.calls),1);self.assertEqual(self.f.book.recoveries,0)
    def test_fresh_body_capacity_reserved_after_retained_prefix(self):
        # Real files are tiny, but forecast must hold both prefix and full retry.
        initial=self.f.book.used
        with patch.object(new.base,"CAP",initial+new.base.rounded(10)+new.base.META_PER_BLOB+1):
            opener=Opener([Response([b"abc",TimeoutError("body")]),Response([b"abcdefghij"])])
            with self.assertRaises(RuntimeError):self.f.get(opener)
        self.assertEqual(len(opener.calls),1);self.assertEqual(self.f.book.recoveries,1)
        self.assertEqual(new.evidence_closed(self.f.root,[ROW],self.f.journal)["bytes"],3)
        self.assertGreater(self.f.book.used,initial)
    def test_stage_eight_and_prefix_cap(self):
        self.rows=[]
        for index in range(1,10):
            name=f"{index:016x}.ltar";row=dict(module=f"Mathlib/F{index}.lean",ltar=name);self.rows.append(row)
            opener=Opener([Response([b"abc",TimeoutError("body")],name=name),
                           Response([b"abcdefghij"],name=name)])
            if index<=8:self.f.get(opener,row=row)
            else:
                with self.assertRaises(RuntimeError):self.f.get(opener,row=row)
                self.assertEqual(len(opener.calls),1)
        self.assertEqual(self.f.book.recoveries,8)
        self.assertEqual(len(new.evidence_closed(self.f.root,self.rows,self.f.journal)["prefixes"]),8)
        f=Fixture()
        try:
            with patch.object(new,"PREFIX_CAP",2):
                opener=Opener([Response([b"abc",TimeoutError("body")]),Response([b"abcdefghij"])])
                with self.assertRaises(RuntimeError):f.get(opener)
            self.assertEqual(len(opener.calls),1);self.assertEqual(f.book.recoveries,0)
        finally:f.close()
    def test_unknown_canonical_part_and_orphan_prefix_rejected(self):
        (self.f.root/"downloads/mathlib-cache"/(NAME+".part")).write_bytes(b"unclosed")
        with self.assertRaises(RuntimeError):new.validate_resume(self.f.root,[ROW],self.f.marker())
        extra=Fixture()
        try:
            (extra.root/new.EVIDENCE_REL).mkdir()
            (extra.root/new.EVIDENCE_REL/"orphan.prefix").write_bytes(b"unknown")
            with self.assertRaises(RuntimeError):new.validate_evidence(extra.root,[ROW],extra.marker())
        finally:extra.close()
    def test_journal_wrong_key_path_hash_duplicate_unpaired_no_fsync_rejected(self):
        self.success(); original=self.f.journal.path.read_bytes()
        lines=[json.loads(z) for z in original.splitlines()]
        for mutation in ("key","path","hash","duplicate","prepared_only","no_fsync","unsynced"):
            changed=[dict(z) for z in lines]
            if mutation=="key":changed[0]["key"]="ffffffffffffffff.ltar"
            if mutation=="path":changed[0]["path"]="../other"
            if mutation=="hash":changed[0]["sha256"]="0"*64
            if mutation=="duplicate":changed.append(dict(changed[-1]))
            if mutation=="prepared_only":changed=changed[:1]
            if mutation=="no_fsync":changed[0]["prefix_fsync_returned"]=False
            data=b"".join(new.encode_row(z) for z in changed)
            self.f.journal.path.write_bytes(data)
            with self.f.journal.path.open("r+b") as stream:stream.flush();os.fsync(stream.fileno())
            marker=dict(body_journal=dict(path=new.JOURNAL_REL,synced_bytes=len(data),
                synced_sha256=hashlib.sha256(data).hexdigest()),prefix_operations_closed=True)
            if mutation=="unsynced":marker["body_journal"]["synced_bytes"]-=1
            with self.assertRaises(RuntimeError):new.validate_evidence(self.f.root,[ROW],marker)
        self.f.journal.path.write_bytes(original)
    def test_commit_journal_fsync_fault_unclosed_and_no_fresh(self):
        native=os.fsync;n=[0]
        def failed(fd):
            n[0]+=1
            if n[0]==3:raise OSError(errno.EIO,"commit fsync failed")
            native(fd)
        opener=Opener([Response([b"abc",TimeoutError("body")]),Response([b"abcdefghij"])])
        with patch.object(new.os,"fsync",side_effect=failed):
            with self.assertRaises(OSError):self.f.get(opener)
        self.assertEqual(len(opener.calls),1)
        with self.assertRaises(RuntimeError):new.validate_evidence(self.f.root,[ROW],self.f.marker())
        owned=self.f.book.settle_unclosed_parts()
        self.assertEqual(owned[0]["bytes"],3)
        self.assertFalse(owned[0]["promoted_to_complete"])
    def test_prepared_fsync_failure_and_rename_gap_rejected(self):
        native=os.fsync;n=[0]
        def failed(fd):
            n[0]+=1
            if n[0]==2:raise OSError(errno.EIO,"prepared journal fsync failed")
            native(fd)
        opener=Opener([Response([b"abc",TimeoutError("body")]),Response([b"abcdefghij"])])
        with patch.object(new.os,"fsync",side_effect=failed):
            with self.assertRaises(OSError):self.f.get(opener)
        self.assertEqual(len(opener.calls),1)
        with self.assertRaises(RuntimeError):new.validate_evidence(self.f.root,[ROW],self.f.marker())
        self.assertEqual(self.f.book.settle_unclosed_parts()[0]["bytes"],3)
        f=Fixture()
        try:
            opener=Opener([Response([b"abc",TimeoutError("body")]),Response([b"abcdefghij"])])
            with patch.object(Path,"rename",side_effect=OSError(errno.EIO,"same-volume rename fault")):
                with self.assertRaises(OSError):f.get(opener)
            self.assertEqual(len(opener.calls),1)
            with self.assertRaises(RuntimeError):new.validate_evidence(f.root,[ROW],f.marker())
            self.assertTrue((f.root/"downloads/mathlib-cache"/(NAME+".part")).exists())
        finally:f.close()
    def test_actual_archived_prefix_modified_rejected(self):
        self.success()
        evidence=new.evidence_closed(self.f.root,[ROW],self.f.journal)
        path=self.f.root/next(iter(evidence["prefixes"].values()))["path"]
        path.write_bytes(b"abd")
        with self.assertRaises(RuntimeError):new.validate_evidence(self.f.root,[ROW],self.f.marker())
    def test_four_workers_compete_and_all_failed_bytes_remain_accounted(self):
        self.rows=[dict(module=f"Mathlib/F{k}.lean",ltar=f"{k:016x}.ltar") for k in range(1,5)]
        openers=[Opener([Response([b"abc",TimeoutError("body")],name=r["ltar"]),
                        Response([b"abcdefghij"],name=r["ltar"])]) for r in self.rows]
        def worker(args):
            r,opener=args
            try:self.f.get(opener,row=r);return True
            except RuntimeError:return False
        with patch.object(new,"MAX_STAGE_RECOVERIES",2):
            with ThreadPoolExecutor(max_workers=4) as pool:outcomes=list(pool.map(worker,zip(self.rows,openers)))
        self.assertEqual(sum(outcomes),2)
        self.assertEqual(self.f.book.recoveries,2)
        before=self.f.book.used
        unclosed=self.f.book.settle_unclosed_parts()
        self.assertEqual(len(unclosed),2)
        self.assertEqual(sum(r["bytes"] for r in unclosed),6)
        self.assertEqual(self.f.book.used-before,2*(new.base.rounded(3)+new.base.META_PER_BLOB))
        self.assertFalse(self.f.book.reservations)
    def test_http_tls_open_backoff_stop_and_long_headers_no_retry(self):
        import urllib.error
        for err in (urllib.error.HTTPError(new.AZURE+NAME,404,"notfound",{},None),
                    ssl.SSLCertVerificationError("TLS"),http.client.RemoteDisconnected("HTTP")):
            opener=Opener([err,Response([b"abcdefghij"])])
            with self.assertRaises(Exception):self.f.get(opener)
            self.assertEqual(len(opener.calls),1)
        count=[0]
        def stop():
            count[0]+=1
            if count[0]==3:raise RuntimeError("stop during opening backoff")
        opener=Opener([TimeoutError("opening"),Response([b"abcdefghij"])])
        with self.assertRaises(RuntimeError):self.f.get(opener,guard=stop)
        self.assertEqual(len(opener.calls),1)
        response=Response([b"abcdefghij"],etag='"'+'x'*257+'"')
        opener=Opener([response,Response([b"abcdefghij"])])
        with self.assertRaises(RuntimeError):self.f.get(opener)
        self.assertEqual(len(opener.calls),1)
        with self.assertRaises(RuntimeError):new.encode_row(dict(value="x"*2048))
    def test_actual_windows_share_deny_lease(self):
        other=new.base.Lease(self.f.root/"audit"/new.base.LEASE_NAME)
        with self.assertRaises(RuntimeError):other.acquire()
        other.close()
    def test_closed_data_contract_retains_original_receipt_prefix(self):
        # Complete a one-key synthetic fixture through the actual stage path.
        p=root();first=Response([b"abc",TimeoutError("body")]);fresh=Response([b"abcdefghij"])
        opener=Opener([first,fresh])
        oldname="0000000000000000.ltar";oldrow=dict(module="Mathlib/Old.lean",ltar=oldname)
        directory=p/"downloads/mathlib-cache";directory.mkdir()
        olddata=b"old123";(directory/oldname).write_bytes(olddata)
        oldrecord=dict(**oldrow,url=new.AZURE+oldname,bytes=len(olddata),
                       sha256=hashlib.sha256(olddata).hexdigest(),http_status=200,
                       acquisition_protocol="public-cache-acquisition-v1",
                       lease_id=str(uuid.uuid4()),transport_policy="original-a02-fixture")
        original=(json.dumps(oldrecord,separators=(", ",": "))+"\n").encode()
        receipt=p/"audit/cache-downloads.jsonl";receipt.write_bytes(original)
        with receipt.open("r+b") as stream:stream.flush();os.fsync(stream.fileno())
        review,review_sha,worker_sha=fixture_review(new)
        with patch.object(new.base,"exact_root",return_value=p),patch.object(new.base,"allocation_unit"), \
             patch.object(new.base,"volume_reserves",fixed_free),patch.object(new.base,"inputs",return_value=[oldrow,ROW]), \
             patch.object(new,"writer_probe",return_value=dict(fixture=True)), \
             patch.object(new.base,"MANIFEST_COUNT",2),patch.object(new.urllib.request,"build_opener",return_value=opener):
            new.acquire(p,p,p,1,review,review_sha)
        complete=json.loads((p/"audit/cache-download-complete.json").read_bytes())
        proof=json.loads((p/"audit/public-cache-acquisition.json").read_bytes())
        self.assertEqual(complete["objects"],2) # Never claim real5826 completion.
        self.assertEqual(complete["acquisition_protocol"],"public-cache-acquisition-v1")
        self.assertEqual(proof["transport_protocol"],new.TRANSPORT)
        self.assertTrue(proof["original_receipt_prefix_unchanged"])
        self.assertEqual(proof["new_transport_gets"],2)
        self.assertEqual(proof["executing_worker_sha256"],worker_sha)
        self.assertEqual(proof["executing_review_sha256"],review_sha)
        self.assertTrue(proof["source_review_final_validated_at_utc"])
        old,evidence=new.validate_resume(p,[oldrow,ROW])
        self.assertEqual(len(old),2);self.assertEqual(evidence["bytes"],3)
        self.assertEqual(receipt.read_bytes()[:len(original)],original)
        self.assertEqual((directory/oldname).read_bytes(),olddata)
        self.assertEqual(proof["resumed_objects"],1)
        EVIDENCE["synthetic_closed_stage"]=dict(root=str(p),objects=2,real5826Complete=False,
                                               old_receipt_exact_bytes_unchanged=True)

    def source_mutation_control(self, kind):
        module=new
        if kind=="worker":
            # Execute an exact copied new worker and a02 guard under owned F,
            # so changing its __file__ changes a real executing source copy,
            # never the frozen production worker.
            project=FIXTURES/("source-copy-"+uuid.uuid4().hex)
            folder=project/"scripts/benchmark-repair";folder.mkdir(parents=True)
            for name in ("minif2f_public_cache_v2.py","minif2f_public_cache_v2.ps1","minif2f_public_cache.py"):
                (folder/name).write_bytes((SCRIPTS/name).read_bytes())
            profile=project/".local-evidence/repository/test/fixtures/repair";profile.mkdir(parents=True)
            (profile/"minif2f-restoration-preflight.json").write_bytes(
                (PROJECT/".local-evidence/repository/test/fixtures/repair/minif2f-restoration-preflight.json").read_bytes())
            spec=importlib.util.spec_from_file_location("executing_copy_source_control",folder/"minif2f_public_cache_v2.py")
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        p=root()
        target=FIXTURES/("protected-source-"+uuid.uuid4().hex+".py")
        target.write_bytes(b"original public fixture source\n")
        review,review_sha,start_worker_sha=fixture_review(module,[target])
        changed=Path(module.__file__) if kind=="worker" else review if kind=="review" else target
        class MutatingOpener(Opener):
            def open(self, request, timeout):
                value=super().open(request,timeout)
                if len(self.calls)==1:
                    with changed.open("ab") as stream:
                        stream.write(b"\n# owned source mutation during synthetic body GET\n")
                        stream.flush();os.fsync(stream.fileno())
                return value
        opener=MutatingOpener([Response([b"abcdefghij"])])
        with patch.object(module.base,"exact_root",return_value=p),patch.object(module.base,"allocation_unit"), \
             patch.object(module.base,"volume_reserves",fixed_free),patch.object(module.base,"inputs",return_value=[ROW]), \
             patch.object(module,"writer_probe",return_value=dict(fixture=True)), \
             patch.object(module.base,"MANIFEST_COUNT",1),patch.object(module.urllib.request,"build_opener",return_value=opener):
            with self.assertRaisesRegex(RuntimeError,"source changed|review bytes differ"):
                module.acquire(p,p,p,1,review,review_sha)
        self.assertEqual(len(opener.calls),1)
        self.assertFalse((p/"audit/public-cache-acquisition.json").exists())
        self.assertFalse((p/"audit/cache-download-complete.json").exists())
        marker=json.loads((p/"audit"/module.base.LEASE_NAME).read_bytes())
        self.assertEqual(marker["outcome"],"aborted")
        self.assertFalse(marker["held"])
        self.assertEqual(marker["executing_worker_sha256"],start_worker_sha)
        self.assertEqual(marker["executing_review_sha256"],review_sha)
        self.assertIsNone(marker["source_review_final_validated_at_utc"])
        self.assertTrue((p/"downloads/mathlib-cache"/NAME).exists())
        EVIDENCE.setdefault("source_final_check_controls",[]).append(
            dict(kind=kind,fixture=str(p),no_success_proof=True,
                 start_worker_sha256=start_worker_sha,start_review_sha256=review_sha,
                 released_aborted=True,production_sources_modified=False))
    def test_protected_source_changed_during_run_no_completion_proof(self):
        self.source_mutation_control("protected")
    def test_frozen_review_changed_during_run_no_completion_proof(self):
        self.source_mutation_control("review")
    def test_executing_worker_copy_changed_no_completion_proof(self):
        self.source_mutation_control("worker")

if __name__=="__main__":
    if "--baseline-red" in sys.argv:
        try:baseline_reproduction()
        finally:
            (FIXTURES/"minif2f-public-cache-v2-startup-red.json").write_bytes(
                (json.dumps(EVIDENCE,indent=2)+"\n").encode())
    else:
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(ProtocolTests)
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        EVIDENCE.update(passed=result.wasSuccessful(),testsRun=result.testsRun,
                       failures=len(result.failures),errors=len(result.errors),
                       source_sha256=hashlib.sha256((SCRIPTS/"minif2f_public_cache_v2.py").read_bytes()).hexdigest())
        (FIXTURES/"minif2f-public-cache-v2-controls.json").write_bytes(
            (json.dumps(EVIDENCE,indent=2)+"\n").encode())
        raise SystemExit(0 if result.wasSuccessful() else 1)
