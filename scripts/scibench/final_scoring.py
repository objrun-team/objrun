"""Derived scoring only. Never turns an invalid raw result into a valid one."""
import copy
NOTE='补跑后仍异常，按失败计分'
def score_row(record,permitted_invalid):
    valid=bool(record['grade'].get('valid'));passed=valid and bool(record['grade'].get('passed'))
    identity=(record['arm'],record['id'])
    assert valid or identity in permitted_invalid,'UnexpectedInvalidOutsideFinalScoringPolicy'
    return {'arm':record['arm'],'id':record['id'],'valid':valid,'rawPassed':bool(record['grade'].get('passed')),'rawOutcome':record['grade'].get('outcome'),'score':int(passed),'countedAsWrong':not passed,'policyFailure':not valid,'note':NOTE if not valid else '', 'attemptId':record.get('attemptId'),'attemptNo':record.get('attemptNo',0),'rawError':record.get('error')}
def fixture():
    records=[{'arm':'objrun','id':'failed','grade':{'valid':False,'passed':False,'outcome':'infrastructure_error'},'error':'ProviderFault:WhitespaceOnly'},{'arm':'baseline','id':'wrong','grade':{'valid':True,'passed':False}},{'arm':'baseline','id':'correct','grade':{'valid':True,'passed':True}}]
    before=copy.deepcopy(records);rows=[score_row(r,{('objrun','failed')}) for r in records]
    assert records==before and rows[0]['valid'] is False and rows[0]['score']==0 and rows[0]['policyFailure'] and rows[0]['note']==NOTE
    assert rows[1]['score']==0 and rows[1]['valid'] and not rows[1]['policyFailure'] and rows[2]['score']==1
    try:score_row(records[0],set());raise AssertionError('UnplannedInvalidAccepted')
    except AssertionError as e:assert str(e)=='UnexpectedInvalidOutsideFinalScoringPolicy'
    return {'allPassed':True,'realProviderCalls':0,'checks':['raw valid=false retained','original error retained','only authorized final invalids assigned policy failure','valid wrong answers remain valid wrong','valid correct unchanged','input records unchanged']}
if __name__=='__main__':
    import json
    print(json.dumps(fixture(),ensure_ascii=True))
