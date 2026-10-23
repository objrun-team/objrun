"""Trusted native-script verifier. Receives JSON values, never candidate code."""
import contextlib
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import runpy
import sys
import types

TASK='crystallographic-wyckoff-position-analysis'
FUNCTION='analyze_wyckoff_position_multiplicities_and_coordinates'

def main():
    assert sys.flags.isolated and sys.dont_write_bytecode
    trusted=json.loads(Path('/opt/objrun/trusted.json').read_bytes());assert trusted['taskId']==TASK
    for pin in trusted['files']:assert hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest()==pin['sha256']
    raw=sys.stdin.buffer.read(2*1024**2+1);assert len(raw)<=2*1024**2
    incoming=json.loads(raw)
    assert set(incoming)=={'protocol','candidateSourceSha256','calls'}
    assert incoming['protocol']=='skillsbench-wyckoff-untrusted-function-values-v1'
    expected=trusted['publicInputs'];rows={};called=[]
    assert len(incoming['calls'])<=len(expected)
    for row in incoming['calls']:
        assert set(row) in ({'path','inputSha256','result'},{'path','inputSha256','error'})
        assert row['path'] in expected and row['path'] not in rows and row['inputSha256']==expected[row['path']]
        rows[row['path']]=row
    def proxy(path):
        assert isinstance(path,str) and path in expected
        called.append(path)
        row=rows.get(path)
        if row is None or 'error' in row:raise RuntimeError('isolated_candidate_function_failed')
        return row['result']
    module=types.ModuleType('solution');setattr(module,FUNCTION,proxy);sys.modules['solution']=module
    output=io.StringIO();collect='--collect' in sys.argv;nodes=[];code=0
    with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
        if collect:
            import pytest
            class Witness:
                def pytest_collection_finish(self,session):nodes.extend(x.nodeid for x in session.items)
            code=int(pytest.main(['-c','/opt/objrun/empty.ini','--confcutdir=/verifier','--collect-only','-q','/verifier/test_outputs.py'],plugins=[Witness()]))
        else:
            try:runpy.run_path('/verifier/test_outputs.py',run_name='__main__')
            except SystemExit as error:code=error.code or 0
    for pin in trusted['files']:assert hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest()==pin['sha256']
    # Official task uses main(), not pytest tests. Retain its actual empty
    # pytest collection/code 5 and its original reward file semantics.
    reward=None if collect else float(Path('/logs/verifier/reward.txt').read_text())
    complete=(code==5 and nodes==[]) if collect else code==0 and len(called)==len(expected) and set(called)==set(expected) and 0<=reward<=1
    print(json.dumps({'protocol':'skillsbench-full-f-private-native-script-values-v1','taskId':TASK,'mode':'collect' if collect else 'grade',
        'nodeIds':nodes,'pytestExitCode':code if collect else None,'originalScriptExitCode':None if collect else code,
        'nativeCaseCount':len(expected),'actualFunctionCallPaths':called,'complete':complete,'reward':reward,
        'candidateExecutablesUsed':False,'candidateSnapshotUsed':False,'candidateCodeExecutedSeparately':True,
        'candidateSourceSha256':incoming['candidateSourceSha256'],'rawOriginalVerifierOutput':output.getvalue(),
        'pythonVersion':sys.version,'pythonPath':sys.executable,'installedPackages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}},separators=(',',':')))

if __name__=='__main__':main()
