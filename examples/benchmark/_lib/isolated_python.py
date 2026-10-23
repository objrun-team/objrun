"""Reusable cold scientific-function grader; no test/reference paths enter a candidate."""
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[3]

def score(slug, request, seconds=120):
    cmd=['docker','run','--rm','-i','--network','none','--read-only','--user','0:0','--cap-drop','ALL','--cap-add','SETUID','--cap-add','SETGID','--cap-add','KILL','--security-opt','no-new-privileges','--memory','2g','--cpus','2','--pids-limit','128','--tmpfs','/tmp:rw,nosuid,size=256m']
    for source,target in [(ROOT/f'examples/benchmark/{slug}/grade.py','/worker/grade.py'),(ROOT/'examples/benchmark/_lib/function_proxy.py','/worker/function_proxy.py'),(ROOT/'examples/benchmark/scicode/worker.py','/worker/worker.py'),(ROOT/'examples/benchmark/scicode/codec.py','/worker/codec.py'),(ROOT/f'.phase1-data/{slug}','/root/oracle'),(ROOT/'.phase1-data/python-extras','/extras'),(ROOT/'.phase1-data/material-extras','/material-extras')]:
        cmd+=['--mount',f'type=bind,source={source},target={target},readonly']
    cmd+=['objrun-scicode:phase1','python','-I','/worker/grade.py']
    try: result=subprocess.run(cmd,input=json.dumps(request),capture_output=True,text=True,encoding='utf-8',timeout=seconds+20)
    except subprocess.TimeoutExpired: return {'valid':False,'passed':False,'errorType':'GraderTimeout'}
    if result.returncode: return {'valid':False,'passed':False,'errorType':'GraderProcessError','diagnostic':result.stderr[-1000:]}
    try: return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError,IndexError): return {'valid':False,'passed':False,'errorType':'GraderProtocolError','diagnostic':result.stderr[-1000:]}
