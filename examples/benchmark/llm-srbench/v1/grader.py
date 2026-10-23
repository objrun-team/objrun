"""Private asynchronous train fitting station; final data is read only after freeze."""
import concurrent.futures,hashlib,json,os,pathlib,signal,subprocess,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'outputs';CFG=json.loads((ROOT/'package/experiment.json').read_text())
POOL=concurrent.futures.ThreadPoolExecutor(max_workers=2);LOCK=threading.RLock();JOBS={}
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.tmp-'+str(threading.get_ident()));t.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n');t.replace(p)
def parse(answer):
    t=answer.strip()
    if t.startswith('```'):t=t.split('\n',1)[1].rsplit('```',1)[0].strip()
    q=json.loads(t)
    if not isinstance(q,dict) or not set(q)<= {'expression','initial'} or not isinstance(q.get('expression'),str):raise ValueError('CandidateSchema')
    return q
def worker(q):
    env={'PATH':str(ROOT/'runtime/bin')+':/usr/bin:/bin','PYTHONUTF8':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','HOME':'/tmp'}
    p=subprocess.Popen(['unshare','--net',str(ROOT/'runtime/bin/python'),str(ROOT/'package/fit_worker.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,cwd='/tmp',start_new_session=True)
    started=time.monotonic()
    try:
        out,err=p.communicate(json.dumps(q).encode(),timeout=q.get('cpuSeconds',30)+30)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid,signal.SIGKILL);p.wait();return {'valid':False,'passed':False,'errorType':'WorkerWallTimeout','pid':p.pid}
    finally:
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    if p.returncode:
        return {'valid':p.returncode==-signal.SIGXCPU,'passed':False,'errorType':'CandidateCPUTimeout' if p.returncode==-signal.SIGXCPU else 'WorkerProcessFault','exitCode':p.returncode,'diagnostic':err.decode(errors='replace')[-1000:]}
    try:r=json.loads(out)
    except Exception:return {'valid':False,'passed':False,'errorType':'WorkerProtocol','diagnostic':err.decode(errors='replace')[-1000:]}
    r.update(wallSeconds=time.monotonic()-started,workerPid=p.pid);return r
def fit(key,answer):
    digest=hashlib.sha256((key+'\0'+answer+'\0'+CFG['environmentTag']).encode()).hexdigest();p=OUT/'fits'/digest/'fit.json'
    if p.exists():return json.loads(p.read_text())
    try:q=parse(answer)
    except (ValueError,KeyError,TypeError):r={'valid':True,'passed':False,'errorType':'CandidateFormat'}
    else:r=worker({**q,'data':str(ROOT/'data/public'/(key+'.npz')),'cpuSeconds':30})
    r.update(candidateSha256=hashlib.sha256(answer.encode()).hexdigest(),cacheKey=digest,key=key)
    if r['valid']:save(p,r)
    return r
def project(r,arm):
    if not r.get('valid'):raise RuntimeError('GraderInfrastructureFault:'+r.get('errorType','unknown'))
    passed=bool(r['passed'])
    if arm=='binary':return {'value':passed}
    return {'value':passed,'note':json.dumps({k:r[k] for k in ('nmse','finiteCoverage','errorType') if k in r},separators=(',',':')) if not passed else ''}
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def reply(self,v,status=200):
        b=json.dumps(v,ensure_ascii=False,allow_nan=False).encode();self.send_response(status);self.send_header('Content-Length',str(len(b)));self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b)
    def do_GET(self):
        if self.path=='/health':self.reply({'ok':True});return
        token=self.path.rsplit('/',1)[-1]
        with LOCK:f=JOBS.get(token)
        if f is None:self.reply({'error':'UnknownJob'},404);return
        if not f.done():self.reply({'state':'pending'});return
        try:self.reply({'state':'done','grade':f.result()})
        except Exception as e:self.reply({'state':'fault','error':str(e)},503)
    def do_POST(self):
        try:
            q=json.loads(self.rfile.read(int(self.headers['Content-Length'])));key=q['key'];answer=q['answer']
            if len(key)!=24 or not key.isalnum() or not (ROOT/'data/public'/(key+'.npz')).is_file():raise ValueError('UnknownTask')
            digest=hashlib.sha256((key+'\0'+answer).encode()).hexdigest()
            with LOCK:
                if digest not in JOBS:JOBS[digest]=POOL.submit(fit,key,answer)
            self.reply({'job':digest})
        except Exception as e:self.reply({'error':str(e)},422)
if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',int(os.environ['GRADER_PORT'])),Handler).serve_forever()
