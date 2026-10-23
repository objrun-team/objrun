"""Explicit code-source boundary and non-executable JSON return-value protocol."""
import hashlib
import io
import json
import tarfile

TASK='crystallographic-wyckoff-position-analysis'
SOURCE='/root/workspace/solution.py'
PROTOCOL='skillsbench-wyckoff-untrusted-function-values-v1'

def source_from_daemon_tar(raw):
    assert len(raw)<=512*1024+32*1024
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
        files=[]
        for member in archive.getmembers():
            assert member.name in ('solution.py','./solution.py') and member.isfile()
            assert member.size<=512*1024
            stream=archive.extractfile(member);body=stream.read(512*1024+1)
            assert len(body)==member.size;files.append(body)
        assert len(files)==1
    # Bytes remain opaque on the host and never enter the trusted image.
    return files[0]

def decode_values(raw,source_sha256,public_inputs):
    assert len(raw)<=2*1024**2
    def invalid_constant(value):raise ValueError('nonfinite_candidate_json')
    def unique_object(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('duplicate_candidate_json_key')
            value[key]=item
        return value
    value=json.loads(raw,parse_constant=invalid_constant,object_pairs_hook=unique_object)
    assert set(value)=={'protocol','candidateSourceSha256','calls'} and value['protocol']==PROTOCOL and value['candidateSourceSha256']==source_sha256
    assert isinstance(value['calls'],list) and len(value['calls'])==len(public_inputs)
    seen=set()
    for row in value['calls']:
        assert isinstance(row,dict) and set(row) in ({'path','inputSha256','result'},{'path','inputSha256','error'})
        assert row['path'] in public_inputs and row['path'] not in seen and row['inputSha256']==public_inputs[row['path']]
        seen.add(row['path'])
        if 'error' in row:assert isinstance(row['error'],str) and len(row['error'])<=128
    assert seen==set(public_inputs)
    return value
