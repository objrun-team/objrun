"""Explicit2270-key namespace; no inherited or all-history per-key budget claim."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

PROJECT=Path(__file__).resolve().parents[2]
REVIEW_PATH=PROJECT/".local-evidence/repository/test/fixtures/repair/minif2f-public-cache-bulk2-review.json"
spec=importlib.util.spec_from_file_location("explicit_bulk_kernel",Path(__file__).with_name("minif2f_public_cache_bulk2.py"))
k=importlib.util.module_from_spec(spec);spec.loader.exec_module(k)
b,c=k.base,k.carry
TRANSPORT=k.TRANSPORT


FAILURE_PATH=PROJECT/".local-evidence/repository/test/fixtures/repair/minif2f-dependency-failures/public-cache-bulk-v1-lease-cursor-failure/agent-readonly-copy-v1/failure-record.json"
FAILURE_SHA="0d07919e285c6fdeedc0155b2af83a6dccff771856e8b68d81769cb196afbe75"
REMOVAL_SHA="1a5edd44ec64cc86fb9f2f56be756a05c682ba38bd7ddb9952423273b022c8d6"
REMOVAL_PATH=FAILURE_PATH.with_name("root-exact-part-removal.json")
BULK1_REVIEW_SHA="79e2871ed137ac9f291b206f98ef76d25108b6b73135539c69d401ce4f4c364a"

def review(expected):
    raw=c.pinned(REVIEW_PATH,expected);data=json.loads(raw)
    if (data.get("protocol")!="public-cache-continued-bulk2-source-review-v1" or data.get("validated") is not True or
        data.get("transport_protocol")!=TRANSPORT or data.get("base_helper_sha256")!=k.BASE_SHA or
        data.get("profile_sha256")!=k.PROFILE_SHA or data.get("real_acquisition_executed") is not False):
        raise RuntimeError("Different explicit bulk source review")
    found=set()
    for p in data["new_sources"]+data["protected_sources"]:
        name=str(Path(p["path"]).resolve()).casefold()
        if name in found:raise RuntimeError("Duplicate reviewed path")
        found.add(name);c.pinned(p["path"],p["sha256"],p["bytes"])
    for p in (Path(__file__),Path(__file__).with_suffix(".ps1"),Path(k.__file__),PROJECT/".local-evidence/repository/test/fixtures/repair/minif2f-restoration-preflight.json"):
        if str(p.resolve()).casefold() not in found:raise RuntimeError("Omitted required bulk source/profile")
    return data


class DispatchJournal(k.Journal):
    def __init__(self,root,lease_id,review_sha):
        self.root,self.path=Path(root),Path(root)/k.DISPATCH_REL
        self.lock=threading.RLock();self.lease_id,self.review_sha=lease_id,review_sha
        if self.path.exists():raise RuntimeError("Existing explicit bulk intent namespace; never reset/retry")
        with self.path.open("xb")as stream:k.sync_stream(stream)
        self.synced_bytes=0;self.synced_sha=k.sha(self.path)
    def append(self,event):
        event=dict(protocol=TRANSPORT,lease_id=self.lease_id,review_sha256=self.review_sha,**event)
        raw=k.encode_row(event)
        with self.lock:
            if self.path.stat().st_size!=self.synced_bytes or self.synced_bytes+len(raw)>16*1024**2:
                raise RuntimeError("Unacknowledged/oversized bulk dispatch journal")
            with self.path.open("ab")as stream:
                if stream.write(raw)!=len(raw):raise RuntimeError("Short bulk intent write")
                k.sync_stream(stream)
            with self.path.open("rb")as check:
                check.seek(self.synced_bytes)
                if check.read()!=raw:raise RuntimeError("Intent readback differs")
            self.synced_bytes+=len(raw)
            # Avoid rehashing the whole growing journal on every append. The
            # closed footer computes its whole SHA after all workers settle.
        return hashlib.sha256(raw).hexdigest()
    def footer(self):
        return dict(path=k.DISPATCH_REL,acknowledged_bytes=self.synced_bytes,
                    actual_bytes=self.path.stat().st_size,sha256=k.sha(self.path))


class LockedLease(c.OwnedLease):
    def __init__(self,path,namespace):
        self.io_lock=threading.RLock();super().__init__(path);self.id=namespace
    def acquire(self):
        with self.io_lock:return super().acquire()
    def write(self,values):
        with self.io_lock:return super().write(values)
    def assert_owned(self):
        with self.io_lock:return super().assert_owned()
    def close(self):
        with self.io_lock:return super().close()


class ThreadSafeDeadline(c.Deadline):
    def __init__(self,*args,**kwargs):
        self.clock_lock=threading.RLock();super().__init__(*args,**kwargs)
    def check(self):
        with self.clock_lock:return super().check()


class ContinuedDispatchJournal(DispatchJournal):
    def __init__(self,root,namespace,review_sha,original):
        self.root,self.path=Path(root),Path(root)/k.DISPATCH_REL
        self.lock=threading.RLock();self.lease_id,self.review_sha=namespace,review_sha
        if self.path.read_bytes()!=original:raise RuntimeError("Original96 raw intent bytes differ")
        self.synced_bytes=len(original);self.synced_sha=hashlib.sha256(original).hexdigest()


def writer_probe(previous_pid):
    proof=c.writer_probe()
    command=r'''$ErrorActionPreference='Stop';$all=@(Get-CimInstance Win32_Process);$excluded=@(__PID__);$cur=__PID__;while($cur){$p=$all|Where-Object ProcessId -eq $cur;if(-not $p){break};$cur=[int]$p.ParentProcessId;$excluded+=$cur};$hits=@();foreach($p in $all){if($excluded -contains [int]$p.ProcessId){continue};if([string]$p.CommandLine -match '(?i)minif2f_public_cache_bulk2?(_stage)?\.(py|ps1)["''\s]+[\s\S]*?acquire(?:["''\s]|$)'){$hits+=[pscustomobject]@{pid=[int]$p.ProcessId;stage='Acquire'}}};$prior=@($all|Where-Object ProcessId -eq __PRIOR__);[pscustomobject]@{bulk_writers=$hits;carry_pid_present=($prior.Count -gt 0)}|ConvertTo-Json -Depth 4 -Compress'''.replace("__PID__",str(os.getpid())).replace("__PRIOR__",str(previous_pid))
    result=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",command],capture_output=True,timeout=10)
    if result.returncode:raise RuntimeError("Bulk writer/previous actor metadata probe failed")
    observed=json.loads(result.stdout.decode("utf-8-sig"))
    if observed["bulk_writers"]or observed["carry_pid_present"]:raise RuntimeError("Previous carry PID or another bulk writer remains")
    proof["bulk_probe"]=observed;return proof


def failure_inputs():
    report=json.loads(c.pinned(FAILURE_PATH,FAILURE_SHA));copied={Path(p["source"]).name:p for p in report["copied_files"]}
    for p in report["copied_files"]:c.pinned(p["archive"],p["sha256"],p["bytes"])
    return report,copied


def removal_proof(path,digest,report):
    path=Path(path).resolve()
    if path!=REMOVAL_PATH.resolve()or digest!=REMOVAL_SHA:raise RuntimeError("Different fixed root removal certificate")
    if not str(path).casefold().startswith(str(PROJECT/"docs/repair-2026-10-08").casefold()+os.sep):raise RuntimeError("Removal proof must be owned F metadata")
    data=json.loads(c.pinned(path,digest));original=json.loads(Path(report["copied_files"][0]["archive"]).read_bytes())
    wanted={str(Path(p["path"]).resolve()).casefold():(p["bytes"],p["sha256"])for p in original["retained_unclosed_owned_parts"]}
    seen={str(Path(p["path"]).resolve()).casefold():(p["bytes"],p["sha256"])for p in data.get("removed",[])}
    if (data.get("protocol")!="bulk-v1-root-part-removal-v1"or data.get("failure_record_sha256")!=FAILURE_SHA or
        data.get("actor_pid")!=106836 or data.get("actor_absent")is not True or len(data.get("removed",[]))!=3 or seen!=wanted or
        data.get("e_mutation_scope")!="exact3_incomplete_paths"or any(Path(p).exists()for p in wanted)):
        raise RuntimeError("Different/unclosed exact3 root removal proof")
    return dict(path=str(path),sha256=digest,bytes=path.stat().st_size)


def preflight(review_sha,removal_path,removal_sha):
    review(review_sha);report,copies=failure_inputs()
    root=b.exact_root(b.ROOT);b.allocation_unit();b.volume_reserves(k.AUDIT_BUDGET)
    if any((root/p).exists()or(root/(p+".new")).exists()for p in(k.INPUT_REL,k.PHASE_REL,"audit/cache-download-complete.json")):
        raise RuntimeError("Bulk2 already consumed/unclosed; no reset")
    removal=removal_proof(removal_path,removal_sha,report)
    for name in (b.LEASE_NAME,"cache-downloads.jsonl","public-cache-bulk-body-attempts.jsonl","public-cache-bulk-get-intents.jsonl","public-cache-bulk-inputs.json"):
        p=copies[name];c.pinned(root/"audit"/name,p["sha256"],p["bytes"])
    marker=json.loads((root/"audit"/b.LEASE_NAME).read_bytes());ThreadSafeDeadline().check()
    if marker.get("held")is not False or marker.get("outcome")!="aborted"or marker.get("prefix_operations_closed")is not True:raise RuntimeError("Bulk1 not released")
    public=PROJECT/".phase1-data/minif2f-restoration-public";core=Path(k.__file__).with_name("minif2f_restore.py")
    rows=b.inputs(root,public,core);old=b.validate_resume(root,rows);raw=(root/"audit/cache-downloads.jsonl").read_bytes()
    baseline=json.loads((root/"audit/public-cache-bulk-inputs.json").read_bytes())
    prefix=raw[:baseline["original3556_prefix_bytes"]]
    if hashlib.sha256(prefix).hexdigest()!=k.CARRY_RECEIPTS_SHA or baseline.get("carry_validator_actual_gate_succeeded")is not True:raise RuntimeError("Original genuine carry3556 binding differs")
    c.pinned(root/c.PHASE_REL,k.CARRY_PHASE_SHA)
    old3556={json.loads(line)["ltar"]for line in prefix.splitlines()};logical={r["ltar"]for r in rows if r["ltar"]not in old3556}
    if len(logical)!=2270:raise RuntimeError("Logical namespace changed")
    evidence=k.validate_evidence(root,rows,marker);k.validate_new_rows(root,{n:r for n,r in old.items()if n not in old3556},evidence)
    dispatch_raw=(root/k.DISPATCH_REL).read_bytes();counts,total,_=inspect_dispatch(root/k.DISPATCH_REL,marker["lease_id"],review_sha,logical,dispatch_raw)
    if total!=96 or marker["actual_opener_calls"]!=96 or marker["new_allowances_consumed"]!=96 or len(old)!=3648:raise RuntimeError("Not exact3648/96 consumed")
    pending=[r for r in rows if r["ltar"]not in old]
    if len(pending)!=2178 or sum(3-counts.get(r["ltar"],0)for r in pending)!=6530:raise RuntimeError("Remaining per-key allowance changed")
    return root,public,core,rows,pending,old,raw,marker,baseline,writer_probe(106836),counts,dispatch_raw,logical,removal,report



def typed_bulk(root,rows,initial_raw,released,allowed_new,prior_counts,external):
    all_rows=b.validate_resume(root,rows)
    raw=(root/"audit/cache-downloads.jsonl").read_bytes()
    if not raw.startswith(initial_raw)or not raw.endswith(b"\n"):raise RuntimeError("Original3556 raw prefix changed")
    evidence=k.validate_evidence(root,rows,released)
    old_names={json.loads(line)["ltar"]for line in initial_raw.splitlines()}
    for name,row in all_rows.items():
        if name in old_names:continue
        if (name not in allowed_new or row.get("transport_protocol")!=TRANSPORT or
            row.get("new_budget_namespace")!=row.get("lease_id") or row.get("old_v3_key_interval")!=[0,3]or
            row.get("all_history_key_gets")is not None or row.get("all_history_global_gets")is not None or
            row.get("v3_plus_bulk_key_interval")!=[row.get("transport_gets"),row.get("transport_gets",0)+3]):
            raise RuntimeError("New row is not the explicit unknown-history budget protocol")
        item=external.get(name)
        if (row.get("execution_generation")!=2 or row.get("body_generation_scope")!="this_execution_only"or row.get("prior_bulk_gets")!=prior_counts.get(name,0)or
            row.get("external_interrupted_prefix_verified")is not(item is not None)or
            row.get("external_interrupted_prefix_sha256")!=(item["sha256"]if item else None)or row.get("external_interrupted_prefix_bytes")!=(item["bytes"]if item else None)):
            raise RuntimeError("Continued execution/archived prefix binding differs")
        if item:
            with (Path(root)/"downloads/mathlib-cache"/name).open("rb")as stream:window=stream.read(item["bytes"])
            if (len(window)!=item["bytes"]or hashlib.sha256(window).hexdigest()!=item["sha256"]or
                row["http"].get("etag")!=item["etag"]or row["http"].get("content-md5")!=item["content_md5"]or row["bytes"]!=item["content_length"]):
                raise RuntimeError("Complete saved body no longer matches interrupted-generation evidence")
    # Kernel applies the same strong MD5/fresh-generation checks to new rows.
    k.validate_new_rows(root,{n:r for n,r in all_rows.items()if n not in old_names},evidence)
    return all_rows,evidence


def inspect_dispatch(path,namespace,review_sha,new_keys,original_raw):
    raw=Path(path).read_bytes();counts={};serial=0
    if len(raw)>16*1024**2 or raw and not raw.endswith(b"\n"):raise RuntimeError("Truncated/oversized dispatch evidence")
    if not raw.startswith(original_raw):raise RuntimeError("Original96 intent bytes changed")
    for line in raw.splitlines():
        if len(line)>2048:raise RuntimeError("Oversized dispatch row")
        r=json.loads(line);name=r["key"];serial+=1;counts[name]=counts.get(name,0)+1
        if (r.get("protocol")!=TRANSPORT or r.get("event")!="dispatch"or r.get("lease_id")!=namespace or
            r.get("review_sha256")!=(BULK1_REVIEW_SHA if serial<=96 else review_sha)or name not in new_keys or r.get("new_key_get")!=counts[name]or
            counts[name]>3 or r.get("new_global_get")!=serial or serial>6810 or
            r.get("v3_window_gets_before")!=1507 or r.get("v3_window_consumed_allowance")!=1507+serial or
            r.get("old_v3_key_interval")!=[0,3]or r.get("v3_plus_bulk_key_interval")!=[counts[name],counts[name]+3]or
            r.get("all_history_key_gets")is not None or r.get("all_history_global_gets")is not None):
            raise RuntimeError("Bulk allowance reset or historical count invented")
    return counts,serial,hashlib.sha256(raw).hexdigest()


def acquire(review_sha,removal_path,removal_sha):
    root,public,core,rows,pending,old,initial_raw,prior_marker,carry_phase,start_probe,prior_counts,original_dispatch,logical_keys,removal,report=preflight(review_sha,removal_path,removal_sha)
    lease=LockedLease(root/"audit"/b.LEASE_NAME,prior_marker["lease_id"]);clock=ThreadSafeDeadline()
    stop=threading.Event();observer=None;book=journal=dispatch=initial=final=None
    completed=dict(old);failures=[];observer_errors=[];source_start=k.sha(__file__)
    def guard():
        if stop.is_set():raise RuntimeError("Shared explicit bulk stop")
        clock.check();lease.assert_owned();book.check()
    def monitor():
        while not stop.wait(10):
            try:guard();writer_probe(prior_marker["pid"])
            except Exception as error:observer_errors.append(type(error).__name__+": "+str(error));stop.set();return
    def footer(outcome,closed,artifacts=None,**extras):
        artifacts=artifacts or []
        return dict(held=False,pid=os.getpid(),outcome=outcome,released_at_utc=k.stamp(),transport_protocol=TRANSPORT,
            execution_generation=2,original_bulk1_failure_sha256=FAILURE_SHA,current_execution_opener_calls=(book.open_calls-96)if book else 0,
            prefix_operations_closed=closed,body_journal=journal.footer()if journal else None,
            dispatch_journal=dispatch.footer()if dispatch else None,new_allowances_consumed=book.gets if book else 96,
            actual_opener_calls=book.open_calls if book else 96,v3_window_gets_before=1507,
            v3_window_opener_calls=1507+(book.open_calls if book else 96),all_history_global_gets=None,
            new_body_retries=book.recoveries if book else 0,abort_retained_parts=len(artifacts),
            preservation_operations_total=9+(book.recoveries if book else 0)+len(artifacts),
            cumulative_failed_prefix_bytes=(book.prefix_bytes if book else 422032)+sum(x["bytes"]for x in artifacts),
            retained_unclosed_owned_parts=artifacts,executing_review_sha256=review_sha,executing_worker_sha256=source_start,
            deadline_utc="2026-10-08T18:16:26.118992+00:00",**extras)
    try:
        lease.acquire();lease.write(dict(held=True,pid=os.getpid(),acquired_at_utc=k.stamp(),transport_protocol=TRANSPORT,execution_generation=2,original_bulk1_failure_sha256=FAILURE_SHA,
            executing_review_sha256=review_sha,executing_worker_sha256=source_start))
        review(review_sha);b.inputs(root,public,core)
        if k.sha(root/c.PHASE_REL)!=k.CARRY_PHASE_SHA or k.sha(root/"audit/cache-downloads.jsonl")!=hashlib.sha256(initial_raw).hexdigest():
            raise RuntimeError("Carry/input prefix changed during lease claim")
        initial=b.full_scan(root);book=k.Book(initial["allocated_envelope_bytes"],422032)
        book.prior_counts=dict(prior_counts);book.get_counts=dict(prior_counts);book.gets=96;book.open_calls=96
        for item in prior_marker["retained_unclosed_owned_parts"]:
            http=item["observed_http"];book.external_prefixes[item["key"]]=dict(bytes=item["bytes"],sha256=item["sha256"],content_length=http["content_length"],etag=http["headers"]["etag"],content_md5=http["headers"]["content-md5"])
        input_cert=dict(protocol=TRANSPORT,lease_id=lease.id,original3648_prefix_bytes=len(initial_raw),
            original3648_prefix_sha256=hashlib.sha256(initial_raw).hexdigest(),carry_phase_sha256=k.CARRY_PHASE_SHA,
            carry_released_lease_sha256=k.CARRY_LEASE_SHA,carry_validator_source_sha256=c.sha(c.__file__),
            original_bulk1_carry_validator_actual_gate_witness_carried=True,pending_count=2178,prior_allowances_consumed=96,remaining_allowances=6530,root_removal_proof=removal,original_failure_record_sha256=FAILURE_SHA,
            pending_manifest_sha256=hashlib.sha256(b"".join(k.encode_row(r)for r in pending)).hexdigest(),
            original_v3_window_gets=1507,all_history_global_gets=None,old_v3_key_interval=[0,3],new_key_get_cap=3,
            new_body_retry_cap=1,abort_evidence_retention_cap=4,preservation_operations_cap=14,
            prefix_cap_bytes=256*1024**2,audit_reserved_bytes=k.AUDIT_BUDGET,
            deadline_utc="2026-10-08T18:16:26.118992+00:00",review_sha256=review_sha)
        b.durable_json(root/k.INPUT_REL,input_cert)
        journal=k.Journal(root);dispatch=ContinuedDispatchJournal(root,lease.id,review_sha,original_dispatch);book.dispatch_journal=dispatch
        observer=threading.Thread(target=monitor,name="explicit-bulk-writer-observer",daemon=True);observer.start()
        def fetch(row):
            answer=k.get_one(row,root,lease,book,journal,guard,root/"audit/cache-downloads.jsonl",completed)
            with book.lock:
                if len(completed)%200==0 or len(completed)==5826:
                    print(json.dumps(dict(completed_objects=len(completed),fixed_objects=5826,new_budget_gets=book.gets,
                        body_retries=book.recoveries,v3_window_gets=1507+book.open_calls,all_history_global_gets=None,
                        candidate_run=False,llm_called=False)),flush=True)
            return answer
        with ThreadPoolExecutor(max_workers=4,thread_name_prefix="explicit-public-bulk")as pool:
            futures={pool.submit(fetch,row):row["ltar"]for row in pending}
            for future in as_completed(futures):
                try:future.result()
                except Exception as error:
                    failures.append(dict(key=futures[future],error=type(error).__name__+": "+str(error)));stop.set()
                    for job in futures:job.cancel()
                    break
        stop.set();observer.join(timeout=35)
        if observer.is_alive()or failures or observer_errors:raise RuntimeError("Explicit bulk aborted: "+json.dumps(dict(objects=failures,observer=observer_errors)))
        released=dict(body_journal=journal.footer(),prefix_operations_closed=True)
        all_rows,evidence=typed_bulk(root,rows,initial_raw,released,{r["ltar"]for r in pending},prior_counts,book.external_prefixes)
        counts,intents,intent_sha=inspect_dispatch(root/k.DISPATCH_REL,lease.id,review_sha,logical_keys,original_dispatch)
        if (len(all_rows)!=5826 or len(completed)!=5826 or set(counts)!=logical_keys or
            sum(all_rows[n]["transport_gets"]for n in counts)!=intents or intents!=book.gets or intents!=book.open_calls):
            raise RuntimeError("Full5826/new2270/get evidence does not close")
        final=b.full_scan(root);mutable={"audit/"+b.LEASE_NAME,"audit/cache-downloads.jsonl",k.JOURNAL_REL,k.DISPATCH_REL,k.INPUT_REL,k.PHASE_REL}
        for name,value in initial["files"].items():
            if name not in mutable and final["files"].get(name)!=value:raise RuntimeError("Pre-existing metadata changed: "+name)
        new_allowed={k.JOURNAL_REL,k.DISPATCH_REL,k.INPUT_REL,k.PHASE_REL}|{r["path"]for r in evidence["prefixes"].values()}|{"downloads/mathlib-cache/"+r["ltar"]for r in pending}
        if set(final["files"])-set(initial["files"])-new_allowed:raise RuntimeError("Unknown new owned file")
        if final["allocated_envelope_bytes"]>book.used or final["allocated_envelope_bytes"]+k.AUDIT_BUDGET>b.CAP:raise RuntimeError("Final allocation exceeds14GiB/ledger")
        review(review_sha);b.inputs(root,public,core);clock.check();end_probe=writer_probe(prior_marker["pid"])
        proof=dict(protocol=b.PROTOCOL,transport_protocol=TRANSPORT,recorded_at_utc=k.stamp(),lease_id=lease.id,
            core_sha256=b.CORE_SHA,bootstrap_receipt_sha256=b.BOOTSTRAP_SHA,public_lock_sha256=b.LOCK_SHA,
            module_cache_manifest_sha256=b.MANIFEST_SHA,objects=5826,workers=4,
            initial_allocated_envelope_bytes=initial["allocated_envelope_bytes"],final_allocated_envelope_bytes=final["allocated_envelope_bytes"],
            initial_metadata_fingerprint_sha256=initial["metadata_fingerprint_sha256"],final_metadata_fingerprint_sha256=final["metadata_fingerprint_sha256"],
            fixed_source_links_verified=final["fixed_source_links_verified"],finalization_envelope_upper_bound_bytes=final["allocated_envelope_bytes"]+k.AUDIT_BUDGET,
            finalization_reserved_bytes=k.AUDIT_BUDGET,ledger_peak_forecast_bytes=book.peak,
            start_writer_probe=start_probe,end_writer_probe=end_probe,pre_existing_files_unchanged_by_metadata=True,
            all_cache_blob_sha256_rechecked=True,original3648_prefix_unchanged=True,
            original3648_prefix_sha256=hashlib.sha256(initial_raw).hexdigest(),root_removal_proof=removal,original_failure_record_sha256=FAILURE_SHA,download_receipts_sha256=k.sha(root/"audit/cache-downloads.jsonl"),
            resumed_objects=3648,new_objects=2178,bulk_namespace_opener_calls=book.open_calls,current_execution_opener_calls=book.open_calls-96,v3_window_opener_calls=1507+book.open_calls,
            all_history_global_gets=None,old_v3_key_interval=[0,3],new_per_key_cap=3,new_body_retries=book.recoveries,
            preservation_operations_total=9+book.recoveries,cumulative_failed_prefix_bytes=book.prefix_bytes,
            bulk_dispatch_sha256=intent_sha,bulk_body_journal=journal.footer(),bulk_input_certificate_sha256=k.sha(root/k.INPUT_REL),
            executing_worker_sha256=source_start,source_end_sha256=k.sha(__file__),executing_review_sha256=review_sha,
            carried_carry_phase_sha256=k.CARRY_PHASE_SHA,full_directory_scans=2,
            deadline_utc="2026-10-08T18:16:26.118992+00:00",candidate_run=False,llm_called=False,
            actual_executed_scope="Host Python public transport only; no Lean/container/candidate",lease_handle_closed=False)
        b.durable_json(root/k.PHASE_REL,dict(protocol=TRANSPORT,state="awaiting_lease_release",validated=False,objects=5826))
        lease.write(footer("complete",True,completed_objects=5826));lease.close()
        review(review_sha);clock.check();writer_probe(prior_marker["pid"]);b.volume_reserves(k.AUDIT_BUDGET)
        proof.update(lease_handle_closed=True,released_lease_sha256=k.sha(root/"audit"/b.LEASE_NAME))
        b.durable_json(root/"audit/public-cache-acquisition.json",proof)
        b.durable_json(root/k.PHASE_REL,dict(protocol=TRANSPORT,state="full5826_closed",validated=True,objects=5826,
            acquisition_proof_sha256=k.sha(root/"audit/public-cache-acquisition.json"),lease_handle_closed=True))
        clock.check()
        complete=dict(recorded_at_utc=k.stamp(),objects=5826,module_cache_manifest_sha256=b.MANIFEST_SHA,
            download_receipts_sha256=proof["download_receipts_sha256"],compressed_bytes=sum(r["bytes"]for r in all_rows.values()),
            owned_envelope_bytes=final["allocated_envelope_bytes"],candidate_run=False,acquisition_protocol=b.PROTOCOL,
            transport_protocol=TRANSPORT,acquisition_proof_sha256=k.sha(root/"audit/public-cache-acquisition.json"))
        b.durable_json(root/"audit/cache-download-complete.json",complete)
        print(json.dumps(dict(objects=5826,cache_complete_sha256=k.sha(root/"audit/cache-download-complete.json"),llm_called=False,candidate_run=False)),flush=True)
    except Exception as error:
        stop.set()
        if observer:
            observer.join(timeout=35)
            if observer.is_alive():raise RuntimeError("Cannot release while owned observer still runs")from error
        if lease.stream is not None:
            parts=[];part_error=evidence_error=None;closed=False
            try:
                if book:
                    parts=book.settle_unclosed_parts()
                    if len(parts)>4 or book.prefix_bytes+sum(x["bytes"]for x in parts)>k.PREFIX_CAP:
                        raise RuntimeError("Failure preservation exceeds authorized forecast; keep every byte")
            except Exception as e:part_error=type(e).__name__+": "+str(e)
            try:
                if journal:k.validate_evidence(root,rows,dict(body_journal=journal.footer(),prefix_operations_closed=True));closed=True
            except Exception as e:evidence_error=type(e).__name__+": "+str(e)
            scan=scan_error=None
            try:scan=b.full_scan(root)["allocated_envelope_bytes"]
            except Exception as e:scan_error=type(e).__name__+": "+str(e)
            lease.write(footer("aborted",closed,parts,failure_post_scan_envelope_bytes=scan,failure_post_scan_error=scan_error,completed_objects=len(completed),error=(type(error).__name__+": "+str(error))[:4096],
                part_validation_error=part_error,evidence_validation_error=evidence_error,observer=observer_errors))
        raise
    finally:lease.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument("stage",choices=("gate","acquire"));parser.add_argument("--review-sha",required=True);parser.add_argument("--removal-proof",required=True);parser.add_argument("--removal-sha",required=True)
    args=parser.parse_args()
    if args.stage=="gate":
        context=preflight(args.review_sha,args.removal_proof,args.removal_sha)
        print(json.dumps(dict(transport_protocol=TRANSPORT,completed_objects=3648,pending_objects=2178,original_namespace_per_key_total_cap=3,
            old_v3_key_interval=[0,3],all_history_global_gets=None,deadline_utc="2026-10-08T18:16:26.118992+00:00",
            writer_probe=context[9],remaining_new_gets=6530,prior_bulk_gets=96,e_write=False,public_get=False,llm_called=False,candidate_run=False)),flush=True)
    else:acquire(args.review_sha,args.removal_proof,args.removal_sha)


if __name__=="__main__":main()
