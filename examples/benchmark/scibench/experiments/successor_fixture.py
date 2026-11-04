"""Exercise actual seal/build against closed mocks and blocking conditions."""
from pathlib import Path
import hashlib,json,shutil,sqlite3,subprocess,sys,tarfile,time

fast=Path('/var/tmp/tgengin-scibench-20261016');base=fast/'fixtures/successor-fixture-2'
assert not base.exists();base.mkdir(parents=True)
source=Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/scibench-switch32-lab-20261016-v1/continuation-fixture-1')
tool=Path(__file__).with_name('prepare_successor_v2.py')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text())
def clone(version):
    r=base/f'scibench-formal-20261016-v{version}-c32';shutil.copytree(source,r,ignore=shutil.ignore_patterns('node_modules','__pycache__'))
    o=r/'outputs/canonical';s=read(o/'status.json');s.update(stopReason='RepeatedProviderFaults',active=[],stage='needs_attention');(o/'status.json').write_text(json.dumps(s))
    (o/'admission-gate.json').write_text('{"valid":true}')
    g=base/f'global-{version}';g.mkdir();old=read(r/'package/continuation.json');db=sqlite3.connect('file:'+old['registryPath']+'?mode=ro',uri=True);target=sqlite3.connect(g/'registry.sqlite');db.backup(target);target.close();db.close()
    old.update(legacyRoot=str(r),registryPath=str(g/'registry.sqlite'),globalLockPath=str(g/'owner.lock'),originManifest=str(r/'provenance/origin-files.json'))
    old['lineage']=[{'root':str(source),'sha256':'fixture-only'}]
    (r/'package/continuation.json').write_text(json.dumps(old))
    pins=read(o/'source-pins.json')
    for x in pins['files']:
        rel=Path(x['path']).relative_to(source);x.update(path=str(r/rel),sha256=sha(r/rel))
    (o/'source-pins.json').write_text(json.dumps(pins))
    (r/'ops').mkdir(exist_ok=True);(r/'ops/continuation_snapshot.py').write_text('# fixture audit source\n')
    (r/'package/engine/app').mkdir(parents=True,exist_ok=True);(r/'package/engine/app/node_modules').mkdir()
    return r
def run(action,r,*extra):
    return subprocess.run(['/usr/bin/python3.11',str(tool),action,'--previous',r.name,'--fixture-base',str(base),*extra],text=True,capture_output=True,timeout=30)
r=clone(3);p=run('seal',r);assert p.returncode==0,p.stdout+p.stderr;assert json.loads(p.stdout)['safeToResumePendingOnly']
archive=r/(r.name+'-results.tar.gz')
with tarfile.open(archive,'w:gz') as t:
    for n in ['package','data','outputs','ops','provenance']:t.add(r/n,arcname=n,filter=lambda x:None if 'node_modules' in Path(x.name).parts else x)
p=run('build',r,'--archive-sha',sha(archive));assert p.returncode==0,p.stdout+p.stderr
new=base/'scibench-formal-20261016-v4-c32';m=read(new/'package/continuation.json');assert m['inheritedRecords']==40 and m['pendingRecords']==1624 and m['admissionGate']['arm']=='objrun'
assert all(sha(new/x['path'])==x['sha256'] for x in read(new/'provenance/origin-files.json'))
db=sqlite3.connect(m['registryPath']);assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==1664;assert db.execute("SELECT count(*) FROM tasks WHERE state='started'").fetchone()[0]==0;db.close()
blocked=clone(5);o=blocked/'outputs/canonical';db=sqlite3.connect(read(blocked/'package/continuation.json')['registryPath'])
for i,p in enumerate(sorted((o/'results').rglob('*.json'))[-3:]):
    row=read(p);row['grade']['valid']=False;row['error']='Error: ProviderFault:fixture';row['completedAtUtc']=f'2026-11-01T00:00:0{i}Z';p.write_text(json.dumps(row));db.execute('UPDATE tasks SET resultSha256=? WHERE arm=? AND id=?',(sha(p),row['arm'],row['id']))
db.commit();db.close();p=run('seal',blocked);assert p.returncode==0 and not json.loads(p.stdout)['safeToResumePendingOnly']
p=run('build',blocked,'--archive-sha','no-archive');assert p.returncode!=0 and not (base/'scibench-formal-20261016-v6-c32').exists()
active=clone(7);p=active/'outputs/canonical/status.json';s=read(p);s['active']=[{'arm':'objrun','id':'fixture-active'}];p.write_text(json.dumps(s));p=run('seal',active);assert p.returncode!=0 and 'ActiveTasksRemain' in p.stderr
pending=clone(9);p=next((pending/'outputs/canonical/calls').rglob('receipt.json'));p.rename(p.with_name('receipt.fixture-preserved.json'));p=run('seal',pending);assert p.returncode!=0 and 'UnreceiptedDispatch' in p.stderr
report={'allPassed':True,'sourcePreservedAndOriginFilesMatch':True,'same1664RegistryReused':True,'nativeGateUsesUnstartedTask':True,'consecutiveFaultsBlockRearm':True,'activeTasksBlockSeal':True,'unreceiptedDispatchBlocksSeal':True,'realModelCalls':0,'actualUsd':0}
(base/'AUDIT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
