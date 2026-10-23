"""Exercise the original SkillsBench stand/child/cache boundary without task content."""
import argparse,http.server,json,os,pathlib,socket,sys,threading,time,traceback,urllib.request,urllib.error,uuid
from concurrent.futures import ThreadPoolExecutor
import _bench_original_owned_guard as guard
from skillsbench_original_stand import Stand
from bounded_native import run
from transport import ENV
from native_process import pin

p=argparse.ArgumentParser();p.add_argument('--base-proof',required=True);p.add_argument('--output',required=True);a=p.parse_args();plan=json.loads(pathlib.Path(a.base_proof).read_bytes())['plan'];token=os.environ['OBJRUN_TB12_STAND_TOKEN']
def verify():
 out=pathlib.Path(plan['nativeOutput']);out.mkdir(parents=True);guard.require_lease(8192,3221225472,'skillsbench',1);_bench_authorized_history('spring-boot-jakarta-migration')
 owner=int(os.environ['NOVAEVE_RESOURCE_LEASE_PID']);assert owner==int(os.environ['NOVAEVE_RESOURCE_PARENT_PID']);os.environ['TGENGIN_GRADER_TOKEN']=token;ENV['TGENGIN_GRADER_TOKEN']=token
 config={'output':str(out/'original-stand'),'runId':plan['neutralRunId'],'schedule':[],'taskReadiness':{},'resourceOwnerPid':owner}
 original=Stand(config);assert ENV['NOVAEVE_RESOURCE_OWNER_PID']==str(owner);cid=None;result={'complete':False,'actorClosed':False,'modelCalls':0,'gradeCalls':0,'referenceCalls':0}
 try:
  nonce=uuid.uuid4().hex;labels={'objrun.skb.role':'full-f-solver','objrun.skb.nonce':nonce}
  argv=['create','--network','none','--memory','4096m','--cpus','1',*[x for k,v in labels.items() for x in ['--label',k+'='+v]],plan['baseImageId'],'/bin/sh','-c','while :; do sleep 1; done']
  cid=original.command(argv).decode().strip();assert len(cid)==64;original.current={'cid':cid};original.command(['start',cid]);original.command(['exec',cid,'mkdir','-p','/rt-lib'])
  mapping=json.loads(pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']).read_bytes());cache=mapping['skillsbenchCacheEntryPin'];copies=[]
  for index,asset in enumerate(mapping['skillsbenchRuntimeCopy']['assets']):
   request=out/('copy-request-'+str(index)+'.json');request.write_text(json.dumps({'source':asset['sourcePin']['path'],'sourcePin':asset['sourcePin'],'cid':cid,'destination':asset['destination'],'expectedLabels':labels,'receiptDirectory':str(out/'runtime-cache'),'leasePid':owner}))
   stdout=out/('copy-'+str(index)+'.stdout');copied=run([sys.executable,'-B',cache['path'],str(request)],ENV,stdout,out/('copy-'+str(index)+'.stderr'),180);assert copied['exitCode']==0 and not copied['faults'] and copied['windowsJobTreeClosed'];copy_result=json.loads(stdout.read_bytes());assert copy_result['result']['guestSha256']==asset['sourcePin']['sha256']
   guest=original.command(['exec',cid,'sha256sum',asset['destination']]).decode().split()[0];assert guest==asset['sourcePin']['sha256'];copies.append({'child':copied,'result':copy_result,'guestSha256':guest})
  original.command(['exec',cid,'chmod','+x','/rt-node'])
  node=next(x for x in mapping['skillsbenchRuntimeCopy']['assets'] if x['sourcePin']['bytes']>100*1024**2);version=original.command(['exec','-e','LD_LIBRARY_PATH=/rt-lib',cid,node['destination'],'--version']).decode().strip();assert version=='v22.22.2'
  # The actual original HTTP entry is a separately bootstrapped child. Empty
  # readiness exercises transport/lease/health/shutdown, never task creation.
  child_config=out/'stand-config.json';child_config.write_text(json.dumps({**config,'output':str(out/'http-stand')}));sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();origin='http://127.0.0.1:'+str(port)
  with ThreadPoolExecutor(max_workers=1) as pool:
   future=pool.submit(run,[sys.executable,'-B',mapping['skillsbenchStandPin']['path'],'--config',str(child_config),'--port',str(port)],ENV,out/'http.stdout',out/'http.stderr',60)
   deadline=time.monotonic()+30;health=None
   while time.monotonic()<deadline:
    if future.done():break
    try:
     health=json.loads(urllib.request.urlopen(origin+'/health',timeout=1).read());break
    except (urllib.error.URLError,TimeoutError):time.sleep(.1)
   assert health and health['protocol']=='skillsbench-full-f-data-stand-v1' and health['readyTaskIds']==[]
   req=urllib.request.Request(origin+'/shutdown',data=b'{}',headers={'X-ObjRun-Grader-Token':token,'Content-Type':'application/json'},method='POST');shutdown=json.loads(urllib.request.urlopen(req,timeout=10).read());child=future.result();assert health['pid']==child['pid'] and shutdown['ownedContainersRemaining']==0 and child['exitCode']==0 and not child['faults'] and child['windowsJobTreeClosed']
  result.update(complete=True,cid=cid,runtimeCopies=copies,nodeVersion=version,actualHttpChild=child,health=health,shutdown=shutdown)
 finally:
  if cid:
   closure=original.stop()
   try:urllib.request.urlopen(os.environ['DOCKER_HOST'].replace('tcp:','http:')+'/containers/'+cid+'/json',timeout=5);raise AssertionError('actor_still_present')
   except urllib.error.HTTPError as e:assert e.code==404
   result.update(actorClosed=True,currentActorStatus=404,originalClosure=closure)
  (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 return result
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  assert self.headers.get('X-ObjRun-Grader-Token')==token;self.rfile.read(int(self.headers.get('Content-Length','0')))
  try:
   value=verify() if self.path=='/up' else {'ownedContainersRemaining':0,'allExactOwnedActorsAbsent':True};assert self.path in ('/up','/close');self.send_response(200);self.end_headers();self.wfile.write(json.dumps(value).encode());self.wfile.flush()
   if self.path=='/close':threading.Thread(target=self.server.shutdown,daemon=True).start()
  except BaseException as e:traceback.print_exc(file=sys.stderr);self.send_response(500);self.end_headers();self.wfile.write(json.dumps({'error':str(e)}).encode())
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);print(json.dumps({'protocol':'tb12-stand-ready-v1','pid':os.getpid(),'port':server.server_port,'modelCalls':0}),flush=True);server.serve_forever();server.server_close()
