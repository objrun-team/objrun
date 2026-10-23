"""Read-only registry/cost audit, with optional final consistent DB backup."""
from pathlib import Path
import argparse,hashlib,json,sqlite3,time,fcntl

ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--deep',action='store_true');ap.add_argument('--final',action='store_true');a=ap.parse_args()
r=a.root.resolve();o=r/'outputs/canonical';m=json.loads((r/'package/continuation.json').read_text());read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
db=sqlite3.connect('file:'+m['registryPath']+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
rows=[dict(x) for x in db.execute('SELECT * FROM tasks ORDER BY arm,id')]
origins=[dict(x) for x in db.execute('SELECT * FROM dispatch_origins ORDER BY path')]
states={k:sum(x['state']==k for x in rows) for k in sorted({x['state'] for x in rows})}
s=read(o/'status.json');old=Path(m['legacyRoot']);p=Path('/proc',str(m['legacyPid']),'cmdline')
old_live=p.exists() and str(old/'package/run.ts').encode() in p.read_bytes()
owner=read(Path(m['globalLockPath']).with_name('owner.json'))
assert owner['pid']==s['pid'] and owner['root']==str(r)
assert all(x['ownerPid']==s['pid'] and x['ownerRoot']==str(r) for x in rows if x['state']=='started')
assert states.get('started',0)<=32
if not a.final:
    lock=open(m['globalLockPath'],'a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);raise AssertionError('GlobalOwnerLockNotHeld')
    except BlockingIOError:pass
    finally:lock.close()
pins=read(o/'source-pins.json')['files'];assert all(sha(Path(x['path']))==x['sha256'] for x in pins)
origin_dispatch={x['path'] for x in origins};fees={'inherited':{'knownUsd':0.,'unknownCount':0,'unknownReserveUsd':0.,'dispatches':0,'unreceipted':0},'new':{'knownUsd':0.,'unknownCount':0,'unknownReserveUsd':0.,'dispatches':0,'unreceipted':0}}
inherited_ids={(x['arm'],x['id']) for x in rows if x['originRoot'] is not None}
unexpected=[];generation_ids=[]
for p in (o/'calls').rglob('dispatch.json'):
    rel=p.relative_to(r).as_posix();kind='inherited' if rel in origin_dispatch else 'new';f=fees[kind];f['dispatches']+=1
    identity=tuple(p.relative_to(o/'calls').parts[:2])
    if kind=='new' and identity in inherited_ids:unexpected.append(rel)
    q=p.with_name('receipt.json')
    if q.exists():
        receipt=read(q);f['knownUsd']+=receipt['actualCostUsd'] or 0
        f['unknownCount']+=bool(receipt['unknownCost'])
        if receipt['unknownCost']:f['unknownReserveUsd']+=receipt['upperBoundUsd']
        if receipt.get('generationId'):generation_ids.append(receipt['generationId'])
    else:f['unreceipted']+=1;f['unknownReserveUsd']+=read(p)['reserveUsd']
records=[read(p) for p in (o/'results').rglob('*.json')]
bad=[]
if a.deep:
    for x in read(Path(m['originManifest'])):
        p=r/x['path']
        if not p.exists() or sha(p)!=x['sha256']:bad.append(x['path'])
assert len(rows)==1664 and len({(x['arm'],x['id']) for x in rows})==1664
assert not old_live and not unexpected and not bad
assert len(generation_ids)==len(set(generation_ids))
assert len(records)==len({(x['arm'],x['id']) for x in records})
assert fees['inherited']['dispatches']==m['inheritedModelCalls'] and fees['inherited']['unreceipted']==0
assert abs(fees['inherited']['knownUsd']-m['inheritedKnownUsd'])<1e-9 and fees['inherited']['unknownCount']==m['inheritedUnknownCount']
assert len(inherited_ids)==m['inheritedRecords']
if a.final:
    assert not s['active'] and states.get('started',0)==0
    p=Path('/proc',str(s['pid']),'cmdline');assert not p.exists() or str(r/'package/run.ts').encode() not in p.read_bytes()
    assert not fees['new']['unreceipted']
    dest=r/'provenance/global-registry-final.sqlite';assert not dest.exists(),'ExistingFinalRegistryNoOverwrite'
    target=sqlite3.connect(dest);db.backup(target);target.close()
db.close()
snapshot={'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'allPassed':True,'deep':a.deep,'legacyOwnerLive':old_live,'newControllerPid':s['pid'],'active':s['active'],'observedActiveTasks':len(s['active']),'states':states,'inheritedRecords':m['inheritedRecords'],'totalCompleted':len(records),'valid':sum(bool(x['grade'].get('valid')) for x in records),'exceptions':sum(not x['grade'].get('valid') for x in records),'duplicateRecordIdentities':0,'duplicateGenerationIds':0,'newDispatchesForInheritedIdentities':unexpected,'originFileMismatches':bad,'feesCountedOnceByOrigin':fees,'registryRows':rows,'originDispatches':origins}
(r/'ops').mkdir(exist_ok=True);p=r/'ops/continuation-status.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(snapshot,indent=2)+'\n');t.replace(p)
print(json.dumps({k:v for k,v in snapshot.items() if k not in ['registryRows','originDispatches','active']},separators=(',',':')))
