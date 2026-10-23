"""Original private source, opaque artifacts, private pytest/Scala scoring."""
import base64
import contextlib
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path, PurePosixPath
import runpy
import shutil
import sys
sys.path.insert(0,'/opt/objrun')
sys.path.insert(0,'/opt/objrun-deps')
from bridge import ScalaBridge, BrowserBridge

def main():
    assert sys.flags.isolated and sys.dont_write_bytecode
    trusted=json.loads(Path('/opt/objrun/trusted.json').read_bytes()); task=trusted['taskId']
    for fixture in trusted['fixtureCopies']: shutil.copytree(fixture['source'],fixture['destination'],dirs_exist_ok=True)
    raw=sys.stdin.buffer.readline(trusted['maximumBytes']*2+65537)
    incoming=json.loads(raw); assert set(incoming)=={'session','artifacts','browserEndpoint'}
    total=0; seen=set()
    for artifact in incoming['artifacts']:
        assert set(artifact)=={'path','base64','sha256'}
        path=artifact['path']; name=PurePosixPath(path)
        assert name.is_absolute() and '\\' not in path and '..' not in name.parts and path not in seen
        assert any(path==p['path'] if p['kind']=='file' else path.startswith(p['path']+'/') for p in trusted['outputPolicies'])
        body=base64.b64decode(artifact['base64'],validate=True); total+=len(body)
        assert total<=trusted['maximumBytes'] and len(seen)<trusted['maximumFiles'] and hashlib.sha256(body).hexdigest()==artifact['sha256']
        seen.add(path); destination=Path(path)
        assert all(not p.is_symlink() for p in [destination,*destination.parents])
        destination.parent.mkdir(parents=True,exist_ok=True); destination.write_bytes(body); destination.chmod(0o644)
    def verify():
        for pin in trusted['files']: assert hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest()==pin['sha256']
    verify()
    for key in ('PYTHONPATH','PYTHONHOME','PYTEST_ADDOPTS','PYTEST_PLUGINS'): os.environ.pop(key,None)
    captured=io.StringIO(); reports=[]; nodes=[]; errors=[]; collect='--collect' in sys.argv
    def callback(request):
        sys.__stdout__.write(json.dumps({'kind':'callback','request':request})+'\n'); sys.__stdout__.flush()
        raw=sys.stdin.buffer.readline(256*1024**2+1)
        assert raw.endswith(b'\n') and len(raw)<=256*1024**2
        return json.loads(raw)
    bridge=(ScalaBridge(callback,incoming['session']) if task=='python-scala-translation'
            else BrowserBridge(incoming['browserEndpoint']) if task=='data-to-d3' and not collect else contextlib.nullcontext())
    with bridge, contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        if task=='python-scala-translation':
            if collect:
                compile(Path('/verifier/test_outputs.py').read_bytes(),'/verifier/test_outputs.py','exec'); code=0; nodes=['native:ScalaTokenizerEvaluator.run_full_evaluation']
            else:
                sys.argv=['/verifier/test_outputs.py','Tokenizer.scala','build.sbt','TokenizerSpec.scala','--project-dir','/root/localtest']
                try: runpy.run_path('/verifier/test_outputs.py',run_name='__main__'); code=0
                except SystemExit as error: code=int(error.code or 0)
                nodes=['native:ScalaTokenizerEvaluator.run_full_evaluation']
        else:
            import pytest
            class Witness:
                def pytest_collection_finish(self, session): nodes.extend(x.nodeid for x in session.items)
                def pytest_collectreport(self, report):
                    if report.failed or report.skipped: errors.append({'node':report.nodeid,'outcome':report.outcome})
                def pytest_runtest_logreport(self, report): reports.append({'nodeId':report.nodeid,'phase':report.when,'outcome':report.outcome,'wasXfail':getattr(report,'wasxfail',None)})
            plugins=[Witness()]
            plugins += [e.load() for e in importlib.metadata.distribution('pytest-json-ctrf').entry_points if e.group=='pytest11']
            args=['-c','/opt/objrun/empty.ini','--confcutdir=/verifier','--ctrf','/logs/verifier/ctrf.json','/verifier/test_outputs.py','-rA','-v']
            if collect: args+=['--collect-only','-q']
            code=int(pytest.main(args,plugins=plugins))
    verify()
    issues=[]
    if not nodes or len(nodes)!=len(set(nodes)) or errors: issues.append('collection_incomplete')
    if task!='python-scala-translation' and not collect:
        for node in nodes:
            phases=[r for r in reports if r['nodeId']==node]
            keys=[r['phase'] for r in phases]
            if keys not in (['setup','call','teardown'],['setup','teardown']) or any(r['outcome']=='skipped' or r['wasXfail'] for r in phases): issues.append('test_phase_incomplete')
    if task=='python-scala-translation' and getattr(bridge,'failure',None): issues.append('execution_callback_fault')
    complete=not issues and code in (0,1)
    result={'taskId':task,'mode':'collect' if collect else 'grade','nodeIds':nodes,'reports':reports,'collectionErrors':errors,
            'pytestExitCode':code,'complete':complete,'validationIssues':issues,'reward':int(complete and code==0 and not collect),
            'passedTests':sum(r['phase']=='call' and r['outcome']=='passed' for r in reports),'failedTests':sum(r['phase']=='call' and r['outcome']=='failed' for r in reports),
            'candidateExecutablesUsed':False,'candidateSnapshotUsed':False,'separateExecutionNamespace':task in ('data-to-d3','python-scala-translation'),
            'nativeScript':task=='python-scala-translation','output':captured.getvalue()[-1024**2:]}
    sys.__stdout__.write(json.dumps({'kind':'result','result':result})+'\n'); sys.__stdout__.flush()
if __name__=='__main__': main()
