"""Actual original route and concurrent HTTP delivery, using only a neutral container fixture."""
import argparse,http.server,json,os,sys,threading,pathlib,traceback,time,uuid,copy,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor
import _bench_original_owned_guard as guard
from docker_owned import OwnedDocker
import stand_v1
p=argparse.ArgumentParser();p.add_argument('--base-proof',required=True);p.add_argument('--output',required=True);a=p.parse_args();plan=json.loads(pathlib.Path(a.base_proof).read_bytes())['plan'];token=os.environ['OBJRUN_TB12_STAND_TOKEN']

def verify():
 out=pathlib.Path(plan['nativeOutput']);out.mkdir(parents=True);guard.guard();_bench_authorized_history('torch-pipeline-parallelism')
 native=OwnedDocker(out/'owned');cid=None;server=None;server_thread=None;result={'complete':False,'modelCalls':0,'gradeCalls':0,'referenceCalls':0}
 fixture_started=threading.Event();callback_receipts=[]
 class NeutralStand(stand_v1.Stand):
  def grade(self,owner,place,label):
   fixture_started.set()
   receipt=native.execute(owner['cid'],['/bin/sh','-c','sleep 1; printf neutral-delivery-callback'])
   assert native.text(receipt)=='neutral-delivery-callback'
   callback_receipts.append(receipt);owner['grades']+=1
   record={'invocationId':uuid.uuid4().hex,'policyReward':int(len(callback_receipts)==2),'neutralProtocolFixtureOnly':True,'benchmarkGradingInvocations':0}
   self.rows.append({'kind':'neutral-protocol-callback','place':place,'record':record,'receipt':receipt});self.persist();return record
 try:
  cid,initial,created=native.create('neutral-grade-delivery',plan['baseImageId'],'/bin/sh',['-c','sleep 180'],network='none',memory_mb=8192,cpus=1,readonly=False,readonly_scratch_bytes=2*1024**3);native.start(cid)
  stand=NeutralStand.__new__(NeutralStand);stand.output=out/'original-route';stand.output.mkdir();stand.native=native;stand.rows=[];stand.fatal=None;stand.gate=threading.RLock()
  place='tb12:neutral/grade-delivery';attempt='tb12-neutral-grade-delivery'
  owner={'cid':cid,'taskId':'torch-pipeline-parallelism','attemptId':attempt,'arm':'F','created':time.monotonic(),'deadline':time.monotonic()+180,'sealed':False,'lock':threading.RLock(),'pendingGrade':None,'grades':0}
  stand.places={place:owner};stand.tasks={'torch-pipeline-parallelism':{'verifierSeconds':900}}
  http_rows=[];http_lock=threading.RLock()
  class ProtocolHandler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    assert self.headers.get('X-ObjRun-Grader-Token')==token
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));started=time.monotonic()
    try:value=stand.route(self.path,body);status=200
    except BaseException as error:value={'type':type(error).__name__,'error':str(error)};status=503
    with http_lock:http_rows.append({'path':self.path,'status':status,'body':body,'value':value,'elapsedSeconds':time.monotonic()-started})
    self.send_response(status);self.end_headers();self.wfile.write(json.dumps(value).encode());self.wfile.flush()
  server=http.server.ThreadingHTTPServer(('127.0.0.1',0),ProtocolHandler);server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start();origin='http://127.0.0.1:'+str(server.server_port)
  def call(path,body,expected=200):
   request=urllib.request.Request(origin+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-ObjRun-Grader-Token':token})
   try:
    with urllib.request.urlopen(request,timeout=30) as response:value=json.load(response);assert response.status==expected;return value
   except urllib.error.HTTPError as error:assert error.code==expected;return json.load(error)
  body={'node':'ran','moment':'done','domain':'bool','input':{'task':{'id':attempt,'place':place},'result':{'kind':'prompt','body':'neutral exact candidate label'}},'feed':[]}
  with ThreadPoolExecutor(max_workers=4) as pool:
   first=pool.submit(call,'/ran',copy.deepcopy(body));assert fixture_started.wait(10)
   duplicate=pool.submit(call,'/ran',copy.deepcopy(body))
   limit=time.monotonic()+10
   while not any(row['kind']=='ran-coalesced' for row in stand.rows) and time.monotonic()<limit:time.sleep(.01)
   assert any(row['kind']=='ran-coalesced' for row in stand.rows)
   assert first.result()==duplicate.result()=={'value':True}
  assert len(callback_receipts)==1 and owner['pendingGrade'] is not None
  mismatched=copy.deepcopy(body);mismatched['input']['result']['body']='different label'
  assert call('/ran',mismatched,503)['error']=='Previous grade invocation not consumed'
  wrong_owner=copy.deepcopy(body);wrong_owner['input']['task']['id']='tb12-wrong-owner'
  assert call('/ran',wrong_owner,503)['error']=='Grader attempt mismatch'
  passed=copy.deepcopy(body);passed['node']='passed';passed['feed']=[{'from':'ran','out':0,'value':True}]
  wrong_feed=copy.deepcopy(passed);wrong_feed['feed'][0]['value']=False
  assert call('/passed',wrong_feed,503)['type']=='AssertionError';assert owner['pendingGrade'] is not None
  with ThreadPoolExecutor(max_workers=2) as pool:
   one=pool.submit(call,'/passed',copy.deepcopy(passed));two=pool.submit(call,'/passed',copy.deepcopy(passed));one=one.result();two=two.result();assert one==two and one['value'] is False
  assert owner['pendingGrade'] is None and len(callback_receipts)==1
  assert call('/passed',passed,503)['error']=='Missing exact /ran binding'
  # A new call after both registered deliveries finish is an independent fixture callback.
  assert call('/ran',body)=={'value':True};assert len(callback_receipts)==2
  assert call('/passed',passed)=={'value':True};assert owner['pendingGrade'] is None
  consumed=[x for x in stand.rows if x['kind']=='grade-original-consumed-once'];coalesced=[x for x in stand.rows if x['kind']=='passed-coalesced-delivered']
  assert len(consumed)==2 and len(coalesced)==1 and len({x['invocationId'] for x in consumed})==2
  assert call('/stop',{'place':place})['exactCidAbsent'];cid_removed=cid
  assert call('/close',{})['allExactOwnedActorsAbsent']
  result.update(complete=True,cid=cid_removed,actualOriginalRoutePin=plan['originalStandPin'],actualOriginalAssertionsPreserved=True,httpInvocations=http_rows,rows=stand.rows,neutralProtocolCallbackCount=2,benchmarkGradingInvocations=0,actualFixtureCallbacks=callback_receipts,originalGradeConsumptions=consumed,coalescedPassedDeliveries=coalesced,negativeCasesRejected=['different-label','wrong-attempt','wrong-feed','no-pending'],scope='Concurrent exact invocation delivery only; neutral callback decisions are not Benchmark grading or restored formal generation')
 finally:
  if server:server.shutdown();server.server_close();server_thread.join(timeout=10);assert not server_thread.is_alive()
  if cid:
   if any(row[0]==cid for row in native.open_actors()):native.remove(cid)
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
