import json
import subprocess
import sys
import time
from pathlib import Path
import psutil

root=Path(__file__).resolve().parents[3]
run=Path((root/'data/covering-array-search/latest-run.txt').read_text())
test=run/'tests/guard'; test.mkdir(exist_ok=True)
p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],creationflags=subprocess.CREATE_NO_WINDOW)
(test/'process.json').write_text(json.dumps({'engine':{'pid':p.pid,'created':psutil.Process(p.pid).create_time()}}))
(test/'deadline.json').write_text(json.dumps({'deadline_epoch':time.time()+2}))
begin=time.monotonic()
g=subprocess.run([sys.executable,str(Path(__file__).with_name('guard.py')),str(test)],capture_output=True,text=True,timeout=10)
assert g.returncode==0 and p.poll() is not None,(g.stdout,g.stderr)
guard_time=time.monotonic()-begin
# Regression: when the guard is a child of the supervisor it must not kill
# itself before writing its enforcement receipt and finalizing the experiment.
family=run/'tests/guard-family'; family.mkdir(exist_ok=True)
family_script='''import os,sys,json,subprocess,time,psutil
from pathlib import Path
d=Path(sys.argv[1]); g=sys.argv[2]
(d/'supervisor-process.json').write_text(json.dumps({'pid':os.getpid(),'created':psutil.Process().create_time()}))
(d/'deadline.json').write_text(json.dumps({'deadline_epoch':time.time()+2}))
subprocess.Popen([sys.executable,g,str(d)],creationflags=subprocess.CREATE_NO_WINDOW)
time.sleep(30)
'''
family_parent=subprocess.Popen([sys.executable,'-c',family_script,str(family),str(Path(__file__).with_name('guard.py'))],creationflags=subprocess.CREATE_NO_WINDOW)
family_parent.wait(timeout=10)
for _ in range(30):
    if (family/'deadline-guard.json').exists(): break
    time.sleep(.1)
assert (family/'deadline-guard.json').exists(), 'Guard must survive killing its parent process tree'

linux=lambda p:'/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
env='/home/imontlaji/.local/share/objrun-ca-20261030-env'
common=['wsl','-d','Ubuntu','--','/usr/bin/timeout','--signal=TERM','--kill-after=2s','3s','bwrap','--unshare-all','--die-with-parent','--new-session','--cap-drop','ALL',
 '--ro-bind','/usr','/usr','--ro-bind','/bin','/bin','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64',
 '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',env,env,'--bind',linux(run/'work'),'/work',
 '--ro-bind',linux(run/'reference'),'/reference','--clearenv','--setenv','HOME','/work','--setenv','PATH',env+'/bin:/usr/bin:/bin',
 '--chdir','/work','/bin/bash','-s']
script='''set -eu
test ! -e /mnt/f
test ! -e /work/../checker.py
test ! -e /reference/../engine
if touch /reference/write-probe 2>/dev/null; then exit 10; fi
python - <<'PY'
import os,socket
assert 'OPENROUTER_API_KEY' not in os.environ
s=socket.socket(); s.settimeout(.3)
assert s.connect_ex(('1.1.1.1',443)) != 0
print('host files inaccessible; reference read-only; no credentials; no network')
PY
echo 'print("harmless archived preflight source")' > /work/history/isolation_marker.py
'''
s=subprocess.run(common,input=script.encode(),capture_output=True,timeout=10)
assert s.returncode==0,(s.stdout,s.stderr)
begin=time.monotonic()
expired=subprocess.run(common,input=b'sleep 60\n',capture_output=True,timeout=10)
assert expired.returncode==124,(expired.returncode,expired.stdout,expired.stderr)
result={'host_guard_passed':True,'guard_survives_parent_tree_shutdown':True,'host_guard_seconds':guard_time,'sandbox_isolation':s.stdout.decode(),
        'external_timeout_passed':True,'external_timeout_seconds':time.monotonic()-begin,
        'external_timeout_exit_code':expired.returncode}
(run/'tests/isolation.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
