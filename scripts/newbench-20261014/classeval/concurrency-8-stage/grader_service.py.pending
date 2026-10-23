"""Official ClassEval v1 scoring in isolated containers. No test text in feedback."""
import argparse
import ast
import hashlib
import io
import json
import pathlib
import re
import struct
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / 'experiment.json').read_text(encoding='utf8'))
IMAGE = json.loads((ROOT / 'classeval-image.json').read_text(encoding='utf8'))['id']
ROWS = {r['task_id']: r for r in json.loads((ROOT / 'upstream/data/ClassEval_data.json').read_text(encoding='utf8'))}
PIPELINE = (ROOT / 'upstream/classeval_evaluation/test_pipeline.py').read_text(encoding='utf8')
# Load exactly the official extract_code implementation, without its path/util imports.
tree = ast.parse(PIPELINE)
official = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AutoTest')
extract_method = next(n for n in official.body if isinstance(n, ast.FunctionDef) and n.name == 'extract_code')
namespace = {'re': re}
exec(compile(ast.fix_missing_locations(ast.Module(body=[extract_method], type_ignores=[])), '<official-extraction>', 'exec'), namespace)

def extract(text):
    return namespace['extract_code'](None, text, 'deepseek-v4.1-flash')

def api(path, data=None, method=None, timeout=30):
    req = urllib.request.Request(CONFIG['dockerEndpoint'] + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
    return json.loads(body) if body else None

def logs(cid):
    with urllib.request.urlopen(CONFIG['dockerEndpoint'] + '/containers/' + cid + '/logs?stdout=1&stderr=1', timeout=20) as response:
        body = response.read()
    result = b''
    while len(body) >= 8:
        n = struct.unpack('>I', body[4:8])[0]
        result += body[8:8+n]
        body = body[8+n:]
    return result.decode(errors='replace')

# Import is included in the first group's five-second timeout, as in run_unit_test.
# Later groups reuse the imported module, matching importlib's module cache.
WORKER = r'''
import contextlib, importlib, io, json, os, sys, unittest
from func_timeout import func_timeout
os.chdir('/work'); sys.path.insert(0, '/work')
open('/work/candidate.py', 'w', encoding='utf8').write(CODE)
details=[]
for index, name in enumerate(NAMES):
    def run():
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            module=importlib.import_module('candidate')
            suite=unittest.TestLoader().loadTestsFromTestCase(getattr(module, name))
            result=unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        types=sorted(set(re.findall(r'(?m)^([A-Za-z_][A-Za-z_0-9]*(?:Error|Exception))(?::|$)', x[1])[-1] if re.findall(r'(?m)^([A-Za-z_][A-Za-z_0-9]*(?:Error|Exception))(?::|$)', x[1]) else 'AssertionError' for x in result.errors+result.failures))
        return {'group':index,'testsRun':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'errorTypes':types,'passed':result.testsRun>0 and result.wasSuccessful()}
    try:
        import re
        item=func_timeout(5,run)
    except BaseException as error:
        item={'group':index,'testsRun':0,'errors':0,'failures':0,'errorTypes':[type(error).__name__],'passed':False}
    details.append(item)
print('OBJRUN_GRADE='+json.dumps({'passed':bool(details) and all(x['passed'] for x in details),'details':details}))
'''

def evaluate(tid, text):
    row = ROWS[tid]
    candidate = extract(text)
    code = '\n'.join(row['import_statement']) + '\n' + candidate + '\n' + row['test']
    worker = 'CODE=' + repr(code) + '\nNAMES=' + repr(row['test_classes']) + '\n' + WORKER
    create = {'Image': IMAGE, 'Cmd': ['python', '-c', worker], 'User': '65534:65534', 'WorkingDir': '/work',
        'Labels': {'org.objrun.owner': 'newbench-20261014', 'org.objrun.benchmark': 'classeval', 'org.objrun.runner': str(args.runner_pid)},
        'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'CapDrop': ['ALL'],
            'SecurityOpt': ['no-new-privileges'], 'PidsLimit': 128, 'Memory': 2147483648, 'NanoCpus': 2000000000,
            'Tmpfs': {'/work': 'rw,nosuid,nodev,size=128m,mode=1777', '/tmp': 'rw,nosuid,nodev,size=128m,mode=1777'},
            'LogConfig': {'Type': 'json-file', 'Config': {'max-size': '1m', 'max-file': '1'}}}}
    cid = None
    try:
        cid = api('/containers/create?name=objrun-newbench-classeval-' + uuid.uuid4().hex[:12], create, 'POST')['Id']
        api('/containers/' + cid + '/start', {}, 'POST')
        waited = api('/containers/' + cid + '/wait', {}, 'POST', timeout=5*len(row['test_classes'])+30)
        output = logs(cid)
        markers = [line[len('OBJRUN_GRADE='):] for line in output.splitlines() if line.startswith('OBJRUN_GRADE=')]
        if waited['StatusCode'] != 0 or not markers:
            return {'valid': False, 'passed': False, 'errorType': 'ContainerScoringError', 'containerId': cid, 'exitCode': waited['StatusCode']}
        value = json.loads(markers[-1])
        details = value['details']
        if len(details) != len(row['test_classes']):
            raise ValueError('MissingTestGroups')
        feedback = json.dumps({'status': 'passed' if value['passed'] else 'rejected', 'groups': details}, separators=(',', ':'))
        return {**value, 'valid': True, 'taskId': tid, 'feedback': feedback[:4000], 'containerId': cid,
            'image': IMAGE, 'candidateSha256': hashlib.sha256(candidate.encode()).hexdigest(), 'officialTimeoutSecondsPerGroup': 5}
    except Exception as error:
        return {'valid': False, 'passed': False, 'errorType': 'ScoringEnvironmentError', 'diagnostic': type(error).__name__}
    finally:
        if cid:
            try: api('/containers/' + cid + '?force=1', method='DELETE')
            except Exception as error:
                with (OUT / 'cleanup-errors.jsonl').open('a', encoding='utf8') as f:
                    f.write(json.dumps({'containerId': cid, 'errorType': type(error).__name__}) + '\n')

guard = threading.Semaphore(CONFIG.get('graderConcurrency', CONFIG.get('concurrency', 2)))
write_lock = threading.Lock()

def grade(tid, text):
    key = hashlib.sha256(json.dumps([tid, text], ensure_ascii=False).encode()).hexdigest()
    cache = OUT / 'cache' / (key + '.json')
    if cache.exists(): return json.loads(cache.read_text(encoding='utf8'))
    with guard: value = evaluate(tid, text)
    with write_lock:
        if value.get('valid'): cache.write_text(json.dumps(value), encoding='utf8')
        with (OUT / 'grader.jsonl').open('a', encoding='utf8') as f:
            f.write(json.dumps({'atUtc': time.time(), 'taskId': tid, 'candidateSha256': hashlib.sha256(text.encode()).hexdigest(), 'verdict': value}) + '\n')
    return value

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        self.send({'ok': True, 'dataset': 'classeval', 'image': IMAGE, 'pid': __import__('os').getpid()})
    def do_POST(self):
        try:
            q = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path == '/grade':
                self.send(grade(q['task_id'], q['code'])); return
            inp = q['input']; task = inp['task']; tid = str(task['id']).split('/')[-1]
            result = inp.get('result', task.get('result', ''))
            text = result.get('body', '') if isinstance(result, dict) else result
            if self.path == '/parsed':
                try: ast.parse('\n'.join(ROWS[tid]['import_statement']) + '\n' + extract(text)); self.send(True)
                except SyntaxError: self.send({'value': False, 'note': 'SyntaxError'})
                return
            value = grade(tid, text)
            if not value.get('valid'): self.send({'valid': False, 'error': value['errorType']}, 503)
            else: self.send({'value': value['passed'], 'note': value['feedback']})
        except Exception as error:
            self.send({'valid': False, 'error': type(error).__name__}, 503)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=0); parser.add_argument('--output', required=True); parser.add_argument('--runner-pid', type=int, required=True)
    args = parser.parse_args(); OUT = pathlib.Path(args.output); (OUT / 'cache').mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(json.dumps({'ready': True, 'port': server.server_port, 'pid': __import__('os').getpid()}), flush=True)
    server.serve_forever()
