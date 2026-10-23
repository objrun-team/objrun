"""Local code-source/JSON boundaries; no candidate code or grader execution."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import uuid
from prepare import HOME,public,save
from code_values import PROTOCOL,source_from_daemon_tar,decode_values

def main():
    cases=[]
    def archive(name='solution.py',kind=tarfile.REGTYPE,duplicate=False):
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w') as tar:
            member=tarfile.TarInfo(name);member.type=kind;member.size=0 if kind!=tarfile.REGTYPE else 4
            tar.addfile(member,io.BytesIO(b'code') if member.size else None)
            if duplicate:tar.addfile(member,io.BytesIO(b'code'))
        return out.getvalue()
    assert source_from_daemon_tar(archive())==b'code';cases.append('opaque_single_source')
    for name,raw in [('traversal',archive('../solution.py')),('foreign',archive('helper.py')),('symlink',archive(kind=tarfile.SYMTYPE)),('hardlink',archive(kind=tarfile.LNKTYPE)),('duplicate',archive(duplicate=True))]:
        try:source_from_daemon_tar(raw)
        except (AssertionError,ValueError):cases.append(name)
        else:raise AssertionError(name+' accepted')
    sha=hashlib.sha256(b'code').hexdigest();inputs={'/root/cif_files/public.cif':'f'*64}
    value={'protocol':PROTOCOL,'candidateSourceSha256':sha,'calls':[{'path':next(iter(inputs)),'inputSha256':'f'*64,'result':{'text':'__import__("os").system("never executed")'}}]}
    assert decode_values(json.dumps(value).encode(),sha,inputs)==value;cases.append('result_string_remains_data')
    for name,mutate in [('foreign_input',lambda v:v['calls'][0].update(path='/verifier/test_outputs.py')),('input_drift',lambda v:v['calls'][0].update(inputSha256='0'*64)),('missing_call',lambda v:v.update(calls=[])),('source_drift',lambda v:v.update(candidateSourceSha256='0'*64))]:
        bad=json.loads(json.dumps(value));mutate(bad)
        try:decode_values(json.dumps(bad).encode(),sha,inputs)
        except (AssertionError,ValueError):cases.append(name)
        else:raise AssertionError(name+' accepted')
    for name,raw in [('duplicate_json_key',b'{"protocol":1,"protocol":2}'),('nonfinite_json',b'{"result":NaN}')]:
        try:decode_values(raw,sha,inputs)
        except (AssertionError,ValueError):cases.append(name)
        else:raise AssertionError(name+' accepted')
    home=HOME/'code-value-controls'/uuid.uuid4().hex;home.mkdir(parents=True)
    pin=save(home/'result.json',{'protocol':'skillsbench-full-f-code-value-boundary-controls-v1','verified':True,'cases':cases,'modelCalls':0,'candidateCodeExecuted':False,'realGraderExecuted':False,'sourcePins':[public.pin(Path(__file__)),public.pin(Path(__file__).with_name('code_values.py'))]},True)
    save(HOME/'code-value-controls/latest.json',{'resultPin':pin});print(json.dumps({'verified':True,'cases':len(cases),'resultPin':pin,'modelCalls':0}))

if __name__=='__main__':main()
