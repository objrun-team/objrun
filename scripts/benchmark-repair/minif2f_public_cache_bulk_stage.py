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
REVIEW_PATH=PROJECT/".local-evidence/repository/test/fixtures/repair/minif2f-public-cache-bulk-review.json"
spec=importlib.util.spec_from_file_location("explicit_bulk_kernel",Path(__file__).with_name("minif2f_public_cache_bulk.py"))
k=importlib.util.module_from_spec(spec);spec.loader.exec_module(k)
b,c=k.base,k.carry
TRANSPORT=k.TRANSPORT


def review(expected):
    raw=c.pinned(REVIEW_PATH,expected);data=json.loads(raw)
    if (data.get("protocol")!="public-cache-explicit-bulk-source-review-v1" or data.get("validated") is not True or
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


def writer_probe(previous_pid):
    proof=c.writer_probe()
    command=r'''$ErrorActionPreference='Stop';$all=@(Get-CimInstance Win32_Process);$excluded=@(__PID__);$cur=__PID__;while($cur){$p=$all|Where-Object ProcessId -eq $cur;if(-not $p){break};$cur=[int]$p.ParentProcessId;$excluded+=$cur};$hits=@();foreach($p in $all){if($excluded -contains [int]$p.ProcessId){continue};if([string]$p.CommandLine -match '(?i)minif2f_public_cache_bulk(_stage)?\.(py|ps1)["''\s]+[\s\S]*?acquire(?:["''\s]|$)'){$hits+=[pscustomobject]@{pid=[int]$p.ProcessId;stage='Acquire'}}};$prior=@($all|Where-Object ProcessId -eq __PRIOR__);[pscustomobject]@{bulk_writers=$hits;carry_pid_present=($prior.Count -gt 0)}|ConvertTo-Json -Depth 4 -Compress'''.replace("__PID__",str(os.getpid())).replace("__PRIOR__",str(previous_pid))
    result=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",command],capture_output=True,timeout=10)
    if result.returncode:raise RuntimeError("Bulk writer/previous actor metadata probe failed")
    observed=json.loads(result.stdout.decode("utf-8-sig"))
    if observed["bulk_writers"]or observed["carry_pid_present"]:raise RuntimeError("Previous carry PID or another bulk writer remains")
    proof["bulk_probe"]=observed;return proof


def preflight(review_sha):
    review(review_sha)
    root=b.exact_root(b.ROOT);b.allocation_unit();b.volume_reserves(k.AUDIT_BUDGET)
    public=PROJECT/".phase1-data/minif2f-restoration-public";core=Path(k.__file__).with_name("minif2f_restore.py")
    owned_new=(k.DISPATCH_REL,k.JOURNAL_REL,k.INPUT_REL,k.PHASE_REL,k.EVIDENCE_REL,"audit/cache-download-complete.json")
    if any((root/p).exists()or(root/(p+".new")).exists()for p in owned_new):
        raise RuntimeError("Existing bulk/full closure or unclosed intent; no automatic new allowance")
    c.pinned(root/c.PHASE_REL,k.CARRY_PHASE_SHA)
    c.pinned(root/"audit"/b.LEASE_NAME,k.CARRY_LEASE_SHA)
    c.pinned(root/"audit/cache-downloads.jsonl",k.CARRY_RECEIPTS_SHA)
    # Genuine pinned carry validator, before replacing its released lease.
    _,auth,prior,rows,_,carry_gate=c.preflight(root,public,core,k.CARRY_REVIEW_SHA,allow_closed=True)
    if carry_gate.get("completed_objects")!=3556:raise RuntimeError("Carry is not closed3556")
    marker=json.loads((root/"audit"/b.LEASE_NAME).read_bytes())
    phase=json.loads((root/c.PHASE_REL).read_bytes())
    if time.time()<k.datetime.fromisoformat(phase["closed_at_utc"]).timestamp():raise RuntimeError("Clock predates actual carry closure")
    k.carry.Deadline().check()
    raw=c.pinned(root/"audit/cache-downloads.jsonl",k.CARRY_RECEIPTS_SHA)
    # The genuine frozen carry validator has just SHA-checked these exact
    # blobs and strict3556 typed rows. Parse its same pinned bytes once.
    old={r["ltar"]:r for r in (json.loads(line)for line in raw.splitlines())}
    pending=[r for r in rows if r["ltar"]not in old]
    if len(old)!=3556 or len(pending)!=2270:raise RuntimeError("Not exactly2270 unique remaining keys")
    return root,public,core,rows,pending,old,raw,marker,phase,writer_probe(marker["pid"])


def typed_bulk(root,rows,initial_raw,released,allowed_new):
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
    # Kernel applies the same strong MD5/fresh-generation checks to new rows.
    k.validate_new_rows(root,{n:r for n,r in all_rows.items()if n not in old_names},evidence)
    return all_rows,evidence


def inspect_dispatch(path,namespace,review_sha,new_keys):
    raw=Path(path).read_bytes();counts={};serial=0
    if len(raw)>16*1024**2 or raw and not raw.endswith(b"\n"):raise RuntimeError("Truncated/oversized dispatch evidence")
    for line in raw.splitlines():
        if len(line)>2048:raise RuntimeError("Oversized dispatch row")
        r=json.loads(line);name=r["key"];serial+=1;counts[name]=counts.get(name,0)+1
        if (r.get("protocol")!=TRANSPORT or r.get("event")!="dispatch"or r.get("lease_id")!=namespace or
            r.get("review_sha256")!=review_sha or name not in new_keys or r.get("new_key_get")!=counts[name]or
            counts[name]>3 or r.get("new_global_get")!=serial or serial>6810 or
            r.get("v3_window_gets_before")!=1507 or r.get("v3_window_consumed_allowance")!=1507+serial or
            r.get("old_v3_key_interval")!=[0,3]or r.get("v3_plus_bulk_key_interval")!=[counts[name],counts[name]+3]or
            r.get("all_history_key_gets")is not None or r.get("all_history_global_gets")is not None):
            raise RuntimeError("Bulk allowance reset or historical count invented")
    return counts,serial,hashlib.sha256(raw).hexdigest()


def acquire(review_sha):
    root,public,core,rows,pending,old,initial_raw,prior_marker,carry_phase,start_probe=preflight(review_sha)
    lease=c.OwnedLease(root/"audit"/b.LEASE_NAME);clock=c.Deadline()
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
            prefix_operations_closed=closed,body_journal=journal.footer()if journal else None,
            dispatch_journal=dispatch.footer()if dispatch else None,new_allowances_consumed=book.gets if book else 0,
            actual_opener_calls=book.open_calls if book else 0,v3_window_gets_before=1507,
            v3_window_opener_calls=1507+(book.open_calls if book else 0),all_history_global_gets=None,
            new_body_retries=book.recoveries if book else 0,abort_retained_parts=len(artifacts),
            preservation_operations_total=6+(book.recoveries if book else 0)+len(artifacts),
            cumulative_failed_prefix_bytes=(book.prefix_bytes if book else 292278)+sum(x["bytes"]for x in artifacts),
            retained_unclosed_owned_parts=artifacts,executing_review_sha256=review_sha,executing_worker_sha256=source_start,
            deadline_utc="2026-10-08T18:16:26.118992+00:00",**extras)
    try:
        lease.acquire();lease.write(dict(held=True,pid=os.getpid(),acquired_at_utc=k.stamp(),transport_protocol=TRANSPORT,
            executing_review_sha256=review_sha,executing_worker_sha256=source_start))
        review(review_sha);b.inputs(root,public,core)
        if k.sha(root/c.PHASE_REL)!=k.CARRY_PHASE_SHA or k.sha(root/"audit/cache-downloads.jsonl")!=k.CARRY_RECEIPTS_SHA:
            raise RuntimeError("Carry/input prefix changed during lease claim")
        initial=b.full_scan(root);book=k.Book(initial["allocated_envelope_bytes"],292278)
        input_cert=dict(protocol=TRANSPORT,lease_id=lease.id,original3556_prefix_bytes=len(initial_raw),
            original3556_prefix_sha256=k.CARRY_RECEIPTS_SHA,carry_phase_sha256=k.CARRY_PHASE_SHA,
            carry_released_lease_sha256=k.CARRY_LEASE_SHA,carry_validator_source_sha256=c.sha(c.__file__),
            carry_validator_actual_gate_succeeded=True,pending_count=2270,
            pending_manifest_sha256=hashlib.sha256(b"".join(k.encode_row(r)for r in pending)).hexdigest(),
            original_v3_window_gets=1507,all_history_global_gets=None,old_v3_key_interval=[0,3],new_key_get_cap=3,
            new_body_retry_cap=4,abort_evidence_retention_cap=4,preservation_operations_cap=14,
            prefix_cap_bytes=256*1024**2,audit_reserved_bytes=k.AUDIT_BUDGET,
            deadline_utc="2026-10-08T18:16:26.118992+00:00",review_sha256=review_sha)
        b.durable_json(root/k.INPUT_REL,input_cert)
        journal=k.Journal(root);dispatch=DispatchJournal(root,lease.id,review_sha);book.dispatch_journal=dispatch
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
        all_rows,evidence=typed_bulk(root,rows,initial_raw,released,{r["ltar"]for r in pending})
        counts,intents,intent_sha=inspect_dispatch(root/k.DISPATCH_REL,lease.id,review_sha,{r["ltar"]for r in pending})
        if (len(all_rows)!=5826 or len(completed)!=5826 or set(counts)!={r["ltar"]for r in pending}or
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
            all_cache_blob_sha256_rechecked=True,original3556_prefix_unchanged=True,
            original3556_prefix_sha256=k.CARRY_RECEIPTS_SHA,download_receipts_sha256=k.sha(root/"audit/cache-downloads.jsonl"),
            resumed_objects=3556,new_objects=2270,new_budget_opener_calls=book.open_calls,v3_window_opener_calls=1507+book.open_calls,
            all_history_global_gets=None,old_v3_key_interval=[0,3],new_per_key_cap=3,new_body_retries=book.recoveries,
            preservation_operations_total=6+book.recoveries,cumulative_failed_prefix_bytes=book.prefix_bytes,
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
    parser=argparse.ArgumentParser();parser.add_argument("stage",choices=("gate","acquire"));parser.add_argument("--review-sha",required=True)
    args=parser.parse_args()
    if args.stage=="gate":
        context=preflight(args.review_sha)
        print(json.dumps(dict(transport_protocol=TRANSPORT,completed_objects=3556,pending_objects=2270,new_namespace_key_get_cap=3,
            old_v3_key_interval=[0,3],all_history_global_gets=None,deadline_utc="2026-10-08T18:16:26.118992+00:00",
            writer_probe=context[-1],e_write=False,public_get=False,llm_called=False,candidate_run=False)),flush=True)
    else:acquire(args.review_sha)


if __name__=="__main__":main()
