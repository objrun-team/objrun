"""Remote trusted control entry. Credential arrives on SSH stdin and is never saved."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT=(Path(__file__).resolve().parents[4] / 'scripts')
PROJECT=ROOT.parents[1]

def runtime_env():
    r=str(PROJECT/'pm-runtime/.pm-agent')
    env={k:v for k,v in os.environ.items() if not k.endswith('_API_KEY')}
    env.update(HOME=r+'/home',TMPDIR=r+'/tmp',TMP=r+'/tmp',TEMP=r+'/tmp',XDG_CACHE_HOME=r+'/cache',
               XDG_CONFIG_HOME=r+'/config',XDG_DATA_HOME=r+'/data',XDG_STATE_HOME=r+'/state',
               PYTHONPYCACHEPREFIX=r+'/cache/python',TPE_REMOTE_DOCKER='1',
               TPE_ENGINE_RUNTIME=str(PROJECT/'pm-runtime/private-docker/mnt/engine-state'),
               PATH=str(PROJECT/'bin/bun-linux-x64')+':'+str(PROJECT/'.venv/bin')+':'+env['PATH'])
    return env

def freeze_check():
    frozen=json.loads((ROOT/'control/freeze.json').read_text())
    for item in frozen['files']:
        if hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()!=item['sha256']:
            raise RuntimeError('FrozenInputChanged:'+item['path'])
    return frozen

def main():
    os.umask(0o077)
    payload=json.load(sys.stdin)
    env=runtime_env()
    os.chdir(PROJECT)
    config=ROOT/'package/formal.json'
    cfg=json.loads(config.read_text())
    env.update(TPE_CONFIG=str(config),TPE_RUN=cfg['run'])
    mode=payload['mode']
    if mode=='services':
        for name in ['owned_proxy','bridge']:
            marker=ROOT/'outputs'/('service-'+name+'.json')
            if marker.exists():raise RuntimeError('ExistingOwnedService:'+name)
            p=subprocess.Popen([str(PROJECT/'.venv/bin/python'),str(ROOT/'package'/(name+'.py'))],env=env,cwd=ROOT,
                stdin=subprocess.DEVNULL,stdout=(ROOT/'outputs'/(name+'.stdout.log')).open('ab'),
                stderr=(ROOT/'outputs'/(name+'.stderr.log')).open('ab'),start_new_session=True)
            marker.write_text(json.dumps({'pid':p.pid,'name':name}))
        print(json.dumps({'services':'started'}));return
    env['OPENROUTER_API_KEY']=payload['key']
    if mode=='finalize':
        freeze_check()
        out=ROOT/'outputs'/cfg['run']
        with (out/'finalize-started.json').open('x') as f:json.dump({'pid':os.getpid(),'modelCalls':0},f)
        p=subprocess.run([str(PROJECT/'.venv/bin/python'),str(ROOT/'package/remote_audit.py'),cfg['run']],cwd=ROOT,env=env,capture_output=True,text=True,timeout=7200)
        if payload['key'] in p.stdout+p.stderr:raise RuntimeError('CredentialOutputSuppressed')
        (out/'finalize.stdout.log').write_text(p.stdout);(out/'finalize.stderr.log').write_text(p.stderr)
        print(json.dumps({'returnCode':p.returncode,'stdout':p.stdout[-12000:],'stderr':p.stderr[-2500:]}));return
    if mode=='preflight':
        command="const {observe,balance}=await import('./package/common.ts');await observe();console.log('Pinned DigitalOcean route, tariff and account verified; no model call.');"
        p=subprocess.run(['bun','-e',command],cwd=ROOT,env=env,capture_output=True,text=True,timeout=150)
        if payload['key'] in p.stdout+p.stderr:raise RuntimeError('CredentialOutputSuppressed')
        print(p.stdout[-2000:]);print(p.stderr[-2000:]);raise SystemExit(p.returncode)
    if mode!='formal':raise RuntimeError('UnsupportedRemoteEntryMode')
    frozen=freeze_check()
    for name in ['pilot-acceptance','remote-acceptance']:
        if not json.loads((ROOT/'control'/(name+'.json')).read_text())['passed']:raise RuntimeError('AcceptanceGate:'+name)
    out=ROOT/'outputs'/cfg['run'];out.mkdir(exist_ok=True)
    marker=out/'launch.json'
    with marker.open('x') as m:
        m.write(json.dumps({'state':'admitted','freeze':frozen['gitCommit'],'keyWritten':False}))
    p=subprocess.Popen(['bun',str(ROOT/'package/run.ts')],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,
        stdout=(out/'controller.stdout.log').open('ab'),stderr=(out/'controller.stderr.log').open('ab'),start_new_session=True)
    record={'pid':p.pid,'host':'novaeve','run':cfg['run'],'entry':str(ROOT/'package/run.ts'),'keyWritten':False,
        'locations':{'controller':'novaeve trusted host','ObjRun':'novaeve trusted host','grader':'novaeve trusted host','solver':'novaeve project-private Docker'},'gitCommit':frozen['gitCommit']}
    marker.write_text(json.dumps(record,indent=2));print(json.dumps(record))

if __name__=='__main__':main()
