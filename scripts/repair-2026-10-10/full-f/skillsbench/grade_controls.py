"""Actual source-pinned original pytest collection + empty/oracle/wrong controls.

This prepares a task, not a model score. Every grade uses a fresh separate image
container, with read-only root, no network and no host mounts. Only opaque
ordinary output bytes move from the oracle container into private grading.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid
from prepare import ROOT,HOME,VENDOR,public,save,utc
from build_environment import DOCKER,ENV
from ordinary_artifacts import Policy,parse_daemon_tar
from bounded_child import run as bounded_run
from docker_mutation_ack import require as require_docker_mutation_ack

def main():
    p=argparse.ArgumentParser();p.add_argument('--task',required=True);a=p.parse_args()
    pointer=json.loads((HOME/'environment-preparation'/a.task/'latest.json').read_bytes())['builtImagesPin']
    if public.pin(Path(pointer['path']))!=pointer:raise ValueError('built image proof drift')
    built=json.loads(Path(pointer['path']).read_bytes())
    runner=Path(built['privateRunnerSourcePin']['path'])
    if runner.parent!=Path(__file__).parent or runner.name not in ('private_eval.py','private_eval_v2.py','private_eval_multi.py','private_eval_score.py'):raise ValueError('foreign private runner')
    if public.pin(runner)!=built['privateRunnerSourcePin']:raise ValueError('private runner changed since image build')
    home=HOME/'grader-controls'/a.task/uuid.uuid4().hex;home.mkdir(parents=True)
    serial=0;containers=[];command_pins=[]
    def command(args,timeout,stdin_body=None,stdout_limit=16*1024**2,allow_missing_path=None):
        nonlocal serial
        serial+=1;prefix=home/('command-%03d'%serial);began=utc()
        outcome=bounded_run([DOCKER,*args],ENV,prefix.with_suffix('.stdout'),prefix.with_suffix('.stderr'),timeout,stdin_body,stdout_limit=stdout_limit)
        code=outcome['exitCode']
        missing=False
        if allow_missing_path and code!=0 and not outcome['faults']:
            cid,path=allow_missing_path
            diagnostic=prefix.with_suffix('.stderr').read_text(errors='replace').strip()
            missing=diagnostic=='Error response from daemon: Could not find the file '+path+' in container '+cid
        record=save(prefix.with_suffix('.json'),{'argv':[DOCKER,*args],**outcome,'childPid':outcome['pid'],'parentPid':os.getpid(),'missingArtifact':missing,'beganAtUtc':began,'finishedAtUtc':utc(),
            'stdoutPin':public.pin(prefix.with_suffix('.stdout')),'stderrPin':public.pin(prefix.with_suffix('.stderr')),'modelCalls':0})
        command_pins.append(record)
        if outcome['faults'] or not outcome['directChildClosed'] or not outcome['pipeReadersClosed']:raise RuntimeError('Docker control capture fault: '+str(record['path']))
        if missing:return None
        if code!=0:raise RuntimeError('Docker original grader operation failed: '+str(record['path']))
        output=prefix.with_suffix('.stdout').read_bytes()
        require_docker_mutation_ack(args,output)
        return output
    def own_create(argv):
        cid=command(argv,30).decode().strip()
        if len(cid)!=64 or any(c not in '0123456789abcdef' for c in cid):raise ValueError('invalid owned container identity')
        containers.append(cid);return cid
    def remove(cid):
        command(['rm','-f',cid],30);containers.remove(cid)
    resources=built['originalResources'];e=resources['environment']
    def private(mode,body=None):
        cid=own_create(['create','-i','--pull','never','--read-only','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--label','objrun.skb.role=full-f-private-control','--label','objrun.skb.task-id='+a.task,
            '--memory',str(e['memory_mb']*1024**2),'--memory-swap',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus']),
            '--tmpfs','/logs/verifier:rw,nosuid,nodev,noexec,size=64m','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=64m',
            *[arg for parent in built.get('artifactTmpfsParents',[built['artifactTmpfsParent']]) for arg in ['--tmpfs',parent+':rw,nosuid,nodev,noexec,size='+str(built['artifactTmpfsBytes'])]],
            '--workdir',built['workingDirectory'],built['privateImageId'],*( ['--collect'] if mode=='collect' else [])])
        incoming={'artifacts':[] if body is None else body if isinstance(body,list) else [{'path':built['dataArtifactPolicy']['output'],'base64':base64.b64encode(body).decode(),'sha256':hashlib.sha256(body).hexdigest()}]}
        inspect=json.loads(command(['inspect',cid],30))[0]
        h=inspect['HostConfig']
        if inspect['Image']!=built['privateImageId'] or not h['ReadonlyRootfs'] or h['NetworkMode']!='none' or h.get('Binds') or h.get('Mounts') or h.get('Privileged'):
            raise ValueError('private namespace substitution')
        raw=command(['start','-a','-i',cid],resources['verifier']['timeout_sec'],json.dumps(incoming).encode());result=json.loads(raw)
        if not result['complete'] or result['taskId']!=a.task or result['candidateExecutablesUsed'] or result['candidateSnapshotUsed']:
            raise ValueError('original complete grader result missing')
        result['containerId']=cid;result['imageId']=built['privateImageId'];result['inspect']=inspect
        pin=save(home/(mode+'-'+uuid.uuid4().hex+'.json'),result,True);remove(cid)
        return result,pin
    result={'protocol':'skillsbench-full-f-actual-grader-controls-v1','taskId':a.task,'createdAtUtc':utc(),'builtImagesPin':pointer,'modelCalls':0,'scoreCertificate':False,'controlsPassed':False}
    try:
        collection,collection_pin=private('collect')
        empty,empty_pin=private('empty')
        oracle=VENDOR/'tasks'/a.task/'oracle/solve.sh'
        cid=own_create(['create','--pull','never','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--label','objrun.skb.role=full-f-oracle-control','--memory',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus']),
            '--entrypoint','/bin/bash',built['candidateImageId'],'/oracle/solve.sh'])
        # This container is a private preparation oracle, never the model's solver.
        command(['cp',str(oracle.parent),cid+':/'],30)
        command(['start','-a',cid],resources['agent']['timeout_sec'])
        artifacts=[];missing=[]
        for output in built.get('outputPolicies',[{'path':built['dataArtifactPolicy']['output'],'kind':'file','maximumFiles':1,'maximumBytes':8*1024**2}]):
            path=output['path']
            tar=command(['cp',cid+':'+path,'-'],30,stdout_limit=output['maximumBytes']+(output['maximumFiles']+8)*2048,allow_missing_path=(cid,path))
            if tar is None:
                missing.append(path);continue
            envelope=parse_daemon_tar(tar,Policy(a.task,path,path,output['kind'],output['maximumBytes'],output['maximumFiles'],True,'csv' if built['dataArtifactPolicy'].get('format')=='CSV' and output['kind']=='file' else None))
            artifacts += [{'path':f['destination'],'base64':base64.b64encode(f['body']).decode(),'sha256':f['sha256']} for f in envelope['files']]
        remove(cid)
        result['oracleMissingArtifactPaths']=missing
        if not artifacts:raise ValueError('original oracle produced no approved artifact')
        body=base64.b64decode(artifacts[0]['base64'])
        correct,correct_pin=private('oracle',artifacts)
        # Explicit malformed ordinary data, never a computed oracle replacement.
        # JSON {} can trigger deliberate skip branches in original tests. Use a
        # genuinely malformed ordinary artifact for v2: actual parser/fixture
        # failures are retained, without skipping any collected node.
        wrong_payload=b'{}\n' if a.task=='3d-scan-calc' else b'not-a-valid-task-artifact\n'
        if a.task=='court-form-filling':
            assert body.count(b'Joyce He')>0,'structured_pdf_negative_missing_public_name'
            wrong_payload=body.replace(b'Joyce He',b'Wrong XX')
            result['wrongFixtureConstructor']='same-length incorrect public plaintiff name in private oracle PDF; checkbox structure preserved'
        wrong_artifacts=[{'path':f['path'],'base64':base64.b64encode(wrong_payload).decode(),'sha256':hashlib.sha256(wrong_payload).hexdigest()} for f in artifacts]
        wrong,wrong_pin=private('wrong',wrong_artifacts)
        nodes=collection['nodeIds']
        decisions=[empty['reward'],correct['reward'],wrong['reward']]
        result.update(collectionPin=collection_pin,emptyPin=empty_pin,oraclePin=correct_pin,wrongPin=wrong_pin,
            originalOraclePin=public.pin(oracle),oracleArtifactSha256=hashlib.sha256(body).hexdigest(),
            oracleArtifactManifest=[{'path':f['path'],'sha256':f['sha256']} for f in artifacts],
            decisions=decisions,controlsPassed=decisions==[0,1,0] and all(r['nodeIds']==nodes for r in (empty,correct,wrong)),
            candidateOutputRegularOnly=True,originalTestsUnchanged=True,namespaceSeparation=True)
        if not result['controlsPassed']:raise ValueError('original empty/oracle/wrong controls differ')
    except Exception as error:
        result['failure']={'type':type(error).__name__,'detail':str(error)}
        raise
    finally:
        for cid in containers[:]:
            try:remove(cid)
            except Exception:pass
        result['ownedContainersRemaining']=len(containers);result['commandPins']=command_pins
        pin=save(home/'result.json',result,True)
        save(HOME/'grader-controls'/a.task/'latest.json',{'controlPin':pin})
        print(json.dumps({'taskId':a.task,'controlPin':pin,'controlsPassed':result['controlsPassed'],'modelCalls':0}))

if __name__=='__main__':main()
