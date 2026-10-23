"""Zero-model contract checks; fake Docker, never invokes a daemon."""
import ast
import io
import json
from pathlib import Path
import tarfile
import tempfile
from unittest.mock import patch
import adapter2_20261013_v1 as adapter
from ordinary_artifacts import ArtifactFault

def archive(name,body=b'data',link=False):
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode='w') as stream:
        entry=tarfile.TarInfo(name);entry.size=len(body)
        if link:entry.type=tarfile.SYMTYPE;entry.linkname='/verifier/test_outputs.py';entry.size=0
        stream.addfile(entry,None if link else io.BytesIO(body))
    return buf.getvalue()

def main():
    adapter.assert_lease=lambda owner,resources:None
    results=[]
    for task in adapter.TASKS:
        row=adapter.descriptor(task);image='sha256:'+'1'*64;private='sha256:'+'2'*64
        built={'taskId':task,'originalResources':row['originalResources'],'candidateImageId':image,
          'privateImageId':private,'privateRunnerSourcePin':adapter.public.pin(Path(adapter.__file__))}
        calls=[];counter=0
        result={'taskId':task,'mode':'grade','complete':True,'nodeIds':['original::test'],
          'reward':0,'candidateExecutablesUsed':False,'candidateSnapshotUsed':False}
        def command(args,**kwargs):
            nonlocal counter
            calls.append((args,kwargs))
            if args[0]=='inspect':return json.dumps([{'State':{'Running':False},'Image':image,'Config':{'Labels':{'objrun.skb.nonce':'nonce'}},'HostConfig':{}}]).encode()
            if args[0]=='commit':return ('sha256:'+'3'*64).encode()
            if args[:2]==['image','inspect']:return json.dumps([{'Config':{'Labels':{'objrun.skb.snapshot-owner':next(a.split('=',1)[1] for a in next(c[0] for c in reversed(calls) if c[0][0]=='commit') if a.startswith('LABEL objrun.skb.snapshot-owner='))}}}]).encode()
            if args[0]=='create':counter+=1;return str(counter).encode()
            if args[0]=='cp' and args[-1]=='-':return archive(Path(args[1].split(':',1)[1]).name)
            if args[:2]==['start','-a']:return json.dumps(result).encode()
            return b''
        evaluated=adapter.evaluate(command,'solver','nonce',built,lambda *a:False)
        assert evaluated['result']['reward']==0
        creates=[c[0] for c in calls if c[0][0]=='create']
        assert all('--cap-drop' in c and '--memory' in c and '--cpus' in c for c in creates)
        grader=next(c for c in creates if private in c)
        assert image not in grader and not any(c.startswith('--volume') for c in grader)
        if task=='fix-visual-stability':assert any(c.startswith('container:') for c in grader)
        else:assert grader[grader.index('--network')+1]=='none'
        assert len([c for c,_ in calls if c[0]=='rm'])==len(creates)
        # Infrastructure transport failure must escape, never become reward 0.
        def failing(args,**kwargs):
            if args[0]=='create':raise RuntimeError('transport_failed')
            return command(args,**kwargs)
        try:adapter.evaluate(failing,'solver','nonce',built,lambda *a:False)
        except RuntimeError as error:assert 'transport_failed' in str(error)
        else:raise AssertionError('transport failure swallowed')
        with tempfile.TemporaryDirectory() as temporary:
            prep=adapter.prepare(task,Path(temporary)/task,image)
            assert not prep['native_ready'] and not prep['registered']
            assert (Path(temporary)/task/'verifier/test_outputs.py').read_bytes()==(adapter.VENDOR/'tasks'/task/'verifier/test_outputs.py').read_bytes()
        results.append({'taskId':task,'candidateIsolation':True,'originalVerifierCopy':True,'errorPropagation':True,'cleanup':True})
    for name,link in [('../test',False),('rar_result.xlsx',True)]:
        try:adapter.replay_tar('reserves-at-risk-calc',[('/root/output/rar_result.xlsx',archive(name,link=link))])
        except ArtifactFault:pass
        else:raise AssertionError('unsafe archive accepted')
    fixture={'exitCode':1,'nodes':['test'],'reports':[{'nodeid':'test','when':'setup','outcome':'failed','failureMessage':'AssertionError: missing output'},{'nodeid':'test','when':'teardown','outcome':'passed'}]}
    adapter.validate_outcome(['test'],fixture,0)
    for code in (2,3,4,5):
        try:adapter.validate_outcome(['test'],{**fixture,'exitCode':code},0)
        except AssertionError:pass
        else:raise AssertionError('pytest infra exit accepted')
    try:adapter.validate_outcome(['test'],{**fixture,'reports':[{'nodeid':'test','when':'setup','outcome':'skipped'}]},0)
    except AssertionError:pass
    else:raise AssertionError('skip accepted')
    base=Path(adapter.__file__).parent
    ast.parse((base/'data_stand_adapter2_20261013_v1.py').read_text())
    import data_stand_adapter2_20261013_v1 as stand_module
    # Actual Stand grade route, refresh and immediate passed cache, injected
    # transport; six-tool forwarding uses the inherited runtime tool contract.
    import threading
    import time
    stand=object.__new__(stand_module.Stand);stand.lock=threading.RLock();stand.latest=None
    stand.current={'place':'task','mutation':0,'running':False,'taskId':'reserves-at-risk-calc'}
    stand.config={'taskReadiness':{'reserves-at-risk-calc':{'adapter':adapter.ADAPTER}}}
    stand.grade_adapter2=lambda c,key,answer: {'verified':True,'passed':False,'valid':True}
    assert stand.grade({'place':'task','said':'candidate'},'verified')['verified']
    stand.assets={'toolNames':['bash','read','write','edit','glob','grep']}
    stand.home=Path(tempfile.mkdtemp());stand.current.update(cid='solver',deadline=int(time.time()*1000)+60000)
    stand.create=lambda body:None;stand.refresh_deadline=lambda:False
    forwarded=[]
    def tool_command(args,*positional,**kwargs):
        forwarded.append(args)
        return json.dumps({'forwarded':True}).encode() if args[0]=='exec' else b''
    stand.command=tool_command
    try:
        for tool in stand.assets['toolNames']:
            assert stand.call({'place':'task','tool':tool,'args':{}})['forwarded']
        assert len([a for a in forwarded if a[0]=='exec'])==6
    finally:
        import shutil
        shutil.rmtree(stand.home)
    with tempfile.TemporaryDirectory() as temporary:
        native=Path(temporary);task='reserves-at-risk-calc';row=adapter.descriptor(task)
        built={'taskId':task,'candidateImageId':'sha256:'+'1'*64,'privateImageId':'sha256:'+'2'*64,'originalResources':row['originalResources'],'privateRunnerSourcePin':adapter.public.pin(Path(adapter.__file__))}
        built_pin=adapter.save(native/'built.json',built)
        collection_pin=adapter.save(native/'collection.json',{'nodeIds':['original::test']})
        control_pin=adapter.save(native/'control.json',{'taskId':task,'controlsPassed':True,'ownedContainersRemaining':0,'builtImagesPin':built_pin,'collectionPin':collection_pin})
        current=object.__new__(stand_module.Stand);current.config={'runId':'test','resourceOwnerPid':123,'output':str(native),'schedule':[{**row,'id':'route'}],'taskReadiness':{task:{'adapter':adapter.ADAPTER,'builtImagesPin':built_pin,'controlPin':control_pin}}}
        current.home=native;current.lock=threading.RLock();current.current=None;current.latest=None;current.timer=None;current.database=None;current.database_task=None;current.serial=0
        current.assets={'assets':[],'toolNames':['bash','read','write','edit','glob','grep']}
        current.arm_deadline=lambda:None;current.refresh_deadline=lambda:False
        native_calls=[]
        def native_command(args,*positional,**kwargs):
            native_calls.append(args)
            if args[0]=='create':return ('a'*64).encode()
            if args[0]=='exec':return json.dumps({'forwarded':True}).encode()
            return b''
        current.command=native_command;graded=[]
        def fake_evaluate(*args,**kwargs):
            graded.append(True)
            return {'result':{'nodeIds':['original::test'],'reward':0,'complete':True,'candidateExecutablesUsed':False,'candidateSnapshotUsed':False}}
        with patch.object(stand_module,'deploy_skills',return_value={'verified':True}),patch.object(adapter,'evaluate',side_effect=fake_evaluate):
            current.create({'place':'skb:route'})
            for tool in current.assets['toolNames']:assert current.call({'place':'skb:route','tool':tool})['forwarded']
            assert not current.grade({'place':'skb:route','said':'candidate'},'verified')['passed']
            assert not current.grade({'place':'skb:route','said':'candidate'},'passed')['passed']
            assert len(graded)==1,'passed should reuse only immediately matching latest grade'
            current.grade({'place':'skb:route','said':'changed'},'verified');assert len(graded)==2
            assert current.stop()['ownedContainersRemaining']==0
        assert any(c[0]=='rm' and c[-1]=='a'*64 for c in native_calls)
    worker=(base/'runtime_private_task_adapter2_20261013_v1.ts').read_text()
    assert 'data_stand_adapter2_20261013_v1.py' in worker and 'BENCHMARK_INFERENCE' in worker
    import pipeline_adapter2_20261013_v1 as pipeline
    pipeline_checks=[]
    for task in adapter.TASKS:
        operations=[];ids={};images={};counter=[0]
        class FakeTransport:
            def __init__(self,*args):pass
            def missing(self,*args):return False
            def command(self,args,**kwargs):
                operations.append(args)
                if args[0]=='build':
                    image='sha256:'+('2' if '-f' in args else '1')*64
                    images[args[args.index('-t')+1]]=image
                if args[:2]==['image','inspect']:
                    image=images.get(args[-1],args[-1]);return json.dumps([{'Id':image}]).encode()
                if args[0]=='create':
                    counter[0]+=1;cid=format(counter[0],'064x');ids[cid]=args[-3];return cid.encode()
                if args[0]=='commit':return ('sha256:'+'3'*64).encode()
                return b''
        def fake_grade(command,cid,nonce,built,missing,mode='grade',**kwargs):
            # Reference controls use preserved successful oracle image only.
            reward=1 if ids[cid]=='sha256:'+'3'*64 else 0
            return {'result':{'taskId':task,'mode':mode,'nodeIds':['original::test'],'complete':True,'reward':None if mode=='collect' else reward,'candidateExecutablesUsed':False,'candidateSnapshotUsed':False}}
        with tempfile.TemporaryDirectory() as temporary,patch.object(pipeline,'Transport',FakeTransport),patch.object(pipeline,'build_args',return_value=[]),patch.object(pipeline,'evaluate',side_effect=fake_grade):
            result=pipeline.pipeline(task,temporary,123,'controls',allow_oracle=True)
            assert Path(result['controlPin']['path']).exists()
            oracle_runs=len([a for a in operations if a[0]=='exec' and '/oracle/solve.sh' in a]);assert oracle_runs==1
            again=pipeline.pipeline(task,temporary,123,'controls',allow_oracle=False)
            assert again['reused'] and len([a for a in operations if a[0]=='exec' and '/oracle/solve.sh' in a])==oracle_runs
            assert len([a for a in operations if a[0]=='rm'])==counter[0]
        pipeline_checks.append({'taskId':task,'originalBuildAndControlChainFakeValidated':True,'successfulReferenceNotRepeated':True,'ownedControlCleanup':True})
    proof={'protocol':adapter.ADAPTER+'-light-contract','checks':results,'unsafeTarRejected':True,'standRouteVerified':True,
      'modelCalls':0,'dockerActions':0,'native_ready':False,'pipelineChecks':pipeline_checks,'sixToolsFakeTransportValidated':True,'standCreateGradeCacheCloseFakeValidated':True,'sixToolsNativeValidated':False,
      'sourcePins':[adapter.public.pin(base/name) for name in ['adapter2_20261013_v1.py','check_adapter2_20261013_v1.py','data_stand_adapter2_20261013_v1.py','runtime_private_task_adapter2_20261013_v1.ts','pipeline_adapter2_20261013_v1.py','stand_contract_adapter2_20261013_v1.py','next-segment/prepare_adapter2_20261013_v1.ts','next-segment/private_task_worker_entry_adapter2_20261013_v1.ts','next-segment/draft_publication_adapter2_20261013_v1.ts']]}
    print(json.dumps(proof,indent=2))

if __name__=='__main__':main()
