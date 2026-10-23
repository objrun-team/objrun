"""Local transport. Credentials travel only through SSH stdin into controller memory."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LOCAL = REPO.parent / 'tmp/minif2f-valid-pilot-20261019-v1'
DEST = REPO / 'docs/minif2f/valid-pilot-20261019-v1'
PROJECT = '/data/ProjectManagement/ICLR2027-TgEngin-miniF2F'
REMOTE = PROJECT + '/pm-runtime/runs/minif2f-pilot-20261019-v1'
RUNTIME_ENV = PROJECT + '/pm-runtime/pilot.env'
PROFILE_CONFIG = None
SCP = ['scp', '-q', '-o', 'ClearAllForwardings=yes']

def ssh(code, payload=None):
    command = 'cd ' + shlex.quote(PROJECT) + ' && /usr/bin/python3.11 -c ' + shlex.quote(code)
    result = subprocess.run(['ssh', '-o', 'ClearAllForwardings=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'novaeve', command],
                            input=json.dumps(payload).encode() if payload is not None else None, capture_output=True)
    if result.returncode: raise RuntimeError(result.stderr.decode(errors='replace')[:2000] + result.stdout.decode(errors='replace')[:2000])
    return result.stdout.decode()

def push_code():
    ssh("import pathlib; assert not (pathlib.Path(" + repr(REMOTE) + ")/'outputs/launch-launch.json').exists(),'Paid source is frozen'")
    bundle = LOCAL / 'package.tar.gz'
    with tarfile.open(bundle, 'w:gz') as tar:
        for path in sorted(HERE.iterdir()):
            if path.is_file() and path.suffix in ('.py', '.json', '.md'):
                if PROFILE_CONFIG and path.name == 'experiment.json': continue
                tar.add(path, arcname='package/' + path.name)
        if PROFILE_CONFIG: tar.add(PROFILE_CONFIG, arcname='package/experiment.json')
        for directory in ['data', 'vendor']:
            for path in sorted((LOCAL / directory).iterdir()):
                if path.is_file(): tar.add(path, arcname=directory + '/' + path.name)
    subprocess.run(SCP + [str(bundle), 'novaeve:' + REMOTE + '/package.tar.gz'], check=True)
    result = ssh("import pathlib,tarfile; r=pathlib.Path(" + repr(REMOTE) + "); assert not (r/'outputs/launch-launch.json').exists(),'Paid source is frozen'; a=tarfile.open(r/'package.tar.gz'); members=a.getmembers(); assert all(m.isfile() and '..' not in pathlib.PurePosixPath(m.name).parts and not m.name.startswith('/') for m in members); a.extractall(r); print('package files',len(members))")
    print(result, end='')

def main():
    global REMOTE, DEST, LOCAL, RUNTIME_ENV, PROFILE_CONFIG
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['prepare-provider', 'recover', 'push-code', 'push-deps', 'bootstrap', 'probe', 'controls', 'launch', 'status', 'pull'])
    parser.add_argument('--profile', choices=['baseten', 'deepinfra'], default='baseten')
    parser.add_argument('--run-version', type=int, choices=[1, 2], default=1)
    parser.add_argument('--control-attempt', type=int, default=1,
                        help='Preserve earlier zero-model controls and launch a numbered retry')
    options = parser.parse_args(); action = options.action
    if options.profile == 'deepinfra':
        if options.run_version != 1 or action in ('recover', 'bootstrap', 'push-deps'):
            parser.error('DeepInfra is a fresh pilot; shared frozen assets cannot be bootstrapped or recovered here')
        REMOTE = PROJECT + '/pm-runtime/runs/minif2f-deepinfra-pilot-20261019-v1'
        DEST = DEST.with_name('valid-deepinfra-pilot-20261019-v1')
        LOCAL = LOCAL.with_name('minif2f-valid-deepinfra-20261019-v1')
        RUNTIME_ENV = PROJECT + '/pm-runtime/deepinfra-pilot.env'
        PROFILE_CONFIG = HERE / 'experiment-deepinfra.json'
    if options.run_version == 2:
        REMOTE = REMOTE.removesuffix('-v1') + '-v2'
        DEST = DEST.with_name(DEST.name.removesuffix('-v1') + '-v2')
    if options.control_attempt < 1 or (options.control_attempt != 1 and action != 'controls'):
        parser.error('--control-attempt is positive and only applies to controls')
    if action == 'prepare-provider':
        if options.profile != 'deepinfra': parser.error('prepare-provider requires --profile deepinfra')
        assert not LOCAL.exists(), 'Profile staging already exists; inspect instead of overwrite'
        LOCAL.mkdir()
        baseline = LOCAL.with_name('minif2f-valid-pilot-20261019-v1')
        for directory in ['data', 'vendor']: shutil.copytree(baseline / directory, LOCAL / directory)
        shutil.copy2(baseline / 'dependency-bundle.json', LOCAL / 'dependency-bundle.json')
        code = (HERE / 'provider_pilot.py').read_text() + '\nprepare(' + repr(PROJECT) + ',' + repr(REMOTE) + ',' + repr(RUNTIME_ENV) + ')'
        print(ssh(code), end=''); return
    if action == 'recover':
        if options.run_version != 2: parser.error('Only one bounded recovery batch (v2) is allowed')
        code = (HERE / 'recovery.py').read_text() + '\nprepare(' + repr(PROJECT) + ',' + repr(REMOTE.removesuffix('-v2') + '-v1') + ',' + repr(REMOTE) + ')'
        print(ssh(code), end=''); return
    if action == 'push-code': push_code(); return
    if action == 'push-deps':
        for name in ['dependency-bundle.json', 'lean-dependencies.tar.gz']:
            subprocess.run(SCP + [str(LOCAL / name), 'novaeve:' + REMOTE + '/' + name], check=True)
        print('dependency bundle uploaded'); return
    if action in ('bootstrap', 'controls', 'launch'):
        key = None
        if action == 'launch':
            env = (REPO.parent / 'TgEngin.env').read_text(encoding='utf-8-sig')
            match = re.search(r'^\s*OPENROUTER_API_KEY\s*=\s*(.+?)\s*$', env, re.M)
            if not match: raise RuntimeError('WorkspaceOpenRouterCredentialMissing')
            key = match[1].strip().strip('"\'')
        code = """
import json,os,pathlib,subprocess,sys,time
project=pathlib.Path(PROJECT);r=pathlib.Path(REMOTE);os.chdir(project)
env={k:v for k,v in os.environ.items() if not any(t in k.upper() for t in ['KEY','TOKEN','SECRET'])}
for line in pathlib.Path(ENV_FILE).read_text().splitlines():
 if line and not line.startswith('#') and '=' in line:
  k,v=line.split('=',1);env[k]=v
env.update(PATH='/usr/bin:/bin',PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',NO_PROXY='127.0.0.1,localhost')
payload=json.load(sys.stdin);action=payload['action'];out=r/'outputs';out.mkdir(exist_ok=True)
stem=action+('-'+str(payload['controlAttempt']) if payload.get('controlAttempt',1)>1 else '')
lock=out/(stem+'-launch.json')
assert not lock.exists(),'Existing launch: inspect instead of duplicate'
entry={'bootstrap':'bootstrap.py','controls':'controls.py','launch':'run.py'}[action]
if action=='launch':env['OPENROUTER_API_KEY']=payload['key']
args=['/usr/bin/python3.11','-u',str(r/'package'/entry),str(r)]
with (out/(stem+'.stdout.log')).open('ab') as stdout,(out/(stem+'.stderr.log')).open('ab') as stderr:
 child=subprocess.Popen(args,cwd=r,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
record={'pid':child.pid,'entry':entry,'root':str(r),'credentialWritten':False,'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
lock.write_text(json.dumps(record,indent=2)+'\\n');print(json.dumps(record))
""".replace('PROJECT', repr(PROJECT)).replace('REMOTE', repr(REMOTE)).replace('ENV_FILE', repr(RUNTIME_ENV))
        print(ssh(code, {'action': action, 'controlAttempt': options.control_attempt, **({'key': key} if key else {})}), end=''); return
    if action == 'status':
        code = "import pathlib,json; r=pathlib.Path(" + repr(REMOTE) + "); print('ROOT',r); "
        code += "\nfor n in ['bootstrap','controls','launch']:\n p=r/'outputs'/(n+'-launch.json'); print(n,p.read_text() if p.exists() else 'not launched')\n for suffix in ['stdout.log','stderr.log']:\n  q=r/'outputs'/(n+'.'+suffix); print(q.name,q.read_text()[-2500:] if q.exists() else '')\np=r/'outputs/status.json'; print('STATUS',p.read_text() if p.exists() else 'not running')"
        print(ssh(code), end=''); return
    if action == 'probe':
        print(ssh("import pathlib,subprocess,json; r=pathlib.Path(" + repr(REMOTE) + "); print('READY', (r/'outputs/environment.json').exists()); print(subprocess.run(['curl','--proxy','http://127.0.0.1:18519','--connect-timeout','8','--max-time','20','-sS','-o',str(r/'outputs/network-models.json'),'-w','%{http_code}', 'https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash-0731/endpoints'],capture_output=True,text=True).__dict__)") , end=''); return
    if action == 'pull':
        DEST.mkdir(parents=True, exist_ok=True)
        print(ssh("import sys;sys.path.insert(0," + repr(REMOTE + '/package') + ");import report;report.finish(" + repr(REMOTE) + ",archive=True)"), end='')
        for name in ['results.tar.gz', 'archive-integrity.json', 'REPORT.md', 'audit.json', 'summary.json', 'status.json']:
            subprocess.run(SCP + ['novaeve:' + REMOTE + '/outputs/' + name, str(DEST / name)], check=True)
        record = json.loads((DEST / 'archive-integrity.json').read_text())
        with (DEST / 'results.tar.gz').open('rb') as stream: assert hashlib.file_digest(stream, 'sha256').hexdigest() == record['sha256']
        full = DEST / 'full-results'; full.mkdir(exist_ok=True)
        with tarfile.open(DEST / 'results.tar.gz', 'r:gz') as archive:
            assert all(not m.name.startswith('/') and '..' not in Path(m.name).parts and (m.isfile() or m.isdir()) for m in archive.getmembers())
            archive.extractall(full, filter='data')
        (DEST / 'retrieval.json').write_text(json.dumps({'archiveSha256Verified': True, 'bytes': (DEST / 'results.tar.gz').stat().st_size, 'completeLogs': str(full)}, indent=2) + '\n')
        print(json.dumps({'downloaded': str(DEST), 'sha256Verified': True})); return

if __name__ == '__main__': main()
