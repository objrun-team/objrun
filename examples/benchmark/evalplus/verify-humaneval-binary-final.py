"""Read-only audit of retained artifacts, followed by separate final reports."""
import collections,datetime,hashlib,json,pathlib,re,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[3]
HOME=ROOT/'docs/evalplus-20261012/humaneval/binary-v1'; OUT=HOME/'full'
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def need(ok,label):
    if not ok: raise RuntimeError(label)
def grader_cache(tid,answer,base):
    key=hashlib.sha256(json.dumps([tid,answer,base,None]).encode()).hexdigest()
    return read(HOME/'grader/cache'/key)
checks={}
for name in ['source-pins.json','length-recovery-v2-source-pins.json']:
    files=read(HOME/name)['files']
    need(all(sha(pathlib.Path(f['path']))==f['sha256'] for f in files),'frozen_source_changed:'+name)
    checks[name]=len(files)
before=read(HOME/'checks/length-recovery-v2-before.json')
for key in ['validResults','priorCalls']:
    need(all(sha(pathlib.Path(f['path']))==f['sha256'] for f in before[key]),'retained_artifact_changed:'+key)
    checks[key+'Unchanged']=len(before[key])
need(read(HOME/'controls.json')['allPassed'],'controls_not_passed')
catalog=read(ROOT/'docs/evalplus-20261012/humaneval/public-tasks.json')
ids=[t['officialId'] for t in catalog];need(len(ids)==len(set(ids))==164,'task_catalog')
paths=list((OUT/'results').glob('*.json')); records=[read(p) for p in paths]
need(len(records)==164 and {r['officialId'] for r in records}==set(ids),'result_ids')
need(all(r['grade']['valid'] for r in records),'invalid_results')
need(not (OUT/'runner-lock.json').exists(),'runner_lock_present')
proc=subprocess.run(['powershell','-NoProfile','-Command',"@(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run-humaneval-binary(?:-v2)?\\.ts[\"\\s]+full' } | Select-Object ProcessId,CreationDate,CommandLine) | ConvertTo-Json -Compress"],capture_output=True,text=True)
need(proc.returncode==0,'process_inspection_failed');need(not proc.stdout.strip() or json.loads(proc.stdout)==[],'runner_still_live')
baseline=read(ROOT/'docs/evalplus-20261012/humaneval/full/calls/baseline/HumanEval-0/sample-0/attempt-0/request.json')
options={k:v for k,v in baseline.items() if k!='messages'}
sample_count=truncated=empty_truncated=0; distribution=collections.Counter()
feedback_checks=base_passed=0
for t in catalog:
    tid=t['officialId'];short=tid.replace('/','-');r=next(r for r in records if r['officialId']==tid)
    taskdir=OUT/'tasks'/short;samples=read(taskdir/'samples.json');candidate=read(taskdir/'candidate.json')
    need(1<=len(samples)<=5 and r['sampleCount']==len(samples),'sample_count:'+tid)
    messages=[{'role':'user','content':t['prompt']}]
    for i,s in enumerate(samples):
        need(s['index']==i,'sample_index:'+tid)
        need(s['baseGrade']['valid'] and s['feedback']==('passed' if s['baseGrade']['passed'] else 'failed'),'binary_feedback:'+tid)
        need(s['baseGrade']==grader_cache(tid,s['answer'],True),'base_grader_cache:'+tid)
        if i<len(samples)-1:need(not s['baseGrade']['passed'],'continued_after_base_pass:'+tid)
        attempts=sorted((OUT/'calls'/short/f'sample-{i}').glob('attempt-*'))
        matches=[p for p in attempts if (p/'receipt.json').exists() and read(p/'receipt.json')['requestSha256']==s['requestSha256'] and read(p/'receipt.json').get('generationId')==s['receipt'].get('generationId')]
        need(len(matches)==1,'sample_request_mapping:'+tid)
        req=read(matches[0]/'request.json');resp=read(matches[0]/'response.json')
        need(req['messages']==messages and {k:v for k,v in req.items() if k!='messages'}==options,'request_protocol:'+tid)
        choice=resp['choices'][0];answer=choice['message'].get('content')
        if answer is None:
            need(choice['finish_reason']=='length' and resp['usage']['completion_tokens']==16384 and s['answer']=='' and s['responseClassification']=='token_budget_exhausted_without_answer','empty_answer_policy:'+tid)
            empty_truncated+=1
        else:need(s['answer']==answer,'answer_not_provider_output:'+tid)
        truncated+=choice['finish_reason']=='length'
        messages.extend([{'role':'assistant','content':s['answer']},{'role':'user','content':s['feedback']}])
    last=samples[-1]
    need(last['baseGrade']['passed'] or len(samples)==5,'premature_stop:'+tid)
    need(r['answer']==last['answer']==candidate['answer'],'final_selection:'+tid)
    need(r['candidateSha256']==candidate['sha256']==hashlib.sha256(r['answer'].encode()).hexdigest(),'candidate_hash:'+tid)
    need(candidate['selectedBeforePlusGrading'] and candidate['frozenAtUtc']<r['completedAtUtc'],'candidate_freeze:'+tid)
    need(r['grade']==grader_cache(tid,r['answer'],False),'final_grader_cache:'+tid)
    if 'groups' in r['grade']:need(set(r['grade']['groups'])=={'base','plus'},'final_scoring_groups:'+tid)
    sample_count+=len(samples);feedback_checks+=len(samples);distribution[len(samples)]+=1;base_passed+=bool(last['baseGrade']['passed'])
calls=list((OUT/'calls').rglob('dispatch.json'));receipts=[]
for p in calls:
    need(p.with_name('receipt.json').exists(),'pending_dispatch:'+str(p));r=read(p.with_name('receipt.json'));d=read(p)
    need(r['requestSha256']==d['requestSha256'],'dispatch_receipt_hash')
    if r.get('responseSha256'):need(sha(p.with_name('response.raw.txt'))==r['responseSha256'],'raw_response_changed')
    receipts.append(r)
need(len(receipts)==len(list((OUT/'calls').rglob('receipt.json'))),'unmapped_receipts')
need(sample_count==len(receipts)==171,'sample_call_totals')
passed=sum(r['grade']['passed'] for r in records);failed=[r['officialId'] for r in records if not r['grade']['passed']]
status=read(OUT/'status.json');need(status['stage']=='complete' and status['valid']==164 and status['passed']==passed,'status_totals')
report={'verifiedAtUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'benchmark':'HumanEval+','protocol':'humaneval-base-binary-max5-v1','adapterRevision':'length-recovery-v2','total':164,'valid':164,'passed':passed,'passRate':passed/164,'failed':failed,'exceptions':0,'sampleCount':sample_count,'samplesPerTaskDistribution':dict(distribution),'basePassed':base_passed,'truncatedSamples':truncated,'emptyTruncatedSamples':empty_truncated,'requests':len(calls),'receipts':len(receipts),'pending':0,'actualCostUsd':sum(r.get('actualCostUsd') or 0 for r in receipts),'unknownCostCount':sum(bool(r.get('unknownCost')) for r in receipts),'unknownCostUpperBoundUsd':sum(r.get('upperBoundUsd',0) for r in receipts if r.get('unknownCost')),'firstRunSeconds':before['priorStatus']['elapsedSeconds'],'recoverySeconds':status['elapsedSeconds'],'totalActiveRunnerSeconds':before['priorStatus']['elapsedSeconds']+status['elapsedSeconds'],'startedAtUtc':before['priorStatus']['startedAtUtc'],'completedAtUtc':status['atUtc'],'checks':checks,'protocolDisclosure':'Feedback contains base correctness only. Stop after first base pass or five samples; freeze selected answer before final official base+plus scoring. Enhanced correctness never enters model history. Empty length-truncated responses count as failed generated samples. All original requests and 161 previously valid results remain byte-identical. Model/provider, token budget, reasoning, temperature, task denominator and shared grader unchanged.'}
need(passed==155,'unexpected_pass_count')
(HOME/'checks/final-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
(HOME/'FINAL-RESULTS.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
md=f'''# HumanEval+ binary-feedback final results

All 164 tasks have valid results: {passed}/164 passed ({100*passed/164:.2f}%), {len(failed)} failed, with 0 interface/environment/grading anomalies. Finished at 2026-10-15 13:13:57 (Asia/Shanghai); the runner exited and no requests remain in flight.

At most 5 generations, with only public base passed/failed feedback and the task’s own answer history, stopping when base passes. After freezing the final candidate, run original EvalPlus v0.3.1 base+plus grading; enhanced tests never influence feedback or stopping. Model: deepseek/deepseek-v4.1-flash, DigitalOcean, no fallback, high, temperature0, 16384 tokens, concurrency 2. This is a binary base-feedback protocol, not standard oracle-free single-shot generation or five rounds of complete base+plus feedback.

There are {sample_count} actual samples, with attempt distribution {dict(sorted(distribution.items()))}; {empty_truncated} exhausted the output budget without producing an answer and count as failed samples. The original adapter mislabeled empty-answer truncation in 3 tasks as interface anomalies. Adapter V2 corrects only this classification, consumes the original samples, and continues remaining attempts. All original 58 frozen-source and 5 new-source checks match; the original 161 valid results and all old request bytes are unchanged, with old anomaly results retained under full/history. Token budgets were not raised, thinking was not extracted as an answer, valid failures were not retried, and the 5-attempt cap was not extended.

All {len(calls)} dispatches have receipts, pending=0. Known model cost is ${report['actualCostUsd']:.9f}, with 0 unknown charges. Initial run: 808.036 seconds; recovery: {status['elapsedSeconds']:.3f} seconds; cumulative active runner time: {report['totalActiveRunnerSeconds']:.3f} seconds (about {report['totalActiveRunnerSeconds']/60:.2f} minutes). Waiting and diagnosis between segments are excluded.

Failed: {', '.join(failed)}.

Per-task results are in full/results; candidates, samples, and base feedback in full/tasks; raw requests/responses and costs in full/calls; actual grading caches and logs in grader. Full read-only verification is in checks/final-verification.json, covering fixed IDs, attempt counts, all request contexts/model parameters, feedback boundaries, stopping candidates, candidate hashes/freeze times, official grading caches, costs, and preserved old-file SHAs.
'''
(HOME/'FINAL-RESULTS.md').write_text(md,encoding='utf-8')
print(json.dumps(report,ensure_ascii=True))
