"""Close the exact recorded pre-dispatch build failure; never kills or deletes."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_transport_v2 as transport


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', required=True, type=Path); p.add_argument('--sha256', required=True)
    a = p.parse_args(); run_pin = task.pin(a.run)
    task.demand(run_pin['sha256'] == a.sha256, 'close_pin', 'Exact original build failure required')
    run = task.read_json(run_pin)
    task.demand(run.get('protocol') == 'skillsbench-ten-environment-build-actual-run-v1' and run.get('results') == []
                and run.get('fault', {}).get('kind') == 'build_docker_command', 'close_scope', 'Only the recorded no-environment pre-dispatch failure')
    layout = task.read_json(run['storageDescriptorPin']); storage.validate_descriptor(layout)
    root = Path(layout['storePhysical']); box = Path(run_pin['path']).parent
    storage.ordinary(box, root)
    task.demand(box.parent == Path(layout['directories']['taskmeta']) and box.name.startswith('environment-builds-'), 'close_scope', 'Exact owned failure directory required')
    for pair in run['sourceSnapshots']:
        task.verify_pin(pair['snapshotPin'])
        task.demand(pair['snapshotPin']['sha256'] == pair['originalPin']['sha256']
                    and pair['snapshotPin']['bytes'] == pair['originalPin']['bytes'], 'close_source', 'Executed source snapshot differs')
    children = []
    rows = run['lastCommandRecords']
    task.demand(len(rows) == 2, 'close_commands', 'Exact inspect/legacy-build-failure records required')
    for serial, entry in enumerate(rows, 1):
        record = transport.validate_command_record(entry['recordPin'], run['actorPid'], serial, entry['argv'], box / '3d-scan-calc', 4*1024**2)
        children.append(storage.native_actor_absent(record['pid']))
        if serial == 1: task.demand(entry['argv'][3:5] == ['image','inspect'] and record['exitCode'] == 0, 'close_commands', 'First operation must be readonly base image inspect')
        else:
            stderr = Path(record['stderrPin']['path']).read_text(encoding='utf-8')
            task.demand(record['exitCode'] == 125 and record['stdoutPin']['bytes'] == 0 and entry['argv'][3] == 'build'
                        and 'unknown flag: --progress' in stderr and 'legacy builder is deprecated' in stderr,
                        'close_pre_dispatch', 'Original raw CLI rejection does not prove pre-dispatch')
    actor = storage.native_actor_absent(run['actorPid'])
    lease = task.read_json(run['buildLeasePin'])
    task.demand(lease.get('protocol') == storage.PROTOCOL + '-native-lease' and lease.get('held') is False
                and lease.get('nonce') == layout['ownerNonce'] and lease.get('pid') == run['actorPid']
                and lease.get('root') == str(root) and lease.get('fixtureOnly') is False,
                'close_lease', 'Actual source-bound build lease has not closed')
    result = {'protocol':'skillsbench-build-predispatch-failure-closed-v1', 'buildRunPin':run_pin,
        'storageDescriptorPin':run['storageDescriptorPin'], 'producerObservation':actor, 'childObservations':children,
        'buildLeasePin':run['buildLeasePin'], 'sourcePin':task.pin(__file__), 'querySourcePin':task.pin(storage.__file__),
        'observedAtUtc':datetime.now(timezone.utc).isoformat(), 'ownedClosed':True, 'namespaceRetired':True,
        'futureWritersAuthorized':False, 'ownedStoreObservation':storage.observe_owned_store(layout),
        'modelCalls':0, 'scoreCertificate':False, 'paidLockReleased':False,
        'scope':'Only exact CLI125 unknown-progress pre-dispatch failure and its native actor/children; no successful environment or score'}
    path = box / 'native-closed.json'; raw = task.canonical(result)
    with path.open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
    task.demand(path.read_bytes() == raw, 'close_readback', 'Actual closure record did not read back')
    print(json.dumps({'closurePin':task.pin(path),'ownedClosed':True,'modelCalls':0}))


if __name__ == '__main__': main()
