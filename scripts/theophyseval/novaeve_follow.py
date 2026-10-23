"""Owned local gate/report follower; all formal scientific execution stays remote."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import time

WORKSPACE=Path(__file__).resolve().parents[3]
LOCAL=WORKSPACE/'tmp/theophyseval-novaeve-20261016-v4'
PILOT=WORKSPACE/'tmp/theophyseval-20261016-v3'
REMOTE='/mnt/aliyunsb/ProjectManagement/ICLR2027-TheoPhysEval/runs/theophyseval-novaeve-20261016-v4'
PROJECT='/mnt/aliyunsb/ProjectManagement/ICLR2027-TheoPhysEval'
RUN='theophyseval-formal-novaeve-20261016-v4'
SSH=['ssh','-F','C:/Users/y1252/Documents/Codex/2026-10-15/s-c/work/scicode/ssh-config','-o','ConnectTimeout=15','novaeve']
CONTROLS=['grading-controls','special-grading-controls','container-controls','engine-controls','timeout-controls','auth-controls','control-plane-controls']

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(name,record):
    p=LOCAL/'outputs'/name;p.parent.mkdir(exist_ok=True,parents=True)
    t=p.with_suffix('.tmp');t.write_text(json.dumps(record,indent=2)+'\n');t.replace(p)
def ssh_script(script,timeout=90):
    p=subprocess.run(SSH+['/usr/bin/python3.11','-'],input=script,text=True,capture_output=True,timeout=timeout)
    if p.returncode:raise RuntimeError('RemoteReadFailure:'+p.stderr[-1200:])
    return json.loads(p.stdout)
def entry(mode):
    key=None
    for line in (WORKSPACE/'TgEngin/.env').read_text(encoding='utf-8-sig').splitlines():
        m=re.match(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$',line)
        if m:key=m[1].strip().strip('\"\'');break
    if not key:raise RuntimeError('MissingExistingAuthorizedKey')
    p=subprocess.run(SSH+[PROJECT+'/.venv/bin/python',REMOTE+'/package/remote_entry.py'],
        input=json.dumps({'mode':mode,'key':key}),capture_output=True,text=True,timeout=7200 if mode=='finalize' else 180)
    if key in p.stdout+p.stderr:raise RuntimeError('CredentialOutputSuppressed')
    if p.returncode:raise RuntimeError('RemoteEntryRejected:'+p.stderr[-1800:])
    return p.stdout[-6000:]
def acceptance():
    out=PILOT/'outputs/theophyseval-pilot-20261016-v3'
    p=subprocess.run([str(WORKSPACE/'tmp/theophyseval-runtime/venv/Scripts/python.exe'),str(PILOT/'package/audit.py'),'theophyseval-pilot-20261016-v3'],capture_output=True,text=True,timeout=300)
    if p.returncode:raise RuntimeError('PilotAuditRejected:'+p.stdout[-2500:]+p.stderr[-500:])
    controls={n:read(PILOT/'control'/(n+'.json'))['passed'] for n in CONTROLS}
    audit=read(out/'audit.json')
    if not audit['passed'] or not all(controls.values()):raise RuntimeError('PilotControlGateRejected')
    return {'passed':True,'pilot':'theophyseval-pilot-20261016-v3','audit':audit,'controls':controls,
        'auditSha256':hashlib.sha256((out/'audit.json').read_bytes()).hexdigest(),'authorizedScope':'49 automatic units x four arms, novaeve only, cap32 tasks and global model requests'}
def snapshot():
    return ssh_script("""import json,pathlib,os
r=pathlib.Path(%r);out=r/'outputs'/%r
def read(p):return json.loads(p.read_text()) if p.exists() else None
print(json.dumps({'remoteAcceptance':read(r/'control/remote-acceptance.json'),'status':read(out/'status.json'),'launch':read(out/'launch.json'),'audit':read(out/'final-audit.json'),'archive':read(out/'archive-receipt.json')}))
"""%(REMOTE,RUN))
def sync_final():
    target=LOCAL/'outputs'/RUN;target.mkdir(exist_ok=True)
    names=['REPORT.md','audit.json','final-audit.json','archive-receipt.json','frozen-config.json','source-pins.json','model-concurrency.json','status.json']
    for name in names:
        p=subprocess.run(['scp','-F',SSH[2],f'novaeve:{REMOTE}/outputs/{RUN}/{name}',str(target/name)],capture_output=True,text=True,timeout=120)
        if p.returncode:raise RuntimeError('ReportSyncFailed:'+name+':'+p.stderr[-400:])
    hashes=ssh_script("import pathlib,json,hashlib\nr=pathlib.Path(%r)/'outputs'/%r\nprint(json.dumps({n:hashlib.sha256((r/n).read_bytes()).hexdigest() for n in %r}))"%(REMOTE,RUN,names))
    for name,digest in hashes.items():
        if hashlib.sha256((target/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('ReportSyncHashMismatch:'+name)
    save('report-sync-receipt.json',{'passed':True,'sha256':hashes,'remoteArchive':read(target/'archive-receipt.json')})

def main():
    LOCAL.joinpath('outputs').mkdir(exist_ok=True)
    with (LOCAL/'outputs/follower-launch.json').open('x') as f:json.dump({'pid':os.getpid(),'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())},f)
    while True:
        pilot=read(PILOT/'outputs/theophyseval-pilot-20261016-v3/status.json')
        remote=snapshot();save('remote-status.json',remote)
        if not remote['launch']:
            save('follower-status.json',{'phase':'waiting_acceptances','pilot':pilot,'remoteAcceptance':remote['remoteAcceptance'],'at':time.time()})
            if pilot['stage'] not in ['running','starting'] and not pilot['active']:
                if pilot['stage']!='complete':raise RuntimeError('PilotNeedsAttention')
                accepted=acceptance();save('pilot-acceptance.json',accepted)
                if remote['remoteAcceptance'] and remote['remoteAcceptance']['passed']:
                    script="import pathlib,json\np=pathlib.Path(%r)/'control/pilot-acceptance.json'\np.write_text(%r)\nprint('{}')"%(REMOTE,json.dumps(accepted,indent=2)+'\n')
                    ssh_script(script)
                    result=entry('preflight');save('preflight-receipt.json',{'passed':True,'message':result,'modelCalls':0})
                    script="import subprocess,json\nr=subprocess.run([%r,%r],capture_output=True,text=True)\nassert r.returncode==0,r.stderr\nprint(r.stdout)"%(PROJECT+'/.venv/bin/python',REMOTE+'/package/remote_freeze.py')
                    freeze=ssh_script(script,180);save('freeze-receipt.json',freeze)
                    launch=entry('formal');save('formal-launch-receipt.json',{'stdout':launch})
        else:
            status=remote['status']
            save('follower-status.json',{'phase':'formal_running' if status and status['stage']=='running' else 'formal_status','remote':remote,'at':time.time()})
            if status and status['stage'] in ['complete','complete_with_exceptions'] and not status['active']:
                if not remote['archive']:
                    audited=entry('finalize');save('final-audit-invocation.json',{'result':audited})
                sync_final();save('follower-status.json',{'phase':'complete','at':time.time(),'finalAudit':read(LOCAL/'outputs'/RUN/'final-audit.json')});return
            if status and status['stage']=='needs_attention':raise RuntimeError('RemoteControllerNeedsAttention')
        time.sleep(30)

if __name__=='__main__':
    try:main()
    except Exception as e:
        save('follower-error.json',{'error':str(e),'at':time.time(),'paidCallsRepeated':False});raise
