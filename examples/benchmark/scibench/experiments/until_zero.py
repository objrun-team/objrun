"""Advance at most one independently archived round per explicit/heartbeat action."""
from pathlib import Path
import argparse,collections,csv,json,re,subprocess,sys,time
from infra_retry_policy import ARMS,classify,sha
REPO=Path(__file__).resolve().parents[4];DOCS=REPO/'docs/scibench';HISTORY=DOCS/'UNTIL_ZERO_HISTORY.json';POLICY=DOCS/'UNTIL_ZERO_POLICY.json';BASE='/var/tmp/tgengin-scibench-20261016';SSH='C:/Users/y1252/Documents/Codex/2026-10-15/s-c/work/scicode/ssh-config'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def local(run):return DOCS/run.removeprefix('scibench-')
def command(script,*args):
 p=subprocess.run([sys.executable,'-X','utf8',str(REPO/'examples/benchmark/scibench/experiments'/script),*args],cwd=REPO,capture_output=True,text=True,timeout=180);assert p.returncode==0,p.stderr[-3000:]+p.stdout[-2000:];print(p.stdout.strip());return p.stdout
def verified_batch(run):
 folder=local(run);audit=read(folder/'AUDIT.json');retrieval=read(folder/'retrieval.json');archive=Path(retrieval['localArchive']);assert retrieval['sha256Verified'] and sha(archive.read_bytes())==retrieval['sha256'] and archive.stat().st_size==retrieval['bytes']
 assert audit['allPassed'] and not audit['partial'] and not audit['activeUnreceiptedDispatches']
 return {'run':run,'root':read(folder/'full-results/outputs/canonical/launch.json')['root'],'records':sum(x['completed'] for x in audit['arms'].values()),'finalAuditPassed':True,'auditSha256':sha((folder/'AUDIT.json').read_bytes()),'localArchiveVerified':True,'archiveSha256':retrieval['sha256'],'archiveBytes':retrieval['bytes']}
def remote(arguments,stdin=None):
 tool=read(DOCS/'UNTIL_ZERO_TOOLING.json');assert tool['ready'];path=tool['remoteDirectory']
 code="from pathlib import Path\nimport hashlib,json,subprocess,sys\np=Path("+repr(path)+");assert hashlib.sha256((p/'TOOL_PINS.json').read_bytes()).hexdigest()=="+repr(tool['toolPinsSha256'])+"\nv=json.loads((p/'TOOL_PINS.json').read_text());assert all(hashlib.sha256((p/x['path']).read_bytes()).hexdigest()==x['sha256'] for x in v['files'])\nr=subprocess.run(['python3.11',str(p/'until_zero_remote.py'),*"+repr(arguments)+"],input="+repr(json.dumps(stdin) if stdin is not None else '')+",capture_output=True,text=True);sys.stdout.write(r.stdout);sys.stderr.write(r.stderr);sys.exit(r.returncode)\n"
 history=stdin['batches'] if stdin is not None else read(HISTORY)['batches'];integrity=tool['historyAuditor']
 prefix="from pathlib import Path\nimport hashlib,subprocess,json\na=Path("+repr(integrity['path'])+");assert hashlib.sha256(a.read_bytes()).hexdigest()=="+repr(integrity['sha256'])+"\nv=subprocess.run(['python3.11',str(a)],input="+repr(json.dumps(history))+",capture_output=True,text=True);assert v.returncode==0,v.stderr+v.stdout\n"
 p=subprocess.run(['ssh','-F',SSH,'novaeve','python3.11','-'],input=prefix+code,capture_output=True,text=True,timeout=120);assert p.returncode==0,p.stderr[-3500:]+p.stdout[-2000:];return json.loads(p.stdout)
def inspection(run,final=False):
 assert re.fullmatch(r'scibench-untilzero-20261016-r[0-9]{3,}-c32',run)
 v=remote(['--inspect',BASE+'/'+run]+(['--final'] if final else []))
 code="""from pathlib import Path
import json
r=Path(ROOT);o=r/'outputs/canonical';read=lambda p:json.loads(p.read_text());s=read(o/'status.json');launch=read(o/'launch.json')
def command(pid):
 p=Path('/proc',str(pid),'cmdline')
 try:return p.read_bytes()
 except FileNotFoundError:return b''
grader=read(o/'grader-process.json') if (o/'grader-process.json').exists() else None
native=[]
for p in (o/'tasks').glob('*/*/engine-process.json'):
 x=read(p);env=Path('/proc',str(x['pid']),'environ')
 try:owned=env.exists() and b'TGENGIN_CONFIG='+str(p.parent/'engine/config.yaml').encode() in env.read_bytes().split(b'\\0')
 except FileNotFoundError:owned=False
 current=str(r/'package/engine/app/src/main.ts').encode() in command(x['pid'])
 assert not current or owned,'NativeProcessOwnershipMismatch'
 if owned:assert x['runnerPid']==s['pid']
 native.append({'id':p.parent.name,'pid':x['pid'],'owned':owned,'terminalRecordExists':(o/'results'/p.parent.parent.name/(p.parent.name+'.json')).exists()})
print(json.dumps({'allPassed':True,'controllerCmdlineOwned':str(r/'package/run.ts').encode() in command(s['pid']),'supervisorCmdlineOwned':str(r/'package/until_zero_remote.py').encode() in command(launch['supervisorPid']),'graderCmdlineOwned':str(r/'package/stand.py').encode() in command(grader['pid']) if grader else False,'runnerLockPresent':(o/'runner-lock.json').exists(),'nativeProcesses':native}))
""".replace('ROOT',repr(BASE+'/'+run))
 p=subprocess.run(['ssh','-F',SSH,'novaeve','python3.11','-'],input=code,capture_output=True,text=True,timeout=30);assert p.returncode==0,p.stderr;v['ownedProcessAudit']=json.loads(p.stdout)
 if final:assert not v['ownedProcessAudit']['runnerLockPresent'] and not any(x['owned'] for x in v['ownedProcessAudit']['nativeProcesses'])
 save(local(run)/'ATTEMPT_AUDIT.json',v);return v
def report(partial=False):
 history=read(HISTORY);batches=history['batches'];current=history.get('currentRun');frames=[];fees={};generations=[];merged={};original={};locations={};statistics={}
 for b in batches+([{'run':current}] if current else []):
  run=b['run'];folder=local(run);root=folder/'full-results';is_current=run==current;aud=read(folder/('PROGRESS_AUDIT.json' if is_current and partial else 'AUDIT.json'));assert aud['allPassed']
  plan=read(root/'package/repair-plan.json') if (root/'package/repair-plan.json').exists() else None
  rows=[(read(p),p) for p in (root/'outputs/canonical/results').glob('*/*.json')]
  if not frames:assert len(rows)==1664
  for r,p in rows:
   k=(r['arm'],r['id'])
   if k in merged:
    assert not merged[k]['grade'].get('valid'),'ExistingValidScoreChanged'
    assert r['originalResultSha256']==sha(original[k].read_bytes()) and r['previousResultSha256']==sha(locations[k].read_bytes()) if plan and plan.get('mode')=='until_zero' else r['originalResultSha256']==sha(original[k].read_bytes())
   else:original[k]=p
   merged[k]=r;locations[k]=p
  denoms={arm:(416 if not frames else sum(x['arm']==arm for x in plan['attempts'])) for arm in ARMS}
  statistics[run]={arm:{'denominator':denoms[arm],'completed':sum(r['arm']==arm for r,_ in rows),'valid':sum(r['arm']==arm and bool(r['grade'].get('valid')) for r,_ in rows),'passed':sum(r['arm']==arm and bool(r['grade'].get('valid') and r['grade'].get('passed')) for r,_ in rows)} for arm in ARMS}
  frames.append(run);fees[run]={k:aud[k] for k in ['actualCostUsd','unknownCostCount','unknownCostUpperBoundUsd','modelCalls']}
  for p in (root/'outputs/canonical/calls').rglob('receipt.json'):
   g=read(p).get('generationId')
   if g:generations.append(g)
 assert len(merged)==1664 and len(generations)==len(set(generations)),'DuplicateGenerationCost'
 statistics['merged']={arm:{'denominator':416,'completed':416,'valid':sum(k[0]==arm and bool(r['grade'].get('valid')) for k,r in merged.items()),'passed':sum(k[0]==arm and bool(r['grade'].get('valid') and r['grade'].get('passed')) for k,r in merged.items())} for arm in ARMS}
 for group in statistics.values():
  for s in group.values():s.update({'EXRateAll':s['passed']/s['denominator'] if s['denominator'] else None,'EXRateValidOnly':s['passed']/s['valid'] if s['valid'] else None})
 remaining=[{'arm':k[0],'id':k[1],'classification':classify(r),'resultPath':str(locations[k]),'attemptId':r.get('attemptId'),'attemptNo':r.get('attemptNo',0)} for k,r in sorted(merged.items()) if not r['grade'].get('valid')]
 combined={k:sum(s[k] for s in fees.values()) for k in ['actualCostUsd','unknownCostCount','unknownCostUpperBoundUsd','modelCalls']}
 v={'allPassed':True,'partial':partial,'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'validScoresNeverRetried':True,'chronologicalReplacementNotBestOf':True,'statistics':statistics,'feesBySource':fees,'combinedFees':combined,'generationIdsUnique':True,'unknownIsNotZero':True,'remainingExceptions':remaining,'remainingCount':len(remaining),'validCount':1664-len(remaining),'classificationCounts':dict(collections.Counter(classify(r) for r in merged.values()))}
 save(DOCS/'UNTIL_ZERO_AUDIT.json',v);save(DOCS/'UNTIL_ZERO_REMAINING_EXCEPTIONS.json',remaining)
 target=local(current or batches[-1]['run']);save(target/'COMBINED_AUDIT.json',v);save(target/'REMAINING_EXCEPTIONS.json',remaining)
 csvpath=DOCS/'UNTIL_ZERO_MERGED_RESULTS.csv'
 with csvpath.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['arm','id','classification','valid','passed','attemptId','attemptNo','resultPath']);w.writeheader()
  for k,r in sorted(merged.items()):w.writerow({'arm':k[0],'id':k[1],'classification':classify(r),'valid':r['grade'].get('valid'),'passed':r['grade'].get('passed') if r['grade'].get('valid') else '', 'attemptId':r.get('attemptId',''),'attemptNo':r.get('attemptNo',0),'resultPath':str(locations[k])})
 (target/'MERGED_RESULTS.csv').write_bytes(csvpath.read_bytes())
 fmt=lambda n:'—' if n is None else f'{n:.2%}'
 lines=['# SciBench 原始、逐轮补跑与合并结果','','按用户最新授权，所有剩余无效记录（包括原生预算耗尽/未提交）逐轮获得独立新尝试，直到0异常。有效答错保留，不择优。原始/合并每组分母416，补跑各组分母为当轮计划数；另列有效样本EX率。','','|批次|方法|完成/分母|有效|通过|总集EX率|有效样本EX率|','|---|---|---:|---:|---:|---:|---:|']
 for run,group in statistics.items():
  for arm,s in group.items():lines.append(f"|{run}|{arm}|{s['completed']}/{s['denominator']}|{s['valid']}|{s['passed']}|{fmt(s['EXRateAll'])}|{fmt(s['EXRateValidOnly'])}|")
 lines+=['',f'有效记录{1664-len(remaining)}/1664；剩余无效{len(remaining)}条。明细见UNTIL_ZERO_REMAINING_EXCEPTIONS.json。','','费用只按各独立来源加一次，原始和补跑全部保留，未知不视为0。']
 for run,s in {**fees,'combined':combined}.items():lines.append(f"- {run}: 已知${s['actualCostUsd']:.9f}，未知/在飞{s['unknownCostCount']}笔，预留${s['unknownCostUpperBoundUsd']:.9f}，请求{s['modelCalls']}笔。")
 text='\n'.join(lines)+'\n';(DOCS/'UNTIL_ZERO_REPORT.md').write_text(text,encoding='utf-8');(target/'COMBINED_REPORT.md').write_text(text,encoding='utf-8')
 policy=read(POLICY);policy.update({'remainingCount':len(remaining),'validCount':1664-len(remaining),'currentRun':current,'phase':'running' if current else 'complete' if not remaining else 'ready_for_next_round','latestCombinedFees':combined,'lastVerifiedAtUtc':v['atUtc']});save(POLICY,policy)
 final_policy_path=DOCS/'FINAL_ATTEMPT_POLICY.json'
 if final_policy_path.exists():
  cap=read(final_policy_path)
  if not current and cap.get('createdRun') and any(b['run']==cap['createdRun'] for b in batches):policy['phase']='final_scoring_required';save(POLICY,policy)
 state={'phase':'until_zero_'+policy['phase'],'atUtc':v['atUtc'],'activeRun':current,'batches':batches,'remainingInvalid':len(remaining),'validCount':1664-len(remaining),'combinedFees':combined,'report':'UNTIL_ZERO_REPORT.md','automationId':'scibench-416'}
 if current:
  launch=read(local(current)/'connection.json')['launch'];state['currentLaunch']=launch;policy.update({'actualControllerPid':launch['pid'],'supervisorPid':launch['supervisorPid'],'actualRoot':launch['root']});save(POLICY,policy)
 save(DOCS/'SCIBENCH_WORKFLOW_STATE.json',state);save(target/'MONITOR_STATE.json',state)
 formal=read(DOCS/'CURRENT_FORMAL_RUN.json');formal.update({'activeRepairRun':current,'lastVerifiedAtUtc':v['atUtc']});save(DOCS/'CURRENT_FORMAL_RUN.json',formal)
 follow={'id':'scibench-416','kind':'heartbeat','status':'ACTIVE','intervalMinutes':15,'untilZeroInvalid':True,'run':current,'lastVerifiedAtUtc':v['atUtc'],'newAutomationsCreated':0,'notificationPolicy':'quiet unless completion, material failure or required action'}
 if current:follow.update({'actualControllerPid':policy['actualControllerPid'],'actualRoot':policy['actualRoot']})
 for d in [target,DOCS/'formal-20261016-v1',DOCS/'formal-20261016-v4-c32',DOCS/'infra-retry-20261016-v1-c32',DOCS/'infra-retry2-20261016-v1-c32']:save(d/'FOLLOWUP.json',follow)
 return v
ap=argparse.ArgumentParser();ap.add_argument('action',choices=['bootstrap','prepare','inspect','monitor','finalize','report']);ap.add_argument('--run');ap.add_argument('--final',action='store_true');ap.add_argument('--partial',action='store_true');a=ap.parse_args()
if a.action=='bootstrap':
 assert read(POLICY)['authorizedUntilZero']
 batches=[verified_batch(run) for run in ['scibench-formal-20261016-v4-c32','scibench-infra-retry-20261016-v1-c32','scibench-infra-retry2-20261016-v1-c32']]
 if HISTORY.exists():assert read(HISTORY)['batches'][:3]==batches,'ExistingHistoryMismatch'
 else:save(HISTORY,{'batches':batches,'currentRun':None})
 v=report();print(json.dumps({'allPassed':True,'batches':len(batches),'remainingCount':v['remainingCount']}));raise SystemExit(0)
h=read(HISTORY);run=a.run or h.get('currentRun')
if a.action=='prepare':
 final_path=DOCS/'FINAL_ATTEMPT_POLICY.json';cap=read(final_path) if final_path.exists() else None
 assert not h.get('currentRun') and (read(POLICY)['authorizedUntilZero'] or (cap and cap['authorizedFinalRound'])),'ExistingRoundInspectNeverRebuild'
 if cap:assert not cap.get('createdRun') and cap['maxAdditionalRounds']==1,'FinalRoundAlreadyCreatedNoMoreRetries'
 assert [verified_batch(b['run']) for b in h['batches']]==h['batches']
 last=local(h['batches'][-1]['run'])/'full-results/outputs/canonical';status=read(last/'status.json')
 assert not re.search(r'AccountOrKeyBalance|BalanceHTTP(?:401|402|403)|InvalidBalance',str(status.get('stopReason') or '')),'RealBalanceOrPermissionRequiresAction'
 for path in (last/'results').glob('*/*.json'):
  record=read(path);assert not re.search(r'AccountOrKeyBalance|BalanceHTTP(?:401|402|403)',str(record.get('error') or '')+' '+str(record.get('budgetReason') or '')+' '+str(record.get('stoppingReason') or '')),'RealBalanceOrPermissionRequiresAction'
 assert not any(read(p).get('httpStatus') in [401,402,403] for p in (last/'calls').rglob('receipt.json')),'ProviderCredentialOrCreditRejectedRequiresAction'
 v=report();assert v['remainingCount']>0,'AlreadyZeroInvalid'
 if cap:assert {(x['arm'],x['id']) for x in v['remainingExceptions']}=={(x['arm'],x['id']) for x in cap['identities']} and len(h['batches'])==cap['sourceBatchCount'],'FinalAttemptScopeChanged'
 proof={'batches':h['batches'],'allInvalidExplicitlyAuthorizedUntilZero':True,'methodBudgetsUnchanged':True,'dollarCap':None,'authorization':'Latest user: all remaining invalid, including original native failures, retry independent rounds until0. Preserve existing valid scores, all prior records/fees, original finite method/transport/fault protection.'}
 if cap:proof.update({'finalAttemptOnly':True,'maxAdditionalRounds':1,'noFurtherRetriesAfterThisRound':True,'authorization':cap['authorization'],'invalidScoringNote':cap['failureNote'],'legacyBuilderGateOnly':True})
 prepared=remote(['--build'],proof);save(local(prepared['run'])/'preparation.json',prepared);h['currentRun']=prepared['run'];save(HISTORY,h);p=read(POLICY);p.update({'phase':'prepared','currentRun':prepared['run'],'currentRoot':prepared['root']});save(POLICY,p)
 if cap:cap.update({'createdRun':prepared['run'],'createdRoot':prepared['root'],'phase':'prepared'});save(final_path,cap)
 print(json.dumps(prepared));raise SystemExit(0)
if a.action=='inspect':print(json.dumps(inspection(run,a.final)));raise SystemExit(0)
if a.action=='report':
 v=report(a.partial);print(json.dumps({k:v[k] for k in ['allPassed','partial','remainingCount','validCount','combinedFees','classificationCounts']}));raise SystemExit(0)
if a.action=='monitor':
 assert run;command('ops.py','status',run);v=inspection(run)
 if v['controllerLive']:
  command('ops.py','sync',run);command('audit_batch.py',str(local(run)),'--partial');summary=report(True);print(json.dumps({'allPassed':True,'running':True,'run':run,'remainingCount':summary['remainingCount'],'states':v['states']}));raise SystemExit(0)
 assert not v['unreceiptedDispatches'] and set(v['states'])=={'complete'},'StoppedWithUnfinishedAttemptsPreserveDoNotRelaunch'
 # Fall through to finalization only after all records have terminal evidence.
v=inspection(run,True);folder=local(run)
if (folder/'retrieval.json').exists():
 retrieval=read(folder/'retrieval.json');archive=Path(retrieval['localArchive']);assert retrieval['sha256Verified'] and sha(archive.read_bytes())==retrieval['sha256'] and archive.stat().st_size==retrieval['bytes'],'ExistingArchiveMismatch'
else:
 assert not v['existingArchive'],'RemoteArchiveExistsRecoverBySHAWithoutOverwrite'
 command('ops.py','retrieve',run)
command('audit_batch.py',str(folder));batch=verified_batch(run)
assert h.get('currentRun')==run
if not any(b['run']==run for b in h['batches']):h['batches'].append(batch)
h['currentRun']=None;save(HISTORY,h);summary=report();print(json.dumps({'allPassed':True,'finalized':run,'remainingCount':summary['remainingCount'],'readyForNextRound':summary['remainingCount']>0 and not (DOCS/'FINAL_ATTEMPT_POLICY.json').exists(),'combinedFees':summary['combinedFees']}))
