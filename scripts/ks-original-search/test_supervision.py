"""Disposable real-process tests of deadline and immediate-success shutdown."""
import json,sys,time,subprocess,tempfile,shutil
from pathlib import Path
import psutil
scripts=Path(__file__).resolve().parent;root=scripts.parents[1];base=root/'data/ks-original-search'
linux=lambda p:'/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
results=[]
for mode in ['deadline','early_success']:
    temp=Path(tempfile.mkdtemp(prefix='supervision-',dir=base));(temp/'work').mkdir()
    for n in ['guard.py','linux_stop.py']:shutil.copy2(scripts/n,temp/n)
    (temp/'finalize.py').write_text('import sys,pathlib; pathlib.Path(sys.argv[1],"finalized").write_text("verified test closeout")')
    children=[subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) for _ in range(2)]
    (temp/'process.json').write_text(json.dumps({name:{'pid':p.pid,'created':psutil.Process(p.pid).create_time()} for name,p in zip(['runner','engine'],children)}))
    proc=subprocess.Popen(['wsl','-d','Ubuntu','--','bwrap','--unshare-all','--die-with-parent','--ro-bind','/usr','/usr','--ro-bind','/bin','/bin','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--proc','/proc','--dev','/dev','--bind',linux(temp/'work'),'/work','--chdir','/work','/bin/bash','-c','while true; do date +%s >> tick; sleep .1; done'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    until=time.time()+10
    while not (temp/'work/tick').exists() and time.time()<until:time.sleep(.1)
    assert (temp/'work/tick').exists(),proc.stderr.read().decode()
    end=time.time()+(1 if mode=='deadline' else 3600)
    (temp/'deadline.json').write_text(json.dumps({'deadline_epoch':end}))
    guard=subprocess.Popen([sys.executable,str(temp/'guard.py'),str(temp)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if mode=='early_success':time.sleep(.2);(temp/'success-certified.json').write_text('{}')
    stdout,stderr=guard.communicate(timeout=20);assert guard.returncode==0,stderr.decode()
    for p in children:p.wait(timeout=3)
    proc.wait(timeout=5)
    receipt=json.loads((temp/'deadline-guard.json').read_text());assert not receipt['linux']['remaining_namespaces'];assert (temp/'finalized').exists()
    results.append({'mode':mode,'passed':True,'receipt':receipt,'test_dir':str(temp)})
(base/'supervision-selftest.json').write_text(json.dumps(results,indent=2));print(json.dumps([{'mode':r['mode'],'passed':r['passed']} for r in results]))
