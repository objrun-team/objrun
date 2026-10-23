"""Offline derived-data boundary controls; no converter/container/grader calls."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import uuid
from prepare import HOME,public,save
import excel_conversion_protocol as protocol

def main():
    task='weighted-gdp-calc';sha=hashlib.sha256(b'opaque workbook').hexdigest();body=b'A,B\n1,2\n'
    sample={'protocol':protocol.PROTOCOL,'taskId':task,'sourceSha256':sha,'sourceExists':True,'converterExitCode':0,'converterSha256':'a'*64,
        'derivedCsv':[{'path':'/root/sheet.csv.0','base64':base64.b64encode(body).decode(),'sha256':hashlib.sha256(body).hexdigest()}]}
    assert protocol.decode(json.dumps(sample).encode(),task,sha)==sample;cases=['opaque_csv_source_hash_binding']
    for name,mutate in [
        ('traversal',lambda v:v['derivedCsv'][0].update(path='/root/../verifier/test_outputs.py')),
        ('code_path',lambda v:v['derivedCsv'][0].update(path='/root/solution.py')),
        ('duplicate_file',lambda v:v['derivedCsv'].append(v['derivedCsv'][0])),
        ('changed_source',lambda v:v.update(sourceSha256='b'*64)),
        ('wrong_profile',lambda v:v.update(taskId='reserves-at-risk-calc')),
        ('changed_bytes',lambda v:v['derivedCsv'][0].update(base64=base64.b64encode(b'changed').decode())),
        ('bool_exit_status',lambda v:v.update(converterExitCode=True)),
        ('foreign_json_field',lambda v:v.update(passed=True)),
    ]:
        value=copy.deepcopy(sample);mutate(value)
        try:protocol.decode(json.dumps(value).encode(),task,sha)
        except (AssertionError,ValueError):cases.append(name)
        else:raise AssertionError('unrejected_'+name)
    try:protocol.decode(json.dumps(sample).replace('"taskId":','"taskId":"forged","taskId":').encode(),task,sha)
    except ValueError:cases.append('duplicate_json_key')
    else:raise AssertionError('unrejected_duplicate_json_key')
    failed=copy.deepcopy(sample);failed['converterExitCode']=1;assert protocol.decode(json.dumps(failed).encode(),task,sha)['converterExitCode']==1;cases.append('original_nonzero_conversion_exit_retained')
    home=HOME/'excel-conversion-protocol-controls'/uuid.uuid4().hex;home.mkdir(parents=True)
    pin=save(home/'result.json',{'protocol':'skillsbench-excel-conversion-boundary-controls-v1','verified':True,'cases':cases,'modelCalls':0,'realConverterExecuted':False,'realGraderExecuted':False,
        'sourcePins':[public.pin(Path(protocol.__file__)),public.pin(Path(__file__))],'scoreCertificate':False},True)
    save(HOME/'excel-conversion-protocol-controls/latest.json',{'resultPin':pin});print(json.dumps({'resultPin':pin,'cases':len(cases),'modelCalls':0}))

if __name__=='__main__':main()
