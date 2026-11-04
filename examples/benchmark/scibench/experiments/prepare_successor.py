"""Seal/reuse a closed NVMe epoch; never re-run a result or reset a task budget."""
from pathlib import Path
import argparse,fcntl,hashlib,json,os,re,sqlite3,tarfile,time

BASE=Path('/var/tmp/tgengin-scibench-20261016')
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def alive(pid,entry):
    p=Path('/proc',str(pid),'cmdline');return p.exists() and str(entry).encode() in p.read_bytes()
def write_once(p,v):
    text=json.dumps(v,indent=2)+'\n'
    if p.exists():assert read(p)==v,'ExistingDifferentCheckpoint';return
    p.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write(text);f.flush();os.fsync(f.fileno())
def scope(name):
    match=re.fullmatch(r'scibench-formal-20261016-v(\d+)-c32',name);assert match and int(match[1])>=3
    root=BASE/name;assert root.resolve().parent==BASE
    return root,int(match[1])
def inspect(old):
    o=old/'outputs/canonical';s=read(o/'status.json');m=read(old/'package/continuation.json')
    assert not s['active'],'ActiveTasksRemain'
    assert not alive(s['pid'],old/'package/run.ts'),'ControllerStillLive'
    assert not alive(read(o/'grader-process.json')['pid'],old/'package/stand.py'),'GraderStillLive'
    assert all(sha(Path(x['path']))==x['sha256'] for x in read(o/'source-pins.json')['files']),'SourcePinMismatch'
    assert all(p.with_name('receipt.json').exists() for p in (o/'calls').rglob('dispatch.json')),'UnreceiptedDispatch'
    assert all((o/'results'/p.parent.parent.name/(p.parent.name+'.json')).exists() for p in (o/'tasks').glob('*/*/started.json')),'UnfinishedTask'
    for p in (o/'tasks').glob('*/*/engine-process.json'):
        pid=read(p)['pid'];e=Path('/proc',str(pid),'environ')
        if e.exists():assert b'TGENGIN_CONFIG='+str(p.parent/'engine/config.yaml').encode() not in e.read_bytes().split(b'\0'),'OwnedNativeStillLive'
    db=sqlite3.connect(m['registryPath']);assert not db.execute("SELECT count(*) FROM tasks WHERE state='started'").fetchone()[0]
    records=sorted([read(p) for p in (o/'results').rglob('*.json')],key=lambda x:x['completedAtUtc'])
    count=0;last_threshold='';last_native_valid=''
    for row in records:
        if str(row.get('error','')).startswith('Error: ProviderFault:'):
            count+=1
            if count>=3:last_threshold=row['completedAtUtc']
        elif row['grade'].get('valid'):count=0
        if row['arm']=='objrun' and row['grade'].get('valid'):last_native_valid=row['completedAtUtc']
    allowed=s['stopReason']=='RepeatedProviderFaults' and count<3 and last_native_valid>last_threshold
    gate=o/'admission-gate.json'
    if not gate.exists() or not read(gate)['valid']:allowed=False
    return s,m,db,records,count,allowed,last_native_valid,last_threshold

ap=argparse.ArgumentParser();ap.add_argument('action',choices=['seal','build']);ap.add_argument('--previous',required=True);ap.add_argument('--archive-sha');ap.add_argument('--fixture-base',type=Path);a=ap.parse_args()
if a.fixture_base:
    fixture=a.fixture_base.resolve();assert fixture.is_relative_to(BASE/'fixtures') and fixture.name.startswith('successor-fixture-')
    BASE=fixture
old,version=scope(a.previous);new=BASE/f'scibench-formal-20261016-v{version+1}-c32'
s,m,db,records,counter,allowed,last_valid,last_threshold=inspect(old)
lease=open(m['globalLockPath'],'a+');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
if a.action=='seal':
    assert len(records)<1664,'UseFinalRetrievalForCompletedExperiment'
    backup=old/'provenance/global-registry-cutover.sqlite'
    if not backup.exists():
        dst=sqlite3.connect(backup);db.backup(dst);dst.close()
    check=sqlite3.connect('file:'+str(backup)+'?mode=ro',uri=True)
    assert list(check.execute('SELECT * FROM tasks ORDER BY arm,id'))==list(db.execute('SELECT * FROM tasks ORDER BY arm,id'));check.close()
    checkpoint={'phase':'drain_complete','mode':'original ProviderFault admission stop; all original task clocks exhausted or completed','controllerPid':s['pid'],'completedRecords':len(records),'sourcePinsUnchanged':True,'allStartsTerminal':True,'allDispatchesReceipted':True,'priorConsecutiveProviderFaults':counter,'priorStopReason':s['stopReason'],'safeToResumePendingOnly':allowed,'lastValidNativeAtUtc':last_valid,'lastProviderFaultThresholdAtUtc':last_threshold,'successorRoot':str(new)}
    write_once(old/'ops/switch32/guard.json',checkpoint)
    write_once(old/'outputs/canonical/runner-lock.json',{'pid':0,'state':'retired_controller','successorRoot':str(new),'globalRegistry':m['registryPath']})
    print(json.dumps(checkpoint));db.close();raise SystemExit(0)

assert allowed,'ProviderHasNotReestablishedNativeSuccess: preserve stop; no automatic rearm'
assert a.archive_sha and not new.exists(),'ArchiveRequiredOrExistingSuccessor'
checkpoint=read(old/'ops/switch32/guard.json');assert checkpoint['safeToResumePendingOnly']
archive=old/(old.name+'-results.tar.gz');assert sha(archive)==a.archive_sha,'ArchiveMismatch'
new.mkdir(mode=0o700)
with tarfile.open(archive) as tar:
    for member in tar.getmembers():
        name=member.name
        if name.startswith(('package/','data/','outputs/canonical/calls/','outputs/canonical/tasks/','outputs/canonical/results/')) or name in ['package','data','outputs/canonical/controls.json','outputs/canonical/prices.json']:
            tar.extract(member,new,filter='data')
        elif name.startswith(('provenance/','ops/','control/')) or name in ['outputs/canonical/status.json','outputs/canonical/launch.json','outputs/canonical/controller.stdout.log','outputs/canonical/controller.stderr.log']:
            member.name='provenance/predecessor/'+name;tar.extract(member,new,filter='data')
(new/'bin').mkdir();(new/'bin/bun').symlink_to((old/'bin/bun').resolve())
(new/'package/engine/app/node_modules').symlink_to((old/'package/engine/app/node_modules').resolve(),target_is_directory=True)
prior={x['path']:x for x in read(old/'provenance/origin-files.json')};origins=[]
for top in ['calls','tasks','results']:
    for p in (new/'outputs/canonical'/top).rglob('*'):
        if not p.is_file():continue
        rel=p.relative_to(new).as_posix();digest=sha(p)
        x=prior.get(rel,{'path':rel,'originRoot':str(old),'originPath':str(old/rel),'sha256':digest});assert digest==x['sha256'];origins.append(x)
(new/'provenance/origin-files.json').write_text(json.dumps(origins,indent=2)+'\n')
db.execute('BEGIN IMMEDIATE')
for row in records:
    rel=Path('outputs/canonical/results')/row['arm']/(row['id']+'.json');entry=db.execute('SELECT state,resultSha256,originRoot FROM tasks WHERE arm=? AND id=?',(row['arm'],row['id'])).fetchone()
    assert entry[0] in ['inherited','complete'] and entry[1]==sha(new/rel)
    if entry[2] is None:db.execute('UPDATE tasks SET originRoot=?,originResult=? WHERE arm=? AND id=?',(str(old),str(old/rel),row['arm'],row['id']))
for p in (new/'outputs/canonical/calls').rglob('dispatch.json'):
    rel=p.relative_to(new).as_posix();entry=db.execute('SELECT sha256 FROM dispatch_origins WHERE path=?',(rel,)).fetchone()
    if entry:assert entry[0]==sha(p)
    else:db.execute('INSERT INTO dispatch_origins VALUES(?,?,?,?)',(rel,str(old),str(old/rel),sha(p)))
db.commit();pending=set(db.execute("SELECT arm,id FROM tasks WHERE state='pending'"));db.close()
catalog=read(new/'data'/read(new/'package/experiment.json')['catalog']);gate=None
for arm in ['objrun','baseline','independent','binary']:
    for task in catalog:
        if (arm,task['id']) in pending:gate={'arm':arm,'id':task['id'],'countsInside1664':True,'purpose':'One unstarted native transport health gate before reopening32; no repeat of a result'};break
    if gate:break
assert gate
receipts=[read(p) for p in (new/'outputs/canonical/calls').rglob('receipt.json')]
manifest={**m,'legacyRoot':str(old),'legacyPid':s['pid'],'legacyArchiveSha256':a.archive_sha,'originManifest':str(new/'provenance/origin-files.json'),'inheritedRecords':len(records),'pendingRecords':1664-len(records),'inheritedModelCalls':len(receipts),'inheritedKnownUsd':sum(x['actualCostUsd'] or 0 for x in receipts),'inheritedUnknownCount':sum(x['unknownCost'] for x in receipts),'inheritedUnknownReserveUsd':sum(x['upperBoundUsd'] for x in receipts if x['unknownCost']),'priorConsecutiveProviderFaults':counter,'priorStopReason':s['stopReason'],'admissionGate':gate,'lineage':m['lineage']+[{'root':str(old),'sha256':a.archive_sha}]}
(new/'package/continuation.json').write_text(json.dumps(manifest,indent=2)+'\n')
changed=[]
for x in read(old/'outputs/canonical/source-pins.json')['files']:
    rel=Path(x['path']).relative_to(old)
    if sha(new/rel)!=x['sha256']:changed.append(rel.as_posix())
assert changed==['package/continuation.json'],changed
(new/'ops').mkdir();tool=new/'ops/continuation_snapshot.py';tool.write_bytes((old/'ops/continuation_snapshot.py').read_bytes())
(new/'ops/tool-pins.json').write_text(json.dumps({'files':[{'path':str(tool),'sha256':sha(tool)}]},indent=2)+'\n')
(new/'provenance/BUILD.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest))
