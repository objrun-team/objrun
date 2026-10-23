"""Freeze portable private build context and ten prospective task descriptors."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_transport_v2 as transport

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / "docs/repair-2026-10-08/skillsbench-ten-takeover-v1/runtime-preparations"
UBUNTU = "ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3"


def save(path, raw):
    with path.open("xb") as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    task.demand(path.read_bytes() == raw, "readback", "Prepared runtime bytes differ after fsync")
    return task.pin(path)


def json_file(path, value): return save(path, task.canonical(value))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--depot", required=True, type=Path); p.add_argument("--depot-sha256", required=True)
    a = p.parse_args()
    depot_pin = task.pin(a.depot)
    task.demand(depot_pin["sha256"] == a.depot_sha256, "depot_pin", "Explicit actual wheel depot changed")
    depot = task.read_json(depot_pin)
    task.demand(depot.get("protocol") == "skillsbench-linux-private-wheel-depot-v1" and depot.get("downloadComplete") is True
                and depot.get("fault") is None and depot.get("dependencies") == task.REQUIREMENTS
                and len(depot.get("commandRecordPins", [])) == 1, "depot_graph", "Complete actual download required")
    for item in depot["sourcePins"]: task.verify_pin(item, 128*1024**2)
    for row in depot["wheels"]:
        task.verify_pin(row["wheelPin"], 64*1024**2); upstream = task.read_json(row["upstreamJsonPin"], 4*1024**2)
        links = [x for x in upstream["urls"] if x["filename"] == Path(row["wheelPin"]["path"]).name]
        task.demand(len(links) == 1 and links[0]["digests"]["sha256"] == row["wheelPin"]["sha256"] == row["publishedSha256"]
                    and links[0]["size"] == row["wheelPin"]["bytes"] and links[0]["url"] == row["downloadUrl"], "depot_digest", "Official wheel digest/source graph differs")
    task.verify_pin(depot["requirementsLockPin"])
    box = HOME / uuid.uuid4().hex; box.mkdir(parents=True, exist_ok=False)
    context = box / "private-image-context"; context.mkdir()
    wheels = context / "wheels"; wheels.mkdir()
    copied = []
    for row in depot["wheels"]:
        pin = row["wheelPin"]
        dest = wheels / Path(pin["path"]).name
        copy = save(dest, Path(pin["path"]).read_bytes())
        task.demand(copy["sha256"] == pin["sha256"] and copy["bytes"] == pin["bytes"], "wheel_copy", "Private context wheel differs")
        copied.append(copy)
    lock = save(context / "requirements.lock.txt", Path(depot["requirementsLockPin"]["path"]).read_bytes())
    runner = save(context / "private_eval.py", Path(__file__).with_name("skb_artifact_private_eval_v2.py").read_bytes())
    manifest = json_file(context / "trusted-inputs.json", task.trusted_input_manifest())
    dockerfile = save(context / "Dockerfile", ("FROM " + UBUNTU + "\n"
        "ENV DEBIAN_FRONTEND=noninteractive\n"
        "RUN apt-get update && apt-get install -y --no-install-recommends python3.12 python3.12-venv python3-pip poppler-utils ca-certificates && rm -rf /var/lib/apt/lists/*\n"
        "COPY wheels /opt/objrun/wheels\n"
        "COPY requirements.lock.txt /opt/objrun/requirements.lock.txt\n"
        "RUN python3.12 -m venv --copies /opt/objrun-verifier && /opt/objrun-verifier/bin/python -m pip install --no-cache-dir --no-index --find-links=/opt/objrun/wheels --require-hashes -r /opt/objrun/requirements.lock.txt && /opt/objrun-verifier/bin/python -m pip check && rm -rf /opt/objrun/wheels\n"
        "COPY private_eval.py /opt/objrun/private_eval.py\n"
        "COPY trusted-inputs.json /opt/objrun/trusted-inputs.json\n"
        "RUN mkdir -p /app/workspace /verifier /logs/verifier && chmod -R a-w /opt/objrun /opt/objrun-verifier\n"
        "WORKDIR /\n").encode())
    nonce = uuid.uuid4().hex
    layout = storage.descriptor(nonce)
    storage_pin = json_file(box / "storage-descriptor.json", layout)
    task_folder = box / "task-descriptors"; task_folder.mkdir()
    descriptors = [json_file(task_folder / (tid + ".json"), task.descriptor(tid)) for tid in task.TASK_IDS]
    original = []
    for tid in task.TASK_IDS: original += task.original_sources(tid)
    sources = [task.pin(__file__), task.pin(task.__file__), task.pin(storage.__file__), task.pin(transport.__file__),
               task.pin(Path(__file__).with_name("skb_artifact_private_eval_v2.py"))] + transport.component_pins()
    try:
        absence = storage.native_actor_absent(depot["actorPid"])
        depot_closure = json_file(box / "depot-producer-closure.json", {"protocol": "skillsbench-native-producer-absence-v1",
            "producerPid": depot["actorPid"], "producerReceiptPin": depot_pin, "querySourcePin": task.pin(__file__),
            "nativeQuerySourcePin": task.pin(storage.__file__), "observation": absence, "observedAtUtc": datetime.now(timezone.utc).isoformat(),
            "producerClosed": True, "modelCalls": 0, "paidLockReleased": False})
    except storage.StorageFault:
        depot_closure = None
    free = {x: shutil.disk_usage(x + ":/").free for x in ("C", "D", "F")}
    resource = storage.assess_resources(layout, free, False, initial=True)
    value = {"protocol": "skillsbench-ten-prepared-runtime-v1", "preparedAtUtc": datetime.now(timezone.utc).isoformat(),
             "actorPid": os.getpid(), "sourcePins": sources, "wheelDepotPin": depot_pin, "depotProducerClosurePin": depot_closure,
             "privateImageContext": str(context), "privateContextPins": [dockerfile, lock, runner, manifest, *copied],
             "privateRunnerPin": task.pin(Path(__file__).with_name("skb_artifact_private_eval_v2.py")), "bakedRunnerPin": runner,
             "trustedManifestSha256": manifest["sha256"], "dependencies": task.REQUIREMENTS,
             "resolvedLockedPackages": [{"name": x["normalizedName"], "version": x["version"]} for x in depot["wheels"]],
             "markerResolutionPolicy": "Host Windows pip marker evaluation with explicit Linux wheel ABI target; all resolved21 distributions are explicitly installed and locked, including colorama/tzdata. Actual Linux pip check and import validation remain required.",
             "storageDescriptorPin": storage_pin, "taskDescriptorPins": descriptors, "originalSourcePins": original,
             "fixedPrivateBase": UBUNTU, "resourceObservation": resource, "volumeFreeBytes": free,
             "originalTestRunnersArchivedByPin": True, "originalTestSourceChanged": False,
             "privateImageBuilt": False, "actualTestCollections": 0, "actualColdControls": 0, "DockerOperations": 0,
             "DOrEWrites": 0, "modelCalls": 0, "paidReady": False, "parentActorClosureRequired": True}
    output = json_file(box / "preparation.json", value)
    print(json.dumps({"preparationPin": output, "taskDescriptors": len(descriptors), "copiedWheels": len(copied),
                      "depotProducerClosurePin": depot_closure, "resourceAdmitted": resource["admitted"],
                      "resourceDeficitBytes": resource["deficitBytes"], "paidReady": False, "modelCalls": 0}))


if __name__ == "__main__": main()
