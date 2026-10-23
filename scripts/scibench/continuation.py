"""Build an isolated outer-scheduler continuation after a verified legacy drain."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,sqlite3,time

sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text())

REGISTRY_TS=r'''
// Outer scheduling only. Solver modules and their clocks/retries are unchanged.
import {Database as RegistryDatabase} from 'bun:sqlite';
const continuation=read(join(HERE,'continuation.json'));
const registry=new RegistryDatabase(continuation.registryPath,{readwrite:true,create:false});
registry.exec('PRAGMA busy_timeout=10000');
const drainPath=join(ROOT,'control/drain.json');
function oldOwnerLive(){
 const p='/proc/'+continuation.legacyPid+'/cmdline';
 return existsSync(p)&&readFileSync(p).includes(Buffer.from(continuation.legacyRoot+'/package/run.ts'));
}
function schedulerDrain(reason:string){stopReason=stopReason??reason;}
process.on('SIGTERM',()=>schedulerDrain('OperatorDrain:SIGTERM'));
process.on('SIGINT',()=>schedulerDrain('OperatorDrain:SIGINT'));
async function execute(task:any,arm:string){
 const resultPath=join(OUT,'results',arm,task.id+'.json');
 const row:any=registry.query('SELECT * FROM tasks WHERE arm=? AND id=?').get(arm,task.id);
 if(!row||row.promptSha256!==hash(task.prompt+suffix))throw Error('GlobalIdentityMismatch:'+arm+'/'+task.id);
 if(existsSync(resultPath)){
  if(!['inherited','complete'].includes(row.state)||row.resultSha256!==hash(readFileSync(resultPath)))throw Error('GlobalResultMismatch:'+arm+'/'+task.id);
  return await executeOne(task,arm);
 }
 if(oldOwnerLive())throw Error('LegacyOwnerStillLive');
 if(read(continuation.legacyRoot+'/ops/switch32/guard.json').phase!=='drain_complete')throw Error('LegacyDrainNotComplete');
 if(existsSync(drainPath)){schedulerDrain('OperatorDrain:control-file');return;}
 if(existsSync(join(OUT,'tasks',arm,task.id,'started.json')))throw Error('UnfinishedTaskRequiresRecovery:'+arm+'/'+task.id);
 const claim=registry.query("UPDATE tasks SET state='started',ownerPid=?,ownerRoot=?,claimedAtUtc=? WHERE arm=? AND id=? AND state='pending'").run(process.pid,ROOT,new Date().toISOString(),arm,task.id);
 if(claim.changes!==1)throw Error('GlobalAdmissionConflict:'+arm+'/'+task.id);
 try{
  const r=await executeOne(task,arm);
  if(!existsSync(resultPath))throw Error('ClaimWithoutTerminalRecord:'+arm+'/'+task.id);
  const done=registry.query("UPDATE tasks SET state='complete',resultSha256=?,completedAtUtc=? WHERE arm=? AND id=? AND state='started' AND ownerPid=? AND ownerRoot=?").run(hash(readFileSync(resultPath)),new Date().toISOString(),arm,task.id,process.pid,ROOT);
  if(done.changes!==1)throw Error('GlobalCompletionConflict:'+arm+'/'+task.id);
  return r;
 }catch(e){
  registry.query("UPDATE tasks SET error=? WHERE arm=? AND id=? AND ownerPid=?").run(String(e),arm,task.id,process.pid);
  throw e;
 }
}
'''

def transform(source):
    assert source.count('async function execute(task:any,arm:string){')==1
    source=source.replace('async function execute(task:any,arm:string){','async function executeOne(task:any,arm:string){')
    needle="const rows=()=>walk(join(OUT,'results')).filter(p=>p.endsWith('.json')).map(read);"
    assert source.count(needle)==1;source=source.replace(needle,needle+'\n'+REGISTRY_TS)
    old="await Promise.all(Array.from({length:cfg.concurrency},async()=>{while(cursor<jobs.length&&!stopReason){const j=jobs[cursor++];await execute(j.task,j.arm);}}));"
    new="""await Promise.all(Array.from({length:cfg.concurrency},async()=>{
   while(cursor<jobs.length&&!stopReason){
    if(existsSync(drainPath)){schedulerDrain('OperatorDrain:control-file');break;}
    const j=jobs[cursor++];
    try{await execute(j.task,j.arm);}catch(e){schedulerDrain(String(e));console.error(String(e));status();}
   }
  }));"""
    assert source.count(old)==1;return source.replace(old,new)

def build(old,new,global_dir,archive_sha,fixture=False):
    assert not new.exists(),'SuccessorExistsNoOverwrite'
    if not fixture:assert sha(old/(old.name+'-results.tar.gz'))==archive_sha,'LegacyArchiveMismatch'
    s=read(old/'outputs/canonical/status.json');guard=read(old/'ops/switch32/guard.json')
    assert guard['phase']=='drain_complete' and not s['active']
    assert not Path('/proc',str(s['pid']),'cmdline').exists() or str(old/'package/run.ts').encode() not in Path('/proc',str(s['pid']),'cmdline').read_bytes()
    sourcepins=read(old/'outputs/canonical/source-pins.json')
    assert all(sha(Path(p['path']))==p['sha256'] for p in sourcepins['files'])
    output=old/'outputs/canonical'
    assert all(p.with_name('receipt.json').exists() for p in (output/'calls').rglob('dispatch.json'))
    assert all((output/'results'/p.parent.parent.name/(p.parent.name+'.json')).exists() for p in (output/'tasks').glob('*/*/started.json'))
    assert not global_dir.exists(),'GlobalRegistryExistsInspectFirst'
    new.mkdir();global_dir.mkdir()
    shutil.copytree(old/'package',new/'package',ignore=shutil.ignore_patterns('node_modules','__pycache__','.env'))
    shutil.copytree(old/'data',new/'data');(new/'bin').mkdir();(new/'bin/bun').symlink_to(old/'bin/bun')
    deps=old/'package/engine/app/node_modules'
    if deps.exists():(new/'package/engine/app/node_modules').symlink_to(deps.resolve(),target_is_directory=True)
    target=new/'outputs/canonical';target.mkdir(parents=True)
    origins=[]
    for n in ['calls','tasks','results']:
        shutil.copytree(output/n,target/n)
        for p in (output/n).rglob('*'):
            if p.is_file():
                rel=p.relative_to(old).as_posix();assert sha(new/rel)==sha(p)
                origins.append({'path':rel,'originRoot':str(old),'originPath':str(p),'sha256':sha(p)})
    for n in ['controls.json','prices.json']:
        if (output/n).exists():shutil.copyfile(output/n,target/n)
    provenance=new/'provenance';provenance.mkdir()
    for n in ['source-pins.json','launch.json','status.json','billing-reconciliation.json']:
        if (output/n).exists():shutil.copyfile(output/n,provenance/('legacy-'+n))
    shutil.copytree(old/'ops/switch32',provenance/'legacy-drain')
    (provenance/'origin-files.json').write_text(json.dumps(origins,indent=2)+'\n')
    cfg=read(new/'package/experiment.json');assert cfg['concurrency']==4
    cfg['concurrency']=32
    (new/'package/experiment.json').write_text(json.dumps(cfg,indent=2)+'\n')
    (new/'package/run.ts').write_text(transform((old/'package/run.ts').read_text()))
    registry=global_dir/'registry.sqlite';db=sqlite3.connect(registry)
    db.executescript('''PRAGMA journal_mode=WAL;
CREATE TABLE tasks(arm TEXT NOT NULL,id TEXT NOT NULL,promptSha256 TEXT NOT NULL,state TEXT NOT NULL,originRoot TEXT,originResult TEXT,resultSha256 TEXT,ownerPid INTEGER,ownerRoot TEXT,claimedAtUtc TEXT,completedAtUtc TEXT,error TEXT,PRIMARY KEY(arm,id));
CREATE TABLE dispatch_origins(path TEXT PRIMARY KEY,originRoot TEXT NOT NULL,originPath TEXT NOT NULL,sha256 TEXT NOT NULL);
''')
    suffix='\nSolve the problem. End with one finite numeric answer in the requested unit inside \\boxed{...}. For scientific notation use a\\times 10^{n}.'
    catalog=read(new/'data'/cfg['catalog']);count=0
    for arm in cfg['arms']:
        for t in catalog:
            p=target/'results'/arm/(t['id']+'.json');r=read(p) if p.exists() else None
            promptsha=hashlib.sha256((t['prompt']+suffix).encode()).hexdigest()
            if r:assert r['arm']==arm and r['id']==t['id'] and r['promptSha256']==promptsha;count+=1
            db.execute('INSERT INTO tasks(arm,id,promptSha256,state,originRoot,originResult,resultSha256) VALUES(?,?,?,?,?,?,?)',(arm,t['id'],promptsha,'inherited' if r else 'pending',str(old) if r else None,str(output/'results'/arm/p.name) if r else None,sha(p) if r else None))
    for p in (output/'calls').rglob('dispatch.json'):
        rel=p.relative_to(old).as_posix();db.execute('INSERT INTO dispatch_origins VALUES(?,?,?,?)',(rel,str(old),str(p),sha(p)))
    db.commit();db.close()
    receipts=[read(p) for p in (output/'calls').rglob('receipt.json')]
    manifest={'legacyRoot':str(old),'legacyPid':s['pid'],'legacyArchiveSha256':archive_sha,'registryPath':str(registry),'globalLockPath':str(global_dir/'owner.lock'),'originManifest':str(provenance/'origin-files.json'),'inheritedRecords':count,'pendingRecords':1664-count,'inheritedModelCalls':len(receipts),'inheritedKnownUsd':sum(x['actualCostUsd'] or 0 for x in receipts),'inheritedUnknownCount':sum(x['unknownCost'] for x in receipts),'inheritedUnknownReserveUsd':sum(x['upperBoundUsd'] for x in receipts if x['unknownCost']),'actualGlobalSlots':32,'sharedArms':cfg['arms'],'fixture':fixture,'protocolModulesUnchanged':True}
    (new/'package/continuation.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for n in ['common.ts','native.ts','sequence.ts','transport.ts','grade.py','stand.py']:
        if fixture and not (old/'package'/n).exists():continue
        assert sha(old/'package'/n)==sha(new/'package'/n)
    (provenance/'BUILD.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--legacy',type=Path,required=True);ap.add_argument('--new',type=Path,required=True);ap.add_argument('--global-dir',type=Path,required=True);ap.add_argument('--archive-sha',required=True);ap.add_argument('--fixture',action='store_true');a=ap.parse_args()
    if not a.fixture:
        base=Path('/mnt/aliyunsb/pingxingwang/tgengin-bench')
        assert a.legacy==base/'scibench-formal-20261016-v1' and a.new==base/'scibench-formal-20261016-v2-c32' and a.global_dir==base/'scibench-formal-20261016-global'
    print(json.dumps(build(a.legacy,a.new,a.global_dir,a.archive_sha,a.fixture)))
