"""Eligibility uses execution/receipt evidence and training records only, never ID/OOD."""
import json,pathlib
def usable_candidate(d,row):
    answers=[]
    if row.get('answer') and (row.get('valid') or (row.get('trainingGrade') or {}).get('valid')):answers.append(row['answer'])
    for name in ['samples.json','feedback.json']:
        p=d/name
        if p.exists():
            for e in json.loads(p.read_text()):
                g=e.get('grade') or {}
                if e.get('answer') and g.get('valid') and isinstance(g.get('expression'),str) and 'parameters' in g:answers.append(e['answer'])
    p=d/'native/native-result.json'
    if p.exists():
        n=json.loads(p.read_text())
        if n.get('answer') and n['answer'] in answers:answers.append(n['answer'])
    for answer in answers:
        try:
            t=answer.strip()
            if t.startswith('```'):t=t.split('\n',1)[1].rsplit('```',1)[0].strip()
            q=json.loads(t)
            if isinstance(q,dict) and isinstance(q.get('expression'),str) and set(q)<={'expression','initial'}:return True
        except (ValueError,TypeError):pass
    return False
def classify(row,started,unknown,has_candidate):
    if not started:return {'eligible':False,'route':'unstarted_not_infrastructure_failure'}
    if unknown and has_candidate:return {'eligible':False,'route':'reconcile_only','reason':'usable_training_candidate_and_unresolved_bill; no resampling'}
    if row is None:return {'eligible':True,'route':'interrupted','reason':'started_without_result'}
    if row.get('valid'):return {'eligible':False,'route':'reconcile_only' if unknown else 'normal_completion','reason':'existing_completed_candidate'}
    error=str(row.get('error',''));low=error.lower()
    # Bad mathematics, rejected expressions and normal format/fit failures never qualify.
    candidate=['candidateformat','candidateschema','candidatecputimeout','invalidexpression','fivecandidateceiling','taskdollarcap','candidate_ceiling']
    if any(x in low for x in candidate):return {'eligible':False,'route':'candidate_failure_not_repairable'}
    if 'the engine did not come up' in low or 'graderstartup' in low or 'engine startup' in low:return {'eligible':True,'route':'engine_start_failure'}
    if any(x in low for x in ['connectionreset','connection reset','brokenpipe','connection aborted','remoteendclosed']):return {'eligible':True,'route':'connection_failure'}
    if any(x in low for x in ['nativecontrollertimeout','interrupted','cancelledatoperatorstop','accountstop:campaignstopped','campaignstoppedbeforenewattemptdispatch']):return {'eligible':True,'route':'interrupted'}
    if unknown:return {'eligible':True,'route':'response_read_failure','reason':'terminated_response_unknown_without_usable_candidate'}
    if any(x in low for x in ['incompleteread','remotedisconnected','responseread','nonjsonresponse','providerresponsefault']):return {'eligible':True,'route':'response_read_failure'}
    return {'eligible':False,'route':'ambiguous_excluded','reason':error}
