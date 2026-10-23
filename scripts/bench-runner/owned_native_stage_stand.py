"""The shared formal-parent HTTP boundary for a pinned original native stage."""
import argparse,http.server,json,os,pathlib,sys,threading,traceback
from owned_native_stage import run_stage
p=argparse.ArgumentParser();p.add_argument('--base-proof',required=True);p.add_argument('--output',required=True);a=p.parse_args()
plan=json.loads(pathlib.Path(a.base_proof).read_bytes())['plan'];token=os.environ['OBJRUN_TB12_STAND_TOKEN'];result=None
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  global result
  assert self.headers.get('X-ObjRun-Grader-Token')==token;self.rfile.read(int(self.headers.get('Content-Length','0')))
  try:
   if self.path=='/up':
    assert result is None
    out=pathlib.Path(plan['nativeOutput']);out.mkdir(parents=True,exist_ok=False)
    result=run_stage(plan,out/'stage');(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');value=result
   else:
    assert self.path=='/close' and result is not None and result['actorClosed']
    value={'ownedContainersRemaining':0,'allExactOwnedActorsAbsent':True}
   self.send_response(200);self.end_headers();self.wfile.write(json.dumps(value).encode());self.wfile.flush()
   if self.path=='/close':threading.Thread(target=self.server.shutdown,daemon=True).start()
  except BaseException as error:
   traceback.print_exc(file=sys.stderr);self.send_response(500);self.end_headers();self.wfile.write(json.dumps({'error':str(error)}).encode())
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);print(json.dumps({'protocol':'tb12-stand-ready-v1','pid':os.getpid(),'port':server.server_port,'modelCalls':0}),flush=True);server.serve_forever();server.server_close()
