"""Exercise the original ordinary-data HTTP worker with pinned passive inputs.

No test, reference solution, score rule, model or scheduler is implemented here.
"""
import argparse,json,os,pathlib,shlex,uuid
from native_process import pin
from ordinary_data_http_binding import read_checked,restore_original_opaque_reference,command_transport
from original_sb_transport import require_original_lease


def run(request,output,owner):
    neutral=request['protocol']=='bench-neutral-original-ordinary-http-v1'
    assert neutral or request['protocol']=='bench-original-ordinary-http-controller-v1'
    task=request['taskId'];config=request['standConfig'];row=config['schedule'][0]
    assert row['taskId']==task and len(config['schedule'])==len(config['taskReadiness'])==1
    proof=config['taskReadiness'][task]
    assert proof['adapter']=='ordinary-data-v1'
    assert proof['builtImagesPin']==request['builtImagesPin'] and proof['controlPin']==request['controlPin']
    built=read_checked(request['builtImagesPin']);control=read_checked(request['controlPin'])
    assert control['controlsPassed'] and control['decisions']==[0,1,0] and control['builtImagesPin']==request['builtImagesPin']
    lease=require_original_lease(owner,row['originalResources'])
    if neutral:
        assert task==lease['taskId']=='zero-model-owned-sb-asset' and request['gradeCalls']==0
        assert built['noBenchContent'] and control['qualificationProof'] is False
    else:
        assert task==lease['taskId'] and request['gradeCalls']==3
        assert request['gradeSeconds']==row['verifierSeconds']==built['originalResources']['verifier']['timeout_sec']
        assert request['expectedDecisions']==[0,1,0]
    history=globals().get('_bench_authorized_history');assert callable(history) and history(task)
    output=pathlib.Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    config={**config,'resourceOwnerPid':owner,'output':str(output/'http')}
    pathlib.Path(config['output']).mkdir()
    from http_stand_client_v1 import HttpStand
    stand=HttpStand(config,uuid.uuid4().hex);place='skb:'+row['id'];tools=[];grades=[];reference=None;closed=None;shutdown=None
    command=command_transport(output/'opaque-transfer',row['originalResources'])
    def save(name,obj):
        p=output/name;p.write_text(json.dumps(obj,indent=2)+'\n',encoding='utf8');return pin(p)
    def call(tool,args):
        value=stand.call(dict(place=place,tool=tool,args=args));assert not value.get('isError'),value
        return value
    def grade(said):
        body=dict(place=place,said=said);value=stand.grade(body,'verified')
        assert value['valid'] and value['verified'];cached=stand.grade(body,'passed')
        assert cached['gradeOwnerPin']==value['gradeOwnerPin'] and cached['passed']==value['passed']
        result=read_checked(value['gradeOwnerPin'])['result'];assert result['complete']
        assert result['nodeIds']==read_checked(control['collectionPin'])['nodeIds']
        grades.append(dict(reward=result['reward'],gradeOwnerPin=value['gradeOwnerPin']))
        return value
    try:
        stand.create(dict(place=place));assert stand.current and stand.current['running']
        requests=request['toolRequests'];assert len(requests)==6 and {x['tool'] for x in requests}=={'bash','read','write','edit','glob','grep'}
        assert set(stand.assets['toolNames'])=={x['tool'] for x in requests}
        for item in requests:
            value=call(item['tool'],item['args']);tools.append(save(item['tool']+'-receipt.json',dict(request=item,response=value,modelCalls=0)))
        if not neutral:assert not grade('ordinary-http-missing')['passed']
        reference=restore_original_opaque_reference(stand,command,request['opaqueReferencePin'],request['builtImagesPin'],request['controlPin'])
        for item in request.get('referenceMetadataSteps',[]):
            assert item['tool']=='bash';call(item['tool'],item['args'])
        if neutral:
            value=call('read',dict(file_path=read_checked(request['opaqueReferencePin'])['files'][0]['destination']))
            assert request['neutralExpectedText'] in json.dumps(value)
        else:
            assert grade('ordinary-http-saved-reference')['passed']
            # Delete only declared answer files, using the original untrusted tool.
            paths=[x['path'] for x in built['outputPolicies']];assert all(x['kind']=='file' and x['maximumFiles']==1 for x in built['outputPolicies'])
            call('bash',dict(command='rm -f -- '+' '.join(shlex.quote(x) for x in paths)))
            assert not grade('ordinary-http-deliberately-wrong')['passed']
            assert [x['reward'] for x in grades]==request['expectedDecisions']
    finally:
        try:closed=stand.stop()
        finally:shutdown=stand.shutdown()
    assert closed['ownedContainersRemaining']==0 and shutdown['workerProcessClosed']
    worker=stand.proc._bench_http_record
    result=dict(protocol='bench-original-ordinary-http-contract-v1',taskId=task,complete=True,actualHttp=True,sixToolsVerified=True,toolReceiptPins=tools,
        gradeOwnerPins=[x['gradeOwnerPin'] for x in grades],decisions=[x['reward'] for x in grades],builtImagesPin=request['builtImagesPin'],controlPin=request['controlPin'],
        opaqueReference=reference,originalOracleRepeated=False,stop=closed,shutdown=shutdown,workerIdentity=dict(pid=worker['pid'],incarnation=worker['incarnation']),
        ownedContainersRemaining=0,modelCalls=0,gradeCalls=len(grades),referenceCalls=0,noBenchContent=neutral,qualificationProof=not neutral,formalReady=False)
    save('result.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--output',required=True);p.add_argument('--resource-owner-pid',required=True,type=int);a=p.parse_args()
    print(json.dumps(run(json.loads(pathlib.Path(a.request).read_bytes()),a.output,a.resource_owner_pid)))
