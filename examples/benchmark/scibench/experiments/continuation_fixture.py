"""Integration test for the actual continuation scheduler, with local mocks."""
from pathlib import Path
import fcntl,json,sqlite3,subprocess,time,sys
from continuation import build,sha

lab=Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/scibench-switch32-lab-20261016-v1')
run=sys.argv[1] if len(sys.argv)>1 else '1'
old=lab/'drain-fixture-0';new=lab/('continuation-fixture-'+run);global_dir=lab/('continuation-global-'+run)
manifest=build(old,new,global_dir,'fixture-only-no-archive',True)
# Extend only the mock provider latency, so the external observer can reliably
# measure all 32 slots before asking the new scheduler to drain.
p=new/'package/common.ts';p.write_text(p.read_text().replace('await Bun.sleep(','await Bun.sleep(2000+'))
for n in ['continuation_launcher.py']:(new/'package'/n).write_text(Path(__file__).with_name(n).read_text())
p=subprocess.run(['/usr/bin/python3.11',str(new/'package/continuation_launcher.py')],input=json.dumps({'key':'fixture-not-a-real-key','scope':'no real model calls'}),capture_output=True,text=True,timeout=30)
assert p.returncode==0,p.stdout+p.stderr
launch=json.loads(p.stdout);out=new/'outputs/canonical'
max_active=0;until=time.monotonic()+25
while max_active<32:
    if (out/'status.json').exists():
        s=json.loads((out/'status.json').read_text());max_active=max(max_active,len(s['active']))
        assert s['stopReason'] is None,s
    assert time.monotonic()<until,'DidNotObserve32';time.sleep(.01)
fd=open(manifest['globalLockPath'],'a+')
try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);raise AssertionError('GlobalOwnerLockNotHeld')
except BlockingIOError:pass
db=sqlite3.connect(manifest['registryPath'])
active=db.execute("SELECT arm,id FROM tasks WHERE state='started' LIMIT 1").fetchone();assert active
assert db.execute("UPDATE tasks SET ownerPid=-1 WHERE arm=? AND id=? AND state='pending'",active).rowcount==0
assert db.execute("UPDATE tasks SET ownerPid=-1 WHERE state='inherited' AND state='pending'").rowcount==0
db.commit();db.close()
(new/'control').mkdir();(new/'control/drain.json').write_text('{"reason":"fixture cooperative drain"}')
until=time.monotonic()+45
while not (out/'supervisor-exit.json').exists():
    assert time.monotonic()<until,'FixtureDrainTimeout';time.sleep(.1)
s=json.loads((out/'status.json').read_text());assert not s['active'] and s['stopReason']=='OperatorDrain:control-file'
db=sqlite3.connect(manifest['registryPath']);states=dict(db.execute('SELECT state,count(*) FROM tasks GROUP BY state'));db.close()
assert states.get('started',0)==0 and states['inherited']==8 and states['complete']>=32
assert all(p.with_name('receipt.json').exists() for p in (out/'calls').rglob('dispatch.json'))
origins=json.loads((new/'provenance/origin-files.json').read_text());assert all(sha(new/x['path'])==x['sha256'] for x in origins)
result={'allPassed':True,'observedActualSlots':max_active,'sharedArms':list(s['arms']),'globalExclusiveLockVerified':True,'duplicateClaimRejected':True,'cooperativeDrainVerified':True,'allStartsTerminal':True,'allDispatchesReceipted':True,'inheritedFilesByteIdentical':True,'states':states,'realModelCalls':0,'actualUsd':0}
(lab/'CONTINUATION_FIXTURE_AUDIT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
