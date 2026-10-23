"""Pinned EvalPlus comparison; candidate runs under UID 65534 without oracle access."""
import ast,importlib.util,json,os,pathlib,pickle,re,signal,subprocess,sys,tempfile,types
ROOT=pathlib.Path(__file__).resolve().parents[2]
DATA=ROOT/'.phase1-data/evalplus-20261012'
EXTRAS=ROOT/'.phase1-data/python-extras'
sys.path[:0]=[str(EXTRAS),str(DATA/'pure-deps'),str(pathlib.Path(__file__).resolve().parent),str(DATA/'vendor')]
from codec import encode,decode
from evalplus.eval import untrusted_check,PASS
from evalplus.eval._special_oracle import MBPP_OUTPUT_NOT_NONE_TASKS
from evalplus.gen.util import trusted_exec
# Load official MBPP deserialization without importing unused datasets/codegen packages.
module=ast.parse((DATA/'vendor/evalplus/data/mbpp.py').read_text())
fn=next(x for x in module.body if isinstance(x,ast.FunctionDef) and x.name=='mbpp_deserialize_inputs')
exec(compile(ast.Module(body=[fn],type_ignores=[]),'official_mbpp_deserialize','exec'))
def drop_uid():
    os.setgroups([]);os.setgid(65534);os.setuid(65534)
def extract(text):
    m=re.search(r'```(?:python|py)?\s*\n(.*?)```',text,re.S)
    return (m.group(1) if m else text).strip()
def score(q):
    dataset=q['dataset'];tid=q['task_id'];code=extract(q['code'])
    try: ast.parse(code)
    except SyntaxError: return {'valid':True,'passed':False,'errorType':'SyntaxError','feedback':'Python syntax error'}
    name={'humaneval':'HumanEvalPlus','mbpp':'MbppPlus'}[dataset]
    row=next(json.loads(x) for x in (DATA/(name+'.jsonl')).read_text().splitlines() if json.loads(x)['task_id']==tid)
    if dataset=='mbpp':
        for g in ['base','plus']: row[g+'_input']=mbpp_deserialize_inputs(tid,row[g+'_input'])
    if q.get('control')=='reference': code=row['prompt']+row['canonical_solution']
    groups=['base'] if q.get('feedback_only') else ['base','plus']
    results={}
    for group in groups:
        inputs=row[group+'_input']
        cache_dir=ROOT/'docs/evalplus-20261012'/dataset/'oracle-cache'
        cache_dir.mkdir(parents=True,exist_ok=True)
        cache=cache_dir/(dataset+'-'+tid.split('/')[-1]+'-'+group+'.pkl')
        if cache.exists(): expected,times=pickle.loads(cache.read_bytes())
        else:
            expected,times=trusted_exec(row['prompt']+row['canonical_solution'],inputs,row['entry_point'],record_time=True,output_not_none=dataset=='mbpp' and row['entry_point'] in MBPP_OUTPUT_NOT_NONE_TASKS)
            cache.write_bytes(pickle.dumps((expected,times)))
        d=pathlib.Path(tempfile.mkdtemp(prefix='ep-',dir='/tmp'));d.chmod(0o755)
        path=d/'candidate.py';path.write_text(code);path.chmod(0o444)
        env={'PATH':'/usr/bin:/bin','EP_EXTRAS':str(EXTRAS),'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
        worker=subprocess.Popen([sys.executable,'-I',str(pathlib.Path(__file__).with_name('worker.py')),str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1,env=env,preexec_fn=drop_uid)
        saved_kill=os.kill
        try:
            ready=json.loads(worker.stdout.readline() or '{}')
            if ready.get('sandboxFailure'): return {'valid':False,'passed':False,'errorType':'SandboxInitializationError','diagnostic':ready.get('diagnostic')}
            if not ready.get('ready'):
                results[group]={'status':'fail','passed':False,'cases':len(inputs),'checked':0,'correct':0,'errorType':ready.get('errorType','CandidateExited')};continue
            if ready['uid']!=65534: raise RuntimeError('PrivilegeBoundaryError')
            def call(*args):
                worker.stdin.write(json.dumps({'function':row['entry_point'],'args':encode(args)})+'\n');worker.stdin.flush()
                reply=json.loads(worker.stdout.readline() or '{}')
                if not reply.get('ok'): raise RuntimeError(reply.get('errorType','CandidateExited'))
                return decode(reply['value'])
            proxy=types.ModuleType('_grading_proxy');proxy.call=call;sys.modules['_grading_proxy']=proxy
            wrapper=f"from _grading_proxy import call\ndef {row['entry_point']}(*args):\n    return call(*args)\n"
            status,details=untrusted_check(dataset,wrapper,inputs,row['entry_point'],expected,row['atol'],times,fast_check=False,min_time_limit=1.0,gt_time_limit_factor=4.0)
            results[group]={'status':status,'passed':status==PASS,'cases':len(inputs),'checked':len(details),'correct':sum(bool(x) for x in details)}
        finally:
            if worker.poll() is None: saved_kill(worker.pid,signal.SIGKILL)
            worker.wait(timeout=5)
            import shutil
            shutil.rmtree(d)
    passed=all(x['passed'] for x in results.values())
    return {'valid':True,'passed':passed,'groups':results,'feedback':'' if passed else 'Public base tests failed: '+json.dumps(results.get('base',{}))}
if __name__=='__main__':
    try: result=score(json.load(sys.stdin))
    except Exception as e: result={'valid':False,'passed':False,'errorType':type(e).__name__,'diagnostic':str(e)[:500]}
    print(json.dumps(result),flush=True)
