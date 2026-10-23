"""Package actual SkillsBench partial/complete pilot bytes once; no model calls.

Uses the manifest/streaming ZIP pattern of package-chemiq-pilot-v6.py. Active
journals are copied only to a captured complete durable prefix. Private engine
configs and credentials are excluded and actual secret values are checked.
"""
import argparse
from datetime import datetime,timezone
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[2]
HOME=ROOT/'docs/repair-2026-10-08/skillsbench-ten-takeover-v1'
D_PARENT=Path('D:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/skillsbench-ten-small-batch')


def digest(raw):return hashlib.sha256(raw).hexdigest()
def document(p):return json.loads(Path(p).read_bytes())


def package(recipe_path):
    recipe_path=recipe_path.resolve();r=document(recipe_path);run=r['runId'];output=Path(r['output']);layout=document(r['storageDescriptorPin']['path']);root=Path(layout['storePhysical'])
    assert r['draftFastFirst'] and r['selectedDistinctTasks']==10 and len(r['taskSchedule'])==20 and root.parent==D_PARENT and recipe_path.parent==output
    secret_values=set()
    for line in (ROOT/'.env').read_text(encoding='utf8').splitlines():
        m=re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*?)\s*$',line)
        if m and re.search('KEY|TOKEN|SECRET|PASSWORD',m[1],re.I):
            value=m[2].strip('"\'')
            if len(value)>=6:secret_values.add(value)
    slot_layouts=[document(p['path']) for p in r['slotStorageDescriptorPins']]
    for s in slot_layouts:
        for p in Path(s['directories']['sqlite']).glob('worker-*/config.yaml'):
            text=p.read_text(encoding='utf8')
            for m in re.finditer(r'(?:publisherToken|token):\s*("[^"\n]+")',text):secret_values.add(json.loads(m[1]))
    needles=[x.encode() for x in secret_values];assert needles
    members={};origins={};excluded=[];mutable=[]
    def check(raw,name):
        expanded=gzip.decompress(raw) if name.endswith('.gz') else raw
        assert not any(x in expanded for x in needles),'Actual credential found in package member: '+name
    def add_raw(name,raw,origin=None):
        assert name and not name.startswith('/') and '\\' not in name and all(x not in ('','..') for x in name.split('/')) and name not in members
        check(raw,name);members[name]=raw
        if origin:origins[name]=origin
    def add_file(name,path,expected=None):
        path=Path(path).resolve();z=path.lstat()
        assert stat.S_ISREG(z.st_mode) and z.st_nlink==1 and not getattr(z,'st_file_attributes',0)&1024
        assert path.name not in ('.env','config.yaml') and path.suffix.lower() not in ('.key','.pem')
        raw=path.read_bytes();assert len(raw)<=512*1024**2
        if expected:assert digest(raw)==expected['sha256'] and ('bytes' not in expected or len(raw)==expected['bytes'])
        add_raw(name,raw,{'path':str(path),'bytes':len(raw),'sha256':digest(raw)})
    def add_tree(prefix,folder):
        folder=Path(folder).resolve()
        for p in sorted(folder.rglob('*')):
            if p.is_file():
                if p.name=='config.yaml' or p.suffix.lower() in ('.key','.pem'):excluded.append(str(p));continue
                add_file(prefix+'/'+p.relative_to(folder).as_posix(),p)
    def add_json(name,value):add_raw(name,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
    records=[];by_index={}
    for p in sorted(output.glob('generation-*.json'),key=lambda p:int(p.stem.split('-')[-1])):
        v=document(p);records.append(v);by_index[v['index']]=v
    assert records and any(c.get('providerAttempted') for v in records for c in v['apiCalls']),'A preparation-only ZIP is not a trial result package'
    add_file('provenance/recipe.json',recipe_path)
    add_file('provenance/run-manifest.json',output/'manifest.json')
    for p in output.glob('*.json'):
        if p.name.startswith(('generation-','task-','stage-grade-')) or p.name in ('prepared-recipe.json','recipe.json','manifest.json'):continue
        if p.name.startswith('tool-ledger-slot-'):add_raw('raw/'+p.name,p.read_bytes());mutable.append(str(p))
        else:add_file('provenance/run/'+p.name,p)
    # A checkpoint pins a journal prefix, not an actively growing EOF.
    journal=Path(layout['directories']['journal']);state_raw=(journal/'api-state.json').read_bytes();state=json.loads(state_raw);prefix=state['durablePrefix']
    with (journal/'api-events.jsonl').open('rb') as f:events_raw=f.read(prefix['bytes'])
    assert len(events_raw)==prefix['bytes'] and (not events_raw or events_raw.endswith(b'\n'))
    lines=events_raw.splitlines(keepends=True);assert len(lines)==prefix['eventCount'] and (digest(lines[-1]) if lines else digest((journal/'journal-config.json').read_bytes()))==prefix['lastSha256']
    add_raw('raw/provider/api-events.jsonl',events_raw);add_raw('raw/provider/api-state.json',state_raw);add_file('raw/provider/journal-config.json',journal/'journal-config.json')
    usage={'promptTokens':0,'completionTokens':0,'cacheHitTokens':0};provider_files=set();requests=finishes=real_requests=0
    for line in lines:
        event=json.loads(line);v=event['record']
        if event['kind']=='start':requests+=1;provider_files.add(Path(v['requestFile']))
        else:
            finishes+=1;real_requests+=int(v.get('providerAttempted') is True)
            if v.get('responseFile'):provider_files.add(Path(v['responseFile']))
            u=v.get('usage') or {};usage['promptTokens']+=u.get('prompt_tokens',0);usage['completionTokens']+=u.get('completion_tokens',0);usage['cacheHitTokens']+=u.get('prompt_cache_hit_tokens',0)
    for p in sorted(provider_files):add_file('raw/provider/'+p.name,p)
    cash=Path(layout['directories']['cash']);add_file('raw/cash/cash-config.json',cash/'cash-config.json')
    cash_raw=(cash/'cash-events.jsonl').read_bytes();cash_raw=cash_raw[:cash_raw.rfind(b'\n')+1];add_raw('raw/cash/cash-events.jsonl',cash_raw)
    if (cash/'cash-close.json').exists():add_file('raw/cash/cash-close.json',cash/'cash-close.json')
    add_json('provenance/active-snapshot.json',{'capturedAtUtc':datetime.now(timezone.utc).isoformat(),'providerDurablePrefix':prefix,
        'providerPendingAtSnapshot':requests-finishes,'activeRunSnapshot':not(output/'summary.json').exists(),'mutableFilesCopiedAsSnapshot':mutable,
        'cashEventsCompleteLinePrefix':True,'feesAreEstimatesNotInvoices':True,'originalUnknownSettled':False})
    evaluations={}
    for row in r['taskSchedule']:
        i=row['index'];v=by_index.get(i);label=row['officialId']+'/'+row['arm'];base='tasks/'+label
        if not v:continue
        add_file(base+'/generation.json',output/('generation-'+str(i)+'.json'))
        if (output/('task-'+str(i)+'.json')).exists():
            v=document(output/('task-'+str(i)+'.json'));add_file(base+'/final-record.json',output/('task-'+str(i)+'.json'))
        add_json(base+'/trace.json',v.get('trace',[]));add_raw(base+'/candidate-answer.txt',(v.get('candidate') or '').encode())
        for p in v.get('databasePins',[]):add_file(base+'/sqlite/'+Path(p['path']).name,p['path'],p)
        cp=(v.get('artifactCapture') or {}).get('capturePin')
        if cp:
            capture=document(cp['path']);add_tree(base+'/capture',Path(cp['path']).parent)
            if capture.get('artifactPin'):add_file(base+'/candidate-artifact/'+Path(capture['artifactPin']['path']).name,capture['artifactPin']['path'],capture['artifactPin'])
        if v.get('solverClosurePin'):add_tree(base+'/owned-solver',Path(v['solverClosurePin']['path']).parent)
        # The real gateway supplies sequential files; join each task's receipts.
        slot=next((j for j,s in enumerate(slot_layouts) if document(v['storageDescriptorPin']['path'])['ownerNonce']==s['ownerNonce']),None)
        for q in v.get('toolQuiescence',{}).get('receipts',[]):
            for kind in ('request','response'):
                p=Path(layout['directories']['raw'])/('tools-slot-'+str(slot))/('tool-'+str(q['index'])+'-'+kind+'.json.gz')
                if p.exists():
                    raw=p.read_bytes();expanded=gzip.decompress(raw);expected=q.get(kind+'Sha256')
                    if expected:assert digest(expanded)==expected
                    add_raw(base+'/tool-receipts/'+p.name,raw,{'path':str(p),'bytes':len(raw),'sha256':digest(raw)})
        grade_path=output/('stage-grade-'+str(i)+'.json');grade=None
        if v.get('finalGradeOwnerPin'):grade={'gradeOwnerPin':v['finalGradeOwnerPin'],'evaluation':v.get('finalEvaluation'),'callerPin':v.get('finalGradeCallerPin')}
        elif grade_path.exists():grade=document(grade_path);add_file('grading/'+label+'/stage-grade.json',grade_path)
        if v.get('finalGradeOwnerPin') and grade_path.exists():
            previous=document(grade_path);add_file('grading/'+label+'/earlier-stage/stage-grade.json',grade_path)
            if previous.get('gradeOwnerPin'):add_tree('grading/'+label+'/earlier-stage/native',Path(previous['gradeOwnerPin']['path']).parent)
            if previous.get('callerPin'):add_file('grading/'+label+'/earlier-stage/caller.json',previous['callerPin']['path'],previous['callerPin'])
        if not grade and v.get('finalGradeCallerPin'):add_file('grading/'+label+'/unverified-caller.json',v['finalGradeCallerPin']['path'],v['finalGradeCallerPin'])
        if grade and grade.get('gradeOwnerPin'):
            gp=grade['gradeOwnerPin'];add_tree('grading/'+label+'/native',Path(gp['path']).parent)
            if grade.get('callerPin'):add_file('grading/'+label+'/caller.json',grade['callerPin']['path'],grade['callerPin'])
            owner=document(gp['path'])
            for name,p in (owner.get('resultPins') or {}).items():add_file('grading/'+label+'/'+name,p['path'],p)
            evaluations[i]=grade.get('evaluation')
    # Once generation and final grading close, retain every feedback grader's
    # original output as well as the authoritative per-task final grade.
    feedback_logs_closed=(output/'summary.json').exists()
    if feedback_logs_closed:
        for slot,s in enumerate(slot_layouts):
            logs=Path(s['storePhysical'])/'private-logs'
            if logs.exists():add_tree('raw/feedback/slot-'+str(slot),logs)
    # Executed snapshots, including the explicitly preserved guard revision.
    add_file('source/manifest.json',r['sourceSnapshotPin']['path'],r['sourceSnapshotPin']);snapshot=document(r['sourceSnapshotPin']['path'])
    source_rows={x['originalPin']['path']:x for x in snapshot['files']}
    if r.get('payloadGuardRevisionPin'):
        add_file('source/payload-guard-revision.json',r['payloadGuardRevisionPin']['path'],r['payloadGuardRevisionPin'])
        for x in document(r['payloadGuardRevisionPin']['path'])['files']:
            original=x['originalPin']['path'];old=source_rows.get(original)
            if old:
                p=Path(original);p=p if p.is_absolute() else ROOT/p
                add_file('source/prior-superseded/'+p.relative_to(ROOT).as_posix(),old['snapshotPin']['path'],old['snapshotPin'])
            source_rows[original]=x
    for original,x in source_rows.items():
        p=Path(original);p=p if p.is_absolute() else ROOT/p
        add_file('source/executed/'+p.relative_to(ROOT).as_posix(),x['snapshotPin']['path'],x['snapshotPin'])
    add_file('source/package-skillsbench-fast-v3.py',Path(__file__).resolve())
    add_file('selection.json',ROOT/'docs/repair-2026-10-08/skillsbench-ten-artifact-readonly-preflight/selection-v1/ten-task-list.json')
    add_file('provenance/public-metadata.json',ROOT/'docs/repair-2026-10-08/skillsbench-ten-artifact-readonly-preflight/selection-v1/public-metadata.json')
    add_file('provenance/collection-index.json',r['collectionIndexPin']['path'],r['collectionIndexPin'])
    for dp in r['taskDescriptorPins']:
        d=document(dp['path']);tid=d['taskId'];add_file('provenance/tasks/'+tid+'/descriptor.json',dp['path'],dp)
        for key in ('candidateImageProofPin','privateRuntimeProofPin','expectedCollectionPin'):
            p=d[key];add_file('provenance/tasks/'+tid+'/'+key+'.json',p['path'],p)
        task_home=ROOT/'.phase1-data/skillsbench/vendor/skillsbench/tasks'/tid
        add_file('source/original-tasks/'+tid+'/task.md',task_home/'task.md')
        add_tree('source/original-tasks/'+tid+'/verifier',task_home/'verifier')
        add_tree('source/original-tasks/'+tid+'/environment',task_home/'environment')
    # Reuse pinned environment/dependency inventories without another build.
    depot=HOME/'wheel-depots/21a479d9e0cb4d30a83d34675b5a7855/depot.json';add_file('provenance/dependencies/offline-wheel-depot.json',depot)
    prior_records=HOME/'first-delivery-v3/provenance'
    if prior_records.exists():add_tree('provenance/existing-records',prior_records)
    add_json('provenance/review-status.json',{'priorImplementationReview':'completed with fixes in v2; prior local14Python/3Bun controls passed',
        'priorReviewRecordsIncluded':prior_records.exists(),'priorFindingsRetained':True,'noNewIndependentReviewPerformedByPackager':True,
        'feedbackGraderRawLogsIncluded':feedback_logs_closed,
        'fastV3IndependentReview':'pending','fullEnvironmentCertification':'pending','fullColdTriplets':'partial successful controls reused',
        'originalShellComparisons':'partial; failures retained','labFractionalControl':'pending','formalScoreCertificate':False,
        'userPriority':'fast actual ZIP delivery; do not delay for repeated review'})
    rows=[]
    for e in r['taskSchedule']:
        i=e['index'];v=by_index.get(i);ev=evaluations.get(i);calls=v.get('apiCalls',[]) if v else []
        real=any(c.get('providerAttempted') and c.get('httpStatus')==200 and c.get('completionValid') and c.get('usage') for c in calls)
        rows.append({'taskId':e['officialId'],'arm':e['arm'],'index':i,'realGenerationCompleted':real,'status':('已评分' if ev.get('valid') else '评分未验证') if ev else '已运行，评分待补' if real else '未完成',
            'officialReward':ev.get('officialReward') if ev else None,'strictAllPassed':ev.get('allTestsPassed') if ev else None,
            'fullCollectionValid':ev.get('valid') if ev else None,'providerRequests':sum(bool(c.get('providerAttempted')) for c in calls),
            'generationValid':v.get('generationValid') if v else None,'runtimeVerdict':v.get('runtimeVerdict') if v else None,
            'originalAgentSeconds':e['taskSeconds'],'originalVerifierSeconds':e['verifierSeconds'],'cpus':e['cpus'],'memoryMb':e['memoryMb'],
            'taskRecordMember':'tasks/'+e['officialId']+'/'+e['arm']+'/generation.json' if v else None,'gradeMember':'grading/'+e['officialId']+'/'+e['arm'] if ev else None,
            'fault':v.get('fault') if v else None})
    complete=sum(x['realGenerationCompleted'] for x in rows);graded=sum(x['officialReward'] is not None for x in rows);passed=sum(x['strictAllPassed'] is True for x in rows)
    summary={'protocol':'skillsbench-actual-pilot-package-summary-v3','runId':run,'packageKind':'complete-results' if complete==20 and graded==20 else 'partial-results',
        'plannedDistinctTasks':10,'plannedTaskRuns':20,'realGenerationCompleted':complete,'gradedTaskRuns':graded,'passedTaskRuns':passed,
        'rejectedGradedTaskRuns':sum(x['fullCollectionValid'] is True and x['strictAllPassed'] is False for x in rows),'unverifiedGrades':sum(x['fullCollectionValid'] is False for x in rows),
        'unfinishedTaskRuns':20-complete,'model':r['model'],'concurrency':2,'originalTaskBudgetsPreserved':True,'providerRequestsInCapturedPrefix':real_requests,
        'providerUsage':usage,'recordedUsageUpperBoundUsdAtSnapshot':state.get('recordedUsageUpperBoundUsd'),'feeEstimateNotInvoice':True,'formalScoreCertified':False,
        'fullEnvironmentCertificationPending':True,'originalUnknownSettled':False,'full87Authorized':False,'rows':rows}
    add_json('summary.json',summary);stream=io.StringIO();w=csv.DictWriter(stream,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows);add_raw('results.csv',b'\xef\xbb\xbf'+stream.getvalue().encode())
    def reward_label(row):
        reward=row['officialReward']
        return str(reward) if reward is not None and row['fullCollectionValid'] is True else row['status']+(f'（原始reward {reward}）' if reward is not None else '')
    table='\n'.join('| '+rows[i]['taskId']+' | '+reward_label(rows[i])+' | '+reward_label(rows[i+1])+' |' for i in range(0,20,2))
    readme=f'# SkillsBench {"完整试跑记录" if complete==20 else "部分结果阶段包"}\n\n固定10题 U/F 各一次，计划20次；实际完成真实生成 {complete}/20，已评分 {graded}/20，严格全通过 {passed} 次。奖励来自原始测试；lab数值奖励与严格全通过布尔分开保存。模型 deepseek-flash，temperature=0，seed=42，max_tokens=8192，两个独立槽并发，原题时间/CPU/RAM预算保持不变。\n\n| 题目 | U 奖励/状态 | F 奖励/状态 |\n|---|---|---|\n{table}\n\nsummary.json 与 results.csv 提供机器可读结果。tasks/ 包含完整已完成轨迹、候选回答和产物、工具回执、捕获与关闭原始证据；grading/ 包含真实私有原测试输出；raw/ 保存实际模型请求/响应、usage、事件链和现有费用记录；source/、provenance/ 保存执行快照、配方、原题评分来源和依赖/环境清单。\n\n阶段包只包含打包时可冻结的真实记录。运行中的日志取已落盘完整前缀；尚未生成或评分的项目明确未完成。初版不代表全部认证完成：快交付v3独立审阅、完整环境认证、剩余冷对照、原始shell全量比较和lab小数控制待补。历史未结费用8.39218元仍未结；费用是估计而非发票。不启动87题，也不支持旧85.1%声明。\n\n离线核验：`python verify-package.py 本ZIP路径`。核验只读取成员大小/SHA256，不跑模型或评分。实际私密配置/凭据不收入ZIP。\n'
    add_raw('README.md',readme.encode());verify=r'''"""Offline member size/SHA256 check; no models, Docker or extraction."""
import hashlib,json,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
 m=json.loads(z.read('package-manifest.json'));names=z.namelist();assert len(names)==len(set(names));expected={x['path'] for x in m['files']}|{'package-manifest.json'};assert set(names)==expected
 for row in m['files']:
  h=hashlib.sha256();size=0
  with z.open(row['path']) as f:
   while b:=f.read(1024*1024):h.update(b);size+=len(b)
  assert size==row['bytes'] and h.hexdigest()==row['sha256'],row['path']
 print(json.dumps({'verified':True,'members':len(names),'modelCalls':0}))
''';add_raw('verify-package.py',verify.encode())
    add_json('provenance/package-inputs.json',{'origins':origins,'privateFilesExcluded':excluded,'actualCredentialValuesChecked':len(needles),
        'actualCredentialsSerialized':False,'allIncludedGzipBodiesExpandedForSecretCheck':True,'packager':'adapted from package-chemiq-pilot-v6.py; own SkillsBench scopes only'})
    manifest={'protocol':'skillsbench-pilot-package-manifest-v3','runId':run,'files':[{'path':name,'bytes':len(raw),'sha256':digest(raw)} for name,raw in sorted(members.items())]}
    add_json('package-manifest.json',manifest)
    folder=root/'taskmeta/pilot-packages';folder.mkdir(exist_ok=True);zip_path=folder/('SkillsBench-'+summary['packageKind']+'-'+uuid.uuid4().hex+'.zip')
    with zipfile.ZipFile(zip_path,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,raw in sorted(members.items()):z.writestr(name,raw)
    # One post-write pass checks CRC/readability, exact member set and SHA.
    with zipfile.ZipFile(zip_path) as z:
        assert len(z.namelist())==len(members) and set(z.namelist())==set(members)
        for row in manifest['files']:
            raw=z.read(row['path']);assert len(raw)==row['bytes'] and digest(raw)==row['sha256']
    h=hashlib.sha256()
    with zip_path.open('rb') as f:
        while b:=f.read(1024*1024):h.update(b)
    receipt={'protocol':'skillsbench-real-pilot-package-receipt-v3','zipPath':str(zip_path),'bytes':zip_path.stat().st_size,'sha256':h.hexdigest(),
        'members':len(members),'actualRealGenerations':complete,'actualGradedRuns':graded,'passedRuns':passed,'packageKind':summary['packageKind'],
        'onePostWriteVerificationPassed':True,'actualCredentialsFound':False,'formalScoreCertified':False,'modelCallsByPackager':0,'packagedAtUtc':datetime.now(timezone.utc).isoformat()}
    dest=HOME/'first-delivery-v3'/('package-receipt-'+uuid.uuid4().hex+'.json');dest.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(receipt),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--recipe',type=Path,required=True);a=p.parse_args();package(a.recipe)
