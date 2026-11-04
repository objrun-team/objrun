"""Launch one isolated continuation with a held experiment-wide flock."""
from pathlib import Path
import fcntl,json,os,signal,subprocess,sys,time,sqlite3

root=(Path(__file__).resolve().parents[4] / 'scripts');out=root/'outputs/canonical'
manifest=json.loads((root/'package/continuation.json').read_text())
payload=json.load(sys.stdin)
if '--supervise' not in sys.argv:
    assert not (out/'launch.json').exists() and not (out/'supervisor-launch.json').exists(),'ExistingLaunchInspectFirst'
    with (out/'supervisor.stdout.log').open('ab') as so,(out/'supervisor.stderr.log').open('ab') as se:
        p=subprocess.Popen(['/usr/bin/python3.11',str(Path(__file__).resolve()),'--supervise'],cwd=root,env={'PATH':str(root/'bin')+':/usr/bin:/bin','PYTHONUTF8':'1'},stdin=subprocess.PIPE,stdout=so,stderr=se,start_new_session=True)
        p.stdin.write(json.dumps(payload).encode());p.stdin.close()
    (out/'supervisor-launch.json').write_text(json.dumps({'pid':p.pid,'root':str(root)})+'\n')
    until=time.monotonic()+25
    while not (out/'launch.json').exists():
        assert p.poll() is None,(out/'supervisor.stderr.log').read_text()
        assert time.monotonic()<until,'SupervisorLaunchTimeout';time.sleep(.1)
    print((out/'launch.json').read_text());sys.exit(0)
key=payload.pop('key');assert isinstance(key,str) and key
lock=open(manifest['globalLockPath'],'a+')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert not (out/'launch.json').exists(),'ExistingLaunchInspectFirst'
legacy=Path(manifest['legacyRoot']);s=json.loads((legacy/'outputs/canonical/status.json').read_text())
assert json.loads((legacy/'ops/switch32/guard.json').read_text())['phase']=='drain_complete' and not s['active']
p=Path('/proc',str(manifest['legacyPid']),'cmdline');assert not p.exists() or str(legacy/'package/run.ts').encode() not in p.read_bytes()
db=sqlite3.connect('file:'+manifest['registryPath']+'?mode=ro',uri=True)
assert not db.execute("SELECT count(*) FROM tasks WHERE state NOT IN ('pending','inherited')").fetchone()[0];db.close()
env={'PATH':str(root/'bin')+':/usr/bin:/bin','PYTHONUTF8':'1','NO_PROXY':'127.0.0.1,localhost','OPENROUTER_API_KEY':key}
with (out/'controller.stdout.log').open('ab') as so,(out/'controller.stderr.log').open('ab') as se:
    child=subprocess.Popen([str(root/'bin/bun'),str(root/'package/run.ts')],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=so,stderr=se)
record={'pid':child.pid,'supervisorPid':os.getpid(),'root':str(root),'entry':'package/run.ts','atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'credentialWritten':False,'metadata':payload,'globalSlots':32,'legacyRoot':str(legacy),'legacyPid':manifest['legacyPid']}
(out/'launch.json').write_text(json.dumps(record,indent=2)+'\n')
Path(manifest['globalLockPath']).with_name('owner.json').write_text(json.dumps(record,indent=2)+'\n')
def drain(*_):
    if child.poll() is None:child.send_signal(signal.SIGTERM)
signal.signal(signal.SIGTERM,drain);signal.signal(signal.SIGINT,drain)
code=child.wait()
(out/'supervisor-exit.json').write_text(json.dumps({'controllerPid':child.pid,'returncode':code,'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})+'\n')
sys.exit(code)
