"""Runpy compatible delegated Pipeline Stand; qualification lifecycle is explicit."""
from bootstrap import install,ROOT
install()
import os,json,time,threading,uuid
from pathlib import Path
import stand_v1
from activation_guard import require_activation,require_lease
from portable_framework import install as install_framework
from pipeline_grade import grade_snapshot
stand_v1.grade_snapshot=grade_snapshot
Base=stand_v1.Stand
class Stand(Base):
 def __init__(self,base_proof,output,token):
  self.pipeline_proof=json.loads(Path(base_proof).read_bytes());require_activation();require_lease(24576,32212254720,'terminal-bench',1);super().__init__(base_proof,output,token)
 def up(self,body):
  assert body['taskId']=='torch-pipeline-parallelism';require_lease(24576,32212254720,'terminal-bench',1);value=super().up(body)
  if self.pipeline_proof.get('qualificationOnly'):
   owner=self.owner(body['place']);prefix,receipt=install_framework(self.native,owner['cid'],self.output/'candidate-portable-framework');owner['portablePrefix']=prefix;self.rows.append({'kind':'qualification-only-portable-setup','place':body['place'],'receipt':receipt,'benchmarkGradingInvocations':0});self.persist()
  return value
 def grade(self,owner,place,label):
  if not self.pipeline_proof.get('qualificationOnly'):return super().grade(owner,place,label)
  # Explicit protocol lifecycle acknowledgement with no original grading invocation.
  row={'invocationId':uuid.uuid4().hex,'policyReward':0,'originalReward':None,'syntheticOnly':True,'benchmarkGradingInvocations':0,'qualificationOnly':True,'directOriginalControlsPin':self.pipeline_proof['directOriginalControlsPin'],'callbackTransportPin':self.pipeline_proof['callbackTransportPin'],'result':{'reward':0}}
  self.rows.append({'kind':'qualification-only-ran-record','place':place,'record':row,'notProductionGrade':True});owner['grades']+=1;self.persist();return row
 def route(self,path,body):
  if path=='/close':
   if not self.gate.acquire(timeout=600):raise RuntimeError('Inflight setup not closed within600s')
   try:return super().route(path,body)
   finally:self.gate.release()
  value=super().route(path,body)
  if path=='/passed' and self.pipeline_proof.get('qualificationOnly'):value.update(syntheticOnly=True,benchmarkGradingInvocations=0,note='Qualification lifecycle only; no new benchmark grading was executed.')
  return value
stand_v1.Stand=Stand
if __name__=='__main__':stand_v1.main()
