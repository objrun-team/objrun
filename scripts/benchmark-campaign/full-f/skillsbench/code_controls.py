"""Actual isolated candidate-function/native-script controls, not model scores."""
import base64
import hashlib
import json
from pathlib import Path
import uuid
from prepare import HOME,VENDOR,public,save,utc
from build_environment import DOCKER,ENV
from bounded_child import run
from code_values import TASK,PROTOCOL,SOURCE,decode_values,source_from_daemon_tar

def main():
    bp=json.loads((HOME/'code-environment-preparation'/TASK/'latest.json').read_bytes())['builtImagesPin'];assert public.pin(Path(bp['path']))==bp
    built=json.loads(Path(bp['path']).read_bytes());assert built['imagesBuilt']
    for pin in built['sourcePins']:assert public.pin(Path(pin['path']))==pin
    home=HOME/'code-grader-controls'/TASK/uuid.uuid4().hex;home.mkdir(parents=True);serial=0;owned=[];commands=[]
    resources=built['originalResources'];env=resources['environment']
    def command(argv,timeout,stdin=None,limit=16*1024**2):
        nonlocal serial
        serial+=1;prefix=home/('command-%03d'%serial);outcome=run([DOCKER,*argv],ENV,prefix.with_suffix('.stdout'),prefix.with_suffix('.stderr'),timeout,stdin,stdout_limit=limit)
        pin=save(prefix.with_suffix('.json'),{'argv':[DOCKER,*argv],**outcome,'stdoutPin':public.pin(prefix.with_suffix('.stdout')),'stderrPin':public.pin(prefix.with_suffix('.stderr')),'modelCalls':0});commands.append(pin)
        if outcome['exitCode'] or outcome['faults']:raise RuntimeError('isolated code control failed: '+pin['path'])
        return prefix.with_suffix('.stdout').read_bytes()
    def create(argv):
        cid=command(['create',*argv],30).decode().strip();assert len(cid)==64 and all(c in '0123456789abcdef' for c in cid);owned.append(cid);return cid
    def remove(cid):command(['rm','-f',cid],30);owned.remove(cid)
    common=['--pull','never','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--memory',str(env['memory_mb']*1024**2),'--memory-swap',str(env['memory_mb']*1024**2),'--cpus',str(env['cpus']),'--workdir',built['workingDirectory']]
    def evaluate(source,mode='grade'):
        sha=hashlib.sha256(source).hexdigest()
        if mode=='collect':values={'protocol':PROTOCOL,'candidateSourceSha256':sha,'calls':[]}
        else:
            cid=create(['-i','--read-only',*common,'--tmpfs','/root/workspace:rw,nosuid,nodev,noexec,size=8m','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=64m',built['executionImageId']])
            public_inputs={Path(p).name:h for p,h in built['publicInputs'].items()}
            raw=command(['start','-a','-i',cid],resources['verifier']['timeout_sec'],json.dumps({'candidateSourceBase64':base64.b64encode(source).decode(),'candidateSourceSha256':sha,'publicInputs':public_inputs}).encode(),2*1024**2)
            values=decode_values(raw,sha,built['publicInputs']);remove(cid)
        cid=create(['-i','--read-only',*common,'--tmpfs','/logs/verifier:rw,nosuid,nodev,noexec,size=64m','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=64m',built['privateImageId'],*(['--collect'] if mode=='collect' else [])])
        inspect=json.loads(command(['inspect',cid],30))[0];h=inspect['HostConfig']
        assert inspect['Image']==built['privateImageId'] and h['ReadonlyRootfs'] and h['NetworkMode']=='none' and not h.get('Binds') and not h.get('Privileged')
        result=json.loads(command(['start','-a','-i',cid],resources['verifier']['timeout_sec'],json.dumps(values).encode()))
        assert result['complete'] and result['taskId']==TASK and not result['candidateExecutablesUsed'] and not result['candidateSnapshotUsed']
        result['privateContainerInspect']=inspect;pin=save(home/(mode+'-'+uuid.uuid4().hex+'.json'),result,True);remove(cid);return result,pin
    source_pins=[public.pin(Path(__file__)),public.pin(Path(__file__).with_name('bounded_child.py')),public.pin(Path(__file__).with_name('code_values.py'))]
    result={'protocol':'skillsbench-full-f-isolated-code-controls-v1','taskId':TASK,'createdAtUtc':utc(),'builtImagesPin':bp,'sourcePins':source_pins,'controlsPassed':False,'modelCalls':0,'scoreCertificate':False}
    try:
        collection,colp=evaluate(b'','collect');empty,ep=evaluate(b'')
        oracle=VENDOR/'tasks'/TASK/'oracle/solve.sh'
        cid=create([*common,'--entrypoint','/bin/bash',built['candidateImageId'],'/opt/original-oracle.sh'])
        command(['cp',str(oracle),cid+':/opt/original-oracle.sh'],30);command(['start','-a',cid],resources['agent']['timeout_sec'])
        source=source_from_daemon_tar(command(['cp',cid+':'+SOURCE,'-'],30,limit=512*1024+32*1024));remove(cid)
        correct,op=evaluate(source)
        wrong,wp=evaluate(b'def analyze_wyckoff_position_multiplicities_and_coordinates(filepath):\n    return {}\n')
        decisions=[r['reward'] for r in (empty,correct,wrong)]
        result.update(collectionPin=colp,emptyPin=ep,oraclePin=op,wrongPin=wp,originalOraclePin=public.pin(oracle),decisions=decisions,
            actualPytestCollection=collection['nodeIds'],nativeCaseCount=collection['nativeCaseCount'],oracleCodeSha256=hashlib.sha256(source).hexdigest(),controlsPassed=decisions==[0,1,0],candidateInterpreterUsedForTrustedGrader=False)
        assert result['controlsPassed']
    except Exception as error:result['failure']={'type':type(error).__name__,'detail':str(error)};raise
    finally:
        for cid in owned[:]:
            try:remove(cid)
            except Exception:pass
        if not all(public.pin(Path(p['path']))==p for p in source_pins):
            result['controlsPassed']=False;result['failure']={'type':'SourceDrift','detail':'Code control source changed during execution'}
        result.update(ownedContainersRemaining=len(owned),commandPins=commands)
        pin=save(home/'result.json',result,True);save(HOME/'code-grader-controls'/TASK/'latest.json',{'controlPin':pin});print(json.dumps({'controlPin':pin,'controlsPassed':result['controlsPassed'],'modelCalls':0}))

if __name__=='__main__':main()
