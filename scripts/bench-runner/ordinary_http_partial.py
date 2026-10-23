"""Read-only reuse of original ordinary HTTP receipts, bound by the signed stage."""
import hashlib,json,pathlib
from native_process import pin

def read(p):
    assert pin(p['path'])==p,'ordinary_partial_full_pin'
    return json.loads(pathlib.Path(p['path']).read_bytes())

def reuse(seed_pin,built_pin,control_pin,requests,mapping):
    # checked_config is the original authenticated root-signed stage binding.
    assert seed_pin in mapping['sourceContractPins'],'partial_seed_not_root_stage_bound'
    envelope=read(seed_pin)
    assert envelope['protocol']=='bench-signed-ordinary-http-partial-success-v1' and envelope['signature']
    s=envelope['plan'];assert s['protocol']=='bench-ordinary-http-partial-success-v1'
    built=read(built_pin);control=read(control_pin)
    assert s['taskId']==built['taskId']==control['taskId'] and s['builtImagesPin']==built_pin and s['controlPin']==control_pin
    assert s['candidateImageId']==built['candidateImageId'] and s['privateImageId']==built['privateImageId']
    assert control['controlsPassed'] and control['ownedContainersRemaining']==0 and control['decisions']==[0,1,0]
    prior=read(s['originalHttpRequestPin']);assert prior['toolRequests']==requests and prior['builtImagesPin']==built_pin and prior['controlPin']==control_pin
    assert s['runtimeAssetPins']==[x['sourcePin'] for x in mapping['skillsbenchRuntimeCopy']['assets']],'partial_exact_runtime_payload'
    closure=read(s['priorExactClosurePin']);correction=read(s['actualGradeAccountingPin'])
    assert closure['allObservedLocalChildrenClosed'] and closure['allExactBuildActorsClosed'] and closure['resourceReleasedAndFreshAbsent']
    assert correction['actualOriginalBenchGradeCalls']==1 and correction['modelCalls']==correction['referenceCalls']==0
    assert correction['actualCompletedEmptyGradePin']==s['emptyGradePin'] and correction['closurePin']==s['priorExactClosurePin']
    assert closure['boundedEvidence']['actorAbsences'] and all(x['status']==404 for x in closure['boundedEvidence']['actorAbsences'])
    assert len(requests)==6 and {x['tool'] for x in requests}=={'bash','read','write','edit','glob','grep'}
    assert len(s['toolReceiptPins'])==len(s['toolHttpReceiptPins'])==6
    for request,tp,hp in zip(requests,s['toolReceiptPins'],s['toolHttpReceiptPins']):
        t=read(tp);h=read(hp)
        assert t['request']==request and t['modelCalls']==0 and not t['response'].get('isError')
        assert h['nativeHttp'] and h['modelCalls']==0 and h['httpStatus']==200 and h['path']=='/place'
        assert h['body']['tool']==request['tool'] and h['body']['args']==request['args'] and h['response']==t['response']
    g=read(s['emptyGradePin']);nodes=read(control['collectionPin'])['nodeIds'];v=g['result']
    assert g['builtImagesPin']==built_pin and g['controlPin']==control_pin
    assert g['candidateAnswerSha256']==hashlib.sha256(b'ordinary-http-missing').hexdigest()
    assert v['complete'] and v['reward']==0 and v['taskId']==s['taskId'] and v['nodeIds']==nodes and v['completedTests']==len(nodes)
    assert v['candidateExecutablesUsed'] is False and v['candidateSnapshotUsed'] is False
    for hp,kind in [(s['emptyVerifiedHttpPin'],'verified'),(s['emptyPassedHttpPin'],'passed')]:
        h=read(hp);assert h['nativeHttp'] and h['modelCalls']==0 and h['httpStatus']==200 and h['path']=='/'+s['taskId']+'/'+kind
        assert h['body']['said']=='ordinary-http-missing' and h['response']['valid'] and not h['response']['passed'] and h['response']['gradeOwnerPin']==s['emptyGradePin']
    return dict(toolReceiptPins=s['toolReceiptPins'],emptyGrade=dict(reward=0,gradeOwnerPin=s['emptyGradePin']),seedPin=seed_pin,reusedToolCount=6,reusedGradeCount=1,newToolCalls=0,newGradeCalls=0,modelCalls=0)
