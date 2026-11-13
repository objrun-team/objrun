"""Audit all 488 records, real HTTP overlap, scoring provenance and the cash ledger."""
import collections
import csv
import hashlib
import json
from pathlib import Path
import random
import tarfile
from lean_worker import digest, save
from sequence import check_messages

def read(p):return json.loads(p.read_text())

def concurrency(root):
    active=set();peak=0;begins={};ends={}
    path=root/'outputs/model-concurrency.jsonl'
    for line in path.read_text().splitlines():
        e=json.loads(line);call=e['callDirectory']
        if e['event']=='http_begin':
            assert call not in begins;begins[call]=e;active.add(call)
        else:
            assert e['event']=='http_end' and call in active and call not in ends
            ends[call]=e;active.remove(call)
        assert len(active)==e['active'] and 0<=len(active)<=16
        peak=max(peak,len(active))
    assert not active and begins.keys()==ends.keys()
    return {'actualHttpPeak':peak,'httpAttemptsWithBeginAndEnd':len(begins),
        'allSlotsClosed':True,'sharedPoolCap':16,'globalPacingSeconds':0},begins,ends

def finish(root,archive=False):
    root=Path(root).resolve();out=root/'outputs';cfg=read(root/'package/experiment.json')
    state=read(out/'status.json');assert state['stage'] in ['complete','complete_with_exceptions']
    assert state['completed']==cfg['expectedRecords']==488
    assert state['actualModelActive']==state['unresolvedDispatches']==state['pendingGrades']==0
    controls=read(out/'controls.json');assert controls['allPassed']
    pins=read(out/'source-pins.json');assert pins==controls['sourcePins']
    assert all(digest((root/p).read_bytes())==h for p,h in pins.items())
    assert digest((out/'pilot-delivery-gate.json').read_bytes())==read(out/'gate-pin.json')['sha256']
    catalog=read(root/'data/public-test.json');assert len(catalog)==244
    overlap,begins,ends=concurrency(root)
    rows=[];all_receipts=[];errors=[];curves={a:{str(b):{'confirmedSolved':0,'unknownCostGroups':0} for b in [.01,.025,.05,.10]} for a in cfg['arms']}
    for task in catalog:
        for arm in cfg['arms']:
            group=arm+'/'+task['name'];d=out/'tasks'/group
            result=read(out/'results'/arm/(task['name']+'.json'));started=read(d/'started.json')
            history=read(d/'samples.json') if (d/'samples.json').exists() else []
            assert result['id']==task['id'] and result['promptSha256']==digest(task['prompt'])==task['promptSha256']
            assert len(history)==result['sampleCount']<=5
            receipts=[];successes={};unknown=False
            excluded={v['callDirectory']:v for p in d.glob('late-*.json') for v in [read(p)]}
            for dispatch_path in (out/'calls'/group).rglob('dispatch.json'):
                call_dir=dispatch_path.parent;call=str(call_dir.relative_to(root))
                dispatch=read(dispatch_path);receipt=read(call_dir/'receipt.json');raw=(call_dir/'request.json').read_bytes();wire=json.loads(raw)
                index=int(call_dir.parent.name.removeprefix('attempt-'));retry=int(call_dir.name.removeprefix('transport-'))
                assert 0<=index<5 and 0<=retry<3
                assert dispatch['atEpoch']<=started['deadlineEpoch']+1
                assert receipt['requestSha256']==dispatch['requestSha256']==digest(raw)
                assert check_messages(wire['messages'],cfg['systemPrompt'],task,arm,history[:index])
                assert not wire.get('tools') and not wire.get('tool_choice')
                assert wire['provider']['only']==[cfg['providerTag']] and not wire['provider']['allow_fallbacks']
                assert wire['model']==cfg['model'] and wire['temperature']==0 and wire['max_tokens']==16384
                assert wire['reasoning']=={'enabled':True,'effort':'medium','exclude':False}
                assert call in begins and call in ends
                assert receipt['networkStartedAtEpoch']==begins[call]['atEpoch']
                assert receipt['networkEndedAtEpoch']==ends[call]['atEpoch']
                if retry:
                    previous=read(call_dir.with_name('transport-%02d'%(retry-1))/'receipt.json')
                    assert previous['retryable'] and not previous['success']
                    assert previous['requestSha256']==receipt['requestSha256']
                    assert receipt['networkStartedAtEpoch']>=previous['completedAtEpoch']+cfg['transportBackoffSeconds']*retry-.05
                if receipt['success']:
                    response=read(call_dir/'response.json')
                    assert (response['model'],response['provider'])==(cfg['model'],cfg['provider'])
                    assert response['id']==receipt['generationId']
                    assert index not in successes
                    answer=response['choices'][0]['message'].get('content') or ''
                    successes[index]=(answer,receipt,call)
                    if index<len(history):
                        assert history[index]['callDirectory']==call and history[index]['answer']==answer
                    else:
                        assert not result['grade']['valid'] and excluded[call]['excludedFromScore'] is True
                receipts.append((dispatch['atEpoch'],receipt,index));all_receipts.append(receipt)
                unknown=unknown or receipt['unknownCost']
            assert len(successes)<=5
            spent=sum(r['actualCostUsd'] if r['actualCostUsd'] is not None else r['reservationUsd'] for _,r,_ in receipts)
            assert spent<=.10+1e-9
            for index,sample in enumerate(history):
                grade=sample['grade']
                assert sample['index']==index and sample['candidateSha256']==digest(sample['answer'])==grade['candidateSha256']
                assert sample['finishedAtEpoch']<=started['deadlineEpoch']+1
                if grade['valid']:
                    original=read(root/grade['gradeDirectory']/'grade.json')
                    assert all(original[k]==grade[k] for k in ['valid','passed','candidateSha256','identity'])
                    if grade['passed']:
                        assert grade['stated'] and grade['compiles'] and grade['sound']
                        assert set(grade['axioms'])<={'propext','Classical.choice','Quot.sound','Lean.ofReduceBool'}
                if index+1<len(history):assert grade['valid'] and not grade['passed']
                if grade['passed']:assert max(successes)==index and index==len(history)-1
            if result['grade']['valid']:
                assert not excluded
                assert result['grade']==history[-1]['grade'] if history else result['stoppingReason'] in ['task_time_cap','task_dollar_cap','batch_dollar_cap','account_balance']
            else:errors.append('InfrastructureException:'+group)
            assert result['candidateSha256']==digest(result['answer'])
            if history:assert result['answer']==history[-1]['answer']
            actual=sum(r['actualCostUsd'] or 0 for _,r,_ in receipts)
            hashes=[digest(v[0]) for v in successes.values()]
            rows.append({'arm':arm,'id':task['id'],'stratum':task['stratum'],'valid':result['grade']['valid'],
                'passed':result['grade']['valid'] and result['grade']['passed'],
                'firstAttemptPassed':bool(history and history[0]['grade']['valid'] and history[0]['grade']['passed']),
                'samples':len(history),'deliveredModelAttempts':len(successes),
                'duplicateCandidates':len(hashes)-len(set(hashes)),'seconds':result['seconds'],
                'stoppingReason':result['stoppingReason'],'actualCostUsd':actual,
                'unknownCostCount':sum(r['unknownCost'] for _,r,_ in receipts),'budgetChargedUsd':spent,
                'modelRequests':len(receipts),'lateExcludedCandidates':len(excluded)})
            costs_by_index={};cumulative=0.
            for _,receipt,index in sorted(receipts,key=lambda v:v[0]):
                cumulative+=receipt['actualCostUsd'] if receipt['actualCostUsd'] is not None else receipt['reservationUsd']
                costs_by_index[index]=cumulative
            for b in [.01,.025,.05,.10]:
                point=curves[arm][str(b)];point['unknownCostGroups']+=int(unknown)
                point['confirmedSolved']+=int(any(s['grade']['valid'] and s['grade']['passed'] and costs_by_index[s['index']]<=b+1e-12 for s in history))
    assert len(rows)==488 and len(all_receipts)==overlap['httpAttemptsWithBeginAndEnd']
    exposure=sum(r['budgetChargedUsd'] for r in rows);assert exposure<=48.80+1e-9
    arms={}
    for arm in cfg['arms']:
        group=[r for r in rows if r['arm']==arm];passed=sum(r['passed'] for r in group);invalid=sum(not r['valid'] for r in group)
        arms[arm]={'records':len(group),'valid':244-invalid,'passed':passed,'confirmedFailed':244-passed-invalid,
            'infrastructureExceptions':invalid,'successFractionRange':[passed/244,(passed+invalid)/244],
            **{k:sum(r[k] for r in group) for k in ['firstAttemptPassed','samples','deliveredModelAttempts','duplicateCandidates','actualCostUsd','unknownCostCount','budgetChargedUsd']}}
    lookup={(r['arm'],r['id']):r for r in rows};pair_counts=collections.Counter();diffs=[]
    for t in catalog:
        a,b=lookup[('independent',t['id'])],lookup[('binary',t['id'])]
        if not(a['valid'] and b['valid']):continue
        x,y=a['passed'],b['passed'];diffs.append(int(y)-int(x))
        pair_counts['bothPass' if x and y else 'binaryOnlyPass' if y else 'independentOnlyPass' if x else 'bothFail']+=1
    paired={'commonValidTasks':len(diffs),'outcomes':dict(pair_counts),'full244PairedComparisonAvailable':len(diffs)==244}
    if len(diffs)==244:
        rng=random.Random(20261019);boot=sorted(100*sum(rng.choices(diffs,k=244))/244 for _ in range(20000))
        paired.update(binaryMinusIndependentPercentagePoints=100*sum(diffs)/244,
            pairedTaskBootstrap95PercentagePoints=[boot[499],boot[19499]],
            uncertainty='Fixed task composition bootstrap; does not measure API rerun variability.')
    a,b=arms['independent'],arms['binary']
    paired['differencePercentagePointBoundsWithInfrastructureUnknowns']=[
        100*(b['passed']-a['passed']-a['infrastructureExceptions'])/244,
        100*(b['passed']+b['infrastructureExceptions']-a['passed'])/244]
    summary={'runId':cfg['runId'],'scope':cfg['scope'],'model':cfg['model'],'providerTag':cfg['providerTag'],
        'taskCount':244,'records':488,'arms':arms,'paired':paired,'actualCostUsd':sum(r['actualCostUsd'] for r in rows),
        'unknownCostCount':sum(r['unknownCostCount'] for r in rows),'budgetChargedUsd':exposure,
        'modelRequests':len(all_receipts),'transportFailures':sum(not r['success'] for r in all_receipts),
        'http429Count':sum(r['httpStatus']==429 for r in all_receipts),
        'lengthTruncatedResponses':sum(r['finishReason']=='length' for r in all_receipts),
        'emptyVisibleResponses':sum(not v[0].strip() for task in catalog for arm in cfg['arms']
            for p in [(out/'tasks'/arm/task['name']/'samples.json')] if p.exists() for v in [(s['answer'],) for s in read(p)]),
        'concurrency':overlap,'pilotExpensesIncluded':False,'rows':rows}
    audit={'protocolAndIntegrityChecksPassed':True,'all488RecordsPresent':True,'infrastructureExceptions':errors,
           'all488GradesValid':not errors,'sourcePinsMatched':True,'messageIsolationPassed':True,
           'strictBinaryFeedbackPassed':True,'costCapsPassed':True,'actualConcurrencyReplayPassed':True}
    save(out/'summary.json',summary);save(out/'audit.json',audit);save(out/'paired-comparison.json',paired)
    save(out/'budget-curves.json',{'units':'settled costs plus conservative unknown reserves','unknownCostsAreNotZero':True,'curves':curves})
    with (out/'results.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    text=f"""# miniF2F-test: 244-task formal experiment

OpenRouter → DeepInfra / 0731, medium, T=0, 16384 tokens, at most five rounds. Both arms share 16 model HTTP slots; Lean concurrency is 4. Event-driven replacement begins as HTTP calls finish, with no global request interval and bounded 429 backoff. Each task per arm has 3600 seconds/$0.10; formal batch cap $48.80, with pilot costs separate.

| Arm | Valid grades | Passed | Infrastructure anomalies | Confirmed cost USD |
| --- | ---: | ---: | ---: | ---: |
| Independent sampling | {a['valid']}/244 | {a['passed']}/244 | {a['infrastructureExceptions']} | {a['actualCostUsd']:.9f} |
| Binary feedback | {b['valid']}/244 | {b['passed']}/244 | {b['infrastructureExceptions']} | {b['actualCostUsd']:.9f} |

Independent first-round passes: {a['firstAttemptPassed']}/244. Total HTTP requests: {len(all_receipts)}; confirmed cost ${summary['actualCostUsd']:.9f}; {summary['unknownCostCount']} unknown charges; budget exposure including conservative reservations ${exposure:.9f}. HTTP429 count: {summary['http429Count']}; length-truncated responses: {summary['lengthTruncatedResponses']}. Unknown costs are not zero, and infrastructure anomalies are not mathematical proof failures.

Actual peak overlapping HTTP calls: {overlap['actualHttpPeak']}, replayed from request start/end events; all slots closed. Audits passed for messages, grading identities, fixed task list/source, and cost caps. Every task counts toward each arm’s denominator of 244; see summary.json for success-rate bounds under anomalies. Full paired statistics and task-bootstrap intervals: paired-comparison.json; dollar checkpoints: budget-curves.json. Bootstrap describes task-composition uncertainty only.

The complete archive includes every request/response, generation ID, visible answer and original reasoning, candidate SHA, raw Lean output, grade, axiom criterion, cache identity, environment/source, actual/unknown costs, concurrency, and anomaly logs. These are fresh test244 trajectories; pilot and historical scores are not mixed in.
"""
    (out/'REPORT.md').write_text(text)
    if archive:
        target=out/'results.tar.gz';integrity=out/'archive-integrity.json'
        if target.exists():
            with target.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==read(integrity)['sha256']
        else:
            paths=[p for name in ['package','vendor','data','outputs'] for p in (root/name).rglob('*')
                   if p.is_file() and p.name not in ['results.tar.gz','archive-integrity.json'] and not p.name.endswith('.tmp')]
            paths += [root/name for name in ['dependency-bundle.json','package.tar.gz'] if (root/name).exists()]
            with tarfile.open(target,'w:gz') as tar:
                for p in paths:tar.add(p,arcname=str(p.relative_to(root)))
            with target.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
            save(integrity,{'archive':'results.tar.gz','sha256':checksum,'bytes':target.stat().st_size,'files':len(paths),
                'completeExperimentLogs':True,'dependencyBundleSeparate':read(root/'dependency-bundle.json')['sha256']})
    return summary
