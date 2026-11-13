"""Prepare, inspect and report the explicitly authorized second repair round."""
from pathlib import Path
import argparse,collections,csv,json,subprocess
from infra_retry_policy import ARMS,classify,sha
from infra_retry2_policy import REPAIR2,PREVIOUS,AUTHORIZED_IDS
REPO=Path(__file__).resolve().parents[4];DOCS=REPO/'docs/scibench';LOCAL=DOCS/REPAIR2.removeprefix('scibench-');SSH='C:/Users/y1252/Documents/Codex/2026-10-15/s-c/work/scicode/ssh-config'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def ssh(code,timeout=60):
 p=subprocess.run(['ssh','-F',SSH,'novaeve','python3.11','-'],input=code,capture_output=True,text=True,timeout=timeout);assert p.returncode==0,p.stderr[-3500:]+p.stdout[-1500:];return p.stdout
ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','inspect','report']);ap.add_argument('--partial',action='store_true');ap.add_argument('--final',action='store_true');a=ap.parse_args()
if a.action=='prepare':
 original=DOCS/read(DOCS/'CURRENT_FORMAL_RUN.json')['run'].removeprefix('scibench-');previous=DOCS/PREVIOUS.removeprefix('scibench-')
 proof={'originalFinalAuditPassed':True,'previousFinalAuditPassed':True,'localArchivesVerified':True,'authorization':'Latest user explicitly includes all six remaining first-round invalid records, including the two native budget/no-submit outcomes; one new complete attempt each. No dollar cap. Keep c5/600s/4branches/12units, bounded3 transport and fault protection. Original seven native records still outside this round.','noAutomaticThirdRound':True}
 for label,folder,count in [('original',original,1664),('previous',previous,47)]:
  audit=read(folder/'AUDIT.json');retrieval=read(folder/'retrieval.json');archive=Path(retrieval['localArchive'])
  assert retrieval['sha256Verified'] and sha(archive.read_bytes())==retrieval['sha256'] and archive.stat().st_size==retrieval['bytes']
  assert audit['allPassed'] and not audit['partial'] and sum(x['completed'] for x in audit['arms'].values())==count and not audit['activeUnreceiptedDispatches']
  proof[label+'ArchiveSha256']=retrieval['sha256'];proof[label+'AuditSha256']=sha((folder/'AUDIT.json').read_bytes());proof['sourceRoot' if label=='original' else 'previousRoot']=read(folder/'full-results/outputs/canonical/launch.json')['root']
 assert read(previous/'ATTEMPT_AUDIT.json')['final'] and read(previous/'COMBINED_AUDIT.json')['allPassed'] and not read(previous/'COMBINED_AUDIT.json')['partial']
 tooling=read(DOCS/'INFRA_RETRY2_TOOLING.json');assert tooling['ready']
 code="from pathlib import Path\nimport hashlib,json,subprocess,sys\np=Path("+repr(tooling['remoteDirectory'])+");assert hashlib.sha256((p/'TOOL_PINS.json').read_bytes()).hexdigest()=="+repr(tooling['toolPinsSha256'])+"\nv=json.loads((p/'TOOL_PINS.json').read_text());assert all(hashlib.sha256((p/x['path']).read_bytes()).hexdigest()==x['sha256'] for x in v['files'])\nr=subprocess.run(['python3.11',str(p/'infra_retry2_build.py')],input="+repr(json.dumps(proof))+",capture_output=True,text=True);sys.stdout.write(r.stdout);sys.stderr.write(r.stderr);sys.exit(r.returncode)\n"
 v=json.loads(ssh(code,120));save(LOCAL/'preparation.json',v);save(LOCAL/'AUTHORIZATION.json',proof);print(json.dumps(v));raise SystemExit(0)
if a.action=='inspect':
 code=r'''
from pathlib import Path
import fcntl,hashlib,json,sqlite3,time
r=Path('/var/tmp/tgengin-scibench-20261016/scibench-infra-retry2-20261016-v1-c32');o=r/'outputs/canonical';read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=read(r/'package/repair-plan.json');s=read(o/'status.json');launch=read(o/'launch.json')
def live(pid,entry):
 p=Path('/proc',str(pid),'cmdline');return p.exists() and str(entry).encode() in p.read_bytes()
running=live(s['pid'],r/'package/run.ts');supervising=live(launch['supervisorPid'],r/'package/infra_retry2_launcher.py');grader=read(o/'grader-process.json') if (o/'grader-process.json').exists() else None
assert launch['root']==str(r) and launch['pid']==s['pid']
assert all(sha(Path(p))==h for p,h in plan['priorRegistryHashes'].items()),'PriorRegistryChanged'
for root,h in [(Path(plan['sourceRoot']),plan['sourceArchiveSha256']),(Path(plan['previousRoot']),plan['previousArchiveSha256'])]:
 assert sha(root/(root.name+'-results.tar.gz'))==h,'PriorArchiveChanged'
 prior=read(root/'outputs/canonical/launch.json');assert not live(prior['pid'],root/'package/run.ts')
assert all(sha(Path(x['path']))==x['sha256'] for x in read(o/'source-pins.json')['files'])
assert all(sha(r/x['path'])==x['sha256'] for x in read(r/'provenance/solver-source-pins.json')['files'])
db=sqlite3.connect('file:'+plan['registryPath']+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;rows=[dict(x) for x in db.execute('SELECT * FROM attempts')]
assert len(rows)==len(plan['attempts'])==6 and len({x['attemptId'] for x in rows})==6 and all(x['attemptNo']==2 for x in rows)
started=[x for x in rows if x['state']=='started'];assert len(started)<=32 and all(x['ownerPid']==s['pid'] for x in started)
for row in rows:
 a=next(x for x in plan['attempts'] if x['attemptId']==row['attemptId'])
 assert row['previousAttemptId']==a['previousAttemptId'] and row['previousResultSha256']==a['previousResultSha256'] and sha(Path(a['previousResultPath']))==a['previousResultSha256'] and sha(Path(a['originalResultPath']))==a['originalResultSha256']
 if row['state']=='complete':assert sha(o/'results'/row['arm']/(row['id']+'.json'))==row['resultSha256']
leases=[]
for path in [*plan['priorGlobalLocks'],plan['globalLockPath']]:
 f=open(path,'a+');leases.append(f)
 if running:
  try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);raise AssertionError('OwnerLeaseMissing')
  except BlockingIOError:pass
 else:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
native=[]
for p in (o/'tasks').glob('*/*/engine-process.json'):
 pid=read(p)['pid'];env=Path('/proc',str(pid),'environ')
 try:owned=env.exists() and b'TGENGIN_CONFIG='+str(p.parent/'engine/config.yaml').encode() in env.read_bytes().split(b'\0')
 except FileNotFoundError:owned=False
 if owned:native.append({'pid':pid,'id':p.parent.name})
unreceipted=[str(p.relative_to(r)) for p in (o/'calls').rglob('dispatch.json') if not p.with_name('receipt.json').exists()]
same=len(s['active'])==len(started) and {(x['arm'],x['id']) for x in s['active']}=={(x['arm'],x['id']) for x in started}
proof=r/'ops/REAL_CONCURRENCY.json'
if same and len(started)==6 and not proof.exists():
 proof.parent.mkdir(exist_ok=True);proof.write_text(json.dumps({'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'pid':s['pid'],'sameIdentitySet':True,'observed':6,'sharedSlotLimit':32,'planned':6,'active':s['active']},indent=2)+'\n')
if FINAL:
 assert not running and not supervising and not s['active'] and not started and not native and not unreceipted and all(x['state']=='complete' for x in rows),'SecondRoundNotFinished'
 assert not (o/'runner-lock.json').exists() and (o/'supervisor-exit.json').exists()
 if grader:assert not live(grader['pid'],r/'package/stand.py')
 dest=r/'provenance/attempts-final.sqlite'
 if dest.exists():
  b=sqlite3.connect('file:'+str(dest)+'?mode=ro',uri=True);assert [tuple(x) for x in b.execute('SELECT * FROM attempts ORDER BY attemptId')]==[tuple(x) for x in db.execute('SELECT * FROM attempts ORDER BY attemptId')];b.close()
 else:b=sqlite3.connect(dest);db.backup(b);b.close()
v={'allPassed':True,'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'final':FINAL,'pid':s['pid'],'supervisorPid':launch['supervisorPid'],'controllerLive':running,'supervisorLive':supervising,'graderLive':live(grader['pid'],r/'package/stand.py') if grader else False,'priorRegistriesUnchanged':True,'priorArchivesUnchanged':True,'sourcePinsUnchanged':True,'states':{k:sum(x['state']==k for x in rows) for k in sorted({x['state'] for x in rows})},'active':s['active'],'native':native,'unreceiptedDispatches':unreceipted,'status':s}
if FINAL:v['registryBackupSha256']=sha(dest)
(r/'ops').mkdir(exist_ok=True);(r/'ops/ATTEMPT_AUDIT.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
'''.replace('FINAL',repr(a.final))
 v=json.loads(ssh(code));save(LOCAL/'ATTEMPT_AUDIT.json',v);print(json.dumps({k:v[k] for k in ['allPassed','atUtc','final','pid','controllerLive','supervisorLive','states','priorRegistriesUnchanged','priorArchivesUnchanged','unreceiptedDispatches']}));raise SystemExit(0)

root=LOCAL/'full-results';plan=read(root/'package/repair-plan.json');original=DOCS/Path(plan['sourceRoot']).name.removeprefix('scibench-');previous=DOCS/PREVIOUS.removeprefix('scibench-')
folders={'original':original,'repair1':previous,'repair2':LOCAL};audits={k:read(v/('PROGRESS_AUDIT.json' if k=='repair2' and a.partial else 'AUDIT.json')) for k,v in folders.items()}
assert all(x['allPassed'] for x in audits.values())
records={k:{(r['arm'],r['id']):r for p in (v/'full-results/outputs/canonical/results').glob('*/*.json') for r in [read(p)]} for k,v in folders.items()}
orig,first,second=(records[k] for k in ['original','repair1','repair2']);attempts={(r['arm'],r['id']):r for r in plan['attempts']};assert len(orig)==1664 and len(first)==47 and len(attempts)==6 and set(second)<=set(attempts)
if not a.partial:assert set(second)==set(attempts),'IncompleteSecondRound'
for k,row in attempts.items():
 assert not first[k]['grade'].get('valid') and sha((previous/'full-results/outputs/canonical/results'/k[0]/(k[1]+'.json')).read_bytes())==row['previousResultSha256']
 assert sha((original/'full-results/outputs/canonical/results'/k[0]/(k[1]+'.json')).read_bytes())==row['originalResultSha256']
 if k in second:assert second[k]['attemptNo']==2 and second[k]['attemptId']==row['attemptId'] and second[k]['previousAttemptId']==row['previousAttemptId'] and second[k]['previousResultSha256']==row['previousResultSha256'] and second[k]['originalResultSha256']==row['originalResultSha256']
after1={**orig,**first};merged={**after1,**second}
assert all(merged[k]==r for k,r in orig.items() if r['grade'].get('valid')) and all(merged[k]==r for k,r in first.items() if r['grade'].get('valid'))
assert all(merged[k]==r for k,r in orig.items() if classify(r).startswith('native_'))
def stats(rows,phase):
 values={}
 for arm in ARMS:
  subset=[r for k,r in rows.items() if k[0]==arm];denom=416 if phase in ['original','mergedAfter1','merged'] else sum(x['arm']==arm for x in (read(previous/'full-results/package/repair-plan.json')['attempts'] if phase=='repair1' else plan['attempts']))
  valid=sum(bool(r['grade'].get('valid')) for r in subset);passed=sum(bool(r['grade'].get('valid') and r['grade'].get('passed')) for r in subset)
  values[arm]={'denominator':denom,'completed':len(subset),'valid':valid,'passed':passed,'EXRateAll':passed/denom if denom else None,'EXRateValidOnly':passed/valid if valid else None}
 return values
sets={**records,'mergedAfter1':after1,'merged':merged};statistics={phase:stats(rows,phase) for phase,rows in sets.items()}
generations=[];origins=[]
for phase,folder in folders.items():
 for p in (folder/'full-results/outputs/canonical/calls').rglob('receipt.json'):
  r=read(p);origins.append((phase,p.relative_to(folder/'full-results').as_posix()))
  if r.get('generationId'):generations.append(r['generationId'])
assert len(origins)==len(set(origins)) and len(generations)==len(set(generations)),'DuplicateOriginOrGenerationCost'
keys=['actualCostUsd','unknownCostCount','unknownCostUpperBoundUsd','modelCalls'];fees={phase:{k:audit[k] for k in keys} for phase,audit in audits.items()};fees['combined']={k:sum(fees[phase][k] for phase in audits) for k in keys}
remaining=[{'arm':k[0],'id':k[1],'originalClassification':classify(orig[k]),'firstClassification':classify(first[k]) if k in first else None,'secondClassification':classify(second[k]) if k in second else None,'secondAttemptId':attempts[k]['attemptId'] if k in attempts else None,'effectiveClassification':classify(r),'secondFinished':k in second} for k,r in sorted(merged.items()) if not r['grade'].get('valid')]
v={'allPassed':True,'partial':a.partial,'mergeRule':plan['mergeRule'],'statistics':statistics,'fees':fees,'feesOriginsCountedOnce':True,'generationIdsUnique':True,'unknownIsNotZero':True,'plannedSecondAttempts':6,'completedSecondAttempts':len(second),'validOriginalOrFirstChanged':0,'classificationCounts':{phase:dict(collections.Counter(classify(r) for r in rows.values())) for phase,rows in sets.items()},'remainingExceptions':remaining}
save(LOCAL/'COMBINED_AUDIT.json',v);save(LOCAL/'REMAINING_EXCEPTIONS.json',remaining)
with (LOCAL/'MERGED_RESULTS.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=['arm','id','originalClassification','firstClassification','secondClassification','effectiveClassification','effectivePassed','secondAttemptId']);w.writeheader()
 for k,r in sorted(merged.items()):w.writerow({'arm':k[0],'id':k[1],'originalClassification':classify(orig[k]),'firstClassification':classify(first[k]) if k in first else '', 'secondClassification':classify(second[k]) if k in second else '', 'effectiveClassification':classify(r),'effectivePassed':r['grade'].get('passed') if r['grade'].get('valid') else '', 'secondAttemptId':attempts.get(k,{}).get('attemptId','')})
fmt=lambda x:'—' if x is None else f'{x:.2%}'
lines=['# SciBench Original, Two Retry Rounds, and Merged Results','',plan['mergeRule'],'','Under the user’s additional authorization, round two includes all 6 invalid records from round one (4 API/infrastructure failures and 2 native budget/no-submission cases); the original 7 native invalid records remain preserved. Each receives only one new complete attempt, without a dollar cap, while method budgets and the API chain remain unchanged.','','|Stage|Method|Completed / denominator|Valid|Passed|Overall EX rate|EX rate on valid samples|','|---|---|---:|---:|---:|---:|---:|']
for phase,arms in statistics.items():
 for arm,s in arms.items():lines.append(f"|{phase}|{arm}|{s['completed']}/{s['denominator']}|{s['valid']}|{s['passed']}|{fmt(s['EXRateAll'])}|{fmt(s['EXRateValidOnly'])}|")
lines+=['',f"Round two completed {len(second)}/6 records; {len(remaining)} remain invalid after merging. See REMAINING_EXCEPTIONS.json.",'','Costs are summed only across independent source ledgers; cumulative historical archives are not added again.']
for phase,s in fees.items():lines.append(f"- {phase}: known ${s['actualCostUsd']:.9f}, {s['unknownCostCount']} unknown-cost/in-flight requests, reserve ${s['unknownCostUpperBoundUsd']:.9f}, {s['modelCalls']} requests.")
(LOCAL/'COMBINED_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:x for k,x in v.items() if k not in ['remainingExceptions','statistics']},ensure_ascii=False))
