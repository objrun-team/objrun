"""One separate native re-attempt for a completed pilot infrastructure exception."""
import json, os, re, time
from pathlib import Path
import run

BASE=run.OUT; REC=BASE/'recovery-271-v1'; TID='climaqa-gold-mcq-271'
def main():
 REC.mkdir(exist_ok=False)
 rows=run.read(BASE/'public.json');task=next(x for x in rows if x['id']==TID)
 original=run.read(BASE/'results/objrun'/f'{TID}.json');native=run.read(BASE/'tasks/objrun'/TID/'native-result.json')
 assert not original['valid'] and 'MissingReasoningContentInToolHistory' in original['error']
 trace=run.read(BASE/'tasks/objrun'/TID/'trace.json')
 assert any(x.get('role')=='tool' and 'this station ended before the call was run' in str(x.get('body')) for x in trace)
 run.BOOK={x['id']:x['answer'] for x in run.read(BASE/'private.json')}
 oldfeedback=run.read(BASE/'tasks/objrun'/TID/'feedback.json')
 seen={}
 for item in oldfeedback:
  if item['node']=='/correct':
   option=run.parse(item['candidate']);assert option
   seen[option]=bool(item['exposed']['value'])
 assert len(seen)<=2 and all(v==(k==run.BOOK[TID]) for k,v in seen.items())
 run.SEEN[('objrun',TID)]=seen;run.OUT=REC
 for line in (run.ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
  if line.strip().startswith('DEEPSEEK_API_KEY='):run.KEY=line.split('=',1)[1].strip().strip('"\'');break
 assert run.KEY
 old_model=run.model
 def model(tid,arm,index,body,deadline):
  # Restore reasoning ONLY from the exact earlier provider response sharing the tool-call IDs.
  response_files=list((REC/'calls'/arm/tid).glob('*/response.json'))
  for msg in body.get('messages',[]):
   if msg.get('role')!='assistant' or isinstance(msg.get('reasoning_content'),str):continue
   ids=[x['id'] for x in msg.get('tool_calls',[])]
   matches=[]
   for p in response_files:
    m=run.read(p)['choices'][0]['message']
    if ids and ids==[x['id'] for x in m.get('tool_calls',[])]:matches.append(m)
   if len(matches)!=1 or not isinstance(matches[0].get('reasoning_content'),str):raise RuntimeError('CannotProveOriginalReasoningField')
   msg['reasoning_content']=matches[0]['reasoning_content']
  return old_model(tid,arm,index,body,deadline)
 run.model=model
 run.save(REC/'protocol.json',{'atUtc':run.now(),'kind':'one separate fresh native attempt for infrastructure exception','originalId':TID,'originalResultRetained':True,'priorJudgedOptions':list(seen),'sharedDistinctOptionBudget':2,'newTaskClockSeconds':600,'modelCallsToDateAreRetainedSeparately':True},True)
 s=run.server();start=time.time()
 try:
  d=REC/'native';d.mkdir();n=run.native(task,d,s);answer=n.get('answer','')
  g=run.grade(TID,'objrun',answer) if not n.get('error') and n.get('candidateHow')=='submitted' else None
  # The native engine's earlier submit tool can be declined as it moves to its
  # dedicated hand-in station. Require that station itself to finish.
  tree=run.read(d/'tree.json');completed_handin=any(x.get('cycle')=='submit' and x.get('done')==1 for x in tree)
  verdict=n.get('engineVerdict') or {}
  valid=bool(g and completed_handin and n.get('engineState') in ('done','failed') and verdict.get('valid') is True and bool(verdict.get('pass'))==g['passed'])
  result={'id':TID,'arm':'objrun','valid':valid,'grade':g,'completedHandinStation':completed_handin,'native':n,'cumulativeDistinctJudgments':len(run.SEEN[('objrun',TID)]),'seconds':time.time()-start}
  run.save(REC/'result.json',result,True);print(json.dumps(result,ensure_ascii=False),flush=True)
 finally:s.shutdown()
if __name__=='__main__':main()
