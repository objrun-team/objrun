"""Fresh three-owner geometry and small executed-source snapshot for fast pilot."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import uuid
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
from skb_artifact_ram_executor_v2 import fresh


def main():
    p=argparse.ArgumentParser();p.add_argument('--collections',type=Path,required=True);p.add_argument('--sha256',required=True);a=p.parse_args()
    cp=task.pin(a.collections.resolve());task.demand(cp['sha256']==a.sha256,'fast_collection_pin','Exact existing actual ten-task collection required');c=task.read_json(cp)
    task.demand(c['actualDistinctTaskCollections']==10,'fast_collection_scope','Fixed ten-task original collection required')
    home=task.REPO/'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/fast-preparations-v3'/uuid.uuid4().hex;home.mkdir(parents=True)
    layouts=[];initial=[]
    for i in range(3):
        box=home/str(i);box.mkdir();lp=fresh(box/'storage-descriptor.json',task.canonical(storage.descriptor(uuid.uuid4().hex)),task.REPO)
        prep=fresh(box/'preparation.json',task.canonical({'protocol':'skillsbench-ten-prepared-runtime-v1','taskDescriptorPins':c['taskDescriptorPins'],
            'storageDescriptorPin':lp,'sourcePins':[task.pin(__file__),task.pin(task.__file__),task.pin(storage.__file__)],'modelCalls':0}),task.REPO)
        argv=['D:/ProgramData/anaconda3/python.exe','-B','-X','utf8',str(Path(__file__).with_name('skb-artifact-D-init-v2.py')),'--preparation',prep['path'],'--preparation-sha256',prep['sha256']]
        child=subprocess.run(argv,cwd=task.REPO,capture_output=True,timeout=30)
        fresh(box/'initializer-caller.json',task.canonical({'argv':argv,'exitCode':child.returncode,'stdout':child.stdout.decode(),'stderr':child.stderr.decode(),'modelCalls':0}),task.REPO)
        task.demand(child.returncode==0,'fast_fresh_store','Actual fresh scoped initializer failed')
        out=json.loads(child.stdout);layouts.append(lp);initial.append(out['initialStorePin'])
    # Reuse existing frozen image/depot/runtime proofs. Copy actual bench/core
    # source bytes once, without another all-history or whole dependency scan.
    scripts=Path(__file__).parent;source_paths=set(scripts.glob('skb*.ts'))|set(scripts.glob('skb*.py'))
    for name in ('benchmark-inference.ts','benchmark-provider.ts','benchmark-usd-cash.ts','openrouter-paid-admission.ts','tb-engine.ts','tb-nginx-contract.ts','tb-tool-gateway.ts','campaign-contract.ts','campaign-journal.ts','scientific-journal-proxy.ts',
        'cny-cash-shadow-v2.ts','paid-resource-proof-v2.ts','paid-resource-admission-v2.ts','jpg-paid-resource-admission-v1.ts','jpg-D-paid-resource-admission-v1.ts',
        'jpg_private_ram_executor.py','jpg_private_ram_profile.py','jpg_d_storage_profile.py','skb-jpg-native-python.json'):
        source_paths.add(scripts/name)
    source_paths.update((task.REPO/'app/src').rglob('*.ts'))
    source_paths.update(p for p in (task.REPO/'package.json',task.REPO/'app/package.json',task.REPO/'bun.lock') if p.exists())
    root=Path(task.read_json(layouts[0])['storePhysical']);snap=root/'source/fast-executed';snap.mkdir();rows=[]
    for path in sorted(source_paths,key=str):
        source=task.pin(path);relative=path.relative_to(task.REPO);dest=snap/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        saved=fresh(dest,path.read_bytes(),root);rows.append({'originalPin':source,'snapshotPin':saved})
    snapshot=fresh(root/'source/fast-source-manifest.json',task.canonical({'protocol':'skillsbench-fast-source-snapshot-v3','files':rows,'modelCalls':0,
        'fullDependencyCertificationPending':True,'originalImageDepotProofsReused':True}),root)
    result=fresh(home/'inputs.json',task.canonical({'collectionIndexPin':cp,'taskDescriptorPins':c['taskDescriptorPins'],'storageDescriptorPin':layouts[0],
        'slotStorageDescriptorPins':layouts[1:],'initialStorePins':initial,'sourceSnapshotPin':snapshot,'sourcePins':[x['originalPin'] for x in rows],
        'preparedAtUtc':datetime.now(timezone.utc).isoformat(),'modelCalls':0,'concurrency':2}),task.REPO)
    print(json.dumps({'fastInputsPin':result,'modelCalls':0}),flush=True)


if __name__=='__main__':main()
