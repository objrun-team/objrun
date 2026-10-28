import collections, hashlib, json, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/climaqa/pilot-20261028-v1'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def parse(s):
 m=re.findall(r'(?im)^\s*Answer:\s*\(?([A-D])\)?\s*$',s)
 return m[0].upper() if len(m)==1 else None
def main():
 pub=read(OUT/'public.json');private={x['id']:x['answer'] for x in read(OUT/'private.json')};pins=read(OUT/'source-pins.json');arms=['baseline','independent','binary','objrun'];rows=[read(x) for x in (OUT/'results').glob('*/*.json')];ids={x['id'] for x in pub}
 checks={};checks['sourcePins']=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==v for p,v in pins['files'].items());checks['scope']=len(ids)==20 and len(rows)==80 and {(r['arm'],r['id']) for r in rows}=={(a,i) for a in arms for i in ids}
 checks['valid']=all(r['valid'] for r in rows);checks['goldMapping']=all(not r['valid'] or r['grade']['passed']==(parse(r['answer'])==private[r['id']]) for r in rows)
 checks['candidateHash']=all(hashlib.sha256(r['answer'].encode()).hexdigest()==r['answerSha256'] for r in rows);checks['judgeCap']=all(r['distinctJudgments']<=2 for r in rows)
 checks['nativeSubmitted']=all(r.get('candidateHow')=='submitted' and not r.get('error') for r in rows if r['arm']=='objrun')
 counts=collections.Counter();first={a:{'known':0,'passed':0} for a in arms};formats=collections.Counter();unique={}
 for r in rows:
  a=r['arm'];tid=r['id'];counts[(a,r.get('complexity'),bool(r.get('grade',{}).get('passed')))]+=1
  if r.get('grade',{}).get('kind')=='invalid_format':formats[a]+=1
  if a!='objrun':
   samples=r.get('samples',[]);assert len(samples)<= (1 if a=='baseline' else 2)
   if samples:
    first[a]['known']+=1;first[a]['passed']+=int(samples[0]['grade']['passed'])
  else:
   path=OUT/'tasks'/a/tid/'feedback.json';f=read(path) if path.exists() else []
   answers=[parse(x['candidate']) for x in f if x['node']=='/correct' and parse(x['candidate'])];unique[tid]=answers
   if answers:first[a]['known']+=1;first[a]['passed']+=int(answers[0]==private[tid])
   assert len(set(answers))<=2
 checks['allJudgmentsWithinCap']=all(len(set(x))<=2 for x in unique.values())
 receipts=list((OUT/'calls').glob('*/*/*/receipt.json'));dispatch=list((OUT/'calls').glob('*/*/*/dispatch.json'));checks['receiptCoverage']=len(receipts)==len(dispatch)
 checks['requestedModel']=all(read(x)['responseModel']=='deepseek-flash' for x in receipts if not read(x).get('error'))
 checks['noModelErrors']=all(not read(x).get('error') for x in receipts)
 checks['publicFields']=all(set(x)=={'id','source_row','complexity','prompt'} for x in pub)
 result={'checks':checks,'allPassed':all(checks.values()),'rows':len(rows),'firstCandidate':first,'invalidFormat':dict(formats),'countsByArmLevelAndPass':[{'arm':a,'level':l,'passed':p,'count':v} for (a,l,p),v in counts.items()],'receipts':len(receipts),'dispatches':len(dispatch)}
 (OUT/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
