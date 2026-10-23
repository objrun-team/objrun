import sys,os,json,hashlib,base64,importlib.util,uuid
from pathlib import Path
ROOT=Path('F:/git/TgEngin-handoff-2026-10-07/TgEngin');HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'scripts/repair-2026-10-10/full-f/novaeve_formal_v1/group-04/adapter_1'))
spec=importlib.util.spec_from_file_location('activation_guard',ROOT/'scripts/repair-2026-10-10/full-f/novaeve_formal_v1/broker/adopted_owner_guard_v81.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard);sys.modules['activation_guard']=guard
from probe_docker_owned import OwnedDocker
class ProbeDocker(OwnedDocker):
 def guard(self):
  guard.require_lease(memory_mb=24576,growth_bytes=32212254720,slug='terminal-bench',slots=1)
  guard.before_forward_guard()
  return super().guard()
def pin(p):
 b=Path(p).read_bytes();return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
if __name__=='__main__':
 output=Path(sys.argv[1]);image=sys.argv[2];output.mkdir(parents=True,exist_ok=False)
 n=ProbeDocker(output/'native');cid=None;proof={'modelCalls':0,'oracleCalls':0,'nativeProbeExecuted':True,'closed':False}
 try:
  cid,initial,create=n.create('mailbox-transport-probe',image,'/bin/sh',['-c','sleep 600'],memory_mb=8192,cpus=1,readonly=True,network='none')
  proof.update(cid=cid,create=create,initial=initial);n.start(cid)
  helper_path=ROOT/'scripts/repair-2026-10-10/full-f/novaeve_formal_v1/group-04/mailbox-transport-v1/mailbox_transport.py'
  spec=importlib.util.spec_from_file_location('actual_mailbox_transport',helper_path);helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
  import time
  deadline=time.monotonic()+600
  def remain():return deadline-time.monotonic()
  request=b'{"id":"32-1","operation":"pipeline","arguments":{"probe":true}}'
  guest="import os;os.makedirs('/tmp/pipeline-mailbox',exist_ok=True);open('/tmp/pipeline-mailbox/32-1.request.json','wb').write("+repr(request)+")"
  proof['guestWrite']=n.execute(cid,['/opt/checker/bin/python','-c',guest])
  proof['find']=n.execute(cid,['find','/tmp/pipeline-mailbox','-maxdepth','1','-type','f'])
  proof['oldCp']=n.command(['cp',cid+':/tmp/pipeline-mailbox/32-1.request.json',str(output/'old-cp-request.json')])
  p=output/'old-cp-request.json';proof['oldCpMatches']=p.is_file() and p.read_bytes()==request
  n.guard();n.assert_actor(cid)
  captured,receipt=helper.capture_request(n,cid,'32-1.request.json',output,remain)
  proof['inNamespaceRead']=receipt;assert captured==json.loads(request) and (output/'32-1.request.json').read_bytes()==request
  proof['requestPin']=pin(output/'32-1.request.json');proof['helperPin']=pin(helper_path)
  reply={'id':'32-1','value':{'transportProbe':True}}
  n.guard();n.assert_actor(cid)
  proof['responseWrite']=helper.deliver_response(n,cid,'32-1.response.json',reply,remain)
  proof['responseConfirm']=n.execute(cid,['/opt/checker/bin/python','-c',"import json; assert json.load(open('/tmp/pipeline-mailbox/32-1.response.json'))=={'id':'32-1','value':{'transportProbe':True}};print('confirmed')"])
  assert n.text(proof['responseConfirm'])=='confirmed';proof['passed']=True
 except BaseException as e:proof['error']=type(e).__name__+':'+str(e);raise
 finally:
  proof['actorClosures']=[]
  actors=[row[0] for row in n.db.execute('SELECT cid FROM actor WHERE closed=0').fetchall()]
  if cid and cid not in actors:actors.append(cid)
  for owned in actors:
   try:
    removal,absence=n.remove(owned);proof['actorClosures'].append({'cid':owned,'removal':removal,'absence':absence})
   except BaseException as e:proof.setdefault('closureErrors',[]).append({'cid':owned,'error':str(e)})
  proof['closed']=not proof.get('closureErrors') and n.db.execute('SELECT COUNT(*) FROM actor WHERE closed=0').fetchone()[0]==0
  (output/'probe-proof.json').write_text(json.dumps(proof,indent=2))
