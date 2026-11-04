"""One new repair controller; separate identity registry, original registry read-only."""
from pathlib import Path
import fcntl,json,os,signal,sqlite3,subprocess,sys,time
from infra_retry_build import require_closed
from infra_retry_policy import sha,PROTOCOL

root=(Path(__file__).resolve().parents[4] / 'scripts');out=root/'outputs/canonical';plan=json.loads((root/'package/repair-plan.json').read_text());payload=json.load(sys.stdin)
if '--supervise' not in sys.argv:
 assert not (out/'launch.json').exists() and not (out/'supervisor-launch.json').exists(),'ExistingRepairLaunchNeverRepeat'
 with (out/'supervisor.stdout.log').open('ab') as so,(out/'supervisor.stderr.log').open('ab') as se:
  child=subprocess.Popen(['/usr/bin/python3.11',str(Path(__file__).resolve()),'--supervise'],cwd=root,env={'PATH':str(root/'bin')+':/usr/bin:/bin','PYTHONUTF8':'1'},stdin=subprocess.PIPE,stdout=so,stderr=se,start_new_session=True)
  child.stdin.write(json.dumps(payload).encode());child.stdin.close()
 (out/'supervisor-launch.json').write_text(json.dumps({'pid':child.pid,'root':str(root)})+'\n')
 until=time.monotonic()+25
 while not (out/'launch.json').exists():
  assert child.poll() is None,(out/'supervisor.stderr.log').read_text()
  assert time.monotonic()<until,'RepairLaunchTimeout';time.sleep(.1)
 print((out/'launch.json').read_text());raise SystemExit(0)
key=payload.pop('key');assert isinstance(key,str) and key
source=Path(plan['sourceRoot']);require_closed(source)
assert sha((source/(source.name+'-results.tar.gz')).read_bytes())==plan['sourceArchiveSha256']
read=lambda p:json.loads(p.read_text())
assert all(read(source/'package/experiment.json')[k]==read(root/'package/experiment.json')[k] for k in PROTOCOL),'RepairProtocolChanged'
assert all(sha((root/x['path']).read_bytes())==x['sha256'] for x in read(root/'provenance/solver-source-pins.json')['files']),'RepairSolverSourceChanged'
old_lock=open(plan['originalGlobalLockPath'],'a+');fcntl.flock(old_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
lock=open(plan['globalLockPath'],'a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert not (out/'launch.json').exists()
db=sqlite3.connect('file:'+plan['registryPath']+'?mode=ro',uri=True)
assert db.execute('SELECT count(*) FROM attempts').fetchone()[0]==len(plan['attempts']) and not db.execute("SELECT count(*) FROM attempts WHERE state!='pending'").fetchone()[0];db.close()
env={'PATH':str(root/'bin')+':/usr/bin:/bin','PYTHONUTF8':'1','NO_PROXY':'127.0.0.1,localhost','OPENROUTER_API_KEY':key}
with (out/'controller.stdout.log').open('ab') as so,(out/'controller.stderr.log').open('ab') as se:
 child=subprocess.Popen([str(root/'bin/bun'),str(root/'package/run.ts')],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=so,stderr=se)
record={'pid':child.pid,'supervisorPid':os.getpid(),'root':str(root),'entry':'package/run.ts','atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'credentialWritten':False,'metadata':payload,'globalSlots':32,'attemptCount':len(plan['attempts']),'sourceRoot':str(source)}
(out/'launch.json').write_text(json.dumps(record,indent=2)+'\n');Path(plan['globalLockPath']).with_name('owner.json').write_text(json.dumps(record,indent=2)+'\n')
def drain(*_):
 if child.poll() is None:child.send_signal(signal.SIGTERM)
signal.signal(signal.SIGTERM,drain);signal.signal(signal.SIGINT,drain)
code=child.wait();(out/'supervisor-exit.json').write_text(json.dumps({'controllerPid':child.pid,'returncode':code,'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})+'\n');raise SystemExit(code)
