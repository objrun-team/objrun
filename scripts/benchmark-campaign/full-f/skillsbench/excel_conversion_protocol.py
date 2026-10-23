"""Fixed official workbook/CSV profiles and a non-executable return boundary."""
import base64
import hashlib
import json
import re

PROTOCOL='skillsbench-pristine-excel-conversion-v1'
PROFILES={
    'weighted-gdp-calc':{'workbook':'/root/gdp.xlsx','csvPrefix':'/root/sheet.csv'},
    'reserves-at-risk-calc':{'workbook':'/root/output/rar_result.xlsx','csvPrefix':'/root/output/sheet.csv'},
    'shock-analysis-demand':{'workbook':'/root/test_demand.xlsx','csvPrefix':'/root/sheet.csv'},
}
MAXIMUM_BYTES=8*1024**2
MAXIMUM_FILES=64

def decode(raw,task_id,expected_source_sha):
    assert task_id in PROFILES and len(raw)<=12*1024**2
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate_conversion_json_key')
            result[key]=value
        return result
    def invalid(value):raise ValueError('nonfinite_conversion_value')
    value=json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
    assert set(value)=={'protocol','taskId','sourceSha256','sourceExists','converterExitCode','converterSha256','derivedCsv'}
    assert value['protocol']==PROTOCOL and value['taskId']==task_id and value['sourceSha256']==expected_source_sha
    assert type(value['sourceExists']) is bool and type(value['converterExitCode']) is int
    assert re.fullmatch('[0-9a-f]{64}',value['converterSha256'])
    assert isinstance(value['derivedCsv'],list) and len(value['derivedCsv'])<=MAXIMUM_FILES
    if not value['sourceExists']:assert value['converterExitCode']==0 and not value['derivedCsv']
    prefix=PROFILES[task_id]['csvPrefix'];paths=set();total=0
    for row in value['derivedCsv']:
        assert isinstance(row,dict) and set(row)=={'path','base64','sha256'}
        assert isinstance(row['path'],str) and re.fullmatch(re.escape(prefix)+r'\.(0|[1-9][0-9]*)',row['path'])
        assert row['path'] not in paths;paths.add(row['path'])
        body=base64.b64decode(row['base64'],validate=True);total+=len(body)
        assert len(body)<=MAXIMUM_BYTES and total<=MAXIMUM_BYTES and hashlib.sha256(body).hexdigest()==row['sha256']
    # A nonzero ssconvert exit remains a real conversion observation. The
    # original test.sh uses `|| true`; original pytest decides the outcome.
    return value
