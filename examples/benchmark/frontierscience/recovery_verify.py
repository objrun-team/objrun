"""Independent local acceptance of recovery identities, budgets, privacy and archives."""
from pathlib import Path
import datetime as dt
import hashlib
import importlib.util
import json
import math
import re
import sqlite3
import sys

REPO=Path(__file__).resolve().parents[3]
NAME='frontierscience-recovery-20261016-v1-deepseek-c32'
LOCAL=REPO/'docs/frontierscience'/NAME
ORIGLOCAL=REPO/'docs/frontierscience/frontierscience-formal-20261016-v1-deepseek-c32'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda b:hashlib.sha256(b if isinstance(b,bytes) else b.encode()).hexdigest()

def main():
    sys.dont_write_bytecode=True
    root=LOCAL/'full-results';out=root/'outputs/canonical';original=ORIGLOCAL/'full-results'
    manifest=read(root/'data/recovery-manifest.json');meta=read(LOCAL/'retrieval.json');checks=[]
    module_spec=importlib.util.spec_from_file_location('verified_frozen_protocol',root/'package/protocol.py')
    frozen_protocol=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(frozen_protocol)
    def check(name,ok,**detail):checks.append({'name':name,'passed':bool(ok),**detail})
    check('original-full-verification',read(ORIGLOCAL/'LOCAL_VERIFICATION.json')['allPassed'])
    om=read(ORIGLOCAL/'retrieval.json')
    check('original-archive-retained',sha(Path(om['archive']).read_bytes())==manifest['originalArchiveSha256']==om['sha256'])
    check('recovery-two-end-sha',meta['twoEndsSha256Verified'] and sha(Path(meta['archive']).read_bytes())==meta['sha256'])
    check('manifest-exact-copy',sha((root/'data/recovery-manifest.json').read_bytes())==sha((LOCAL/'recovery-manifest.json').read_bytes()))
    check('200-unique-original-identities',len(manifest['entries'])==200 and len({(e['arm'],e['id']) for e in manifest['entries']})==200)
    selected={(e['arm'],e['id']):e for e in manifest['entries'] if e['action'] in {'objrun_once','score_once'}}
    check('round-one-only',manifest['round']==1 and all(e['round']==1 for e in selected.values()))
    records={(r['arm'],r['id']):r for p in (out/'results').glob('*/*.json') for r in [read(p)]}
    finals={(r['arm'],r['id']):r for p in (out/'final-results').glob('*/*.json') for r in [read(p)]}
    check('recovery-identity-map',set(records)==set(finals)==set(selected))
    check('exclusive-identity-locks',{(p.parent.name,p.stem) for p in (out/'recovery-locks').glob('*/*.json')}==set(selected))
    check('controls-acceptance',read(out/'controls.json')['allPassed'])
    check('original-drained',read(out/'original-freeze.json')['originalProcessIdsLive']==[] and read(out/'original-freeze.json')['pendingJobs']==[] and read(out/'original-freeze.json')['unresolvedDispatches']==[])
    for rel,digest in read(out/'source-pins.json')['files'].items():check('source:'+rel,sha((root/rel).read_bytes())==digest)
    for name in ['protocol.py','runtime.py','native.ts']:
        check('unchanged-frozen-adapter:'+name,sha((root/'package'/name).read_bytes())==sha((original/'package'/name).read_bytes()))
    for pin in read(root/'provenance/dependencies.json')['files']:
        check('dependency:'+pin['path'],sha((root/pin['path']).read_bytes())==pin['sha256'])
    check('archived-bun-matches-original-pin',sha((root/'bin/bun').read_bytes())==read(original/'provenance/dependencies.json')['bunSha256'])
    check('dataset-identical',sha((root/'data/test.jsonl').read_bytes())==manifest['dataSha256']==sha((original/'data/test.jsonl').read_bytes()))
    book={r['task_group_id']:r for r in map(json.loads,(root/'data/test.jsonl').read_text(encoding='utf-8').splitlines())}
    for ident,e in selected.items():
        arm,tid=ident;r=records[ident];f=finals[ident];d=out/'tasks'/arm/tid;frozen=read(d/'frozen-candidate.json')
        check('frozen-candidate:'+arm+'/'+tid,sha(r['answer'])==r['candidateSha256']==f['candidateSha256']==frozen['candidateSha256'] and r['answer']==frozen['answer'])
        if e['action']=='score_once':
            orig=read(original/'outputs/canonical/results'/arm/(tid+'.json'))
            check('score-only-no-regeneration:'+tid,bool(orig['answer']) and r['answer']==orig['answer'] and not list((out/'calls/solve'/tid/arm).glob('**/dispatch.json')) and r['extraSolveSeconds']==0)
            check('score-only-original-blind-invalid:'+tid,not read(original/'outputs/canonical/final-results'/arm/(tid+'.json'))['grade']['valid'])
        else:
            check('eligible-real-early-fault:'+tid,e['evidence']['earlyInfrastructureFailure'] and not e['evidence']['normalBudgetBoundary'])
            check('explicit-extra600:'+tid,r['extraSolveSeconds']==600 and math.isclose(r['deadlineEpoch']-r['startedEpoch'],600,abs_tol=1e-6) and r['startedEpoch']>e['evidence']['originalDeadlineEpoch'])
            spec=read(d/'input.json')
            check('public-only-worker-input:'+tid,spec['task']=={'id':tid,'problem':book[tid]['problem']} and set(spec)=={'task','directory','deadlineEpoch','fixture','run'})
            db=sqlite3.connect('file:'+str(d/'engine/data/h2h.sqlite')+'?mode=ro',uri=True)
            delivered=[];counts={}
            for node,at,body in db.execute("select t.node,m.at,m.body from task_repair t join agent_bot_msg m on m.instance=t.instance and m.unit=t.unit where m.kind='call' order by m.at,m.seq"):
                for c in json.loads(body).get('calls',[]):
                    if c['name']=='submit' and at<=r['deadlineEpoch']*1000:delivered.append(c['input'].get('answer',''))
            check('real-submit-delivery:'+tid,(delivered[-1] if delivered else '')==r['answer'])
            for node,body in db.execute("select t.node,m.body from task_repair t join agent_bot_msg m on m.instance=t.instance and m.unit=t.unit where m.kind='tool'"):
                v=json.loads(body);g=v.get('value',{})
                if v.get('name')=='verify' and not str(v.get('id','')).startswith('g-') and g.get('valid') is not False and g.get('pass') in [0,1]:counts[node]=counts.get(node,0)+1
            check('per-attempt-c5:'+tid,all(v<=5 for v in counts.values()),counts=counts)
            check('only-four-tools:'+tid,{x[0] for x in db.execute('select name from tool where usable=1')}=={'submit','verify','task_tree','node_load'})
            task=db.execute('select solve_seconds,max_branches from task').fetchone()
            check('engine600-branch4:'+tid,task==(600,4))
            cycles=db.execute("select cycle,max_units from cycle where mode='repair' and cycle in ('ask','act')").fetchall()
            check('cycle12:'+tid,len(cycles)==2 and all(x[1]==12 for x in cycles));db.close()
            for feedback in read(d/'feedback.json') if (d/'feedback.json').exists() else []:
                check('limited-feedback:'+tid,set(feedback['exposed'])=={'value','note'} and feedback['exposed']['note'] in ['','Provide an answer to the question.'])
    freeze_epoch=dt.datetime.fromisoformat(read(out/'final-freeze.json')['atUtc']).timestamp()
    events=[]
    for p in (out/'calls').glob('**/request.json'):
        q=read(p);dispatch=read(p.with_name('dispatch.json'));rel=p.relative_to(out/'calls');cat=rel.parts[0]
        check('official-wire:'+str(rel),q['model']=='deepseek-flash' and q['thinking']=={'type':'enabled'} and q['reasoning_effort']=='high' and q['max_tokens']==16384 and 'temperature' not in q and 'provider' not in q and dispatch['endpoint']=='https://api.deepseek.com/chat/completions')
        check('request-sha:'+str(rel),sha(json.dumps(q,sort_keys=True,ensure_ascii=False))==dispatch['requestSha256'])
        check('receipt:'+str(rel),p.with_name('receipt.json').exists())
        receipt=read(p.with_name('receipt.json'));events.extend([(receipt['startedEpoch'],1,cat),(receipt['endedEpoch'],-1,cat)])
        if cat=='solve':
            r=records[('objrun',rel.parts[1])]
            check('fixed-extra-deadline:'+str(rel),math.isclose(dispatch['deadlineEpoch'],r['deadlineEpoch'],rel_tol=0,abs_tol=1e-6) and dispatch['startedEpoch']<=r['deadlineEpoch'])
            check('no-blind-feedback-loop:'+str(rel),dispatch['startedEpoch']<freeze_epoch)
            for m in q['messages']:
                if m['role']=='assistant':check('thinking-history:'+str(rel),isinstance(m.get('reasoning_content'),str))
        elif cat in {'online','final'}:
            payload=json.loads(q['messages'][1]['content'])
            job=read(out/'jobs'/cat/(rel.parts[1]+'.json'));row=book[job['id']]
            check('private-blind-payload:'+str(rel),len(q['messages'])==2 and payload=={'problem':row['problem'],'reference_answer':row['answer'],'candidate_answer':job['candidate']})
            check('exact-frozen-grading-messages:'+str(rel),q['messages']==frozen_protocol.judge_messages(row,job['candidate']))
            if cat=='final':check('blind-after-all-freezes:'+str(rel),dispatch['startedEpoch']>=freeze_epoch)
    peak=active=solve=grader=0;maxsolve=maxgrader=0
    for at,delta,cat in sorted(events,key=lambda x:(x[0],x[1])):
        active+=delta;solve+=delta if cat=='solve' else 0;grader+=delta if cat!='solve' else 0
        peak=max(peak,active);maxsolve=max(maxsolve,solve);maxgrader=max(maxgrader,grader)
    check('shared-api32-solve24-grader8',peak<=32 and maxsolve<=24 and maxgrader<=8,peak=peak,solve=maxsolve,grader=maxgrader)
    check('one-independent-final-per-identity',len(list((out/'jobs/final').glob('*.json')))==len(selected))
    for home in {p.parent.parent for p in (out/'calls').glob('**/dispatch.json')}:
        check('three-attempt-bound:'+str(home.relative_to(out)),len(list(home.glob('attempt-*/dispatch.json')))<=3)
    text=(REPO/'.env').read_text(encoding='utf-8-sig');m=re.search(r'^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=\s*(.*?)\s*$',text,re.M)
    if m:
        secret=m[1].strip().strip('\"\'').encode();hits=[]
        for p in root.rglob('*'):
            if p.is_file() and len(secret)>8 and secret in p.read_bytes():hits.append(p.relative_to(root).as_posix())
        check('credential-absent',not hits,hitFiles=hits)
    result={'allPassed':all(c['passed'] for c in checks),'checks':len(checks),'failures':[c for c in checks if not c['passed']],
            'archiveSha256':meta['sha256'],'recoveryTasks':len(records),'details':checks}
    (LOCAL/'LOCAL_VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='details'}))
    if not result['allPassed']:sys.exit(1)

if __name__=='__main__':main()
