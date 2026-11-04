"""Read-only independent verification of the downloaded complete run and archive."""
from pathlib import Path
import hashlib
import json
import math
import re
import sqlite3
import sys
import tarfile

repo=Path(__file__).resolve().parents[3]
local=repo/'docs/frontierscience/frontierscience-formal-20261016-v1-deepseek-c32'
root=local/'full-results';out=root/'outputs/canonical'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda b:hashlib.sha256(b if isinstance(b,bytes) else b.encode()).hexdigest()
checks=[]
def check(name,ok,**detail):checks.append({'name':name,'passed':bool(ok),**detail})
meta=read(local/'retrieval.json');archive=Path(meta['archive'])
check('two-end-archive-sha',meta['twoEndsSha256Verified'] and sha(archive.read_bytes())==meta['sha256'])
source=read(root/'data/source.json');cfg=read(root/'package/experiment.json')
check('official-dataset-sha',sha((root/'data/test.jsonl').read_bytes())==source['fileSha256']=='450e7fceb53c8140283a752f0d62a3abc69a85e252d4dbbd5d9dfbfb762db4e4')
ids=set(source['ids']);expected={(a,i) for a in cfg['arms'] for i in ids}
original={};final={}
for category,target in [('results',original),('final-results',final)]:
    rows=[read(p) for p in (out/category).glob('*/*.json')]
    for r in rows:target[(r['arm'],r['id'])]=r
    check('200-unique-'+category,len(rows)==len(target)==200 and set(target)==expected)
check('controls',read(out/'controls.json')['allPassed'])
check('server-audit',read(out/'AUDIT.json')['allPassed'])
for rel,digest in read(out/'source-pins.json')['files'].items():check('source:'+rel,sha((root/rel).read_bytes())==digest)
deps=read(root/'provenance/dependencies.json')
for pin in deps['files']:check('dependency:'+pin['path'],sha((root/pin['path']).read_bytes())==pin['sha256'])
for ident,r in original.items():
    arm,tid=ident;directory=out/'tasks'/arm/tid;f=read(directory/'frozen-candidate.json')
    check('candidate:'+arm+'/'+tid,r['answer']==f['answer'] and sha(r['answer'])==r['candidateSha256']==f['candidateSha256']==final.get(ident,{}).get('candidateSha256'))
    if arm=='baseline':
        calls=list((out/'calls/solve'/tid/'baseline').glob('*/attempt-*/request.json'))
        check('single-logical-generation:'+tid,len({p.parent.parent for p in calls})==1)
        for p in calls:check('single-no-feedback:'+tid,read(p)['messages']==[{'role':'user','content':next(x['problem'] for x in read(root/'data/public-tasks.json') if x['id']==tid)}])
    else:
        db=sqlite3.connect('file:'+str(directory/'engine/data/h2h.sqlite')+'?mode=ro',uri=True)
        submissions=[];check_counts={}
        for node,at,body in db.execute("select t.node,m.at,m.body from task_repair t join agent_bot_msg m on m.instance=t.instance and m.unit=t.unit where m.kind='call' order by m.at,m.seq"):
            for c in json.loads(body).get('calls',[]):
                if c['name']=='submit' and at<=r['deadlineEpoch']*1000:submissions.append(c['input'].get('answer',''))
        check('actual-delivery:'+tid,(submissions[-1] if submissions else '')==r['answer'])
        for node,body in db.execute("select t.node,m.body from task_repair t join agent_bot_msg m on m.instance=t.instance and m.unit=t.unit where m.kind='tool'"):
            v=json.loads(body);g=v.get('value',{})
            if v.get('name')=='verify' and not str(v.get('id','')).startswith('g-') and g.get('valid') is not False and g.get('pass') in [0,1]:check_counts[node]=check_counts.get(node,0)+1
        check('attempt-c5:'+tid,all(v<=5 for v in check_counts.values()))
        db.close()
        for feedback in read(directory/'feedback.json') if (directory/'feedback.json').exists() else []:
            e=feedback['exposed'];check('limited-feedback:'+tid,set(e)=={'value','note'} and e['note'] in ['', 'Provide an answer to the question.'])
for p in (out/'calls').glob('**/request.json'):
    q=read(p);d=read(p.with_name('dispatch.json'));rel=p.relative_to(out/'calls');category=rel.parts[0]
    check('official-wire:'+str(rel),q['model']=='deepseek-flash' and q['thinking']=={'type':'enabled'} and q['reasoning_effort']=='high' and q['max_tokens']==16384 and 'temperature' not in q and 'provider' not in q and d['endpoint']=='https://api.deepseek.com/chat/completions')
    check('dispatch-sha:'+str(rel),sha(json.dumps(q,sort_keys=True,ensure_ascii=False))==d['requestSha256'])
    check('receipt:'+str(rel),p.with_name('receipt.json').exists())
    if category=='solve':
        tid=rel.parts[1];arm=rel.parts[2];r=original.get((arm,tid))
        check('original-deadline:'+str(rel),r and math.isclose(d['deadlineEpoch'],r['deadlineEpoch'],rel_tol=0,abs_tol=.000001) and d['startedEpoch']<=r['deadlineEpoch'])
    if category in {'online','final'}:
        payload=json.loads(q['messages'][1]['content']);check('blind-payload:'+str(rel),len(q['messages'])==2 and set(payload)=={'problem','reference_answer','candidate_answer'})
for home in {p.parent.parent for p in (out/'calls').glob('**/dispatch.json')}:check('retry-bound:'+str(home.relative_to(out)),len(list(home.glob('attempt-*/dispatch.json')))<=3)
final_requests=list((out/'calls/final').glob('*/attempt-*/request.json'))
check('200-fresh-final-calls',len({p.parent.parent for p in final_requests})==200)
text=(repo/'.env').read_text(encoding='utf-8-sig');m=re.search(r'^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=\s*(.*?)\s*$',text,re.M)
if m:
    secret=m[1].strip().strip('\"\'').encode();hits=[]
    for p in root.rglob('*'):
        if p.is_file() and len(secret)>8 and secret in p.read_bytes():hits.append(p.relative_to(root).as_posix())
    check('credential-absent-from-complete-archive',not hits,hitFiles=hits)
result={'allPassed':all(c['passed'] for c in checks),'checks':len(checks),'failures':[c for c in checks if not c['passed']],
        'archiveSha256':meta['sha256'],'originalTasks':len(original),'finalTasks':len(final),'validFinalTasks':sum(r.get('solverValid') and r['grade'].get('valid') for r in final.values()),'details':checks}
(local/'LOCAL_VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='details'}))
if not result['allPassed']:sys.exit(1)
