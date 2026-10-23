"""Zero-model controls against the dedicated binary grader after environment restoration."""
import json,pathlib,urllib.request,datetime
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/evalplus-20261012/humaneval/binary-v1'
cfg=json.loads((OUT/'config.json').read_text())
row=json.loads((ROOT/'.phase1-data/evalplus-20261012/HumanEvalPlus.jsonl').read_text().splitlines()[0])
reference=row['prompt']+row['canonical_solution']
isolation='''try:
    open('/mnt/f/git/TgEngin-handoff-2026-10-07/TgEngin/.phase1-data/evalplus-20261012/HumanEvalPlus.jsonl').read()
except PermissionError: pass
else: raise AssertionError('oracle read allowed')
import socket
try: socket.socket()
except PermissionError: pass
else: raise AssertionError('network allowed')
import subprocess
try: subprocess.run(['/bin/true'])
except PermissionError: pass
else: raise AssertionError('process allowed')
'''+reference
records=[]
for kind,code,expected,base in [
    ('reference-base',reference,True,True),('reference-final',reference,True,False),
    ('wrong-base','def '+row['entry_point']+'(*args): return False',False,True),
    ('syntax-base','def invalid(:',False,True),('isolation-final',isolation,True,False)]:
    req=urllib.request.Request(f"http://127.0.0.1:{cfg['graderPort']}/grade",data=json.dumps({'task_id':row['task_id'],'code':code,'feedback_only':base}).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=180) as r: grade=json.load(r)
    ok=grade.get('valid') is True and grade.get('passed') is expected
    if base and 'plus' in grade.get('groups',{}): ok=False
    record={'kind':kind,'checkPassed':ok,'grade':grade};records.append(record)
    print(json.dumps({'kind':kind,'checkPassed':ok}),flush=True)
summary={'allPassed':all(r['checkPassed'] for r in records),'atUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'modelCalls':0,'dockerForbidden':True,'records':records}
(OUT/'controls.json').write_text(json.dumps(summary,indent=2)+'\n')
raise SystemExit(0 if summary['allPassed'] else 1)
