"""Actual zero-provider initialization of one fresh SkillsBench D owner namespace."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import uuid
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / "docs/repair-2026-10-08/skillsbench-ten-takeover-v1/initializer-runs"


def save(path, value):
    raw = task.canonical(value)
    with path.open("xb") as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    task.demand(path.read_bytes() == raw, "init_readback", "Initialization evidence fsync/readback failed")
    return task.pin(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preparation", required=True, type=Path); p.add_argument("--preparation-sha256", required=True)
    a = p.parse_args()
    preparation_pin = task.pin(a.preparation)
    task.demand(preparation_pin["sha256"] == a.preparation_sha256, "init_preparation", "Exact prepared runtime changed")
    prepared = task.read_json(preparation_pin)
    task.demand(prepared.get("protocol") == "skillsbench-ten-prepared-runtime-v1" and len(prepared.get("taskDescriptorPins", [])) == 10,
                "init_scope", "Only the prospective fixed ten-task SkillsBench namespace")
    for source in prepared["sourcePins"]: task.verify_pin(source, 128*1024**2)
    layout = task.read_json(prepared["storageDescriptorPin"]); storage.validate_descriptor(layout)
    root = Path(layout["storePhysical"])
    task.demand(root == Path(storage.D_PARENT) / layout["ownerNonce"], "init_owner", "Exact newly declared D owner required")
    box = HOME / uuid.uuid4().hex; box.mkdir(parents=True, exist_ok=False)
    sources = [task.pin(__file__), task.pin(task.__file__), task.pin(storage.__file__)]
    free = {volume: shutil.disk_usage(volume + ":/").free for volume in ("C", "D", "F")}
    resources = storage.assess_resources(layout, free, False, initial=True)
    created = []; fault = None; initial_store_pin = None; lease = None; setup_closed = False
    try:
        task.demand(resources["admitted"], "init_resource_guard", "Actual C/D/F resource guard rejected initialization")
        task.demand(not os.path.lexists(root), "init_fresh_owner", "Refuse an existing or unknown owner namespace")
        parent = Path(storage.D_PARENT)
        missing = []
        while not parent.exists():
            missing.append(parent); parent = parent.parent
        storage.ordinary(parent, Path("D:/"))
        for directory in reversed(missing):
            directory.mkdir(exist_ok=False); created.append(str(directory)); storage.ordinary(directory, Path("D:/"))
        root.mkdir(exist_ok=False); created.append(str(root)); storage.ordinary(root, Path("D:/"))
        for directory in layout["directories"].values():
            Path(directory).mkdir(exist_ok=False); created.append(directory); storage.ordinary(Path(directory), root)
        lease = storage.NativeStorageLease(root, layout["ownerNonce"]); lease.path = root / "leases/setup.lock"
        with lease:
            lease.assert_owned()
            intent = save(root / "taskmeta/initial-store-intent.json", {"protocol": "skb-ten-D-store-initialization-v2-intent",
                "ownerNonce": layout["ownerNonce"], "creatorPid": os.getpid(), "preparationPin": preparation_pin,
                "descriptorPin": prepared["storageDescriptorPin"], "sourcePins": sources, "createdDirectories": created,
                "storeLogical": layout["storeLogical"], "storePhysical": layout["storePhysical"],
                "DockerOperations": 0, "modelCalls": 0, "canonicalPaidLockAcquired": False})
        lease_pin = task.pin(lease.path); final = task.read_json(lease_pin)
        task.demand(final.get("held") is False and final.get("pid") == os.getpid() and final.get("nonce") == layout["ownerNonce"]
                    and final.get("root") == str(root), "init_setup_close", "Actual setup native handle did not close")
        setup_closed = True
        initial_store_pin = save(root / "taskmeta/initial-store.json", {"protocol": "skb-ten-D-store-initialization-v2",
            "ownerNonce": layout["ownerNonce"], "creatorPid": os.getpid(), "preparationPin": preparation_pin,
            "storageDescriptorPin": prepared["storageDescriptorPin"], "sourcePins": sources, "intentPin": intent,
            "setupClosedLeasePin": lease_pin, "setupNativeHandleClosed": True, "actualDirectoryIdentityVerified": True,
            "resourceObservation": resources, "initializedAtUtc": datetime.now(timezone.utc).isoformat(),
            "ownedStoreObservation": storage.observe_owned_store(layout), "modelCalls": 0, "DockerOperations": 0,
            "paidLockAcquired": False, "paidReady": False, "parentActorClosureRequired": True})
    except BaseException as error:
        fault = {"type": type(error).__name__, "kind": getattr(error, "kind", None)}
    task.demand(sources == [task.pin(__file__), task.pin(task.__file__), task.pin(storage.__file__)], "init_source_drift", "Initializer source changed")
    value = {"protocol": "skb-ten-D-initializer-actual-run-v2", "actorPid": os.getpid(), "sourcePins": sources,
        "preparationPin": preparation_pin, "storageDescriptorPin": prepared["storageDescriptorPin"],
        "resourceObservation": resources, "volumeFreeBytes": free, "createdDirectories": created,
        "initialStorePin": initial_store_pin, "setupNativeHandleClosed": setup_closed,
        "fault": fault, "completedAtUtc": datetime.now(timezone.utc).isoformat(),
        "DOrEWrites": len(created), "DockerOperations": 0, "modelCalls": 0, "canonicalPaidLockAcquired": False,
        "paidReady": False, "parentActorClosureRequired": True}
    run_pin = save(box / "run.json", value)
    print(json.dumps({"runPin": run_pin, "initialStorePin": initial_store_pin, "fault": fault,
                      "resourceDeficitBytes": resources["deficitBytes"], "DOrEWrites": len(created), "modelCalls": 0}))
    raise SystemExit(1 if fault else 0)


if __name__ == "__main__": main()
