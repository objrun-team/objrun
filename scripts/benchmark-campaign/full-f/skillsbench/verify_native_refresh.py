"""Actual same-candidate missing/helper/dependency refresh; zero model calls."""
import base64
import hashlib
import json
import os
from pathlib import Path
import uuid
from prepare import HOME,public,save,utc
from code_values import TASK,SOURCE,source_from_daemon_tar
from data_stand import Stand
import data_stand
import bounded_child
import snapshot_function_adapter
import candidate_snapshot_exec
import stream_code_digest
import control_cleanup
import docker_mutation_ack

def main():
    home=HOME/'native-snapshot-refresh-controls'/uuid.uuid4().hex;home.mkdir(parents=True)
    bp=json.loads((HOME/'code-environment-preparation'/TASK/'latest.json').read_bytes())['builtImagesPin']
    cp=json.loads((HOME/'code-grader-controls'/TASK/'latest.json').read_bytes())['controlPin']
    assert public.pin(Path(bp['path']))==bp and public.pin(Path(cp['path']))==cp
    control=json.loads(Path(cp['path']).read_bytes());assert control['controlsPassed'] and control['builtImagesPin']==bp
    source=None
    for pin in control['commandPins']:
        assert public.pin(Path(pin['path']))==pin
        command=json.loads(Path(pin['path']).read_bytes());argv=command['argv']
        if len(argv)>=4 and argv[-1]=='-' and argv[-2].endswith(':'+SOURCE) and argv[-3]=='cp':
            raw=command['stdoutPin'];assert public.pin(Path(raw['path']))==raw
            source=source_from_daemon_tar(Path(raw['path']).read_bytes())
    assert source is not None and hashlib.sha256(source).hexdigest()==control['oracleCodeSha256']
    row=next(r for r in json.loads((HOME/'manifest.json').read_bytes())['taskSchedule'] if r['taskId']==TASK)
    run_id='repair-'+uuid.uuid4().hex;place='skb:'+run_id+'/skillsbench/F/0/'+TASK
    previous=os.environ.get('TGENGIN_GRADER_TOKEN');os.environ['TGENGIN_GRADER_TOKEN']=uuid.uuid4().hex+uuid.uuid4().hex
    result={'protocol':'skillsbench-full-f-native-snapshot-refresh-controls-v1','taskId':TASK,'createdAtUtc':utc(),'modelCalls':0,'scoreCertificate':False,
        'verified':False,'candidateEnvironmentParityVerified':False,'originalVerifierBudgetVerified':False,'storageBudgetParityVerified':False,
        'scope':'Zero-model native integration controls; source transport/storage parity and full runtime financial lifecycle still pending','steps':[]}
    modules=[data_stand,bounded_child,snapshot_function_adapter,candidate_snapshot_exec,stream_code_digest,control_cleanup,docker_mutation_ack]
    result['sourcePins']=[public.pin(Path(m.__file__)) for m in modules]+[public.pin(Path(__file__)),public.pin(Path(__file__).with_name('code_values.py'))]
    stand=None
    def mutate(paths):
        payload=base64.b64encode(json.dumps({name:base64.b64encode(body).decode() for name,body in paths.items()}).encode()).decode()
        script="import base64,json,pathlib,site; data=json.loads(base64.b64decode('"+payload+"')); [(pathlib.Path(site.getsitepackages()[0])/name[6:] if name.startswith('@site/') else pathlib.Path(name)).write_bytes(base64.b64decode(body)) for name,body in data.items()]"
        stand.call({'place':place,'tool':'bash','args':{'command':'python3 -c "'+script+'"','timeout_ms':30000}})
    def grade(label):
        query={'place':place,'said':'same-native-answer-label'}
        verified=stand.grade(query,'verified');passed=stand.grade(query,'passed');assert verified['gradeOwnerPin']==passed['gradeOwnerPin'] and verified['verified']
        pin=verified['gradeOwnerPin'];assert public.pin(Path(pin['path']))==pin
        receipt=json.loads(Path(pin['path']).read_bytes());assert receipt['candidateSnapshotUsedForTrustedGrader'] is False and receipt['candidateInterpreterUsedForTrustedGrader'] is False
        result['steps'].append({'label':label,'reward':receipt['result']['reward'],'gradeOwnerPin':pin,'sourceSha256':receipt['sourceSha256'],
            'sourceBytes':receipt['sourceBytes'],'originalStorageBytes':receipt['originalStorageBytes'],'sourceDigestReceiptPin':receipt['sourceDigestReceiptPin'],
            'candidateExecutionSnapshotUsed':receipt['candidateExecutionSnapshotUsed'],'sourceCaptureState':receipt['sourceCaptureState'],'elapsedSeconds':receipt['elapsedSeconds']})
    try:
        stand=Stand({'output':str(home),'runId':run_id,'schedule':[row],'taskReadiness':{TASK:{'adapter':'wyckoff-function-native-v1','builtImagesPin':bp,'controlPin':cp}}})
        stand.call({'place':place,'op':'ping'});grade('missing-source')
        mutate({'/root/workspace/native_helper.py':source,'@site/native_dependency.py':b'from native_helper import analyze_wyckoff_position_multiplicities_and_coordinates\n',
            SOURCE:b'from native_dependency import analyze_wyckoff_position_multiplicities_and_coordinates\n'})
        stand.call({'place':place,'tool':'bash','args':{'command':'python3 -c "from pathlib import Path; p=Path(\'/root/workspace/solution.py\'); p.write_bytes(p.read_bytes()+b\'# original-storage streaming control\\n\'*32768)"','timeout_ms':30000}})
        grade('helper-and-installed-dependency')
        mutate({'@site/native_dependency.py':b'def analyze_wyckoff_position_multiplicities_and_coordinates(filepath):\n    return {}\n'})
        grade('changed-dependency-same-entry-source')
        assert [s['reward'] for s in result['steps']]==[0,1,0]
        assert result['steps'][1]['sourceSha256']==result['steps'][2]['sourceSha256']
        assert result['steps'][1]['sourceBytes']>512*1024
        assert all(s['originalStorageBytes']==row['originalResources']['environment']['storage_mb']*1024**2 for s in result['steps'])
        assert len({s['gradeOwnerPin']['path'] for s in result['steps']})==3
        assert result['steps'][0]['sourceCaptureState']=='absent' and not result['steps'][0]['candidateExecutionSnapshotUsed']
        assert all(s['elapsedSeconds']<=row['verifierSeconds'] for s in result['steps'])
        assert all(public.pin(Path(p['path']))==p for p in result['sourcePins'])
        result.update(verified=True,candidateEnvironmentParityVerified=True,originalVerifierBudgetVerified=True,storageBudgetParityVerified=True)
    except Exception as error:
        result['failure']={'type':type(error).__name__,'detail':str(error)}
        result['uncleanExecutionResources']=getattr(error,'ownedResourcesRemaining',[]);raise
    finally:
        cleanup_error=control_cleanup.capture(result,stand)
        if cleanup_error is None:
            result['ownedResourcesRemaining']=len(result.get('uncleanExecutionResources',[]))+result['solverClosure']['ownedContainersRemaining'] if stand else None
        if previous is None:os.environ.pop('TGENGIN_GRADER_TOKEN',None)
        else:os.environ['TGENGIN_GRADER_TOKEN']=previous
        pin=save(home/'result.json',result,True);save(HOME/'native-snapshot-refresh-controls/latest.json',{'resultPin':pin})
        print(json.dumps({'resultPin':pin,'verified':result['verified'],'modelCalls':0}))
        if cleanup_error is not None and 'failure' not in result:raise cleanup_error

if __name__=='__main__':main()
