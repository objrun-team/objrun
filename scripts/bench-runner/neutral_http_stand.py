"""Benign original Stand launcher protocol; no task, checker, engine or model."""
import argparse,http.server,json,os,sys,threading,pathlib,traceback
import infrastructure_acceptance
p=argparse.ArgumentParser();p.add_argument('--base-proof',required=True);p.add_argument('--output',required=True);a=p.parse_args()
plan=json.loads(pathlib.Path(a.base_proof).read_bytes())['plan'];token=os.environ['OBJRUN_TB12_STAND_TOKEN']
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  assert self.headers.get('X-ObjRun-Grader-Token')==token
  self.rfile.read(int(self.headers.get('Content-Length','0')))
  try:
   if self.path=='/up':
    sys.argv=[infrastructure_acceptance.__file__,a.base_proof,plan['nativeOutput']];infrastructure_acceptance.main();value={'complete':True,'modelCalls':0}
   elif self.path=='/close':value={'ownedContainersRemaining':0,'modelCalls':0}
   else:raise ValueError('neutral_route_not_allowed')
   self.send_response(200);self.end_headers();self.wfile.write(json.dumps(value).encode());self.wfile.flush()
   if self.path=='/close':threading.Thread(target=self.server.shutdown,daemon=True).start()
  except BaseException as e:
   traceback.print_exc(file=sys.stderr);self.send_response(500);self.end_headers();self.wfile.write(json.dumps({'error':str(e)}).encode())
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
print(json.dumps({'protocol':'tb12-stand-ready-v1','pid':os.getpid(),'port':server.server_port,'modelCalls':0}),flush=True)
server.serve_forever();server.server_close()
