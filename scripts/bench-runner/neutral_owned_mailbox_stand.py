"""Actual checker exit/mailbox lifecycle race; no checker or benchmark is executed."""
import argparse,http.server,json,os,sys,threading,pathlib,traceback,urllib.request,urllib.error,time
from concurrent.futures import ThreadPoolExecutor
import _bench_original_owned_guard as guard
from docker_owned import OwnedDocker
from mailbox_transport import capture_request,deliver_response
p=argparse.ArgumentParser();p.add_argument('--base-proof',required=True);p.add_argument('--output',required=True);a=p.parse_args();plan=json.loads(pathlib.Path(a.base_proof).read_bytes())['plan'];token=os.environ['OBJRUN_TB12_STAND_TOKEN']
def verify():
 out=pathlib.Path(plan['nativeOutput']);out.mkdir(parents=True);guard.guard();_bench_authorized_history('torch-pipeline-parallelism')
 native=OwnedDocker(out);cid=None;result={'complete':False,'modelCalls':0,'gradeCalls':0,'referenceCalls':0}
 def remain():return max(.001,300-(time.monotonic()-started))
 started=time.monotonic()
 try:
  cid,initial,create=native.create('neutral-mailbox-checker',plan['baseImageId'],'/bin/sh',['-c',"mkdir -p /tmp/pipeline-mailbox; printf '%s' '{\"id\":\"1-1\",\"operation\":\"pipeline\",\"arguments\":{}}' > /tmp/pipeline-mailbox/1-1.request.json; sleep 5; printf '%s\\n' 'NEUTRAL_FINAL:complete'"],network='none',memory_mb=8192,cpus=1,readonly=True,readonly_scratch_bytes=2*1024**3)
  with ThreadPoolExecutor(max_workers=1) as pool:
   future=pool.submit(native.start,cid,True,60)
   while not native.assert_actor(cid)['State']['Running']:
    assert not future.done();time.sleep(.05)
   refused=False
   try:capture_request(native,cid,'1-1.request.json',out,remain)
   except RuntimeError:refused=True
   assert refused and native.assert_actor(cid)['State']['Running']
   listing=native.execute(cid,['find','/tmp/pipeline-mailbox','-maxdepth','1','-type','f','-name','*.request.json','-printf','%f\\n']);assert native.text(listing)=='1-1.request.json'
   # The exact original race: listing sees the request, then PID1 naturally exits.
   receipt=future.result();final=native.assert_actor(cid);assert final['State']['Status']=='exited' and final['State']['ExitCode']==0 and receipt['exitCode']==0 and receipt['closeObserved'];assert native.text(receipt)=='NEUTRAL_FINAL:complete'
  request,read=capture_request(native,cid,'1-1.request.json',out,remain);assert request is None and read['exitCode']==1 and read['mailboxTerminalObservation']['noReplyFabricated']
  write=deliver_response(native,cid,'1-1.response.json',{'id':'1-1','value':None},remain);assert write['exitCode']==1 and write['mailboxTerminalObservation']['requiresOriginalFinalFrame']
  result.update(complete=True,cid=cid,liveExecutionErrorPreserved=refused,lateRead=read,lateWrite=write,originalLifecycleState=final,originalFinalFrameReceipt=receipt,preExitMailboxListing=listing)
 finally:
  if cid:
   native.remove(cid)
   try:urllib.request.urlopen(os.environ['DOCKER_HOST'].replace('tcp:','http:')+'/containers/'+cid+'/json',timeout=5);raise AssertionError('actor_still_present')
   except urllib.error.HTTPError as error:assert error.code==404
   result.update(actorClosed=True,currentActorStatus=404)
  (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 return result
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  assert self.headers.get('X-ObjRun-Grader-Token')==token;self.rfile.read(int(self.headers.get('Content-Length','0')))
  try:
   value=verify() if self.path=='/up' else {'ownedContainersRemaining':0,'allExactOwnedActorsAbsent':True};assert self.path in ('/up','/close');self.send_response(200);self.end_headers();self.wfile.write(json.dumps(value).encode());self.wfile.flush()
   if self.path=='/close':threading.Thread(target=self.server.shutdown,daemon=True).start()
  except BaseException as error:traceback.print_exc(file=sys.stderr);self.send_response(500);self.end_headers();self.wfile.write(json.dumps({'error':str(error)}).encode())
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);print(json.dumps({'protocol':'tb12-stand-ready-v1','pid':os.getpid(),'port':server.server_port,'modelCalls':0}),flush=True);server.serve_forever();server.server_close()
