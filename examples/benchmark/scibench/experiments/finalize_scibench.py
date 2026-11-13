"""Verify all archives, derive terminal scoring, and create an independent final bundle."""
from pathlib import Path
import argparse,collections,csv,hashlib,json,math,sqlite3,tarfile,time,tomllib
from final_scoring import NOTE,score_row,fixture
from infra_retry_policy import ARMS,PROTOCOL,classify,sha
REPO=Path(__file__).resolve().parents[4];DOCS=REPO/'docs/scibench';DEST=DOCS/'final-20261016'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def digest_file(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  while b:=f.read(1024*1024):h.update(b)
 return h.hexdigest()
ap=argparse.ArgumentParser();ap.add_argument('--record-followup-stopped',action='store_true');a=ap.parse_args()
if a.record_followup_stopped:
 metadata=read(DEST/'FINAL_RETRIEVAL.json');assert digest_file(Path(metadata['archive']))==metadata['sha256'] and read(DEST/'FINAL_AUDIT.json')['allPassed']
 automation=tomllib.loads(Path('C:/Users/y1252/.codex/automations/scibench-416/automation.toml').read_text(encoding='utf-8'));assert automation['id']=='scibench-416' and automation['status']=='PAUSED'
 receipt={'automationId':'scibench-416','status':'PAUSED','atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'finalArchiveSha256':metadata['sha256'],'allRequestedWorkCompleted':True,'noFurtherAttempts':True};save(DEST/'FOLLOWUP_STOPPED.json',receipt)
 for folder in [DEST,DOCS/'formal-20261016-v1',*(DOCS/b['run'].removeprefix('scibench-') for b in read(DOCS/'UNTIL_ZERO_HISTORY.json')['batches'])]:
  p=folder/'FOLLOWUP.json';v=read(p) if p.exists() else {};v.update(receipt);save(p,v)
 state=read(DOCS/'SCIBENCH_WORKFLOW_STATE.json');state['automationStatus']='PAUSED';state['followupStoppedAtUtc']=receipt['atUtc'];save(DOCS/'SCIBENCH_WORKFLOW_STATE.json',state);print(json.dumps(receipt));raise SystemExit(0)
if (DEST/'FINAL_RETRIEVAL.json').exists():
 v=read(DEST/'FINAL_RETRIEVAL.json');assert digest_file(Path(v['archive']))==v['sha256'] and Path(v['archive']).stat().st_size==v['bytes'] and read(DEST/'FINAL_AUDIT.json')['allPassed'];print(json.dumps(v));raise SystemExit(0)
cap=read(DOCS/'FINAL_ATTEMPT_POLICY.json');history=read(DOCS/'UNTIL_ZERO_HISTORY.json');assert cap['authorizedFinalRound'] and cap['maxAdditionalRounds']==1 and cap['createdRun'] and history['currentRun'] is None
batches=history['batches'];assert len(batches)==cap['sourceBatchCount']+1==6 and batches[-1]['run']==cap['createdRun']
permitted={(x['arm'],x['id']) for x in cap['identities']};assert permitted=={('objrun','scibench-atkins-011'),('objrun','scibench-atkins-031')}
DEST.mkdir(exist_ok=True);bundle=DEST/'scibench-final-20261016-archive.tar';assert not bundle.exists(),'ExistingFinalBundleRecoverMetadataWithoutOverwrite'
checks=[]
def check(name,condition):
 assert condition,name
 checks.append({'name':name,'passed':True})
check('scoring-policy-fixture',fixture()['allPassed'])
merged={};locations={};original_paths={};last_attempts={};statistics={};fees={};archive_members={};generation_ids=[];origins=[];source_archives=[];total_dispatches=0;original_cfg=None;calls_ledger=[]
for index,b in enumerate(batches):
 folder=DOCS/b['run'].removeprefix('scibench-');root=folder/'full-results';out=root/'outputs/canonical';retrieval=read(folder/'retrieval.json');audit=read(folder/'AUDIT.json');archive=Path(retrieval['localArchive'])
 check('final-audit:'+b['run'],audit['allPassed'] and not audit['partial'] and audit['activeUnreceiptedDispatches']==0 and sum(x['completed'] for x in audit['arms'].values())==b['records'])
 check('archive-sha:'+b['run'],retrieval['sha256Verified'] and archive.stat().st_size==retrieval['bytes']==b['archiveBytes'] and digest_file(archive)==retrieval['sha256']==b['archiveSha256'])
 check('audit-sha:'+b['run'],digest_file(folder/'AUDIT.json')==b['auditSha256'])
 count=0
 with tarfile.open(archive) as t:
  for member in t:
   target=(root/member.name).resolve();check_target=target.is_relative_to(root.resolve());assert check_target,'ArchivePathEscape'
   if member.isfile() or member.islnk():
    assert target.is_file(),'MissingArchiveMember:'+b['run']+':'+member.name
    h=hashlib.sha256();stream=t.extractfile(member)
    while raw:=stream.read(1024*1024):h.update(raw)
    assert digest_file(target)==h.hexdigest(),'ArchiveMirrorMismatch:'+b['run']+':'+member.name
    count+=1
   elif member.issym():assert target.exists(),'MissingArchiveSymlink'
 archive_members[b['run']]=count;check('all-archive-members:'+b['run'],count>0);print(json.dumps({'verifiedArchiveMembers':count,'run':b['run']}),flush=True)
 cfg=read(root/'package/experiment.json')
 if original_cfg is None:original_cfg=cfg
 check('same-model-and-method:'+b['run'],all(cfg[k]==original_cfg[k] for k in PROTOCOL) and cfg['perQuestionDollarCap'] is None and cfg['pilotBudgetUsd'] is None)
 plan=read(root/'package/repair-plan.json') if (root/'package/repair-plan.json').exists() else None
 records=[(read(p),p) for p in sorted((out/'results').glob('*/*.json'))];check('unique-records:'+b['run'],len(records)==b['records']==len({(r['arm'],r['id']) for r,p in records}))
 for r,path in records:
  identity=(r['arm'],r['id'])
  if index==0:original_paths[identity]=path
  else:
   check('only-previous-invalid:'+b['run']+'/'+r['id'],identity in merged and not merged[identity]['grade'].get('valid'))
   check('original-link:'+b['run']+'/'+r['id'],r['originalResultSha256']==digest_file(original_paths[identity]))
   if 'previousResultSha256' in r:check('previous-link:'+b['run']+'/'+r['id'],r['previousResultSha256']==digest_file(locations[identity]))
   check('attempt-monotonic:'+b['run']+'/'+r['id'],r['attemptNo']==last_attempts.get(identity,0)+1)
   last_attempts[identity]=r['attemptNo']
  merged[identity]=r;locations[identity]=path
 if index==len(batches)-1:
  check('only-two-final-attempts',{(r['arm'],r['id']) for r,p in records}==permitted and len(records)==2 and all(r['attemptNo']==5 for r,p in records))
  authorization=read(root/'package/final-attempt-authorization.json');check('final-authorization-in-source-pins',authorization['maxAdditionalRounds']==1 and authorization['failureNote']==NOTE and plan['authorization']['finalAttemptOnly'] and plan['authorization']['noFurtherRetriesAfterThisRound'])
  inspection=read(folder/'ATTEMPT_AUDIT.json');check('final-processes-and-dispatches-closed',inspection['final'] and not inspection['controllerLive'] and not inspection['supervisorLive'] and not inspection['unreceiptedDispatches'] and inspection['states']=={'complete':2} and not inspection['ownedProcessAudit']['runnerLockPresent'] and not any(x['owned'] for x in inspection['ownedProcessAudit']['nativeProcesses']))
  snapshot=root/'provenance/attempts-final.sqlite';db=sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True);rounds=list(db.execute('SELECT roundNo FROM rounds ORDER BY roundNo'));check('no-extra-round-created',rounds==[(3,),(4,),(5,)]);db.close()
 receipts=[];dispatches=list((out/'calls').rglob('dispatch.json'));origin_map=None;formal_tasks=None
 if index==0:
  db=sqlite3.connect((root/'provenance/global-registry-final.sqlite').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;origin_map={r['path']:dict(r) for r in db.execute('SELECT * FROM dispatch_origins')};formal_tasks={(r['arm'],r['id']):dict(r) for r in db.execute('SELECT * FROM tasks')};db.close()
  continuation=read(root/'package/continuation.json');check('formal-inherited-origin-map-complete',len(origin_map)==continuation['inheritedModelCalls'] and set(origin_map)<={p.relative_to(root).as_posix() for p in dispatches} and sum(r['originRoot'] is not None for r in formal_tasks.values())==continuation['inheritedRecords'])
 for d in dispatches:
  rp=d.with_name('receipt.json');check('all-dispatches-receipted:'+b['run']+':'+d.relative_to(out/'calls').as_posix(),rp.exists());receipt=read(rp);receipts.append(receipt);relative=d.relative_to(root).as_posix()
  origin=origin_map[relative] if origin_map is not None and relative in origin_map else {'originRoot':b['root'],'originPath':b['root']+'/'+relative}
  if origin_map is not None:
   task=formal_tasks[tuple(d.relative_to(out/'calls').parts[:2])]
   if relative in origin_map:check('formal-origin-sha:'+relative,task['originRoot'] is not None and digest_file(d)==origin['sha256'])
   else:
    dispatch=read(d);check('formal-new-dispatch-owner:'+relative,task['originRoot'] is None and task['state']=='complete' and task['ownerRoot']==b['root'] and task['ownerPid']==dispatch['pid'] and task['claimedAtUtc']<=dispatch['atUtc']<=task['completedAtUtc'])
  origins.append((origin['originRoot'],origin['originPath']))
  calls_ledger.append({'batch':b['run'],'canonicalDispatch':relative,'originRoot':origin['originRoot'],'originDispatch':origin['originPath'],'generationId':receipt.get('generationId'),'actualCostUsd':receipt['actualCostUsd'],'unknownCost':str(bool(receipt['unknownCost'])).lower(),'unknownReserveUsd':receipt['upperBoundUsd'] if receipt['unknownCost'] else 0,'httpStatus':receipt['httpStatus'],'fault':receipt.get('fault')})
  if receipt.get('generationId'):generation_ids.append(receipt['generationId'])
 known=sum(r['actualCostUsd'] or 0 for r in receipts);unknown=sum(bool(r['unknownCost']) for r in receipts);reserve=sum(r['upperBoundUsd'] for r in receipts if r['unknownCost'])
 check('fees-conserved:'+b['run'],len(dispatches)==audit['modelCalls'] and math.isclose(known,audit['actualCostUsd'],abs_tol=1e-8) and unknown==audit['unknownCostCount'] and math.isclose(reserve,audit['unknownCostUpperBoundUsd'],abs_tol=1e-8))
 fees[b['run']]={'knownUsd':known,'unknownCount':unknown,'unknownReserveUsd':reserve,'dispatches':len(dispatches),'receipts':len(receipts),'inflight':0};total_dispatches+=len(dispatches)
 statistics[b['run']]={}
 for arm in ARMS:
  selected=[r for r,p in records if r['arm']==arm];denominator=416 if index==0 else sum(x['arm']==arm for x in plan['attempts']);valid=sum(bool(r['grade'].get('valid')) for r in selected);passed=sum(bool(r['grade'].get('valid') and r['grade'].get('passed')) for r in selected)
  statistics[b['run']][arm]={'denominator':denominator,'records':len(selected),'rawValid':valid,'passed':passed,'rawValidWrong':valid-passed,'rawInvalid':len(selected)-valid,'EXRateAll':passed/denominator if denominator else None,'EXRateValidOnly':passed/valid if valid else None}
 source_archives.append({'run':b['run'],'path':str(archive),'sha256':retrieval['sha256'],'bytes':retrieval['bytes'],'records':b['records'],'auditChecks':audit['checks'],'allPassed':True})
check('all1664-identities',len(merged)==1664)
check('unique-dispatch-origins',len(origins)==len(set(origins)))
check('unique-generation-costs',len(generation_ids)==len(set(generation_ids)))
raw_hashes={k:digest_file(path) for k,path in locations.items()};scored=[{**score_row(r,permitted),'classification':classify(r),'rawResultPath':str(locations[k]),'rawResultSha256':raw_hashes[k]} for k,r in sorted(merged.items())]
exceptions=[r for r in scored if not r['valid']];check('remaining-invalid-only-final-identities',{(r['arm'],r['id']) for r in exceptions}<=permitted)
final_stats={}
for arm in ARMS:
 rows=[r for r in scored if r['arm']==arm];passed=sum(r['score'] for r in rows);valid=sum(r['valid'] for r in rows);wrong=sum(r['countedAsWrong'] for r in rows)
 final_stats[arm]={'denominator':416,'passed':passed,'countedWrong':wrong,'rawValid':valid,'rawValidWrong':sum(r['valid'] and not r['score'] for r in rows),'rawInvalid':sum(not r['valid'] for r in rows),'policyFailures':sum(r['policyFailure'] for r in rows),'EXRateAll':passed/416,'EXRateValidOnly':passed/valid if valid else None}
 check('score-denominator:'+arm,passed+wrong==len(rows)==416)
combined={'knownUsd':sum(x['knownUsd'] for x in fees.values()),'unknownCount':sum(x['unknownCount'] for x in fees.values()),'unknownReserveUsd':sum(x['unknownReserveUsd'] for x in fees.values()),'dispatches':total_dispatches,'receipts':total_dispatches,'inflight':0}
for name,rows in [('CALLS_LEDGER.csv',calls_ledger),('UNKNOWN_COSTS.csv',[r for r in calls_ledger if r['unknownCost']=='true'])]:
 with (DEST/name).open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=['batch','canonicalDispatch','originRoot','originDispatch','generationId','actualCostUsd','unknownCost','unknownReserveUsd','httpStatus','fault']);w.writeheader();w.writerows(rows)
check('unknown-cost-ledger-complete',sum(r['unknownCost']=='true' for r in calls_ledger)==combined['unknownCount'])
save(DEST/'FEES.json',{'bySource':fees,'combined':combined,'eachOriginCountedOnce':True,'generationIdsUnique':True,'unknownIsNotZero':True,'legacyEpochArchivesNotAddedAgain':True})
save(DEST/'REMAINING_EXCEPTIONS.json',exceptions);save(DEST/'AUTHORIZATION.json',cap)
with (DEST/'FINAL_RESULTS.csv').open('w',newline='',encoding='utf-8-sig') as f:
 fields=['arm','id','valid','rawPassed','rawOutcome','classification','score','countedAsWrong','policyFailure','note','attemptId','attemptNo','rawError','rawResultPath','rawResultSha256'];writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
 for row in scored:writer.writerow({**row,'valid':str(row['valid']).lower(),'rawPassed':str(row['rawPassed']).lower(),'countedAsWrong':str(row['countedAsWrong']).lower(),'policyFailure':str(row['policyFailure']).lower()})
with (DEST/'BATCHES.csv').open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.DictWriter(f,fieldnames=['run','records','bytes','sha256','auditChecks','allPassed','path']);w.writeheader();w.writerows(source_archives)
fmt=lambda x:'—' if x is None else f'{x:.2%}'
passed=sum(r['score'] for r in scored);valid=sum(r['valid'] for r in scored);wrong=1664-passed
lines=['# SciBench Final Results','','Under the latest authorization, the last two records receive only one additional attempt, with no further retries after this round. Original exceptions, valid=false, errors, logs, and costs are preserved. Only final scoring counts still-invalid records as failures.','','|Method|Passed / 416|Scored incorrect|Originally valid|Still invalid, scored as failures|Overall EX rate|EX rate on valid samples|','|---|---:|---:|---:|---:|---:|---:|']
for arm,s in final_stats.items():lines.append(f"|{arm}|{s['passed']}/416|{s['countedWrong']}|{s['rawValid']}|{s['policyFailures']}|{fmt(s['EXRateAll'])}|{fmt(s['EXRateValidOnly'])}|")
lines+=['',f'Total: {passed}/1664 passed ({passed/1664:.2%}), {wrong} scored incorrect; {valid}/1664 originally valid grades, with {len(exceptions)} records still invalid.', '',f'Each still-invalid record carries the note: **{NOTE}**. Finalizing scores does not eliminate the original exceptions or change valid=false to true.']
for r in exceptions:lines.append(f"- {r['arm']}/{r['id']}: valid=false, {r['classification']}, score=0; {NOTE}.")
lines+=['','## Original and Per-Round Results','','Each round’s denominator is the planned count for that method; the original denominator is 416 per arm. Valid incorrect answers are not rerun. Only invalid records are replaced chronologically, without selecting the best result.','','|Batch|Method|Records / denominator|Valid|Passed|Invalid|Overall EX rate|EX rate on valid samples|','|---|---|---:|---:|---:|---:|---:|---:|']
for run,groups in statistics.items():
 for arm,s in groups.items():
  if s['denominator']:lines.append(f"|{run}|{arm}|{s['records']}/{s['denominator']}|{s['rawValid']}|{s['passed']}|{s['rawInvalid']}|{fmt(s['EXRateAll'])}|{fmt(s['EXRateValidOnly'])}|")
lines+=['','## Costs','','Historical and new costs are counted once per independent source, without adding cumulative archives from old epochs. Unknown costs are retained; reserves are neither settled costs nor zero.','','|Source|Known USD|Unknown-cost requests|Reserve for unknown costs (USD)|Requests / receipts|','|---|---:|---:|---:|---:|']
for run,s in {**fees,'Total':combined}.items():lines.append(f"|{run}|{s['knownUsd']:.9f}|{s['unknownCount']}|{s['unknownReserveUsd']:.9f}|{s['dispatches']}/{s['receipts']}|")
lines+=['','## Archives and Audit','','All batches are complete, their processes have exited, no requests are in flight, and every dispatch has a receipt. Each independent archive’s SHA256 and all archive members have been verified against the local mirror; original raw results remain unchanged. The final bundle contains six complete original archives and derived reports. Detailed hashes are in MANIFEST.json and FINAL_RETRIEVAL.json.','', 'This report applies the user’s latest bounded-finalization policy, superseding the previous continuous until0 retries. Stop the existing scibench-416 follow-up after verifying the final archive.']
(DEST/'FINAL_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
check('raw-effective-records-unchanged',all(digest_file(locations[k])==digest for k,digest in raw_hashes.items()))
audit={'allPassed':True,'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'checks':checks,'sourceArchives':source_archives,'archiveMembersVerified':archive_members,'statistics':statistics,'finalStatistics':final_stats,'scoredRecords':1664,'passed':passed,'countedWrong':wrong,'rawValid':valid,'rawInvalid':len(exceptions),'policyFailures':len(exceptions),'policyNote':NOTE,'rawRecordsUnmodified':True,'noMoreRetries':True,'additionalRoundsCreated':1,'feesBySource':fees,'combinedFees':combined,'generationIdsUnique':True,'allDispatchesReceipted':True,'allArchived':True,'followupReadyToPause':True}
save(DEST/'FINAL_AUDIT.json',audit)
for b in batches:
 folder=DOCS/b['run'].removeprefix('scibench-');supplement=DEST/'supplements'/b['run'];supplement.mkdir(parents=True,exist_ok=True)
 for name in ['AUDIT.json','retrieval.json','ATTEMPT_AUDIT.json','FINAL_READINESS.json','BILLING_LOOKUP.json','billing-reconciliation.post-archive.json','FAULT_REVIEW.json']:
  source=folder/name
  if source.exists():
   target=supplement/name
   if target.exists():assert digest_file(target)==digest_file(source),'ExistingSupplementMismatch'
   else:target.write_bytes(source.read_bytes())
manifest={'schema':1,'sourceArchives':source_archives,'files':[{'path':p.relative_to(DEST).as_posix(),'sha256':digest_file(p),'bytes':p.stat().st_size} for p in sorted(DEST.rglob('*')) if p.is_file() and p.name not in ['MANIFEST.json','FINAL_RETRIEVAL.json']],'rawExceptionPolicy':NOTE,'noMoreRetries':True};save(DEST/'MANIFEST.json',manifest)
temporary=bundle.with_suffix('.incomplete');assert not temporary.exists(),'IncompleteBundleRequiresInspection'
with tarfile.open(temporary,'w') as t:
 for source in source_archives:t.add(source['path'],arcname='batches/'+Path(source['path']).name)
 for row in manifest['files']:t.add(DEST/row['path'],arcname='reports/'+row['path'])
 t.add(DEST/'MANIFEST.json',arcname='reports/MANIFEST.json')
temporary.rename(bundle);metadata={'archive':str(bundle),'sha256':digest_file(bundle),'bytes':bundle.stat().st_size,'sourceArchiveCount':len(source_archives),'allSourcesSha256Verified':True,'allSourceArchiveMembersVerified':True,'finalAuditAllPassed':True,'scoredRecords':1664,'passed':passed,'rawInvalid':len(exceptions),'policyFailures':len(exceptions)}
with tarfile.open(bundle) as t:
 for source in source_archives:
  f=t.extractfile('batches/'+Path(source['path']).name);h=hashlib.sha256()
  while raw:=f.read(1024*1024):h.update(raw)
  assert h.hexdigest()==source['sha256'],'FinalNestedArchiveMismatch'
 for row in manifest['files']:assert sha(t.extractfile('reports/'+row['path']).read())==row['sha256']
metadata['bundleContentsVerified']=True;save(DEST/'FINAL_RETRIEVAL.json',metadata)
cap.update({'phase':'complete','completedAdditionalRounds':1,'finalRawInvalid':len(exceptions),'finalReport':str(DEST/'FINAL_REPORT.md'),'noFurtherRetries':True});save(DOCS/'FINAL_ATTEMPT_POLICY.json',cap)
policy=read(DOCS/'UNTIL_ZERO_POLICY.json');policy.update({'authorizedUntilZero':False,'phase':'closed_by_final_scoring_policy','currentRun':None,'remainingRawInvalid':len(exceptions),'statisticalRecords':1664,'finalScoringPolicy':str(DEST/'FINAL_AUDIT.json')});save(DOCS/'UNTIL_ZERO_POLICY.json',policy)
save(DOCS/'SCIBENCH_WORKFLOW_STATE.json',{'phase':'completed_with_policy_failures' if exceptions else 'completed','activeRun':None,'scoredRecords':1664,'passed':passed,'countedWrong':wrong,'rawValid':valid,'rawInvalid':len(exceptions),'policyFailures':len(exceptions),'policyNote':NOTE,'combinedFees':combined,'finalReport':str(DEST/'FINAL_REPORT.md'),'finalArchive':metadata,'automationId':'scibench-416','automationStatus':'ready_to_pause'})
central=read(DOCS/'UNTIL_ZERO_AUDIT.json');central.update({'supersededByFinalScoringPolicy':True,'finalScoringAudit':str(DEST/'FINAL_AUDIT.json'),'rawInvalidPreserved':len(exceptions),'noMoreRetries':True});save(DOCS/'UNTIL_ZERO_AUDIT.json',central)
with (DOCS/'UNTIL_ZERO_REPORT.md').open('a',encoding='utf-8') as f:f.write('\n\nThe latest bounded-finalization policy is complete: retain still-invalid records, score them as failures, and perform no further retries. Final statistics and costs are in final-20261016/FINAL_REPORT.md.\n')
print(json.dumps({'allPassed':True,'final':metadata,'passed':passed,'countedWrong':wrong,'rawValid':valid,'policyFailures':len(exceptions),'fees':combined},ensure_ascii=True))
