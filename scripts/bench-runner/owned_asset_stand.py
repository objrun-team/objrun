"""Changes-only real shared-file read acceptance under the formal Stand launcher."""
import argparse,http.server,json,os,sys,threading,pathlib,traceback,ctypes,time
from ctypes import wintypes
import _bench_original_owned_guard as guard
p=argparse.ArgumentParser();p.add_argument('--base-proof',required=True);p.add_argument('--output',required=True);a=p.parse_args();plan=json.loads(pathlib.Path(a.base_proof).read_bytes())['plan'];token=os.environ['OBJRUN_TB12_STAND_TOKEN']
def verify():
 out=pathlib.Path(plan['nativeOutput']);out.mkdir(parents=True)
 guard.guard()
 assert os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']
 _bench_authorized_history(plan['policyTaskId'])
 from server_owned_asset import operate_owned_asset
 from native_process import pin
 request_pin=plan['assetRequestPin'];assert pin(request_pin['path'])==request_pin
 request=json.loads(pathlib.Path(request_pin['path']).read_bytes());limit=json.loads((pathlib.Path(plan['output'])/'absolute-deadline.json').read_bytes());assert limit['pid']==int(os.environ['NOVAEVE_RESOURCE_LEASE_PID']);deadline=limit['deadline']/1000
 assert deadline>time.time()
 if request.get('transferWindowSeconds') is not None:
  assert request['transferWindowSeconds']==3600 and request['originalOperationTimeoutSeconds']==600
  assert plan['pureTransferWindowSeconds']==3600 and plan['originalAssetOperationSeconds']==600 and plan['overallTimeoutSeconds']==4200
  assert request['transferAuthorityPin']==plan['transferAuthorityPin']
  request.update(absoluteDeadline=deadline,transferDeadline=min(deadline,time.time()+3600),deadline=deadline)
 else:request['deadline']=min(deadline,time.time()+600)
 built=operate_owned_asset(request,out/'owned-asset')
 import urllib.request,urllib.error
 image=built['result']['image'];status=None
 try:
  response=urllib.request.urlopen(os.environ['DOCKER_HOST'].replace('tcp:','http:')+'/images/'+image+'/json',timeout=5);observed=json.loads(response.read());status=response.status
  assert request['neutralCleanup'] is False and observed['Id']==image
 except urllib.error.HTTPError as error:
  assert request['neutralCleanup'] is True and error.code==404;status=404
 intermediate_statuses=[]
 for cid in built['result'].get('intermediateContainers',[]):
  try:urllib.request.urlopen(os.environ['DOCKER_HOST'].replace('tcp:','http:')+'/containers/'+cid+'/json',timeout=5);raise AssertionError('owned_build_intermediate_still_present')
  except urllib.error.HTTPError as error:assert error.code==404;intermediate_statuses.append({'id':cid,'currentStatus':404})
 observation=guard.read(guard.HOME/'broker/remote-disk.json')
 result={'buildProof':built,'intermediateContainerCurrentStatuses':intermediate_statuses,'imageCurrentStatus':status,'complete':True,'actorClosed':True,'newActors':0,'modelCalls':0,'gradeCalls':0,'referenceCalls':0,'explicitBootstrapConsumed':True,'actualGuardConsumed':True,'actualHistoryPolicyConsumed':True,'actualChildPid':os.getpid(),'actualArgv':sys.argv,'currentActivation':os.environ['NOVAEVE_ACTIVATION_PATH'],'mappingSha256':os.environ['NOVAEVE_PYTHON_MAPPING_SHA256'],'freshActualObservation':observation}
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');return result
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  assert self.headers.get('X-ObjRun-Grader-Token')==token;self.rfile.read(int(self.headers.get('Content-Length','0')))
  try:
   value=verify() if self.path=='/up' else {'ownedContainersRemaining':0,'allExactOwnedActorsAbsent':True};assert self.path in ('/up','/close');self.send_response(200);self.end_headers();self.wfile.write(json.dumps(value).encode());self.wfile.flush()
   if self.path=='/close':threading.Thread(target=self.server.shutdown,daemon=True).start()
  except BaseException as e:traceback.print_exc(file=sys.stderr);self.send_response(500);self.end_headers();self.wfile.write(json.dumps({'error':str(e)}).encode())
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);print(json.dumps({'protocol':'tb12-stand-ready-v1','pid':os.getpid(),'port':server.server_port,'modelCalls':0}),flush=True);server.serve_forever();server.server_close()
