"""Independent local readback of the complete remote archive; never calls a model."""
from pathlib import Path
import hashlib
import json
import re
import sqlite3
from protocol import NAME,PARAMETERS,digest

REPO=Path(__file__).resolve().parents[4];LOCAL=REPO/'docs/olympiadbench'/NAME

def main():
    meta=json.loads((LOCAL/'retrieval.json').read_text(encoding='utf-8'));root=Path(meta['fullResults']);out=root/'outputs/canonical';checks=[]
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    def check(name,value,**extra):checks.append({'name':name,'passed':bool(value),**extra})
    archive=Path(meta['archive']);check('two-end-archive-sha256',meta['twoEndsSha256Verified'] and digest(archive.read_bytes())==meta['sha256'] and archive.stat().st_size==meta['bytes'])
    for manifest in ['source-pins.json','dependencies.json']:
        for rel,sha in read(root/'provenance'/manifest)['files'].items():check(manifest+':'+rel,(root/rel).is_file() and digest((root/rel).read_bytes())==sha)
    public=read(root/'data/public-tasks.json');ids={r['id'] for r in public};rows=[read(p) for p in (out/'results').glob('*/*.json')]
    check('472-unique-identities',len(rows)==472 and {(r['arm'],r['id']) for r in rows}=={(a,i) for a in ['baseline','objrun'] for i in ids} and len(ids)==236)
    check('remote-audit',read(out/'AUDIT.json')['allPassed']);check('zero-model-acceptance',read(out/'controls.json')['allPassed'] and read(out/'controls.json')['modelCalls']==0)
    canary=read(out/'canary.json');check('canary8x2',canary['allPassed'] and len(canary['records'])==16 and len(set(canary['ids']))==8)
    events=[];costs={a:{'lower':0,'upper':0,'unknown':0,'requests':0} for a in ['baseline','objrun']}
    for r in rows:
        d=out/'tasks'/r['arm']/r['id'];candidate=read(d/'frozen-candidate.json')
        check('candidate:'+r['arm']+'/'+r['id'],digest(r['answer'])==r['candidateSha256']==candidate['candidateSha256'] and r['answer']==candidate['answer']==(d/'final-answer.txt').read_text(encoding='utf-8'))
        if r['grade'].get('valid'):check('grade:'+r['arm']+'/'+r['id'],r['grade']['candidateSha256']==r['candidateSha256'] and r['grade']['taskId']==r['id'])
        if r['arm']=='objrun' and (d/'engine/data/h2h.sqlite').exists():
            db=sqlite3.connect('file:'+str(d/'engine/data/h2h.sqlite')+'?mode=ro',uri=True)
            delivered=[]
            for at,body in db.execute("select m.at,m.body from task_repair t join agent_bot_msg m on m.instance=t.instance and m.unit=t.unit where m.kind='call' order by m.at,m.seq"):
                for c in json.loads(body).get('calls',[]):
                    if c['name']=='submit' and at<=r['deadlineEpoch']*1000:
                        # Match frozen native finalCandidate: malformed arguments supply an empty answer.
                        argument=c.get('input')
                        answer=argument.get('answer') if isinstance(argument,dict) else None
                        delivered.append(answer if isinstance(answer,str) else '')
            check('native-submit:'+r['id'],(delivered[-1] if delivered else '')==r['answer']);db.close()
    for p in (out/'calls').glob('**/dispatch.json'):
        relative=p.relative_to(out/'calls');arm=relative.parts[2];d=read(p);q=read(p.with_name('request.json'))
        check('official-wire:'+str(relative),all(q.get(k)==v for k,v in PARAMETERS.items()) and 'temperature' not in q and 'provider' not in q and d['endpoint']=='https://api.deepseek.com/chat/completions')
        check('request-identity:'+str(relative),digest(q)==d['requestSha256']);costs[arm]['requests']+=1
        if not p.with_name('receipt.json').exists():costs[arm]['unknown']+=1;check('settled:'+str(relative),False);continue
        r=read(p.with_name('receipt.json'));c=r['cost'];events.extend([(r['startedEpoch'],1),(r['endedEpoch'],-1)])
        if c['kind']=='unknown':costs[arm]['unknown']+=1
        else:costs[arm]['lower']+=c['lowerUsd'];costs[arm]['upper']+=c['upperUsd']
        u=r.get('usage') or {}
        if 'prompt_cache_hit_tokens' in u and 'prompt_cache_miss_tokens' in u:check('usage:'+str(relative),u['prompt_tokens']==u['prompt_cache_hit_tokens']+u['prompt_cache_miss_tokens'])
    active=peak=0
    for at,delta in sorted(events,key=lambda x:(x[0],x[1])):active+=delta;peak=max(peak,active)
    check('global-model16',peak<=16 and active==0,peak=peak)
    summary=read(out/'SUMMARY.json')
    for arm,c in costs.items():
        reported=summary['accounting']['byArm'].get(arm,{})
        check('cost-reconciliation:'+arm,abs(c['lower']-reported.get('estimateLowerUsd',-1))<1e-8 and abs(c['upper']-reported.get('estimateUpperUsd',-1))<1e-8 and c['unknown']==reported.get('unknownCostRequests') and c['requests']==reported.get('requests'))
        usable=[r for r in rows if r['arm']==arm and r['solverValid'] and r['grade'].get('valid')]
        check('score-reconciliation:'+arm,len(usable)==summary['arms'][arm]['valid'] and sum(r['grade']['passed'] for r in usable)==summary['arms'][arm]['passed'])
    credential=(REPO/'.env').read_text(encoding='utf-8-sig');match=re.search(r'^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=\s*(.*?)\s*$',credential,re.M)
    if match:
        secret=match[1].strip().strip('\"\'').encode();hits=[]
        if len(secret)>8:
            for p in root.rglob('*'):
                if p.is_file() and secret in p.read_bytes():hits.append(p.relative_to(root).as_posix())
        check('credential-absent-from-delivery',not hits,hitFiles=hits)
    result={'allPassed':all(x['passed'] for x in checks),'checkCount':len(checks),'failures':[x for x in checks if not x['passed']],'checks':checks,'costs':costs,'archiveSha256':meta['sha256']}
    (LOCAL/'LOCAL_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name in ['REPORT.md','SUMMARY.json','AUDIT.json','FINAL_RESULTS.csv']:(LOCAL/name).write_bytes((out/name).read_bytes())
    print(json.dumps({'allPassed':result['allPassed'],'checks':len(checks),'failures':result['failures'][:10],'arms':summary['arms'],'costs':costs}))
    if not result['allPassed']:raise SystemExit(1)

if __name__=='__main__':main()
