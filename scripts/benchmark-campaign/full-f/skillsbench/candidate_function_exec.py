"""UNTRUSTED execution side: public inputs and candidate code, no private tests.

Only the Wyckoff function protocol is implemented. This process's stdout is
untrusted data; the separate private grader decides the score.
"""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

FUNCTION='analyze_wyckoff_position_multiplicities_and_coordinates'

def main():
    assert sys.flags.isolated and sys.dont_write_bytecode
    raw=sys.stdin.buffer.read(1024**2+1);assert len(raw)<=1024**2
    incoming=json.loads(raw);assert set(incoming)=={'candidateSourceBase64','candidateSourceSha256','publicInputs'}
    source=base64.b64decode(incoming['candidateSourceBase64'],validate=True)
    assert len(source)<=512*1024 and hashlib.sha256(source).hexdigest()==incoming['candidateSourceSha256']
    expected={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/root/cif_files').glob('*.cif')}
    assert incoming['publicInputs']==expected and expected
    path=Path('/root/workspace/solution.py');path.write_bytes(source);path.chmod(0o644)
    calls=[];initial_error=None;captured=io.StringIO()
    # Logging is untrusted and bounded by the host transport; never returned
    # to the grader as a command, module, pickle or executable object.
    with contextlib.redirect_stdout(captured),contextlib.redirect_stderr(captured):
        try:
            sys.path.insert(0,'/root/workspace')
            spec=importlib.util.spec_from_file_location('solution',path);module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module);function=getattr(module,FUNCTION)
        except BaseException as error:initial_error=type(error).__name__
        for name,sha in sorted(expected.items()):
            row={'path':'/root/cif_files/'+name,'inputSha256':sha}
            try:
                if initial_error:raise RuntimeError(initial_error)
                value=function(row['path'])
                # Serialize inside the untrusted side; no Python objects or
                # reducers cross into trusted code.
                serialized=json.dumps(value,allow_nan=False)
                if len(serialized.encode())>128*1024:raise ValueError('result_limit')
                row['result']=json.loads(serialized)
            except BaseException as error:row['error']=type(error).__name__
            calls.append(row)
    print(json.dumps({'protocol':'skillsbench-wyckoff-untrusted-function-values-v1','candidateSourceSha256':incoming['candidateSourceSha256'],'calls':calls},allow_nan=False,separators=(',',':')))

if __name__=='__main__':main()
