"""Local final-verification gate and separate original/repair/merged reporting."""
from pathlib import Path
import argparse,csv,json,subprocess,sys
from infra_retry_policy import ARMS,REPAIR,classify,sha

REPO=Path(__file__).resolve().parents[4];DOCS=REPO/'docs/scibench'
SSH='C:/Users/y1252/Documents/Codex/2026-10-15/s-c/work/scicode/ssh-config'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','inspect','report']);ap.add_argument('--source-run');ap.add_argument('--partial',action='store_true');ap.add_argument('--final',action='store_true');ap.add_argument('--fixture-docs',type=Path);a=ap.parse_args()
if a.fixture_docs:
 assert a.action=='report' and a.fixture_docs.resolve().is_relative_to(REPO.parent/'tmp/scibench-infra-retry-fixtures')
 DOCS=a.fixture_docs.resolve()
local=DOCS/REPAIR.removeprefix('scibench-')
if a.action=='inspect':
 code=r'''
from pathlib import Path
import fcntl,hashlib,json,sqlite3,time
r=Path('/var/tmp/tgengin-scibench-20261016/scibench-infra-retry-20261016-v1-c32');o=r/'outputs/canonical';read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=read(r/'package/repair-plan.json');s=read(o/'status.json');launch=read(o/'launch.json');source=Path(plan['sourceRoot'])
def live(pid,entry):
 p=Path('/proc',str(pid),'cmdline');return p.exists() and str(entry).encode() in p.read_bytes()
running=live(s['pid'],r/'package/run.ts');grader=read(o/'grader-process.json') if (o/'grader-process.json').exists() else None
assert launch['root']==str(r) and launch['pid']==s['pid']
assert not live(plan['sourcePid'],source/'package/run.ts'),'OriginalControllerReappeared'
assert sha(Path(plan['originalRegistryPath']))==plan['originalRegistrySha256AtBuild'],'OriginalRegistryChanged'
assert all(sha(Path(x['path']))==x['sha256'] for x in read(o/'source-pins.json')['files'])
assert all(sha(source/x['path'])==x['sha256'] for x in read(r/'provenance/solver-source-pins.json')['files'])
db=sqlite3.connect('file:'+plan['registryPath']+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;rows=[dict(x) for x in db.execute('SELECT * FROM attempts')]
assert len(rows)==len(plan['attempts'])==len({x['attemptId'] for x in rows}) and all(x['attemptNo']==1 for x in rows)
started=[x for x in rows if x['state']=='started'];assert len(started)<=32 and all(x['ownerPid']==s['pid'] for x in started)
for row in rows:
 if row['state']=='complete':assert sha(o/'results'/row['arm']/(row['id']+'.json'))==row['resultSha256']
native=[]
for task in s['active']:
 if task['arm']!='objrun':continue
 d=o/'tasks'/task['arm']/task['id'];p=d/'engine-process.json'
 if not p.exists():continue
 pid=read(p)['pid'];env=Path('/proc',str(pid),'environ')
 try:owned=env.exists() and b'TGENGIN_CONFIG='+str(d/'engine/config.yaml').encode() in env.read_bytes().split(b'\0')
 except FileNotFoundError:owned=False
 completed=(o/'results'/task['arm']/(task['id']+'.json')).exists()
 assert owned or completed or not live(pid,r/'package/engine/app/src/main.ts'),'NativeOwnershipMismatch'
 native.append({'pid':pid,'identity':task,'owned':owned,'completedSinceSnapshot':completed})
unreceipted=[str(p.relative_to(r)) for p in (o/'calls').rglob('dispatch.json') if not p.with_name('receipt.json').exists()]
lock=open(plan['globalLockPath'],'a+')
if running:
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);raise AssertionError('OwnerLockMissing')
 except BlockingIOError:pass
else:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
proof32=len(s['active'])==len(started)==32 and {(x['arm'],x['id']) for x in s['active']}=={(x['arm'],x['id']) for x in started}
if proof32 and not (r/'ops/REAL_CONCURRENCY32.json').exists():
 (r/'ops').mkdir(exist_ok=True);(r/'ops/REAL_CONCURRENCY32.json').write_text(json.dumps({'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'pid':s['pid'],'sameIdentitySet':True,'active':s['active'],'count':32},indent=2)+'\n')
if FINAL:
 assert not running and not s['active'] and not started and not unreceipted and all(x['state']=='complete' for x in rows),'RepairNotFinished'
 if grader:assert not live(grader['pid'],r/'package/stand.py')
 for p in (o/'tasks').glob('*/*/engine-process.json'):
  env=Path('/proc',str(read(p)['pid']),'environ')
  if env.exists():assert b'TGENGIN_CONFIG='+str(p.parent/'engine/config.yaml').encode() not in env.read_bytes().split(b'\0')
 dest=r/'provenance/attempts-final.sqlite'
 if dest.exists():
  b=sqlite3.connect('file:'+str(dest)+'?mode=ro',uri=True);assert [tuple(x) for x in b.execute('SELECT * FROM attempts ORDER BY attemptId')]==[tuple(x) for x in db.execute('SELECT * FROM attempts ORDER BY attemptId')];b.close()
 else:b=sqlite3.connect(dest);db.backup(b);b.close()
lock.close();db.close()
v={'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'allPassed':True,'final':FINAL,'root':str(r),'pid':s['pid'],'controllerLive':running,'graderLive':live(grader['pid'],r/'package/stand.py') if grader else False,'sourcePinsUnchanged':True,'originalRegistryUnchanged':True,'plannedAttempts':len(rows),'states':{k:sum(x['state']==k for x in rows) for k in sorted({x['state'] for x in rows})},'unreceiptedDispatches':unreceipted,'native':native,'status':s}
(r/'ops').mkdir(exist_ok=True);(r/'ops/ATTEMPT_AUDIT.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
'''.replace('FINAL',repr(a.final))
 p=subprocess.run(['ssh','-F',SSH,'novaeve','python3.11','-'],input=code,capture_output=True,text=True,timeout=60);assert p.returncode==0,p.stderr[-3000:]
 local.mkdir(parents=True,exist_ok=True);(local/'ATTEMPT_AUDIT.json').write_text(p.stdout,encoding='utf-8');v=json.loads(p.stdout);print(json.dumps({k:v[k] for k in ['atUtc','allPassed','final','pid','controllerLive','originalRegistryUnchanged','plannedAttempts','states','unreceiptedDispatches']}));raise SystemExit(0)
if a.action=='prepare':
 assert a.source_run and a.source_run.startswith('scibench-formal-20261016-v')
 original=DOCS/a.source_run.removeprefix('scibench-');retrieval=read(original/'retrieval.json');audit=read(original/'AUDIT.json')
 archive=Path(retrieval['localArchive']);assert retrieval['sha256Verified'] and sha(archive.read_bytes())==retrieval['sha256']
 assert audit['allPassed'] and not audit['partial'] and sum(s['completed'] for s in audit['arms'].values())==1664 and not audit['activeUnreceiptedDispatches']
 tooling=read(DOCS/'INFRA_RETRY_TOOLING.json');assert tooling['ready']
 proof={'sourceRoot':read(original/'full-results/outputs/canonical/launch.json')['root'],'sourceArchiveSha256':retrieval['sha256'],'originalAuditSha256':sha((original/'AUDIT.json').read_bytes()),'originalAuditAllPassed':True,'originalRecords':1664,'localArchiveSha256Verified':True,'sourceRun':a.source_run}
 remote_code="from pathlib import Path\nimport hashlib,json,subprocess,sys\np=Path("+repr(tooling['remoteDirectory'])+");assert hashlib.sha256((p/'TOOL_PINS.json').read_bytes()).hexdigest()=="+repr(tooling['toolPinsSha256'])+"\nv=json.loads((p/'TOOL_PINS.json').read_text());assert all(hashlib.sha256((p/x['path']).read_bytes()).hexdigest()==x['sha256'] for x in v['files'])\nr=subprocess.run(['python3.11',str(p/'infra_retry_build.py')],input="+repr(json.dumps(proof))+",capture_output=True,text=True);sys.stdout.write(r.stdout);sys.stderr.write(r.stderr);sys.exit(r.returncode)\n"
 cmd=['ssh','-F',SSH,'novaeve','python3.11','-']
 p=subprocess.run(cmd,input=remote_code,capture_output=True,text=True,timeout=120);assert p.returncode==0,p.stderr[-3000:]
 local.mkdir(parents=True,exist_ok=True);(local/'preparation.json').write_text(p.stdout,encoding='utf-8');print(p.stdout)
 raise SystemExit(0)

root=local/'full-results';plan=read(root/'package/repair-plan.json');original=DOCS/Path(plan['sourceRoot']).name.removeprefix('scibench-');originroot=original/'full-results'
oa=read(original/'AUDIT.json');ra=read(local/('PROGRESS_AUDIT.json' if a.partial else 'AUDIT.json'));assert oa['allPassed'] and ra['allPassed']
originals={(r['arm'],r['id']):r for p in (originroot/'outputs/canonical/results').rglob('*.json') for r in [read(p)]}
repaired={(r['arm'],r['id']):r for p in (root/'outputs/canonical/results').rglob('*.json') for r in [read(p)]}
attempts={(r['arm'],r['id']):r for r in plan['attempts']}
assert len(originals)==1664 and set(repaired)<=set(attempts)
if not a.partial:assert set(repaired)==set(attempts),'NotEveryPlannedAttemptHasATerminalRecord'
for identity,row in attempts.items():
 p=originroot/'outputs/canonical/results'/identity[0]/(identity[1]+'.json')
 assert sha(p.read_bytes())==row['originalResultSha256'] and classify(originals[identity]).startswith('infra_')
 if identity in repaired:assert repaired[identity]['attemptId']==row['attemptId'] and repaired[identity]['originalResultSha256']==row['originalResultSha256']
merged={k:repaired.get(k,r) if k in attempts else r for k,r in originals.items()}
def stats(rows,full):
 return {arm:{'denominator':416 if full else sum(k[0]==arm for k in attempts),'records':sum(k[0]==arm for k in rows),'valid':sum(k[0]==arm and bool(r['grade'].get('valid')) for k,r in rows.items()),'passed':sum(k[0]==arm and bool(r['grade'].get('valid') and r['grade']['passed']) for k,r in rows.items())} for arm in ARMS}
statistics={'original':stats(originals,True),'repair':stats(repaired,False),'merged':stats(merged,True)}
classification_counts={phase:{kind:sum(classify(r)==kind for r in rows.values()) for kind in sorted({classify(r) for r in rows.values()})} for phase,rows in [('original',originals),('repair',repaired),('merged',merged)]}
for arms in statistics.values():
 for s in arms.values():s.update({'EXRateAll':s['passed']/s['denominator'] if s['denominator'] else None,'EXRateValidOnly':s['passed']/s['valid'] if s['valid'] else None})
ids=[]
for batch in [originroot,root]:
 for p in (batch/'outputs/canonical/calls').rglob('receipt.json'):
  generation=read(p).get('generationId')
  if generation:ids.append(generation)
assert len(ids)==len(set(ids)),'DuplicateOriginOrGenerationCost'
remaining=[{'arm':k[0],'id':k[1],'originalClassification':classify(originals[k]),'attemptId':attempts.get(k,{}).get('attemptId'),'repairClassification':classify(repaired[k]) if k in repaired else None,'effectiveClassification':classify(r),'repairAttemptFinished':k in repaired} for k,r in sorted(merged.items()) if not r['grade'].get('valid')]
fees={'original':{k:oa[k] for k in ['actualCostUsd','unknownCostCount','unknownCostUpperBoundUsd','modelCalls']},'repair':{k:ra[k] for k in ['actualCostUsd','unknownCostCount','unknownCostUpperBoundUsd','modelCalls']},'combined':{k:oa[k]+ra[k] for k in ['actualCostUsd','unknownCostCount','unknownCostUpperBoundUsd','modelCalls']},'historicalOriginCountedOnce':True,'unknownIsNotZero':True}
report={'allPassed':True,'partial':a.partial,'mergeRule':plan['mergeRule'],'statistics':statistics,'fees':fees,'plannedRepairs':len(attempts),'completedRepairs':len(repaired),'remainingExceptions':remaining,'validOriginalChanged':sum(k not in attempts and merged[k]!=r for k,r in originals.items())}
report['classificationCounts']=classification_counts
assert report['validOriginalChanged']==0
(local/'COMBINED_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(local/'REMAINING_EXCEPTIONS.json').write_text(json.dumps(remaining,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with (local/'MERGED_RESULTS.csv').open('w',newline='',encoding='utf-8-sig') as f:
 fields=['arm','id','originalClassification','originalPassed','attemptId','repairClassification','repairPassed','effectiveClassification','effectivePassed'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for k,r in sorted(merged.items()):w.writerow({'arm':k[0],'id':k[1],'originalClassification':classify(originals[k]),'originalPassed':originals[k]['grade'].get('passed') if originals[k]['grade'].get('valid') else '', 'attemptId':attempts.get(k,{}).get('attemptId',''),'repairClassification':classify(repaired[k]) if k in repaired else '', 'repairPassed':repaired[k]['grade'].get('passed') if k in repaired and repaired[k]['grade'].get('valid') else '', 'effectiveClassification':classify(r),'effectivePassed':r['grade'].get('passed') if r['grade'].get('valid') else ''})
lines=['# SciBench Original, Single Infrastructure Retry, and Merged Results','',plan['mergeRule'],'','Overall EX-rate denominators: 416 per arm for original/merged results, and the planned exception count for each retry arm. EX rates on valid graded samples are also shown; errors are not disguised as incorrect answers.','','| Result | Arm | Records / denominator | Valid | Passed | Overall EX rate | EX rate on valid samples |','|---|---|---:|---:|---:|---:|---:|']
fmt=lambda x:'—' if x is None else f'{x:.2%}'
for phase,arms in statistics.items():
 for arm,s in arms.items():lines.append(f"| {phase} | {arm} | {s['records']}/{s['denominator']} | {s['valid']} | {s['passed']} | {fmt(s['EXRateAll'])} | {fmt(s['EXRateValidOnly'])} |")
lines+=['',f"Single retry completed for {len(repaired)}/{len(attempts)} records; {len(remaining)} exceptions remain after merging. See REMAINING_EXCEPTIONS.json for individual records.",'',f"Original known cost: ${oa['actualCostUsd']:.9f}; new retry cost: ${ra['actualCostUsd']:.9f}; total: ${fees['combined']['actualCostUsd']:.9f}.",f"Original unknown-cost requests: {oa['unknownCostCount']}; retry unknown-cost/in-flight requests: {ra['unknownCostCount']}; total reserve: ${fees['combined']['unknownCostUpperBoundUsd']:.9f}. Unknown costs are not zero; cumulative historical archive costs are not added again."]
for phase,counts in classification_counts.items():lines.extend(['',phase+' classification: '+json.dumps(counts,ensure_ascii=False)])
(local/'COMBINED_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='remainingExceptions'},ensure_ascii=False))
