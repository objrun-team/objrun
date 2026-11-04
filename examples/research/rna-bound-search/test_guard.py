import subprocess,sys,json,time,psutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
run=ROOT/'data/rna-bound-search/run-20261030-a'
out=run/'preflight/guard-test';out.mkdir(exist_ok=True)
p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'],creationflags=subprocess.CREATE_NO_WINDOW)
(out/'process.json').write_text(json.dumps({'runner':{'pid':p.pid,'created':psutil.Process(p.pid).create_time()}}))
(out/'deadline.json').write_text(json.dumps({'deadline_epoch':time.time()+1.5}))
g=subprocess.run([sys.executable,str(run/'guard.py'),str(out)],capture_output=True,text=True,timeout=15)
assert g.returncode==0 and p.wait(timeout=5)!=0
linux=lambda p:'/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
env='/home/imontlaji/.local/share/objrun-rna-20261030-env'
code='import subprocess; subprocess.run(["bash","-c","(sleep 3; touch /work/should-not-survive) & wait"],timeout=0.5)'
argv=['wsl','-d','Ubuntu','--','bwrap','--unshare-all','--die-with-parent','--new-session','--ro-bind','/usr','/usr','--ro-bind','/bin','/bin','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--clearenv','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',env,env,'--bind',linux(out),'/work','--setenv','PATH',env+'/bin:/usr/bin:/bin',env+'/bin/python','-c',code]
q=subprocess.run(argv,text=True,capture_output=True,timeout=15)
time.sleep(3.5)
assert not (out/'should-not-survive').exists(),'background descendant survived PID namespace'
r={'windows_identity_guard_pass':True,'linux_namespace_descendant_stop_pass':True,'linux_exit_code':q.returncode}
(out/'test-result.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
