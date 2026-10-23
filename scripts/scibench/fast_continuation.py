"""Continue the same registry and protocol on owned local NVMe after drain."""
from pathlib import Path
import argparse,fcntl,hashlib,json,os,sqlite3,tarfile,time

ap=argparse.ArgumentParser();ap.add_argument('--archive-sha',required=True);a=ap.parse_args()
base=Path('/mnt/aliyunsb/pingxingwang/tgengin-bench');old=base/'scibench-formal-20261016-v2-c32'
fast=Path('/var/tmp/tgengin-scibench-20261016');new=fast/'scibench-formal-20261016-v3-c32'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text())
assert not new.exists(),'NeverOverwriteSuccessor'
archive=old/(old.name+'-results.tar.gz');assert sha(archive)==a.archive_sha
s=read(old/'outputs/canonical/status.json');previous=read(old/'package/continuation.json')
assert not s['active'] and not Path('/proc',str(s['pid']),'cmdline').exists()
assert read(old/'ops/switch32/guard.json')['phase']=='drain_complete'
checkpoint=read(old/'ops/switch32/guard.json')
assert checkpoint['priorConsecutiveProviderFaults']==0,'ProviderFaultGuardStillTripped'
lock=open(previous['globalLockPath'],'a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
db=sqlite3.connect(previous['registryPath']);db.row_factory=sqlite3.Row
assert db.execute("SELECT count(*) FROM tasks WHERE state='started'").fetchone()[0]==0
new.mkdir(mode=0o700)
with tarfile.open(archive) as tar:
    chosen=[]
    for member in tar.getmembers():
        name=member.name
        if name.startswith(('package/','data/','outputs/canonical/calls/','outputs/canonical/tasks/','outputs/canonical/results/')) or name in ['package','data','outputs/canonical/controls.json','outputs/canonical/prices.json']:
            chosen.append(member)
    tar.extractall(new,members=chosen,filter='data')
    (new/'provenance').mkdir()
    # Retain the preceding provenance, logs, controls, archive and registry snapshot.
    for member in tar.getmembers():
        if member.name.startswith(('provenance/','ops/','control/')) or member.name in ['outputs/canonical/status.json','outputs/canonical/launch.json','outputs/canonical/controller.stdout.log','outputs/canonical/controller.stderr.log']:
            member.name='provenance/predecessor/'+member.name
            tar.extract(member,new,filter='data')
(new/'bin').mkdir();(new/'bin/bun').symlink_to((old/'bin/bun').resolve())
supplement=old/(old.name+'-cutover-supplement.tar.gz')
with tarfile.open(supplement) as tar:
    for member in tar.getmembers():
        member.name='provenance/predecessor-cutover/'+member.name;tar.extract(member,new,filter='data')
deps=fast/'runtime-v1/node_modules';assert deps.exists()
(new/'package/engine/app/node_modules').symlink_to(deps,target_is_directory=True)
prior_files={x['path']:x for x in read(old/'provenance/origin-files.json')}
origins=[]
for top in ['calls','tasks','results']:
    for p in (new/'outputs/canonical'/top).rglob('*'):
        if not p.is_file():continue
        rel=p.relative_to(new).as_posix();digest=sha(p)
        if rel in prior_files:
            item=prior_files[rel];assert digest==item['sha256']
        else:item={'path':rel,'originRoot':str(old),'originPath':str(old/rel),'sha256':digest}
        origins.append(item)
(new/'provenance/origin-files.json').write_text(json.dumps(origins,indent=2)+'\n')
records=list((new/'outputs/canonical/results').rglob('*.json'))
db.execute('BEGIN IMMEDIATE')
for p in records:
    row=read(p);registered=db.execute('SELECT * FROM tasks WHERE arm=? AND id=?',(row['arm'],row['id'])).fetchone()
    assert registered and registered['state'] in ['inherited','complete'] and registered['resultSha256']==sha(p)
    if registered['originRoot'] is None:
        db.execute('UPDATE tasks SET originRoot=?,originResult=? WHERE arm=? AND id=?',(str(old),str(old/p.relative_to(new)),row['arm'],row['id']))
for p in (new/'outputs/canonical/calls').rglob('dispatch.json'):
    rel=p.relative_to(new).as_posix();entry=db.execute('SELECT * FROM dispatch_origins WHERE path=?',(rel,)).fetchone()
    if entry:assert entry['sha256']==sha(p)
    else:db.execute('INSERT INTO dispatch_origins VALUES(?,?,?,?)',(rel,str(old),str(old/rel),sha(p)))
db.commit()
assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==1664
assert db.execute("SELECT count(*) FROM tasks WHERE state IN ('inherited','complete')").fetchone()[0]==len(records)
pending_baseline={x[0] for x in db.execute("SELECT id FROM tasks WHERE arm='baseline' AND state='pending'")}
catalog=read(new/'data'/read(new/'package/experiment.json')['catalog'])
gate=next(x['id'] for x in catalog if x['id'] in pending_baseline)
db.close()
receipts=[read(p) for p in (new/'outputs/canonical/calls').rglob('receipt.json')]
assert all(p.with_name('receipt.json').exists() for p in (new/'outputs/canonical/calls').rglob('dispatch.json'))
m={**previous,'legacyRoot':str(old),'legacyPid':s['pid'],'legacyArchiveSha256':a.archive_sha,'originManifest':str(new/'provenance/origin-files.json'),'inheritedRecords':len(records),'pendingRecords':1664-len(records),'inheritedModelCalls':len(receipts),'inheritedKnownUsd':sum(x['actualCostUsd'] or 0 for x in receipts),'inheritedUnknownCount':sum(x['unknownCost'] for x in receipts),'inheritedUnknownReserveUsd':sum(x['upperBoundUsd'] for x in receipts if x['unknownCost']),'storage':'owned NVMe ext4; runtime dependency bytes retained','lineage':[{'root':previous['legacyRoot'],'sha256':previous['legacyArchiveSha256']},{'root':str(old),'sha256':a.archive_sha}],'sameGlobalRegistry':True,'priorConsecutiveProviderFaults':checkpoint['priorConsecutiveProviderFaults'],'priorStopReason':s['stopReason'],'admissionGate':{'arm':'baseline','id':gate,'countsInside1664':True,'maxCandidates':1,'purpose':'Validate repaired control plane with the next unstarted baseline before opening32; never rerun it'}}
(new/'package/continuation.json').write_text(json.dumps(m,indent=2)+'\n')
launcher=new/'package/continuation_launcher.py';text=launcher.read_text();needle="state NOT IN ('pending','inherited')";assert text.count(needle)==1
launcher.write_text(text.replace(needle,"state NOT IN ('pending','inherited','complete')"))
controller=new/'package/run.ts';text=controller.read_text()
anchor="const continuation=read(join(HERE,'continuation.json'));"
assert text.count(anchor)==1;text=text.replace(anchor,anchor+"\nconsecutiveProviderFaults=continuation.priorConsecutiveProviderFaults??0;")
anchor="  stage='running';status();"
gate_code="""  if(continuation.admissionGate){
   const gate=continuation.admissionGate;stage='admission_gate';status();
   const task=catalog.find((t:any)=>t.id===gate.id);if(!task)throw Error('AdmissionGateIdentityMissing');
   const r=await execute(task,gate.arm);
   save(join(OUT,'admission-gate.json'),{arm:gate.arm,id:gate.id,countsInside1664:true,valid:r?.grade?.valid??false,atUtc:new Date().toISOString()});
   if(!r?.grade?.valid){stage='needs_attention';stopReason=stopReason??'AdmissionGateFailed';return;}
  }
"""
assert text.count(anchor)==1;controller.write_text(text.replace(anchor,gate_code+anchor))
pins=read(old/'outputs/canonical/source-pins.json')['files'];changed=[]
for x in pins:
    p=Path(x['path']);assert sha(p)==x['sha256'];rel=p.relative_to(old)
    if sha(new/rel)!=x['sha256']:changed.append(rel.as_posix())
assert set(changed)=={'package/continuation.json','package/continuation_launcher.py','package/run.ts'},changed
(new/'provenance/PROTOCOL_DIFF.json').write_text(json.dumps({'allPassed':True,'changedPinnedFiles':changed,'sameSolverAndModel':True,'sameExperimentConfig':True,'onlyStorageAndOuterAdmissionChanged':True,'gateConsumesOnePreviouslyUnstartedBaselineInside1664':True,'globalRegistryPreserved':True,'legacySourcePinsUnchanged':True},indent=2)+'\n')
(new/'provenance/BUILD.json').write_text(json.dumps(m,indent=2)+'\n')
print(json.dumps(m))
