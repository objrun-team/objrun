import sys,os,json,hashlib,base64,importlib.util,uuid
from pathlib import Path
ROOT=Path('F:/git/TgEngin-handoff-2026-10-07/TgEngin');HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'scripts/benchmark-campaign/full-f/novaeve_formal_v1/group-04/adapter_1'))
spec=importlib.util.spec_from_file_location('activation_guard',ROOT/'scripts/benchmark-campaign/full-f/novaeve_formal_v1/broker/adopted_owner_guard_v81.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard);sys.modules['activation_guard']=guard
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
  request=b'{"protocol":"pipeline-mailbox-tiny-probe","id":"known-request","values":[1,2,3]}\n'
  guest="import os;os.makedirs('/tmp/pipeline-mailbox',exist_ok=True);open('/tmp/pipeline-mailbox/request.json','wb').write("+repr(request)+")"
  proof['guestWrite']=n.execute(cid,['python3','-c',guest])
  proof['find']=n.execute(cid,['find','/tmp/pipeline-mailbox','-maxdepth','1','-type','f'])
  cp=n.command(['cp',cid+':/tmp/pipeline-mailbox/request.json',str(output/'old-cp-request.json')]);proof['oldCp']=cp
  p=output/'old-cp-request.json';proof['oldCpMatches']=p.is_file() and p.read_bytes()==request
  readcode="import os,json,stat,hashlib,base64; p='/tmp/pipeline-mailbox/request.json'; fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW); a=os.fstat(fd); assert stat.S_ISREG(a.st_mode) and a.st_size<=4096; b=os.read(fd,4097); z=os.fstat(fd); os.close(fd); assert len(b)==a.st_size and (a.st_ino,a.st_dev,a.st_size,a.st_mtime_ns)==(z.st_ino,z.st_dev,z.st_size,z.st_mtime_ns); json.loads(b); print(json.dumps({'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'base64':base64.b64encode(b).decode()}))"
  proof['inNamespaceRead']=n.execute(cid,['python3','-c',readcode]);payload=json.loads(n.text(proof['inNamespaceRead']));actual=base64.b64decode(payload['base64'],validate=True);assert actual==request and payload['sha256']==hashlib.sha256(actual).hexdigest();(output/'request-reconstructed.json').write_bytes(actual);proof['requestPin']=pin(output/'request-reconstructed.json')
  response=b'{"protocol":"pipeline-mailbox-tiny-probe","id":"known-request","ok":true}\n'
  writecode="import os,sys,json; p='/tmp/pipeline-mailbox/response.json'; b=sys.stdin.buffer.read(4097); assert len(b)<=4096; json.loads(b); t=p+'.atomic'; fd=os.open(t,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600); os.write(fd,b); os.fsync(fd); os.close(fd); os.replace(t,p); d=os.open('/tmp/pipeline-mailbox',os.O_RDONLY|os.O_DIRECTORY); os.fsync(d); os.close(d)"
  proof['responseWrite']=n.command(['exec','-i',cid,'python3','-c',writecode],stdin=response)
  proof['responseConfirm']=n.execute(cid,['python3','-c',"import json; assert json.load(open('/tmp/pipeline-mailbox/response.json'))=={'protocol':'pipeline-mailbox-tiny-probe','id':'known-request','ok':True};print('confirmed')"]);assert n.text(proof['responseConfirm'])=='confirmed';proof['passed']=True
 except BaseException as e:proof['error']=type(e).__name__+':'+str(e);raise
 finally:
  if cid:
   try:proof['removal'],proof['absence']=n.remove(cid);proof['closed']=True
   except BaseException as e:proof['closureError']=str(e)
  (output/'probe-proof.json').write_text(json.dumps(proof,indent=2))
