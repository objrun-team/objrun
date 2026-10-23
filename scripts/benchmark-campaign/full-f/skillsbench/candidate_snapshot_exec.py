"""Untrusted function execution in the candidate's isolated filesystem copy.

Unlike the single-source preparation driver, this retains helper modules and
installed candidate dependencies. No private verifier/oracle is provided.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

def main():
    assert sys.flags.isolated and sys.dont_write_bytecode
    raw=sys.stdin.buffer.read(1024**2+1);assert len(raw)<=1024**2
    incoming=json.loads(raw);assert set(incoming)=={'candidateSourceSha256','publicInputs'}
    source=Path('/root/workspace/solution.py');digest=hashlib.sha256()
    with source.open('rb') as file:
        while True:
            chunk=file.read(65536)
            if not chunk:break
            digest.update(chunk)
    assert digest.hexdigest()==incoming['candidateSourceSha256']
    inputs=incoming['publicInputs'];assert inputs
    for path,sha in inputs.items():
        assert path.startswith('/root/cif_files/') and Path(path).name.endswith('.cif')
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
    captured=io.StringIO();calls=[];initial_error=None
    with contextlib.redirect_stdout(captured),contextlib.redirect_stderr(captured):
        try:
            sys.path.insert(0,'/root/workspace')
            spec=importlib.util.spec_from_file_location('solution',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            function=getattr(module,'analyze_wyckoff_position_multiplicities_and_coordinates')
        except BaseException as error:initial_error=type(error).__name__
        for path,sha in sorted(inputs.items()):
            row={'path':path,'inputSha256':sha}
            try:
                if initial_error:raise RuntimeError(initial_error)
                value=function(path);encoded=json.dumps(value,allow_nan=False)
                if len(encoded.encode())>128*1024:raise ValueError('result_limit')
                row['result']=json.loads(encoded)
            except BaseException as error:row['error']=type(error).__name__
            calls.append(row)
    print(json.dumps({'protocol':'skillsbench-wyckoff-untrusted-function-values-v1','candidateSourceSha256':incoming['candidateSourceSha256'],'calls':calls},allow_nan=False,separators=(',',':')))

if __name__=='__main__':main()
