"""Actual owned upload path rejection, trusted staging, guest hash and execution."""
import argparse,http.server,json,os,sys,threading,pathlib,traceback,urllib.request,urllib.error,uuid
import _bench_original_owned_guard as guard
from docker_owned import OwnedDocker
from private_staging import stage_private_upload,tree
p=argparse.ArgumentParser();p.add_argument('--base-proof',required=True);p.add_argument('--output',required=True);a=p.parse_args();plan=json.loads(pathlib.Path(a.base_proof).read_bytes())['plan'];token=os.environ['OBJRUN_TB12_STAND_TOKEN']

def verify():
 out=pathlib.Path(plan['nativeOutput']);out.mkdir(parents=True);guard.guard();_bench_authorized_history('torch-pipeline-parallelism')
 native=OwnedDocker(out);cid=None;result={'complete':False,'modelCalls':0,'gradeCalls':0,'referenceCalls':0}
 try:
  cid,initial,create=native.create('neutral-private-staging',plan['baseImageId'],'/bin/sh',['-c','exec sleep infinity'],network='none',memory_mb=2048,cpus=1);native.start(cid)
  source=pathlib.Path(plan['neutralPrivateSource']);rejected=False
  try:native.upload(source,cid,'/tests')
  except AssertionError:rejected=True
  assert rejected,'old_upload_path_must_reject_real_fixture'
  staging=out/'grades'/uuid.uuid4().hex/'staging';staging.mkdir(parents=True)
  upload=stage_private_upload(native,source,cid,'/tests',staging)
  hashes={}
  for item in tree(source)['files']:
   receipt=native.execute(cid,['/usr/bin/sha256sum','/tests/'+item['path']]);assert native.text(receipt).split()[0]==item['sha256'];hashes[item['path']]=receipt
  ran=native.execute(cid,['/bin/sh','/tests/neutral.sh']);assert native.text(ran)=='neutral-private-staging-ok'
  # Unknown roots and incorrect grade output must remain rejected before upload.
  bad=False
  try:stage_private_upload(native,source,cid,'/inputs',staging)
  except AssertionError:bad=True
  assert bad
  result.update(complete=True,cid=cid,originalUploadRejected=True,unboundInputRejected=True,upload=upload,guestHashReceipts=hashes,neutralExecution=ran,sourceBeforeAfterEqual=True)
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
