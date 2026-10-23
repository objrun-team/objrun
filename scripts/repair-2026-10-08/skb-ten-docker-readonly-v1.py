"""Capture exact readonly Docker inventory through the frozen bounded primitive."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import uuid
import skb_artifact_task_v2 as task
import skb_artifact_transport_v2 as transport

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / "docs/repair-2026-10-08/skillsbench-ten-takeover-v1/docker-readonly"


def save(path, value):
    raw = task.canonical(value)
    with path.open("xb") as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    task.demand(path.read_bytes() == raw, "readback", "Readonly evidence fsync/readback failed")
    return task.pin(path)


def main():
    box = HOME / uuid.uuid4().hex
    box.mkdir(parents=True, exist_ok=False)
    plans = json.loads((ROOT / "docs/repair-2026-10-08/skillsbench-ten-artifact-readonly-preflight/selection-v1/private-depot-and-adapter-plan.json").read_bytes())
    image_ids = sorted({x["fixedBase"]["cachedImageId"] for x in plans["solverImagePlans"] if x.get("fixedBase")})
    image_ids.append("sha256:92892771245d31d0b1af4a0c603effbdaf02bf62c1c055081f44a462f5261ced")
    commands = [["version", "--format", "{{json .}}"], ["info", "--format", "{{json .}}"],
                ["image", "inspect", *image_ids], ["ps", "--all", "--no-trunc", "--format", "{{json .}}"]]
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "PATH", "PATHEXT") if k in os.environ}
    env.update({"TEMP": str(box), "TMP": str(box), "TMPDIR": str(box), "PYTHONDONTWRITEBYTECODE": "1"})
    def guard(amount=0):
        task.demand(shutil.disk_usage("F:/").free >= 1024**3 + amount, "readonly_room", "F readonly capture reserve missing")
    records = []
    fault = None
    before = transport.component_pins() + [task.pin(__file__), task.pin(transport.__file__)]
    for serial, args in enumerate(commands, 1):
        argv = [str(transport.DOCKER), "--host", transport.DOCKER_HOST, *args]
        row, out, err = transport.bounded_child(argv, env, box, serial, guard, 30, 2*1024**2)
        record = task.pin(box / ("command-%03d.json" % serial))
        transport.validate_command_record(record, os.getpid(), serial, argv, box, 2*1024**2)
        records.append({"argv": argv, "recordPin": record, "exitCode": row["exitCode"]})
        if row["exitCode"] != 0:
            fault = "readonly_docker_command_failed"; break
    task.demand(before == transport.component_pins() + [task.pin(__file__), task.pin(transport.__file__)], "source_drift", "Readonly native sources changed")
    value = {"protocol": "skillsbench-ten-docker-readonly-v1", "observedAtUtc": datetime.now(timezone.utc).isoformat(),
             "actorPid": os.getpid(), "sourcePins": before, "dockerClientPin": task.pin(transport.DOCKER),
             "records": records, "fault": fault, "volumeFreeBytes": {x: shutil.disk_usage(x + ":/").free for x in ("C", "D", "F")},
             "modelCalls": 0, "DockerMutations": 0, "DOrEWrites": 0,
             "nativeCommandsClosed": True, "paidLockAcquired": False, "paidReady": False,
             "parentActorClosureRequired": True}
    receipt = save(box / "observation.json", value)
    print(json.dumps({"observationPin": receipt, "fault": fault, "commandsCaptured": len(records), "volumeFreeBytes": value["volumeFreeBytes"]}))
    raise SystemExit(1 if fault else 0)


if __name__ == "__main__": main()
