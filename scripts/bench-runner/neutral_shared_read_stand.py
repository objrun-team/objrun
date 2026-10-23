"""Changes-only real shared-file read acceptance under the formal Stand launcher."""
import argparse,http.server,json,os,sys,threading,pathlib,traceback,ctypes,time
from ctypes import wintypes
import _bench_original_owned_guard as guard
p=argparse.ArgumentParser();p.add_argument('--base-proof',required=True);p.add_argument('--output',required=True);a=p.parse_args();plan=json.loads(pathlib.Path(a.base_proof).read_bytes())['plan'];token=os.environ['OBJRUN_TB12_STAND_TOKEN']
def verify():
 out=pathlib.Path(plan['nativeOutput']);out.mkdir(parents=True)
 guard.guard();fixture=out/'exclusive-fixture.json';fixture.write_text('{"actual":true}')
 k=ctypes.WinDLL('kernel32',use_last_error=True);k.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];k.CreateFileW.restype=wintypes.HANDLE;k.CloseHandle.argtypes=[wintypes.HANDLE]
 handle=k.CreateFileW(str(fixture),0x80000000,0,None,3,0x80,None);assert handle not in (None,ctypes.c_void_p(-1).value)
 refused=False
 try:fixture.read_bytes()
 except PermissionError:refused=True
 assert refused,'real_exclusive_handle_must_refuse_old_read'
 timer=threading.Timer(.075,lambda:k.CloseHandle(handle));timer.start();start=time.monotonic();actual=guard.read_shared_json(fixture);elapsed=time.monotonic()-start;timer.join();assert actual=={'actual':True} and .05<=elapsed<.3
 observation=guard.read(guard.HOME/'broker/remote-disk.json');assert 0<=time.time()*1000-observation['observedAtMs']<=10000 and observation['freeBytes']>=5*1024**3
 result={'complete':True,'actorClosed':True,'newActors':0,'modelCalls':0,'gradeCalls':0,'referenceCalls':0,'actualOldReadPermissionDenied':refused,'retryElapsedSeconds':elapsed,'freshActualObservation':observation,'noStaleFallback':True}
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');return result
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  assert self.headers.get('X-ObjRun-Grader-Token')==token;self.rfile.read(int(self.headers.get('Content-Length','0')))
  try:
   value=verify() if self.path=='/up' else {'ownedContainersRemaining':0};assert self.path in ('/up','/close');self.send_response(200);self.end_headers();self.wfile.write(json.dumps(value).encode());self.wfile.flush()
   if self.path=='/close':threading.Thread(target=self.server.shutdown,daemon=True).start()
  except BaseException as e:traceback.print_exc(file=sys.stderr);self.send_response(500);self.end_headers();self.wfile.write(json.dumps({'error':str(e)}).encode())
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);print(json.dumps({'protocol':'tb12-stand-ready-v1','pid':os.getpid(),'port':server.server_port,'modelCalls':0}),flush=True);server.serve_forever();server.server_close()
