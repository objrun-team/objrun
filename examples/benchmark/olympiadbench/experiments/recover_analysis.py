"""One-time offline report recovery; leaves the frozen scientific package intact."""
from pathlib import Path
from ops import LOCAL, REMOTE, remote


def main():
    code = r'''
from pathlib import Path
import datetime as dt
import hashlib,json,os,subprocess
r=Path(REMOTE_ROOT);out=r/'outputs/canonical';recovery=out/'analysis-recovery-v2'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def exclusive(p,value):
 with p.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
s=read(out/'status.json')
assert s['stage']=='finalizing' and not s['active'] and not s['api']['activeApiRequests']
assert not recovery.exists(),'ExistingRecoveryInspectBeforeRepeat'
for p in Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:cmd=(p/'cmdline').read_bytes()
 except OSError:continue
 assert not (str(r/'package/controller.py').encode() in cmd or str(r/'package/native.ts').encode() in cmd),'OwnedScienceProcessStillAlive'
assert len(list((out/'results').glob('*/*.json')))==472
for name in ['AUDIT.json','SUMMARY.json','REPORT.md','FINAL_RESULTS.csv','final-freeze.json']:
 assert not (out/name).exists(),'ExistingAnalysisOutputInspectBeforeRepeat:'+name
recovery.mkdir()
(recovery/'recover-analysis-executed.py').write_text(RECOVERY_SOURCE)
for name,source in OPERATIONAL_SOURCES.items():(recovery/name).write_text(source)
for source,name in [(r/'package/report.py','report-original.py'),(out/'controller.stderr.log','controller-original-error.log'),(out/'status.json','status-before-recovery.json')]:
 (recovery/name).write_bytes(source.read_bytes())
env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(r/'package')}
red=subprocess.run([str(r/'venv/bin/python'),str(r/'package/report.py')],cwd=r,env=env,capture_output=True,text=True)
(recovery/'red-replay.stdout.log').write_text(red.stdout)
(recovery/'red-replay.stderr.log').write_text(red.stderr)
assert red.returncode!=0 and "'str' object has no attribute 'get'" in red.stderr
original=(r/'package/report.py').read_text()
old="delivered.append(c['input'].get('answer',''))"
new="delivered.append(c['input'].get('answer') if isinstance(c.get('input'),dict) and isinstance(c['input'].get('answer'),str) else '')"
assert original.count(old)==1
corrected=recovery/'report-corrected-v1.py'
corrected.write_text(original.replace(old,new))
exclusive(recovery/'CORRECTION.json',{
 'reason':'Offline reader assumed every submit input was an object. One stored call has a string input. Native finalCandidate treats non-object or non-string answer as empty, without JSON decoding. Later submit remains the frozen final answer.',
 'affectedTask':'olympiadbench-physics-en-989','scope':'offline analysis only; no regeneration, rescoring, candidate edits, or frozen package changes',
 'replacement':{'old':old,'new':new},'originalReportSha256':sha(r/'package/report.py'),'correctedReportSha256':sha(corrected),
 'nativePolicySource':'package/engine/app/src/objective/candidate.ts','nativePolicySha256':sha(r/'package/engine/app/src/objective/candidate.ts'),
 'redReturnCode':red.returncode,'atUtc':dt.datetime.now(dt.timezone.utc).isoformat()})
green=subprocess.run([str(r/'venv/bin/python'),str(corrected)],cwd=r,env=env,capture_output=True,text=True)
(recovery/'green-replay.stdout.log').write_text(green.stdout)
(recovery/'green-replay.stderr.log').write_text(green.stderr)
assert green.returncode==0,green.stderr[-2000:]
audit=read(out/'AUDIT.json');assert audit['allPassed'],json.dumps(audit['failures'][:10])
rows=[read(p) for p in (out/'results').glob('*/*.json')]
assert len(rows)==472 and len({(x['arm'],x['id']) for x in rows})==472
exclusive(out/'final-freeze.json',{'atUtc':dt.datetime.now(dt.timezone.utc).isoformat(),'count':len(rows),'auditPassed':True,'analysisRecovery':'outputs/canonical/analysis-recovery-v2/CORRECTION.json'})
s['stage']='complete' if all(x['solverValid'] and x['grade'].get('valid') for x in rows) else 'complete_with_exceptions'
s['atUtc']=dt.datetime.now(dt.timezone.utc).isoformat();s['analysisRecovery']='outputs/canonical/analysis-recovery-v2/CORRECTION.json'
tmp=out/'status.recovery.tmp';tmp.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n');tmp.replace(out/'status.json')
print(json.dumps({'stage':s['stage'],'count':len(rows),'auditPassed':True,'analysisRecovery':s['analysisRecovery'],'report':json.loads(green.stdout)}))
'''.replace('REMOTE_ROOT', repr(REMOTE))
    sources={n:Path(__file__).with_name(n).read_text(encoding='utf-8') for n in ['ops.py','follow.py','verify_local.py']}
    sources.update({p.name:p.read_text(encoding='utf-8') for p in (LOCAL/'analysis-recovery-v1').iterdir() if p.suffix in {'.py','.json'}})
    code='RECOVERY_SOURCE='+repr(Path(__file__).read_text(encoding='utf-8'))+'\nOPERATIONAL_SOURCES='+repr(sources)+'\n'+code
    compile(code,'<offline-recovery>','exec')
    print(remote(code, 300))


if __name__ == '__main__':
    main()
