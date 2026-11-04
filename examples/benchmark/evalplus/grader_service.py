import argparse,hashlib,json,pathlib,subprocess,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=pathlib.Path(__file__).resolve().parents[3]
ap=argparse.ArgumentParser();ap.add_argument('--dataset',choices=['humaneval','mbpp'],required=True);ap.add_argument('--port',type=int,required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=True)
executor='WSL Ubuntu Python venv (Docker forbidden)'
guard=threading.Semaphore(2);write_lock=threading.Lock()
def grade(tid,code,feedback=False,control=None):
    key=hashlib.sha256(json.dumps([tid,code,feedback,control]).encode()).hexdigest();cache=out/'cache'/key;cache.parent.mkdir(exist_ok=True)
    if cache.exists(): return json.loads(cache.read_text())
    req={'dataset':a.dataset,'task_id':tid,'code':code,'feedback_only':feedback,'control':control}
    with guard:
        try:
            r=subprocess.run(['/tmp/objrun-evalplus-20261012/venv/bin/python','-I',str(pathlib.Path(__file__).with_name('grade.py'))],input=json.dumps(req),capture_output=True,text=True,encoding='utf-8',timeout=170)
            v=json.loads(r.stdout.strip().splitlines()[-1]) if not r.returncode else {'valid':False,'passed':False,'errorType':'GraderProcessError','diagnostic':r.stderr[-500:]}
        except subprocess.TimeoutExpired: v={'valid':False,'passed':False,'errorType':'GraderServiceTimeout'}
        except Exception as e: v={'valid':False,'passed':False,'errorType':type(e).__name__,'diagnostic':str(e)[:500]}
    if v.get('valid'): cache.write_text(json.dumps(v))
    with write_lock:
        with (out/'grader.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps({'at':time.time(),'task_id':tid,'candidateSha256':hashlib.sha256(code.encode()).hexdigest(),'feedbackOnly':feedback,'control':control,'verdict':v})+'\n')
    return v
class H(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,v,status=200):
        b=json.dumps(v).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self): self.send({'ok':True,'dataset':a.dataset,'executor':executor})
    def do_POST(self):
        try:
            q=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path=='/grade': v=grade(q['task_id'],q['code'],q.get('feedback_only',False),q.get('control'));self.send(v);return
            inp=q['input'];task=inp['task'];tid=str(task['id']).split('/')[-2:];tid='/'.join(tid)
            value=inp.get('result',task.get('result',''));text=value.get('body','') if isinstance(value,dict) else value
            import ast
            import re
            def extract(text):
                m=re.search(r'```(?:python|py)?\s*\n(.*?)```',text,re.S)
                return (m.group(1) if m else text).strip()
            if self.path=='/parsed':
                try: ast.parse(extract(text));self.send(True)
                except SyntaxError: self.send({'value':False,'note':'Python syntax error'})
                return
            v=grade(tid,text,True)
            if not v.get('valid'): self.send({'valid':False,'error':v.get('errorType')},503)
            else: self.send({'value':bool(v['passed']),'note':v.get('feedback','')})
        except Exception as e: self.send({'valid':False,'error':type(e).__name__,'diagnostic':str(e)[:300]},503)
print(json.dumps({'ready':True,'dataset':a.dataset,'port':a.port}),flush=True)
ThreadingHTTPServer(('127.0.0.1',a.port),H).serve_forever()
