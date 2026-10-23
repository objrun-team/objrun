"""Same-run latest verify control through the new stand; zero models, no score."""
import base64
import hashlib
import json
import os
from pathlib import Path
import uuid
from prepare import HOME,public,save,utc
from ordinary_artifacts import Policy,parse_daemon_tar
from data_stand import Stand
import data_stand
import bounded_child
import task_skills
import control_cleanup
import docker_mutation_ack

def main():
    tid='3d-scan-calc';home=HOME/'state-refresh-controls'/uuid.uuid4().hex;home.mkdir(parents=True)
    bp=json.loads((HOME/'environment-preparation'/tid/'latest.json').read_bytes())['builtImagesPin']
    cp=json.loads((HOME/'grader-controls'/tid/'latest.json').read_bytes())['controlPin']
    built=json.loads(Path(bp['path']).read_bytes());control=json.loads(Path(cp['path']).read_bytes())
    assert public.pin(Path(bp['path']))==bp and public.pin(Path(cp['path']))==cp and control['builtImagesPin']==bp and control['controlsPassed']
    path=built['dataArtifactPolicy']['output'];correct=None
    for pin in control['commandPins']:
        assert public.pin(Path(pin['path']))==pin
        command=json.loads(Path(pin['path']).read_bytes());argv=command['argv']
        if len(argv)>=4 and argv[-1]=='-' and argv[-2].endswith(':'+path) and argv[-3]=='cp':
            source=command['stdoutPin'];assert public.pin(Path(source['path']))==source
            correct=parse_daemon_tar(Path(source['path']).read_bytes(),Policy(tid,path,path,'file',8*1024**2,1,True))['files'][0]['body']
    assert correct is not None and hashlib.sha256(correct).hexdigest()==control['oracleArtifactSha256']
    manifest=json.loads((HOME/'manifest.json').read_bytes());row=next(r for r in manifest['taskSchedule'] if r['taskId']==tid)
    run_id='repair-'+uuid.uuid4().hex;previous=os.environ.get('TGENGIN_GRADER_TOKEN');os.environ['TGENGIN_GRADER_TOKEN']=uuid.uuid4().hex+uuid.uuid4().hex
    row={**row,'id':'skb-'+hashlib.sha256((run_id+'/'+tid).encode()).hexdigest()[:32]}
    stand=None;result={'protocol':'skillsbench-full-f-same-run-state-refresh-control-v1','taskId':tid,'createdAtUtc':utc(),
        'scope':'one-task zero-model isolation control; not full F result','modelCalls':0,'scoreCertificate':False,'verified':False,'steps':[]}
    result['sourcePins']=[public.pin(Path(data_stand.__file__)),public.pin(Path(bounded_child.__file__)),public.pin(Path(task_skills.__file__)),public.pin(Path(control_cleanup.__file__)),public.pin(Path(docker_mutation_ack.__file__)),public.pin(Path(__file__))]
    try:
        stand=Stand({'output':str(home),'runId':run_id,'schedule':[row],'taskReadiness':{tid:{'builtImagesPin':bp,'controlPin':cp}}})
        place='skb:'+row['id']
        deployment=stand.call({'place':place,'op':'ping'})['skillsDeploymentPin']
        proof=json.loads(Path(deployment['path']).read_bytes());assert public.pin(Path(deployment['path']))==deployment and proof['verified']
        skill_read=stand.call({'place':place,'tool':'read','args':{'file_path':proof['metadata'][0]['location']}})
        assert not skill_read.get('isError') and 'mesh-analysis' in json.dumps(skill_read),'original_skill_read_failed'
        helper=stand.call({'place':place,'tool':'bash','args':{'command':"python3 -c \"import sys;sys.path.append('/root/.claude/skills/mesh-analysis/scripts');from mesh_tool import MeshAnalyzer;print(MeshAnalyzer('/root/scan_data.stl').analyze_largest_component())\"",'timeout_ms':30000}})
        assert not helper.get('isError') and 'main_part_volume' in json.dumps(helper),'original_skill_helper_failed'
        result.update(skillsDeploymentPin=deployment,skillsReadVerified=True,skillsHelperExecuted=True,skillsToolReceipts=[skill_read,helper])
        for body in [b'{}\n',correct,b'{}\n']:
            encoded=base64.b64encode(body).decode()
            command="python3 -c \"import base64,pathlib;pathlib.Path('"+path+"').write_bytes(base64.b64decode('"+encoded+"'))\""
            stand.call({'place':place,'tool':'bash','args':{'command':command,'timeout_ms':30000}})
            query={'place':place,'said':'fixed-answer-label'}
            verified=stand.grade(query,'verified');passed=stand.grade(query,'passed')
            assert verified['gradeOwnerPin']==passed['gradeOwnerPin'] and verified['verified']
            result['steps'].append({'reward':json.loads(verified['note'])['reward'],'artifactSha256':hashlib.sha256(body).hexdigest(),'gradeOwnerPin':verified['gradeOwnerPin']})
        result['verified']=[s['reward'] for s in result['steps']]==[0,1,0] and len({s['gradeOwnerPin']['path'] for s in result['steps']})==3
        result['shortEngineIdMappingVerified']=True
        result['opaqueInterruptionSnapshotControl']=stand.retain_interruption()
        assert result['opaqueInterruptionSnapshotControl']['usedForTrustedGrader'] is False
        assert all(public.pin(Path(pin['path']))==pin for pin in result['sourcePins'])
        assert result['verified']
    except Exception as error:
        result['failure']={'type':type(error).__name__,'detail':str(error)};raise
    finally:
        cleanup_error=control_cleanup.capture(result,stand)
        if previous is None:os.environ.pop('TGENGIN_GRADER_TOKEN',None)
        else:os.environ['TGENGIN_GRADER_TOKEN']=previous
        pin=save(home/'result.json',result,True);save(HOME/'state-refresh-controls/latest.json',{'resultPin':pin})
        print(json.dumps({'resultPin':pin,'verified':result['verified'],'modelCalls':0}))
        if cleanup_error is not None and 'failure' not in result:raise cleanup_error

if __name__=='__main__':main()
