"""One fixed failed phase, explicit root-reviewed prefix0 recovery.

Gate/check only read E and save F reports. Restore is the sole E-writing mode,
never run by preparation/tests. No object decoding, GET, model, broad migration,
deletion, partial takeover or automatic resume. All old bytes remain archived.
"""
from pathlib import Path
import argparse
import ctypes
from ctypes import wintypes
import datetime
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import uuid

PROJECT = Path(__file__).resolve().parents[2]
DOCS = PROJECT / "docs/repair-2026-10-08"
ROOT = Path("E:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/minif2f-v415")
FAST_SOURCE = PROJECT / "scripts/repair-2026-10-08/minif2f_fast_unpack_v2.py"
OLD_SOURCE = PROJECT / "scripts/repair-2026-10-08/minif2f_fast_unpack.py"
OLD_SHA = "3e4d3f5ac688eca0e4b9b3a8afdcf710448d1816451f64dcaa1051a5750c44cb"
FAST_SHA = "ef0ddf5d708f6507d256af7a3c77e68c71a1eb7adda79ab7a7f19e9a246fbc09"
PROTOCOL = "minif2f-fast-prefix0-recovery-v2"
FAST_PROTOCOL = "bounded-official-cache-unpack-v2-archive-dot-prefix"
OLD_PID = 107912
OLD_CID = "21fefd14ab28968506f122d565156232b6419397a3b3bf372b8d17c351586113"
OLD_NONCE = "06bec841f3c84e198447b63716a3a4d6"
OLD_STAGE = "cache-fast-stage-" + OLD_NONCE
HISTORY = "cache-fast-failed-prefix0-" + OLD_NONCE
EMPTY_SHA = hashlib.sha256(b"").hexdigest()
FILES = {
    "cache-fast-progress.json": (5366, "c05216b153b3f01f6d8a5ca5f60106de4ba63de7b2397ea2fda2dacde191bac5"),
    "cache-fast-container.json": (427, "22a91d9c11d4649a2c8746e51f7c3db547e57e45158602b72455d375768560b2"),
    "cache-fast-unpack.lock": (313, "a8047ebc98d30e7f8b43fd8ac03f119d4efed92a00ff724339ef5241ee906af2"),
    "cache-fast-commits.jsonl": (0, EMPTY_SHA),
    "cache-unpacked.jsonl": (0, EMPTY_SHA),
}


def need(value, why):
    if not value:
        raise RuntimeError(why)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pin(path):
    path = Path(path)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}


def ordinary(path):
    for p in [*reversed(path.parents), path]:
        s = p.lstat()
        need(stat.S_ISDIR(s.st_mode) and not s.st_file_attributes & 0x400, "Nonordinary ancestor: " + str(p))


def file_pin(path, expected):
    path = Path(path)
    s = path.lstat()
    need(stat.S_ISREG(s.st_mode) and not s.st_file_attributes & 0x400, "Nonregular/reparse file")
    actual = pin(path)
    need(actual["bytes"] == expected[0] and actual["sha256"] == expected[1], "Original failed phase bytes changed: " + path.name)
    return actual


def save(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    need(path.read_bytes() == raw, "Evidence fsync/readback mismatch")
    return pin(path)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def semantics(progress, owner, lease):
    need(progress["protocol"] == "bounded-official-cache-unpack-v1" and progress["validated"] is False and
        progress["state"] == "failed_preserve_partials" and progress["prefix_before"] == progress["processed_prefix"] == 0 and
        progress["requested_count"] == 2 and progress["error_type"] == "archive_path" and
        progress["error"] == "Archive path is not a bounded canonical relative path" and
        progress["reviewed_script_sha256"] == OLD_SHA and progress["worker"]["container_id"] == OLD_CID and
        progress["candidate_run"] is False and progress["llm_called"] is False and progress["public_get"] is False,
        "Not the one approved failed prefix0 phase")
    need(owner["protocol"] == "bounded-official-cache-unpack-v1" and owner["state"] == "removed" and
        owner["container_id"] == OLD_CID and owner["name"] == "objrun-minif-fast-dc4a6642ba9b" and
        owner["owner_label"] == OLD_NONCE and owner["image_id"] == progress["worker"]["image_id"] and
        bool(owner["removed_at_utc"]), "Old owned-container identity/closure differs")
    need(lease["protocol"] == "public-cache-acquisition-v1" and lease["run_id"] == "01a119ed-fdf7-7c32-b323-de9bab1290b6" and
        lease["stage"] == "bounded-official-cache-unpack-v1" and lease["held"] is False and
        lease["pid"] == OLD_PID and lease["outcome"] == "infrastructure_invalid", "Old fast lease is active/unknown")


def stage_inventory(path, expected_names):
    ordinary(path)
    rows = []
    for current, children, names in os.walk(path, followlinks=False):
        need(not names, "Nonempty partial stage must be retained; recovery denied")
        for n in children:
            p = Path(current) / n; s = p.lstat()
            need(stat.S_ISDIR(s.st_mode) and not s.st_file_attributes & 0x400, "Stage reparse/non-directory")
            rows.append({"relativePath": p.relative_to(path).as_posix(), "device": str(s.st_dev),
                "fileId": str(s.st_ino), "mtimeNs": str(s.st_mtime_ns), "ctimeNs": str(s.st_ctime_ns),
                "atimeNs": str(s.st_atime_ns), "attributes": s.st_file_attributes, "bytes": s.st_size})
    need(len(rows) == 28 and {r["relativePath"] for r in rows} == set(expected_names), "Unknown/missing stage directory set")
    return rows


def stable_stage(rows):
    # Access timestamps may move during readonly traversal. Preserve the full
    # observations, but only compare identity/content-independent attributes.
    return [{k:v for k,v in r.items() if k != "atimeNs"} for r in rows]


def stage_root_identity(path):
    ordinary(path)
    s = path.lstat()
    return {"device":str(s.st_dev),"fileId":str(s.st_ino),"mtimeNs":str(s.st_mtime_ns),
        "ctimeNs":str(s.st_ctime_ns),"atimeNs":str(s.st_atime_ns),"attributes":s.st_file_attributes,"bytes":s.st_size}


def same_renamed_root(before, after):
    need(all(before[k] == after[k] for k in ("device","fileId","mtimeNs")),"Stage root identity/mtime changed")


def stable_inputs(value):
    return {**value,"stageInventory":stable_stage(value["stageInventory"]),
        "stageRootIdentity":{k:v for k,v in value["stageRootIdentity"].items() if k != "atimeNs"}}


def audit_no_partial(audit):
    ordinary(audit)
    for p in audit.rglob("*"):
        need(p.name not in ("cache-fast-item.json","cache-fast-intent.json") and not p.name.endswith((".new",".part")),
            "Unclosed intent/new/partial audit artifact")


def absence():
    ps = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    command = "$ErrorActionPreference='Stop';$taskItems=@(Get-Process -ErrorAction Stop);[pscustomobject]@{pid=107912;present=($null -ne ($taskItems|Where-Object Id -eq 107912));observedAtUtc=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Compress"
    p = subprocess.run([str(ps), "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, timeout=30)
    need(p.returncode == 0, "Actual PID query failed")
    observed = json.loads(p.stdout.decode("utf-8-sig"))
    need(observed["pid"] == OLD_PID and observed["present"] is False, "Original PID present/unknown")
    d = subprocess.run(["docker", "inspect", OLD_CID], capture_output=True, timeout=30)
    stderr = d.stderr.decode("utf-8", errors="replace")
    need(d.returncode != 0 and "no such" in stderr.casefold() and OLD_CID in stderr,
        "Actual daemon did not confirm exact original CID absent")
    return {"observedAtUtc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "pid": observed,
        "docker": {"containerId": OLD_CID, "returncode": d.returncode, "stderr": stderr,
            "stdoutSha256": hashlib.sha256(d.stdout).hexdigest(), "stderrSha256": hashlib.sha256(d.stderr).hexdigest(), "absent": True},
        "mutatingDockerOperations": 0}


class Handle:
    """Native share-deny; create-new for new markers, read-only for old bytes."""
    def __init__(self, path, create=False):
        import msvcrt
        self.path = path; self.stream = None
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = api.CreateFileW
        fn.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        fn.restype = wintypes.HANDLE
        h = fn(str(path), 0xC0000000 if create else 0x80000000, 0, None, 1 if create else 3, 0x00200080, None)
        need(h != ctypes.c_void_p(-1).value, "Native share-deny/create-new handle unavailable")
        fd = msvcrt.open_osfhandle(h, (os.O_RDWR if create else os.O_RDONLY) | os.O_BINARY)
        self.stream = os.fdopen(fd, "r+b" if create else "rb", buffering=0)
    def write(self, value):
        raw = (json.dumps(value,sort_keys=True)+"\n").encode(); need(len(raw) <= 16384,"Lease exceeds bound")
        self.stream.seek(0); self.stream.write(raw); self.stream.truncate(); self.stream.flush(); os.fsync(self.stream.fileno())
        self.stream.seek(0); need(self.stream.read() == raw,"Native lease readback mismatch")
        return hashlib.sha256(raw).hexdigest()
    def close(self):
        if self.stream: self.stream.close(); self.stream = None


def review(path, expected):
    need(path.stat().st_size <= 1024**2 and digest(path) == expected,"Frozen recovery review changed")
    value = json.loads(path.read_bytes())
    need(value["protocol"] == "minif2f-fast-v2-source-review-v1" and value["recoveryFailureNonce"] == OLD_NONCE,"Wrong source review")
    for p in value["executionPins"] + value["protectedPins"]:
        need(pin(Path(p["path"])) == p,"Frozen new/old/protected source changed")
    need(digest(FAST_SOURCE) == FAST_SHA and digest(OLD_SOURCE) == OLD_SHA,"Source version mismatch")
    return value


def validate(review_value):
    ordinary(ROOT)
    audit = ROOT / "audit"
    for name in (HISTORY,"cache-fast-prefix0-recovery.lock","cache-fast-prefix0-recovery.json","cache-fast-prefix0-recovery-partial.json"):
        need(not os.path.lexists(audit/name),"Prior/partial recovery exists; no automatic takeover")
    pins = {n:file_pin(audit/n,expected) for n,expected in FILES.items()}
    progress, owner, lease = [json.loads((audit/n).read_bytes()) for n in ["cache-fast-progress.json","cache-fast-container.json","cache-fast-unpack.lock"]]
    semantics(progress,owner,lease)
    diagnosis = json.loads((DOCS/"minif2f-fast-first-archive-diagnosis.json").read_bytes())
    names = [r["relativePath"] for r in diagnosis["stageInventory"]]
    stage = stage_inventory(audit/OLD_STAGE,names)
    stage_root = stage_root_identity(audit/OLD_STAGE)
    audit_no_partial(audit)
    fast = module(FAST_SOURCE,"fixed_fast_v2_recovery")
    helper = fast.load_helper(PROJECT)
    helper.exact_root(ROOT); helper.allocation_unit(); helper.volume_reserves()
    acq = json.loads((audit/"public-cache-acquisition.lock").read_bytes())
    need(acq["held"] is False and acq["outcome"] == "complete" and acq["completed_objects"] == 5826,"Original5826 acquisition unclosed")
    need(digest(audit/"public-cache-acquisition.lock") == progress["original_acquisition_lease_sha256"],"Original acquisition lease changed")
    records, provenance = fast.inputs(PROJECT,ROOT,helper)
    need(provenance == progress["input_provenance"] and len(records) == 5826,"5826 closed provenance differs")
    blobdir = ROOT/"downloads/mathlib-cache"
    need({p.name for p in blobdir.iterdir()} == {r["ltar"] for r in records},"Unknown/missing original compressed object")
    for r in records:
        file_pin(blobdir/r["ltar"],(r["bytes"],r["sha256"]))
    need(fast.source_identity(PROJECT,ROOT,helper) == progress["source_before"],"Bootstrap/toolchain/source identity changed")
    for r in records[:2]:
        for value in fast.ltar_paths((blobdir/r["ltar"]).read_bytes()):
            need(not os.path.lexists(ROOT/"mathlib4"/value),"Unexpected existing output for approved first2 objects")
    return {"pins":pins,"stageInventory":stage,"stageRootIdentity":stage_root,"sourceIdentity":progress["source_before"],"inputProvenance":provenance,
        "objects":5826,"acquisitionLease":pin(audit/"public-cache-acquisition.lock"),"space":helper.full_scan(ROOT)["allocated_envelope_bytes"]},fast,helper


def baseline(receipt_sha):
    return {"protocol":FAST_PROTOCOL,"state":"recovered_prefix0_not_decoded","validated":True,
        "processed_prefix":0,"prefix_before":0,"decoded_objects":0,"cache_unpack_complete":False,
        "whole5826OutputCertified":False,"receipts_sha256":EMPTY_SHA,"commits_sha256":EMPTY_SHA,
        "recovery_protocol":PROTOCOL,"recovery_receipt_sha256":receipt_sha,"candidate_run":False,"llm_called":False,"public_get":False}


def pending_baseline(nonce):
    return {**baseline(""),"validated":False,"state":"prefix0_recovery_pending","recovery_owner_nonce":nonce}


def native_closed_marker(path, expected_pin=None, expected_sha=None):
    ordinary(path.parent)
    s=path.lstat()
    need(stat.S_ISREG(s.st_mode) and not s.st_file_attributes & 0x400,"Nonregular/reparse closure lease")
    h=Handle(path)
    try:
        raw=h.stream.read(16385)
        need(0 < len(raw) <= 16384,"Closure lease is empty/oversized")
        actual={"path":str(path),"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
        need(expected_pin is None or actual==expected_pin,"Closure lease bytes changed")
        need(expected_sha is None or actual["sha256"]==expected_sha,"Original acquisition lease changed")
        value=json.loads(raw)
        need(value["held"] is False,"Closure lease is still held")
        return value
    finally:h.close()


def check_closed(review_value, review_path):
    ordinary(ROOT);audit=ROOT/"audit";ordinary(audit)
    receipt=audit/"cache-fast-prefix0-recovery.json";r=json.loads(receipt.read_bytes());receipt_pin=pin(receipt)
    need(r["protocol"]==PROTOCOL and r["closed"] is True and r["nativeLeaseHandlesClosed"] is True and
        r["decoded_objects"]==0 and r["cache_unpack_complete"] is False,"Recovery unclosed")
    need(r["reviewPin"]==pin(review_path) and r["sourcePins"]==review_value["executionPins"]+review_value["protectedPins"],
        "Recovery source/review binding changed")
    nonce=r["ownerNonce"];need(re.fullmatch("[0-9a-f]{32}",nonce) is not None,"Recovery nonce differs")
    history=audit/HISTORY;ordinary(history);need(r["history"]==str(history),"Recovery history path differs")
    for n,e in FILES.items():file_pin(history/n,e)
    expected_pins={n:{"path":str(audit/n),"bytes":e[0],"sha256":e[1]} for n,e in FILES.items()}
    need(r["originalPins"]==expected_pins,"Original phase pin binding differs")
    intent_path=audit/("cache-fast-prefix0-transaction-"+nonce+".json")
    need(r["intentPin"]["path"]==str(intent_path),"Recovery intent path differs")
    file_pin(intent_path,(r["intentPin"]["bytes"],r["intentPin"]["sha256"]))
    intent=json.loads(intent_path.read_bytes())
    need(intent["protocol"]==PROTOCOL+"-intent" and intent["ownerNonce"]==nonce and
        intent["reviewPin"]==r["reviewPin"] and intent["originalPins"]==r["originalPins"] and
        intent["stageOriginalInventory"]==r["stageOriginalInventory"] and intent["stageRootOriginalIdentity"]==r["stageRootBefore"],
        "Recovery intent binding differs")
    names=[v["relativePath"] for v in r["stageOriginalInventory"]]
    archived=stage_inventory(history/"stage",names)
    need(stable_stage(archived)==stable_stage(r["stageArchivedInventory"]),"Archived stage changed")
    same_renamed_root(r["stageRootBefore"],r["stageRootAfter"])
    same_renamed_root(r["stageRootAfter"],stage_root_identity(history/"stage"))
    audit_no_partial(audit)
    for n in ("cache-fast-commits.jsonl","cache-unpacked.jsonl"):file_pin(audit/n,(0,EMPTY_SHA))
    progress_path=audit/"cache-fast-progress.json"
    s=progress_path.lstat();need(stat.S_ISREG(s.st_mode) and not s.st_file_attributes & 0x400,"Nonregular/reparse baseline")
    need(json.loads(progress_path.read_bytes())==baseline(receipt_pin["sha256"]),"Recovery baseline is pending/changed/not prefix0")
    old_progress=json.loads((history/"cache-fast-progress.json").read_bytes())
    need(r["inputProvenance"]==old_progress["input_provenance"] and r["sourceIdentity"]==old_progress["source_before"],
        "Original input/source provenance differs")
    acq=native_closed_marker(audit/"public-cache-acquisition.lock",expected_sha=old_progress["original_acquisition_lease_sha256"])
    need(acq["protocol"]=="public-cache-acquisition-v1" and acq["run_id"]=="01a119ed-fdf7-7c32-b323-de9bab1290b6" and
        acq["outcome"]=="complete" and acq["completed_objects"]==5826,"Original acquisition is unclosed")
    fresh=native_closed_marker(audit/"cache-fast-unpack.lock",r["freshFastLeasePin"])
    own=native_closed_marker(audit/"cache-fast-prefix0-recovery.lock",r["recoveryLeasePin"])
    need(fresh["protocol"]=="public-cache-acquisition-v1" and fresh["run_id"]==acq["run_id"] and fresh["lease_id"]==nonce and
        fresh["stage"]==PROTOCOL and fresh["outcome"]=="recovered_prefix0_not_decoded" and
        own["protocol"]==PROTOCOL and own["ownerNonce"]==nonce and own["reviewSha256"]==r["reviewPin"]["sha256"] and
        own["outcome"]==fresh["outcome"] and type(fresh["pid"]) is int and fresh["pid"]>0 and own["pid"]==fresh["pid"],
        "Actual released lease identity differs")
    fast=module(FAST_SOURCE,"fixed_fast_v2_closed_recovery")
    need(fast.verified_prefix(ROOT,[]) == ([],set()),"Actual prefix0 is unclosed")
    return {"protocol":PROTOCOL,"historyPreserved":True,"receiptPin":receipt_pin,"baselinePin":pin(progress_path),
        "nativeShareDenyReopensVerified":3,"decoded_objects":0,"cache_unpack_complete":False,"e_write":False,"candidate_run":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=["gate","restore","check-closed"])
    parser.add_argument("--review",type=Path,required=True);parser.add_argument("--review-sha",required=True)
    parser.add_argument("--gate",type=Path);parser.add_argument("--gate-sha")
    args=parser.parse_args(); started_review_sha=args.review_sha
    review_value=review(args.review,args.review_sha)
    if args.stage == "check-closed":
        print(json.dumps(check_closed(review_value,args.review)));return
    actual,fast,helper=validate(review_value); observed=absence()
    gate={"protocol":PROTOCOL+"-gate","validated":True,"reviewPin":pin(args.review),"inputs":actual,"actualAbsence":observed,"E_write":False,
        "decoded_objects":0,"cache_unpack_complete":False,"recordedAtUtc":datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if args.stage == "gate":
        review(args.review,started_review_sha)
        print(json.dumps(save(DOCS/("minif2f-fast-prefix0-gate-"+uuid.uuid4().hex+".json"),gate)));return
    need(args.gate and args.gate_sha and digest(args.gate)==args.gate_sha,"Restore requires reviewed actual Gate")
    prior=json.loads(args.gate.read_bytes())
    need(prior["protocol"]==gate["protocol"] and prior["validated"] is True and prior["reviewPin"]==gate["reviewPin"] and stable_inputs(prior["inputs"])==stable_inputs(actual),"Reviewed Gate inputs changed")
    age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(prior["recordedAtUtc"])).total_seconds()
    need(0<=age<=600,"Recovery Gate over600s; create new readonly Gate")
    audit=ROOT/"audit"; history=audit/HISTORY; nonce=uuid.uuid4().hex
    transaction=audit/("cache-fast-prefix0-transaction-"+nonce+".json")
    lease=None;canonical_lease=None; closed=False
    try:
        with fast.AcquisitionGuard(audit/"public-cache-acquisition.lock"):
            lease=Handle(audit/"cache-fast-prefix0-recovery.lock",True)
            held={"protocol":PROTOCOL,"ownerNonce":nonce,"held":True,"pid":os.getpid(),"reviewSha256":started_review_sha}
            lease.write(held);helper.writer_probe(); absence()
            for n,e in FILES.items():file_pin(audit/n,e)
            stage_now=stage_inventory(audit/OLD_STAGE,[r["relativePath"] for r in actual["stageInventory"]])
            root_now=stage_root_identity(audit/OLD_STAGE)
            need(stable_stage(stage_now)==stable_stage(actual["stageInventory"]),"Stage identity/metadata changed")
            need({k:v for k,v in root_now.items() if k != "atimeNs"}=={k:v for k,v in actual["stageRootIdentity"].items() if k != "atimeNs"},"Stage root changed since actual Gate")
            review(args.review,started_review_sha)
            save(transaction,{"protocol":PROTOCOL+"-intent","ownerNonce":nonce,"gatePin":pin(args.gate),"reviewPin":pin(args.review),"originalPins":actual["pins"],"stageOriginalInventory":stage_now,"stageRootOriginalIdentity":root_now,"historyTarget":str(history)})
            need(not history.exists(),"Fresh exact history leaf required"); history.mkdir()
            # Same-E rename preserves bytes. No delete, decode or compressed-object operation.
            for name in FILES:
                source=audit/name;target=history/name
                need(source.parent==audit and target.parent==history and not os.path.lexists(target),"Exact original metadata rename fence")
                os.rename(source,target);file_pin(target,FILES[name])
                if name=="cache-fast-progress.json":
                    # Old receipts still exist at this point. Immediately add a
                    # false anchor before any journal is moved; all old/new
                    # verified_prefix gates reject every later partial state.
                    save(source,pending_baseline(nonce))
                if name=="cache-fast-unpack.lock":
                    canonical_lease=Handle(source,True)
                    canonical_lease.write({"protocol":helper.PROTOCOL,"run_id":helper.RUN_ID,"lease_id":nonce,"held":True,"pid":os.getpid(),"stage":PROTOCOL})
            os.rename(audit/OLD_STAGE,history/"stage")
            moved=stage_inventory(history/"stage",[r["relativePath"] for r in stage_now])
            moved_root=stage_root_identity(history/"stage");same_renamed_root(root_now,moved_root)
            need([(r["relativePath"],r["device"],r["fileId"],r["mtimeNs"]) for r in moved]==[(r["relativePath"],r["device"],r["fileId"],r["mtimeNs"]) for r in stage_now],"Stage directory identity/mtime changed")
            for name in ("cache-fast-commits.jsonl","cache-unpacked.jsonl"):
                with (audit/name).open("xb") as f:f.flush();os.fsync(f.fileno())
            provisional={"protocol":PROTOCOL,"closed":False,"ownerNonce":nonce,"decoded_objects":0,"cache_unpack_complete":False,
                "reviewPin":pin(args.review),"sourcePins":review_value["executionPins"]+review_value["protectedPins"],
                "history":str(history),"originalPins":actual["pins"],"stageOriginalInventory":stage_now,"stageArchivedInventory":moved,"stageRootBefore":root_now,"stageRootAfter":moved_root,
                "inputProvenance":actual["inputProvenance"],"sourceIdentity":actual["sourceIdentity"],"actualAbsence":absence(),"intentPin":pin(transaction)}
            save(audit/"cache-fast-prefix0-recovery-partial.json",provisional)
            # With no validated progress, both old and v2 gates reject a partial recovery.
            need(json.loads((audit/"cache-fast-progress.json").read_bytes())==pending_baseline(nonce),"Recovery pending anchor changed")
            canonical_lease.write({"protocol":helper.PROTOCOL,"run_id":helper.RUN_ID,"lease_id":nonce,"held":False,"pid":os.getpid(),"stage":PROTOCOL,"outcome":"recovered_prefix0_not_decoded"})
            lease.write({**held,"held":False,"outcome":"recovered_prefix0_not_decoded"})
            review(args.review,started_review_sha)
        # No usable baseline is published until native writable/read guards close.
        canonical_lease.close();canonical_lease=None;lease.close();lease=None
        for n,e in FILES.items():file_pin(history/n,e)
        review(args.review,started_review_sha)
        result={**provisional,"closed":True,"nativeLeaseHandlesClosed":True,"recordedAtUtc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "freshFastLeasePin":pin(audit/"cache-fast-unpack.lock"),"recoveryLeasePin":pin(audit/"cache-fast-prefix0-recovery.lock")}
        receipt_pin=save(audit/"cache-fast-prefix0-recovery.json",result)
        need(json.loads((audit/"cache-fast-progress.json").read_bytes())==pending_baseline(nonce),"Pending anchor changed before publication")
        fast.durable_json(audit/"cache-fast-progress.json",baseline(receipt_pin["sha256"]))
        baseline_pin=pin(audit/"cache-fast-progress.json")
        closed=True
        need(fast.verified_prefix(ROOT,[]) == ([],set()),"V2 empty prefix must validate")
        old=module(OLD_SOURCE,"original_fast_after_recovery")
        try:old.verified_prefix(ROOT,[])
        except old.InfraError:pass
        else:raise RuntimeError("Old failed decoder must reject v2 baseline")
        print(json.dumps({"protocol":PROTOCOL,"restored":True,"decoded_objects":0,"cache_unpack_complete":False,"receiptPin":receipt_pin,"baselinePin":baseline_pin,"oldPhasePreserved":True}))
    except BaseException:
        # Keep every old/new/partial path and held/false marker as actual evidence.
        # Nothing is silently deleted, resumed, overwritten or represented as decoded.
        raise
    finally:
        if canonical_lease:canonical_lease.close()
        if lease:lease.close()


if __name__=="__main__":main()
