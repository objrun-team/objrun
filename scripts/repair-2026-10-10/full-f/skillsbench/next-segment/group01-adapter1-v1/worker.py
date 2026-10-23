"""Reviewed worker -> scoped Stand. No scheduler, registration, or model call."""
import hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent; CORE=HERE.parents[1]
sys.path.insert(0,str(CORE));sys.path.insert(0,str(HERE))
from prepare import public,save
from snapshot_adapter import evaluate_snapshot,require_lease,TASKS

def load_stand():
 source=CORE/'data_stand.py'; code=(HERE/'stand_base.py').read_text(encoding='utf8')
 # Reuse six-tool gateway, deadline, runtime deployment, HTTP and ownership lifecycle.
 # One explicit scoped runner substitution; shared/live source remains unchanged.
 old="runner.parent==ROOT/'scripts/repair-2026-10-10/full-f/skillsbench' and runner.name in ('private_eval.py','private_eval_v2.py','private_eval_multi.py','private_eval_score.py')"
 assert code.count(old)==1
 code=code.replace(old,"runner==Path("+repr(str(HERE/'private_runner.py'))+")")
 namespace={'__file__':str(source),'__name__':'group01_scoped_stand'};exec(compile(code,str(source),'exec'),namespace)
 Base=namespace['Stand']
 class Stand(Base):
  def create(self,body):
   tid=self.identify(body['place']);assert tid in TASKS
   proof=self.config['taskReadiness'][tid];built=json.loads(Path(proof['builtImagesPin']['path']).read_bytes())
   require_lease(self.config['resourceOwnerPid'],built['aggregateMemoryMb'])
   for pin in built['builtSourcePins']: assert public.pin(Path(pin['path']))==pin
   super().create(body)
  def grade(self,body,kind):
   with self.lock:
    assert self.current and body['place']==self.current['place'];c=self.current;answer=str(body.get('said',''));key=(c['place'],c['mutation'],answer)
    if kind=='passed' and self.latest and self.latest[0]==key:return self.latest[1]
    if c['running']:self.command(['stop','-t','1',c['cid']]);c['running']=False
    try:
     evaluation=evaluate_snapshot(self.command,c['cid'],c['nonce'],c['built'],self.config['resourceOwnerPid']);result=evaluation['result']
     collection=json.loads(Path(c['control']['collectionPin']['path']).read_bytes())
     assert result['nodeIds']==collection['nodeIds'] and result['complete']
     pin=save(self.home/('grade-'+__import__('uuid').uuid4().hex+'.json'),{**evaluation,'solverNonce':c['nonce'],'mutation':c['mutation'],'answerSha256':hashlib.sha256(answer.encode()).hexdigest()},True)
     value={'gradeOwnerPin':pin,'valid':True,'verified':True,'passed':result['reward']==1,'note':json.dumps({'reward':result['reward'],'tests':len(result['nodeIds'])})}
     self.latest=(key,value);return value
    finally:
     if __import__('time').time()*1000<c['deadline'] and not self.refresh_deadline():self.command(['start',c['cid']]);c['running']=True
 namespace['Stand']=Stand
 return namespace

if __name__=='__main__': load_stand()['main']()
