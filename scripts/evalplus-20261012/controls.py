import concurrent.futures,hashlib,json,pathlib,requests,time
ROOT=pathlib.Path(__file__).resolve().parents[2];OUT=ROOT/'docs/evalplus-20261012'
sources=json.loads((OUT/'sources.json').read_text());records=[]
def control(slug,tid,kind):
 port={'humaneval':17961,'mbpp':17962}[slug]
 name={'humaneval':'HumanEvalPlus','mbpp':'MbppPlus'}[slug]
 row=next(json.loads(x) for x in (ROOT/f'.phase1-data/evalplus-20261012/{name}.jsonl').read_text().splitlines() if json.loads(x)['task_id']==tid)
 code=row['prompt']+row['canonical_solution']
 if kind=='wrong': code='def '+row['entry_point']+'(*args):\n    raise RuntimeError("deliberately wrong")'
 if kind=='isolation':
  linux='/mnt/f/git/TgEngin-handoff-2026-10-07/TgEngin/.phase1-data/evalplus-20261012/'+name+'.jsonl'
  code=f'''try:
    open({linux!r}).read()
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
'''+code
 q={'task_id':tid,'code':code}
 start=time.time();v=requests.post(f'http://127.0.0.1:{port}/grade',json=q,timeout=180).json()
 ok=v.get('valid') is True and v.get('passed') is (kind!='wrong')
 return {'dataset':slug,'taskId':tid,'kind':kind,'checkPassed':ok,'seconds':time.time()-start,'verdict':v}
jobs=[]
for s,d in sources['datasets'].items():
 for tid in d['pilotIds']:
  jobs.extend([(s,tid,'reference'),(s,tid,'wrong')])
 jobs.append((s,d['pilotIds'][0],'isolation'))
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 for r in pool.map(lambda args:control(*args),jobs): records.append(r);print(json.dumps({k:r[k] for k in ['dataset','taskId','kind','checkPassed']}),flush=True)
summary={'allPassed':all(r['checkPassed'] for r in records),'records':records,'modelCalls':0,'dockerForbidden':True,'officialEvaluator':'v0.3.1','rpcAdapterDisclosed':True}
(OUT/'controls.json').write_text(json.dumps(summary,indent=2)+'\n')
raise SystemExit(0 if summary['allPassed'] else 1)
