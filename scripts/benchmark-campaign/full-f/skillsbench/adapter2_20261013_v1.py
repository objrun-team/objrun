"""Three source-bound adapters. Docker command and broker admission are injected.

No model, registration, scheduler or Docker call occurs at import/preparation.
Browser application execution stays in an untrusted full snapshot; only the
network namespace is shared with the original private Playwright assertions.
"""
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tarfile
import time
import uuid
import sys
if "--private" not in sys.argv:
    from prepare import ROOT, HOME, VENDOR, public, save
    from ordinary_artifacts import Policy, parse_daemon_tar

TASKS = ('fix-visual-stability', 'multilingual-video-dubbing', 'reserves-at-risk-calc')
ADAPTER = 'group01-adapter2-v1'
def assert_lease(owner_pid, resources):
    from datetime import datetime, timezone
    connection=json.loads((HOME.parent/'control.json').read_bytes())['broker']
    status=json.loads(Path(connection['healthPath']).read_bytes())
    assert status['healthy'] and status['pid']==connection['pid'] and status['runId']==connection['runId']
    assert 0 <= (datetime.now(timezone.utc)-datetime.fromisoformat(status['atUtc'].replace('Z','+00:00'))).total_seconds()<30
    slots=[r for r in status['resourceSlots'] if r['pid']==owner_pid and r['slug']=='skillsbench' and r['kind']=='heavy-container']
    assert len(slots)==1 and slots[0]['memoryMb']>=2*resources['environment']['memory_mb'],'original_aggregate_broker_lease_required'
OUTPUTS = {
 'multilingual-video-dubbing': ['/outputs/dubbed.mp4','/outputs/report.json','/outputs/tts_segments/seg_0.wav'],
 'reserves-at-risk-calc': ['/root/output/rar_result.xlsx'],
}

def descriptor(task):
    assert task in TASKS
    row=json.loads((HOME/'task-descriptors'/f'{task}.json').read_bytes())
    for key in ('taskSourcePin','verifierRunnerPin'):
        assert public.pin(Path(row[key]['path']))==row[key]
    assert public.tree(VENDOR/'tasks'/task/'verifier')==row['verifierSource']
    return row

def prepare(task, output, candidate_image):
    row=descriptor(task);out=Path(output);out.mkdir(parents=True,exist_ok=False)
    assert re.fullmatch(r'sha256:[0-9a-f]{64}',candidate_image)
    shutil.copytree(VENDOR/'tasks'/task/'verifier',out/'verifier')
    shutil.copyfile(__file__,out/'adapter2_20261013_v1.py')
    # Each verifier keeps its original test.sh, assertions, dependency versions
    # and reward protocol. Runtime network cannot fetch candidate-selected code.
    deps={
      'fix-visual-stability':'RUN pip3 install --break-system-packages pytest==8.3.4 pytest-json-ctrf==0.5.2 playwright==1.49.1 Pillow==11.0.0 && python3 -m playwright install chromium\n',
      'multilingual-video-dubbing':'RUN /opt/venv/bin/python -m pip install pytest==9.0.2 pytest-json-ctrf==0.3.6 pysrt==1.1.2 numpy==1.26.4 soundfile==0.13.1\n',
      'reserves-at-risk-calc':'RUN pip3 install --break-system-packages pytest==8.4.1 pytest-json-ctrf==0.3.5 openpyxl==3.1.5\nRUN apt-get update && apt-get install -y curl gnumeric && curl -LsSf https://astral.sh/uv/0.9.7/install.sh | sh\nRUN /root/.local/bin/uvx --with pytest==8.4.1 --with pytest-json-ctrf==0.3.5 --with openpyxl==3.1.5 pytest --version\n',
    }[task]
    (out/'Dockerfile.private').write_text('FROM '+candidate_image+'\n'+deps+'COPY verifier/ /verifier/\nCOPY adapter2_20261013_v1.py /opt/objrun/private.py\nENTRYPOINT ["python3","-I","-B","/opt/objrun/private.py","--private","'+task+'"]\n')
    plugin='''import json
from pathlib import Path
rows=[]
nodes=[]
def pytest_collection_finish(session):
    nodes.extend(x.nodeid for x in session.items)
def pytest_runtest_logreport(report):
    rows.append({'nodeid':report.nodeid,'when':report.when,'outcome':report.outcome,'failureMessage':getattr(getattr(report.longrepr,'reprcrash',None),'message','') if report.failed else ''})
def pytest_sessionfinish(session,exitstatus):
    Path('/logs/verifier/native-outcome.json').write_text(json.dumps({'exitCode':int(exitstatus),'nodes':nodes,'reports':rows}))
'''
    (out/'outcome_plugin.py').write_text(plugin)
    docker=out/'Dockerfile.private';docker.write_text(docker.read_text().replace('COPY adapter2_20261013_v1.py', 'COPY outcome_plugin.py /opt/objrun/outcome_plugin.py\nCOPY adapter2_20261013_v1.py'))
    manifest={'protocol':ADAPTER+'-prepare','taskId':task,'adapter':ADAPTER,'candidateImageId':candidate_image,
      'originalResources':row['originalResources'],'workingDirectory':row['workdir'],'taskSourcePin':row['taskSourcePin'],
      'officialEnvironmentTree':row['environmentSource'],'verifierSource':row['verifierSource'],
      'privateRunnerSourcePin':public.pin(Path(__file__)),'sourcePins':[public.pin(Path(__file__))],
      'modelCalls':0,'native_ready':False,'registered':False,'privateImageId':None,
      'candidateBuildCommand':['docker','build','-f',str(VENDOR/'tasks'/task/'environment/Dockerfile'),str(VENDOR/'tasks'/task/'environment')],
      'privateBuildCommand':['docker','build','-f',str(out/'Dockerfile.private'),str(out)],
      'requiredAdmission':'existing sole broker lease; coordinator injects admitted command callback',
      'qualification':'qualify(command, built, controls, output) in this module; no model; no publication',
      'draftWorkerSource':str(Path(__file__).with_name('runtime_private_task_adapter2_20261013_v1.ts')),
      'draftStandSource':str(Path(__file__).with_name('data_stand_adapter2_20261013_v1.py'))}
    save(out/'preparation.json',manifest);return manifest

def replay_tar(task, raw_rows):
    blobs=[]
    for path, raw in raw_rows:
        assert path in OUTPUTS[task]
        cap=min(1024**3,descriptor(task)['originalResources']['environment']['storage_mb']*1024**2//len(OUTPUTS[task]))
        parsed=parse_daemon_tar(raw,Policy(task,path,path,'file',cap,1,True))
        blobs.extend(parsed['files'])
    assert len({b['destination'] for b in blobs})==len(blobs)
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as tar:
        for blob in blobs:
            member=tarfile.TarInfo(blob['destination'].lstrip('/'));member.size=len(blob['body']);member.mode=0o600
            tar.addfile(member,io.BytesIO(blob['body']))
    return stream.getvalue(),[{k:v for k,v in b.items() if k!='body'} for b in blobs]

def evaluate(command,cid,nonce,built,missing,mode='grade',owner_pid=None):
    task=built['taskId'];assert task in TASKS and mode in ('grade','collect')
    row=descriptor(task);assert built['originalResources']==row['originalResources']
    assert_lease(owner_pid,row['originalResources'])
    assert public.pin(Path(__file__))==built['privateRunnerSourcePin']
    assert re.fullmatch(r'sha256:[0-9a-f]{64}',built['privateImageId'])
    started=time.monotonic();owned=[];snapshot=None;owner=uuid.uuid4().hex
    def run(args,stdin=None,cap=16*1024**2):
        left=row['verifierSeconds']-(time.monotonic()-started)
        if left<=0:raise TimeoutError('original_combined_verifier_budget')
        return command(args,timeout=left,stdin=stdin,stdout_limit=cap)
    inspect=json.loads(run(['inspect',cid]))[0]
    assert not inspect['State']['Running'] and inspect['Image'] in [built['candidateImageId'],*built.get('controlImageIds',[])]
    assert inspect['Config']['Labels']['objrun.skb.nonce']==nonce
    assert not inspect['HostConfig'].get('Binds') and not inspect['HostConfig'].get('Mounts')
    e=row['originalResources']['environment']
    common=['--pull','never','--cap-drop','ALL','--security-opt','no-new-privileges','--memory',str(e['memory_mb']*1024**2),'--memory-swap',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus'])]
    manifest=[];absent=[]
    try:
        network='none'
        if task=='fix-visual-stability' and mode=='grade':
            snapshot=run(['commit','--change','LABEL objrun.skb.snapshot-owner='+owner,cid]).decode().strip()
            assert re.fullmatch(r'sha256:[0-9a-f]{64}',snapshot)
            # Original public build/start commands; no private tests or oracle
            # enter this snapshot. Full installed candidate deps are retained.
            shell='cd /api && npm start &\ncd /app\nnpm install\nnpm run build\nnpm start &\nwait'
            app=run(['create',*common,'--network',{'public':'bridge','no-network':'none'}[e['network_mode']],'--entrypoint','/bin/bash',snapshot,'-c',shell]).decode().strip();owned.append(app)
            run(['start',app]);network='container:'+app
        raw_rows=[]
        if task in OUTPUTS and mode=='grade':
            for path in OUTPUTS[task]:
                try:raw_rows.append((path,run(['cp',cid+':'+path,'-'],cap=e['storage_mb']*1024**2+18432)))
                except RuntimeError as error:
                    if not missing(error,cid,path):raise
                    absent.append(path)
        incoming,manifest=replay_tar(task,raw_rows) if task in OUTPUTS else (b'',[])
        gid=run(['create','-i',*common,'--network',network,'--workdir',row['workdir'],built['privateImageId'],'--mode',mode]).decode().strip();owned.append(gid)
        if incoming:
            run(['cp','-',gid+':/'],stdin=incoming)
        result=json.loads(run(['start','-a',gid]))
        assert result['taskId']==task and result['mode']==mode and result['complete']
        assert result['candidateExecutablesUsed'] is False and result['candidateSnapshotUsed'] is False
        return {'result':result,'artifactManifest':manifest,'missingArtifactPaths':absent,'candidateExecutionSnapshotUsed':snapshot is not None,
          'candidateSnapshotUsedForTrustedGrader':False,'elapsedSeconds':time.monotonic()-started,'modelCalls':0}
    finally:
        errors=[]
        for container in reversed(owned):
            try:command(['rm','-f',container])
            except Exception as error:errors.append(str(error))
        if snapshot:
            try:
                image=json.loads(command(['image','inspect',snapshot]))[0]
                assert image['Config']['Labels']['objrun.skb.snapshot-owner']==owner
                command(['image','rm',snapshot])
            except Exception as error:errors.append(str(error))
        if errors:raise RuntimeError('owned_resource_cleanup_failed: '+repr(errors))

def validate_outcome(nodes,outcome,reward):
    assert outcome['exitCode'] in (0,1),'original_pytest_infrastructure_failure'
    assert outcome['nodes']==nodes,'original_node_collection_changed'
    calls=[r for r in outcome['reports'] if r['when']=='call']
    setups={r['nodeid']:r for r in outcome['reports'] if r['when']=='setup'}
    assert set(setups)==set(nodes)
    expected_calls=[]
    for node in nodes:
        setup=setups[node]
        if setup['outcome']=='passed':expected_calls.append(node)
        else:
            assert setup['outcome']=='failed' and any(marker in setup['failureMessage'] for marker in ('AssertionError','Failed:')),'original_fixture_infrastructure_fault_or_skip'
    assert [r['nodeid'] for r in calls]==expected_calls and all(r['outcome'] in ('passed','failed') for r in calls),'original_call_missing_or_skipped'
    assert all(r['outcome']=='passed' for r in outcome['reports'] if r['when']=='teardown'),'original_teardown_failed'
    assert reward==float(outcome['exitCode']==0),'original_reward_exit_disagreement'

def private(task,mode):
    # Runs only inside immutable trusted image. Original test files untouched.
    import subprocess
    import sys
    logs=Path('/logs/verifier');logs.mkdir(parents=True,exist_ok=True)
    nodes=[]
    import pytest
    class Witness:
        def pytest_collection_finish(self,session):nodes.extend(x.nodeid for x in session.items)
    # Use pytest's collection hook to retain parameterized node IDs exactly.
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        code=pytest.main(['--collect-only','-q','/verifier/test_outputs.py'],plugins=[Witness()])
    assert code==0 and nodes
    reward=None;passed=failed=0
    if mode=='grade':
        if task=='fix-visual-stability':
            # Browser startup is candidate execution. Trusted original tests
            # connect via loopback in that isolated network namespace.
            wait='until curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 | grep -q "200"; do sleep 1; done'
            subprocess.run(['/bin/bash','-c',wait],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            proc=subprocess.run([sys.executable,'-m','pytest','--ctrf',str(logs/'ctrf.json'),'/verifier/test_outputs.py','-rA','-v'],capture_output=True,text=True,env={**__import__('os').environ,'PYTHONPATH':'/opt/objrun','PYTEST_PLUGINS':'outcome_plugin'})
            reward=float(proc.returncode==0)
        else:
            proc=subprocess.run(['/bin/bash','/verifier/test.sh'],capture_output=True,text=True,env={**__import__('os').environ,'UV_OFFLINE':'1','PYTHONPATH':'/opt/objrun','PYTEST_PLUGINS':'outcome_plugin'})
            if proc.returncode:raise RuntimeError('original_runner_failed: '+proc.stderr)
            reward=float((logs/'reward.txt').read_text().strip())
        report=json.loads((logs/'ctrf.json').read_bytes())['results']
        actual=[t['name'] for t in report['tests']]
        assert len(actual)==len(nodes),'original_test_count_changed'
        outcome=json.loads((logs/'native-outcome.json').read_bytes())
        validate_outcome(nodes,outcome,reward)
        passed=report['summary']['passed'];failed=report['summary']['failed']
        assert reward in (0,1)
    print(json.dumps({'taskId':task,'mode':mode,'complete':True,'nodeIds':nodes,'reward':reward,'passedTests':passed,'failedTests':failed,
      'candidateExecutablesUsed':False,'candidateSnapshotUsed':False,'originalVerifierUnmodified':True}))

def qualify(command,built,controls,output,owner_pid):
    """Coordinator owns lease and candidate controls; no oracle replay here.

    controls is three exact stopped containers from independently prepared
    missing/reference/wrong controls, each (cid, nonce, missing_callback).
    """
    assert len(controls)==3
    collection=evaluate(command,*controls[0][:2],built,controls[0][2],mode='collect',owner_pid=owner_pid)
    rows=[evaluate(command,cid,nonce,built,missing,owner_pid=owner_pid) for cid,nonce,missing in controls]
    assert [r['result']['reward'] for r in rows]==[0,1,0]
    assert all(r['result']['nodeIds']==collection['result']['nodeIds'] for r in rows)
    destination=Path(output);evidence=destination.parent/(destination.stem+'-evidence');evidence.mkdir(parents=True,exist_ok=False)
    built_pin=save(evidence/'built-images.json',built)
    collection_pin=save(evidence/'collection.json',collection['result'])
    case_pins=[save(evidence/(name+'.json'),result['result']) for name,result in zip(('empty','oracle','wrong'),rows)]
    value={'protocol':ADAPTER+'-controls','taskId':built['taskId'],'controlsPassed':True,'decisions':[0,1,0],
      'builtImagesPin':built_pin,'collectionPin':collection_pin,'emptyPin':case_pins[0],'oraclePin':case_pins[1],'wrongPin':case_pins[2],
      'collection':collection,'cases':rows,'modelCalls':0,'ownedContainersRemaining':0,
      'native_ready':False,'remaining':'six-tools and full Stand up/begin/place/ran/passed/close acceptance required'}
    save(destination,value);return value

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--private',choices=TASKS);parser.add_argument('--mode',choices=['grade','collect'],default='grade')
    parser.add_argument('--prepare',choices=TASKS);parser.add_argument('--output');parser.add_argument('--candidate-image')
    args=parser.parse_args()
    if args.private:private(args.private,args.mode)
    elif args.prepare:print(json.dumps(prepare(args.prepare,args.output,args.candidate_image)))
    else:parser.error('choose --private or --prepare')
