"""Exact stopped-solver data capture; import is inert, CLI is explicit.

No candidate directory, script, shell, venv or snapshot enters private grading.
Only the fixed single data-file path of a source-bound task is transferred.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import threading
import time
import uuid
import skb_artifact_storage_v2 as storage
import skb_artifact_task_v2 as task
import skb_artifact_transport_v2 as transport

PROTOCOL = "skillsbench-data-artifact-capture-v1"
ERR_CAP = 256*1024


def sources():
    return [task.pin(p) for p in (Path(__file__), Path(task.__file__), Path(storage.__file__), Path(transport.__file__))] + transport.component_pins()


def fresh(path, raw, boundary):
    p = Path(path); storage.ordinary(p.parent, boundary)
    with p.open("xb") as f:
        task.demand(f.write(raw) == len(raw), "short_write", "Capture evidence incomplete")
        f.flush(); os.fsync(f.fileno())
    item = task.pin(p)
    task.demand(item["bytes"] == len(raw) and item["sha256"] == hashlib.sha256(raw).hexdigest(), "readback", "Capture fsync/readback differs")
    return item


def missing_artifact(rc, out, err, path, cid):
    if type(rc) is not int or rc != 1 or out != b"" or not re.fullmatch("[0-9a-f]{64}", cid): return False
    try: lines=err.decode("utf-8", errors="strict").splitlines()
    except UnicodeError: return False
    if len(lines) != 1: return False
    line=lines[0].strip()
    # Known Docker daemon missing-file form; target and immutable CID stay exact.
    pattern="(?i:Error response from daemon: Could not find the file )"+re.escape(path)+"(?i: in container )"+re.escape(cid)
    return re.fullmatch(pattern, line) is not None


def parse_artifact_tar(raw, basename, maximum):
    task.demand(isinstance(raw, bytes) and len(raw) <= maximum+65536, "tar_cap", "Bounded daemon TAR exceeded its exact cap")
    task.demand(isinstance(basename, str) and basename not in ("", ".", "..") and "/" not in basename and "\\" not in basename,
                "artifact_name", "One exact declared basename required")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        members=archive.getmembers()
        task.demand(len(members)==1 and members[0].name in (basename,"./"+basename), "tar_scope", "Only one exact output member accepted")
        member=members[0]
        if member.issym(): return {"state":"symlink","memberKind":"symlink","size":member.size},None
        if member.isdir(): return {"state":"directory","memberKind":"directory","size":member.size},None
        task.demand(member.isfile() and not member.islnk(), "tar_kind", "Hardlink/special member denied")
        if member.size > maximum: return {"state":"too_large","memberKind":"regular","size":member.size},None
        source=archive.extractfile(member); body=source.read(maximum+1)
        task.demand(len(body)==member.size and len(body)<=maximum, "tar_incomplete", "Transferred regular body incomplete")
        return {"state":"regular","memberKind":"regular","size":member.size},body


def validate_solver_inspect(actual, descriptor, owner):
    task.validate_descriptor(descriptor)
    built = task.read_json(descriptor["candidateImageProofPin"])
    task.demand(owner.get("protocol")=="skillsbench-solver-owner-v1" and owner.get("role")=="solver"
                and owner.get("taskId")==descriptor["taskId"] and re.fullmatch("[0-9a-f]{32}",owner.get("instanceNonce",""))
                and re.fullmatch("[0-9a-f]{64}",owner.get("containerID","")), "solver_owner", "Exact source-bound solver owner required")
    cid=owner["containerID"]; name="/objrun-skb-solver-"+owner["instanceNonce"]
    h=actual.get("HostConfig",{}); state=actual.get("State",{}); labels=actual.get("Config",{}).get("Labels") or {}
    e=descriptor["originalResources"]["environment"]
    task.demand(actual.get("Id")==cid and actual.get("Name")==name and actual.get("Image")==built.get("imageId")
                and owner.get("imageId")==built.get("imageId") and state.get("Running") is False
                and state.get("Paused") is False and state.get("Dead") is False and state.get("Pid")==0,
                "solver_identity", "Exact candidate must actually be stopped with its original immutable image")
    task.demand(not h.get("Binds") and not h.get("Mounts") and not h.get("Privileged") and not h.get("PidMode")
                and not h.get("IpcMode") in ("host",) and h.get("NetworkMode") in ("none","bridge","default")
                and h.get("Memory")==e["memory_mb"]*1024**2 and h.get("NanoCpus")==e["cpus"]*10**9,
                "solver_namespace", "Solver host binds/namespace/runtime resource substitution")
    task.demand(labels.get("objrun.skb.task-id")==descriptor["taskId"] and labels.get("objrun.skb.instance-nonce")==owner["instanceNonce"]
                and labels.get("objrun.skb.role")=="solver", "solver_labels", "Solver exact task/role/nonce differs")
    size=actual.get("SizeRw")
    task.demand(type(size) is int and 0<=size<=descriptor["solverWritableBudgetBytes"], "solver_budget", "Actual solver write budget exceeded")
    return size


def capture_artifacts(task_descriptor_pin, exact_stopped_solver_owner_pin, output_directory, storage_descriptor, docker_client_pin, storage_descriptor_pin):
    descriptor=task.read_json(task_descriptor_pin); task.validate_descriptor(descriptor)
    task.demand(descriptor.get("candidateImageProofPin") is not None, "not_ready", "Actual source-bound candidate image required")
    storage.validate_descriptor(storage_descriptor)
    task.demand(task.read_json(storage_descriptor_pin) == storage_descriptor, "storage_source", "Actual storage descriptor Pin differs")
    task.verify_pin(docker_client_pin,64*1024**2)
    task.demand(Path(docker_client_pin["path"])==transport.DOCKER and docker_client_pin["sha256"]==transport.DOCKER_SHA,
                "docker_client", "Exact installed Docker client required")
    owner=task.read_json(exact_stopped_solver_owner_pin)
    box=Path(output_directory); root=Path(storage_descriptor["storePhysical"])
    task.demand(box.parent==Path(storage_descriptor["directories"]["captures"]) and re.fullmatch("capture-[0-9a-f]{32}",box.name),
                "output", "Fresh declared D captures leaf required")
    storage.ordinary(box.parent,Path("D:/")); task.demand(not os.path.lexists(box),"not_fresh","Capture leaf already exists")
    box.mkdir(); before=sources(); task_sources=task.original_sources(descriptor["taskId"])
    lease=storage.InstanceLease(storage_descriptor,box.name[8:],box); serial=0; records=[]; failed=True
    spec=descriptor["outputArtifacts"][0]; cid=owner.get("containerID","")
    env=transport.sanitized_environment(storage_descriptor,storage)
    scan_lock=threading.RLock(); last_scan=0.0; observed=None; command_reserve=0

    def guard(amount=0):
        nonlocal last_scan, observed
        lease.assert_owned()
        with scan_lock:
            now=time.monotonic()
            if observed is None or now-last_scan>=0.5:
                observed=storage.observe_owned_store(storage_descriptor)
                # The scan itself can exceed the polling interval. Start the
                # interval after it finishes, so pipe readers can drain.
                last_scan=time.monotonic()
            # Reserve the entire bounded command, rather than re-hash public
            # PCAP/environment data on every4KiB pipe chunk. Other producers
            # must retain their own admissions; this is not a kernel quota.
            task.demand(observed["allocatedEnvelopeBytes"]+max(amount,command_reserve)<=storage.STORE_CAP-2*1024**2,
                        "D_budget","Capture full-command reserve exceeds owned store cap")
            free={volume:__import__("shutil").disk_usage(volume+":/").free for volume in ("C","D","F")}
            task.demand(free["D"]>=storage.D_MIN+max(amount,command_reserve),"D_budget","Capture cannot preserve D physical reserve")
            bounds=storage.assess_resources(storage_descriptor,free,True,getattr(guard,"solver_size",0),
                                            solver_writable_limit=descriptor["solverWritableBudgetBytes"])
            task.demand(bounds["admitted"],"resources","Actual C/D/F solver+metadata reserve missing")

    def command(*args,cap=1024**2,checked=True):
        nonlocal serial, command_reserve, observed
        serial+=1;task.demand(serial<=6,"command_cap","Capture command bound exceeded")
        task.demand(sources()==before and task.original_sources(descriptor["taskId"])==task_sources,"source_drift","Capture source changed")
        with scan_lock: command_reserve=cap+ERR_CAP+1024**2;observed=None
        row,out,err=transport.bounded_child([str(transport.DOCKER),"--host",transport.DOCKER_HOST,*args],env,box,serial,guard,30,cap)
        records.append(task.pin(box/("command-%03d.json"%serial)))
        task.demand(sources()==before and task.original_sources(descriptor["taskId"])==task_sources,"source_drift","Source changed across exact command")
        if checked:task.demand(row["exitCode"]==0,"docker_command","Exact Docker transfer/inspect failed; bytes retained")
        return row,out,err

    try:
        lease.acquire()
        _,raw,_=command("container","inspect","--size",cid); arr=json.loads(raw)
        task.demand(isinstance(arr,list) and len(arr)==1,"solver_inspect","Single exact inspect required")
        guard.solver_size=validate_solver_inspect(arr[0],descriptor,owner)
        before_inspect=task.pin(box/"command-001.stdout.bin")
        row,raw,err=command("cp",cid+":"+spec["containerPath"],"-",cap=spec["maximumBytes"]+65536,checked=False)
        artifact_pin=None
        if row["exitCode"]!=0:
            task.demand(missing_artifact(row["exitCode"],raw,err,spec["containerPath"],cid),"artifact_transfer","Failure is not an exact missing-file event")
            member={"state":"absent","memberKind":None,"size":None}
        else:
            member,body=parse_artifact_tar(raw,Path(spec["containerPath"]).name,spec["maximumBytes"])
            if body is not None:artifact_pin=fresh(box/Path(spec["containerPath"]).name,body,box)
        _,after_raw,_=command("container","inspect","--size",cid); after=json.loads(after_raw)
        task.demand(isinstance(after,list) and len(after)==1 and validate_solver_inspect(after[0],descriptor,owner)==guard.solver_size,
                    "solver_drift","Stopped solver/source changed across transfer")
        guard(32768)
        closure=lease.release(); failed=False
        receipt={"protocol":PROTOCOL,"taskId":descriptor["taskId"],"taskDescriptorPin":task_descriptor_pin,"ownerPin":exact_stopped_solver_owner_pin,
                 "storageDescriptorPin":storage_descriptor_pin,"storageOwnerNonce":storage_descriptor["ownerNonce"],"captureNonce":box.name[8:],
                 "dockerClientPin":docker_client_pin,
                 "artifactPath":spec["containerPath"],"state":member["state"],"artifactPin":artifact_pin,"ownedContainerID":cid,
                 "containerStopped":True,"daemonEvidence":{"containerId":cid,"method":"docker-cp-tar","memberKind":member["memberKind"],"size":member["size"],
                    "rawTarCaptureComplete":row["exitCode"]==0,"missingFileDiagnosticMatched":member["state"]=="absent",
                    "beforeInspectPin":before_inspect,"afterInspectPin":task.pin(box/"command-003.stdout.bin"),"transferRecordPin":records[1]},
                 "leaseClosurePin":closure,"commandRecords":records,"sourcePins":before,"sourceBeforeAfterEqual":sources()==before,
                 "actorPid":os.getpid(),"cliActorClosureRequired":True,"models":0,"actualTestsExecuted":False}
        task.demand(receipt["sourceBeforeAfterEqual"],"source_drift","Capture source changed before final receipt")
        return fresh(box/"capture.json",task.canonical(receipt),box)
    finally:
        if failed:lease.retain_after_failure()


def validate_capture_receipt(task_descriptor_pin, receipt_pin):
    descriptor=task.read_json(task_descriptor_pin);task.validate_descriptor(descriptor)
    value=task.read_json(receipt_pin)
    task.demand(value.get("protocol")==PROTOCOL and value.get("taskId")==descriptor["taskId"] and value.get("taskDescriptorPin")==task_descriptor_pin
                and value.get("artifactPath")==descriptor["outputArtifacts"][0]["containerPath"] and value.get("sourcePins")==sources()
                and value.get("sourceBeforeAfterEqual") is True and value.get("containerStopped") is True and value.get("cliActorClosureRequired") is True,
                "capture_receipt","Complete source-bound exact data capture graph required")
    owner=task.read_json(value["ownerPin"]); evidence=value["daemonEvidence"]
    layout=task.read_json(value["storageDescriptorPin"]);storage.validate_descriptor(layout)
    box=Path(receipt_pin["path"]).parent
    task.demand(box.parent==Path(layout["directories"]["captures"]) and box.name=="capture-"+value.get("captureNonce","")
                and re.fullmatch("[0-9a-f]{32}",value.get("captureNonce","")) and Path(receipt_pin["path"]).name=="capture.json"
                and value.get("storageOwnerNonce")==layout["ownerNonce"] and type(value.get("actorPid")) is int and value["actorPid"]>0
                and value.get("ownedContainerID")==owner.get("containerID")==evidence.get("containerId")
                and evidence.get("method")=="docker-cp-tar" and value.get("state") in ("regular","absent","directory","symlink","too_large"),
                "capture_owner","Exact storage/task/operation/CID/actor scope required")
    storage.ordinary(box,Path(layout["storePhysical"]))
    task.verify_pin(value["dockerClientPin"],64*1024**2)
    task.demand(Path(value["dockerClientPin"]["path"])==transport.DOCKER and value["dockerClientPin"]["sha256"]==transport.DOCKER_SHA,
                "capture_client","Fixed Docker client source differs")
    argv_prefix=[str(transport.DOCKER),"--host",transport.DOCKER_HOST]
    expected_argv=[argv_prefix+["container","inspect","--size",value["ownedContainerID"]],
                   argv_prefix+["cp",value["ownedContainerID"]+":"+value["artifactPath"],"-"],
                   argv_prefix+["container","inspect","--size",value["ownedContainerID"]]]
    task.demand(isinstance(value["commandRecords"],list) and len(value["commandRecords"])==3,"capture_commands","Exact inspect/transfer/inspect graph required")
    records=[transport.validate_command_record(item,value["actorPid"],i+1,expected_argv[i],box,
              descriptor["outputArtifacts"][0]["maximumBytes"]+65536 if i==1 else 1024**2)
             for i,item in enumerate(value["commandRecords"])]
    task.demand(evidence["beforeInspectPin"]==records[0]["stdoutPin"] and evidence["afterInspectPin"]==records[2]["stdoutPin"]
                and evidence["transferRecordPin"]==value["commandRecords"][1] and records[0]["exitCode"]==records[2]["exitCode"]==0,
                "capture_commands","Inspect/transfer evidence is not a member of the exact actual command graph")
    inspections=[]
    for key in ("beforeInspectPin","afterInspectPin"):
        arr=task.read_json(evidence[key]);task.demand(isinstance(arr,list) and len(arr)==1,"capture_inspect","Exact inspect graph required")
        validate_solver_inspect(arr[0],descriptor,owner)
        inspections.append(arr[0])
    task.demand(inspections[0]==inspections[1],"capture_solver_drift","Stopped solver daemon state changed during transfer")
    transfer=records[1]
    stdout=Path(transfer["stdoutPin"]["path"]).read_bytes();stderr=Path(transfer["stderrPin"]["path"]).read_bytes()
    if value["state"]=="absent":
        task.demand(missing_artifact(transfer["exitCode"],stdout,stderr,value["artifactPath"],value["ownedContainerID"]) and value.get("artifactPin") is None,
                    "capture_absent","Exact raw missing-file evidence required")
    else:
        task.demand(transfer["exitCode"]==0,"capture_transfer","Complete daemon transfer required")
        member,body=parse_artifact_tar(stdout,Path(value["artifactPath"]).name,descriptor["outputArtifacts"][0]["maximumBytes"])
        task.demand(member["state"]==value["state"] and member["memberKind"]==evidence["memberKind"] and member["size"]==evidence["size"],
                    "capture_member","Actual raw TAR/member identity differs")
        if body is not None:
            p=value["artifactPin"];task.verify_pin(p,8*1024**2)
            task.demand(Path(p["path"]).parent==Path(receipt_pin["path"]).parent and Path(p["path"]).name==Path(value["artifactPath"]).name
                        and p["bytes"]==len(body) and p["sha256"]==hashlib.sha256(body).hexdigest(),"capture_artifact","Sealed output differs")
        else:task.demand(value.get("artifactPin") is None,"capture_format","Format failure cannot supply regular bytes")
    storage.validate_instance_closure(value["leaseClosurePin"],layout,value["captureNonce"],value["actorPid"],box)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture",action="store_true",required=True)
    for name in ("task-descriptor","storage-descriptor","owner"):
        parser.add_argument("--"+name,type=Path,required=True);parser.add_argument("--"+name+"-sha256",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();pins={}
    for name in ("task_descriptor","storage_descriptor","owner"):
        p=task.pin(getattr(args,name));task.demand(p["sha256"]==getattr(args,name+"_sha256"),"cli_pin","Explicit CLI input SHA changed");pins[name]=p
    output=capture_artifacts(pins["task_descriptor"],pins["owner"],args.output,task.read_json(pins["storage_descriptor"]),task.pin(transport.DOCKER),pins["storage_descriptor"])
    print(json.dumps({"captureReceiptPin":output,"cliActorClosureRequired":True}))


if __name__ == "__main__":main()
