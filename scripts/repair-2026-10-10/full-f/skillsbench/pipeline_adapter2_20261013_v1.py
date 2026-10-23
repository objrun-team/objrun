"""Bounded native build/control pipeline, invoked only by leased TS launcher."""
import argparse
import json
from pathlib import Path
import uuid
from adapter2_20261013_v1 import TASKS, descriptor, prepare, qualify, evaluate, assert_lease, public, save, ROOT, VENDOR
from build_environment import DOCKER, ENV
from bounded_child import run as bounded_run
from apt_build_proxy import build_args
from docker_mutation_ack import require

class Transport:
    def __init__(self,home,owner,resources):
        self.home=home;self.owner=owner;self.resources=resources;self.serial=0;self.last=None
    def command(self,args,timeout=30,stdin=None,stdout_limit=16*1024**2):
        assert_lease(self.owner,self.resources)
        self.serial+=1;prefix=self.home/('command-%06d'%self.serial);self.last=prefix
        result=bounded_run([DOCKER,*args],ENV,prefix.with_suffix('.stdout'),prefix.with_suffix('.stderr'),timeout,stdin,stdout_limit=stdout_limit)
        save(prefix.with_suffix('.json'),{'argv':[DOCKER,*args],**result,'stdoutPin':public.pin(prefix.with_suffix('.stdout')),'stderrPin':public.pin(prefix.with_suffix('.stderr')),'modelCalls':0})
        if result['exitCode'] or result['faults']:raise RuntimeError('bounded_docker_operation_failed: '+str(prefix))
        output=prefix.with_suffix('.stdout').read_bytes();require(args,output);return output
    def missing(self,error,cid,path):
        record=json.loads(self.last.with_suffix('.json').read_bytes())
        diagnostic=self.last.with_suffix('.stderr').read_text(errors='replace').strip()
        return record['exitCode']!=0 and not record['faults'] and diagnostic=='Error response from daemon: Could not find the file '+path+' in container '+cid

def pipeline(task,home,owner,stage,allow_oracle=False):
    row=descriptor(task);source=VENDOR/'tasks'/task;before=public.tree(source)
    home=Path(home);home.mkdir(parents=True,exist_ok=True);run=home/uuid.uuid4().hex;run.mkdir()
    transport=Transport(run,owner,row['originalResources']);command=transport.command
    e=row['originalResources']['environment'];checkpoint=home/'built-images.json'
    old=json.loads(checkpoint.read_bytes()) if checkpoint.exists() else None
    candidate=None
    if old and old.get('officialEnvironmentTree')==row['environmentSource']:
        candidate=json.loads(command(['image','inspect',old['candidateImageId']]))[0]['Id']
    if candidate is None:
        tag='objrun-g01-a2-candidate:'+task+'-'+uuid.uuid4().hex
        command(['build','--pull=false','--force-rm=true',*build_args(),'--label','objrun.skb.role=full-f-pristine','--label','objrun.skb.task-id='+task,'-t',tag,str(source/'environment')],timeout=e['build_timeout_sec'],stdout_limit=32*1024**2)
        candidate=json.loads(command(['image','inspect',tag]))[0]['Id']
    private=None
    if old and old['candidateImageId']==candidate and old['privateRunnerSourcePin']==public.pin(Path(__file__).with_name('adapter2_20261013_v1.py')) and old.get('verifierSource')==row['verifierSource']:
        private=json.loads(command(['image','inspect',old['privateImageId']]))[0]['Id']
        built=old
    else:
        context=run/'private-context';built=prepare(task,context,candidate)
        tag='objrun-g01-a2-private:'+task+'-'+uuid.uuid4().hex
        command(['build','--pull=false','--force-rm=true',*build_args(),'-f',str(context/'Dockerfile.private'),'-t',tag,str(context)],timeout=e['build_timeout_sec'],stdout_limit=32*1024**2)
        private=json.loads(command(['image','inspect',tag]))[0]['Id']
        built.update(privateImageId=private,sourceBeforeAfterEqual=public.tree(source)==before)
        assert built['sourceBeforeAfterEqual'];save(checkpoint,built)
    assert private!=candidate
    if stage=='build':return {'builtImagesPin':public.pin(checkpoint),'modelCalls':0,'registered':False}
    # A successful qualification is reused; never repeat a reference because
    # draft/publication or Stand acceptance later failed.
    control_path=home/'controls.json'
    if control_path.exists():
        previous=json.loads(control_path.read_bytes())
        if previous['controlsPassed'] and previous['builtImagesPin']==public.pin(checkpoint):
            for key in ('collectionPin','emptyPin','oraclePin','wrongPin'):
                assert public.pin(Path(previous[key]['path']))==previous[key]
            return {'controlPin':public.pin(control_path),'reused':True,'modelCalls':0,'registered':False}
    owned=[]
    def create(image=candidate):
        nonce=uuid.uuid4().hex
        cid=command(['create','--pull','never','--network',{'public':'bridge','no-network':'none'}[e['network_mode']],
          '--label','objrun.skb.role=full-f-solver','--label','objrun.skb.nonce='+nonce,'--memory',str(e['memory_mb']*1024**2),
          '--memory-swap',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus']),'--cap-drop','ALL','--security-opt','no-new-privileges',
          '--workdir',row['workdir'],'--entrypoint','/bin/bash',image,'-c','exec sleep infinity']).decode().strip()
        owned.append(cid);return cid,nonce,transport.missing
    try:
        empty=create();col=evaluate(command,*empty[:2],built,empty[2],mode='collect',owner_pid=owner)
        save(home/'collection-only.json',col['result'])
        if stage=='collection':return {'collectionPin':public.pin(home/'collection-only.json'),'modelCalls':0,'registered':False}
        empty_result=evaluate(command,*empty[:2],built,empty[2],owner_pid=owner)
        assert empty_result['result']['reward']==0
        reference_path=home/'reference-checkpoint.json';reference=None
        oracle_tree=public.tree(source/'oracle')
        if reference_path.exists():
            prior=json.loads(reference_path.read_bytes())
            if prior['oracleTree']==oracle_tree and prior['candidateImageId']==candidate:
                image=json.loads(command(['image','inspect',prior['referenceImageId']]))[0]
                assert image['Id']==prior['referenceImageId'];reference=prior['referenceImageId']
        if reference is None:
            assert allow_oracle,'explicit_original_oracle_once_flag_required'
            oracle=create();command(['start',oracle[0]])
            command(['cp',str(source/'oracle'),oracle[0]+':/oracle'])
            # Original script and all oracle assets, original task budget.
            command(['exec',oracle[0],'/bin/bash','/oracle/solve.sh'],timeout=row['taskSeconds'],stdout_limit=32*1024**2)
            command(['exec',oracle[0],'/bin/bash','-c','rm -rf /oracle'])
            command(['stop','-t','1',oracle[0]])
            reference=command(['commit','--change','LABEL objrun.skb.role=group01-adapter2-reference-control',oracle[0]]).decode().strip()
            save(reference_path,{'oracleTree':oracle_tree,'candidateImageId':candidate,'referenceImageId':reference,'oracleCompleted':True,'modelCalls':0})
        oracle=create(reference);wrong=create()
        built={**built,'controlImageIds':[reference]}
        command(['start',wrong[0]])
        if task=='fix-visual-stability':
            script="from pathlib import Path; Path('/app/src/app/page.tsx').write_text('export default function Page(){return <main>Wrong</main>}')"
        else:
            paths=__import__('adapter2_20261013_v1').OUTPUTS[task]
            script='from pathlib import Path\nfor p in '+repr(paths)+":\n q=Path(p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b'wrong')"
        command(['exec',wrong[0],'python3','-c',script]);command(['stop','-t','1',wrong[0]])
        # Empty already passed its 0 check; avoid repeating it in qualification.
        oracle_result=evaluate(command,*oracle[:2],built,oracle[2],owner_pid=owner)
        wrong_result=evaluate(command,*wrong[:2],built,wrong[2],owner_pid=owner)
        assert [r['result']['reward'] for r in (empty_result,oracle_result,wrong_result)]==[0,1,0]
        assert all(r['result']['nodeIds']==col['result']['nodeIds'] for r in (empty_result,oracle_result,wrong_result))
        built_pin=save(checkpoint,built);evidence=run/'controls';evidence.mkdir()
        pins={name+'Pin':save(evidence/(name+'.json'),value['result']) for name,value in [('collection',col),('empty',empty_result),('oracle',oracle_result),('wrong',wrong_result)]}
        value={'protocol':'group01-adapter2-v1-controls','taskId':task,'controlsPassed':True,'decisions':[0,1,0],'builtImagesPin':built_pin,**pins,'modelCalls':0,'ownedContainersRemaining':0,'native_ready':False}
    finally:
        errors=[]
        for cid in reversed(owned):
            try:command(['rm','-f',cid])
            except Exception as error:errors.append(str(error))
        if errors:raise RuntimeError('owned_control_cleanup_failed: '+repr(errors))
    assert public.tree(source)==before
    save(control_path,value);return {'controlPin':public.pin(control_path),'modelCalls':0,'registered':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--task',choices=TASKS,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--resource-owner-pid',type=int,required=True);p.add_argument('--stage',choices=['build','collection','controls'],required=True)
    p.add_argument('--allow-original-oracle-once',action='store_true');a=p.parse_args()
    print(json.dumps(pipeline(a.task,a.output,a.resource_owner_pid,a.stage,a.allow_original_oracle_once)))
