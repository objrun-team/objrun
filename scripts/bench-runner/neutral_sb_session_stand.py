"""Zero-model formal launcher -> explicit Bun -> original SB session boundary."""
import argparse,http.server,json,os,pathlib,threading,traceback,sys,time
import _bench_original_owned_guard as guard
from native_process import capture,pin
p=argparse.ArgumentParser();p.add_argument('--base-proof',required=True);p.add_argument('--output',required=True);a=p.parse_args();plan_path=pathlib.Path(a.base_proof);plan=json.loads(plan_path.read_bytes())['plan'];token=os.environ['OBJRUN_TB12_STAND_TOKEN']
def check(value):
 actual=pin(value['path']);assert actual['bytes']==value['bytes'] and actual['sha256']==value['sha256'];return value['path']
def verify():
 guard.require_lease(8192,3221225472,'skillsbench',1);_bench_authorized_history('spring-boot-jakarta-migration')
 out=pathlib.Path(plan['nativeOutput']);out.mkdir(parents=True)
 deadline=int(os.environ['NOVAEVE_INFRASTRUCTURE_DEADLINE_MS']);assert deadline>time.time()*1000
 argv=[check(plan['sessionBunPin']),check(plan['sessionEntryPin']),str(plan_path),pin(plan_path)['sha256'],str(out/'session')]
 row=capture(argv,out/'session-process',max(.001,(deadline-time.time()*1000)/1000),env=dict(os.environ),cwd=plan['root'])
 assert row['closeObserved'] and row['exitCode']==0 and not row['error'] and not row['timedOut'],'actual_session_child_failed'
 session=json.loads((out/'session/result.json').read_bytes());assert session['complete'] and session['closure']['resourceReleasePermitted']
 result={'complete':True,'actorClosed':True,'sessionResultPin':pin(out/'session/result.json'),'actualSessionProcess':row,'modelCalls':0,'gradeCalls':0,'referenceCalls':0,'formalReady':False,'scope':'Shared single-task SB resource/admission/cash/explicit child lifecycle only'}
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');return result
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  assert self.headers.get('X-ObjRun-Grader-Token')==token;self.rfile.read(int(self.headers.get('Content-Length','0')))
  try:
   assert self.path in ('/up','/close')
   value=verify() if self.path=='/up' else {'ownedContainersRemaining':0}
   self.send_response(200);self.end_headers();self.wfile.write(json.dumps(value).encode());self.wfile.flush()
   if self.path=='/close':threading.Thread(target=self.server.shutdown,daemon=True).start()
  except BaseException as error:
   traceback.print_exc(file=sys.stderr);self.send_response(500);self.end_headers();self.wfile.write(json.dumps({'error':str(error)}).encode())
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);print(json.dumps({'protocol':'tb12-stand-ready-v1','pid':os.getpid(),'port':server.server_port,'modelCalls':0}),flush=True);server.serve_forever();server.server_close()
