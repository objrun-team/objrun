"""F-only freeze of explicit bulk authorization, actual controls and source pins."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re

PROJECT=Path(__file__).resolve().parents[2]
DOC=PROJECT/'docs/repair-2026-10-08'
CONTROL=DOC/'minif2f-public-cache-bulk-controls'


def pin(path):
    path=Path(path).resolve();raw=path.read_bytes()
    return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def write_new(path,data):
    raw=(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode()
    with Path(path).open('xb')as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())


prior_path=DOC/'minif2f-public-cache-root-carry-review.json'
if pin(prior_path)['sha256']!='1a4ce79743fe80e89c673b79f934399d1663ae7a0066d52c4c5e5964cb168bc4':raise RuntimeError('Frozen carry review differs')
prior=json.loads(prior_path.read_bytes());protected={}
for expected in prior['new_sources']+prior['protected_sources']:
    actual=pin(expected['path'])
    if actual['sha256']!=expected['sha256']or actual['bytes']!=expected['bytes']:raise RuntimeError('Protected carry/old source changed: '+actual['path'])
    protected[str(Path(actual['path']).resolve()).casefold()]=actual
protected[str(prior_path.resolve()).casefold()]=pin(prior_path)
log=(CONTROL/'run-1.stderr.txt').read_text(encoding='utf-8')
if len(re.findall(r'\.\.\. ok',log))!=12 or 'Ran 12 tests'not in log or not log.rstrip().endswith('OK'):raise RuntimeError('Actual12-control evidence differs')
for path in (CONTROL/'run-1.stdout.txt',CONTROL/'run-1.stderr.txt',CONTROL/'writer-probe-ast.ps1'):
    protected[str(path.resolve()).casefold()]=pin(path)
auth_path=DOC/'minif2f-public-cache-bulk-authorization.json'
auth=dict(protocol='explicit-root-new-key-complete-bulk-authorization-v1',
    recorded_at_utc=datetime.now(timezone.utc).isoformat(),scope='Root authorized F-only preparation; root separately reviews and launches actual E/network stage',
    authorization_facts='Root accepted bulk4 workers/new GET3/key/body retry1/key and4/stage; abort retain4; no changed frozen source, deadline, or historical attribution',
    prior_complete_objects=3556,new_keys=2270,maximum_final_objects=5826,
    carry_phase_sha256='6b1f63ad1f78331d60254dc2b48ec2da3e66f3ce645ab0fbbd27d43342265c2b',
    carry_receipts_sha256='0a1341f62fd894701915886aec9e4f4258a686e73e54c644bab7a289a9b48713',
    carry_released_lease_sha256='eae8be6693a60271d4378981b8f33422619a3005ef962afa0b0e5d2cff8b4c63',
    deadline_utc='2026-10-08T18:16:26.118992+00:00',workers=4,
    new_per_key_get_cap=3,new_global_get_cap=6810,new_body_retry_per_key_cap=1,new_body_retry_stage_cap=4,
    old_v3_key_interval=[0,3],v3_plus_bulk_key_interval_maximum=[0,6],
    old_v3_start_window_gets=1505,carry_window_gets=2,v3_window_maximum_gets=8317,
    all_history_global_gets=None,all_history_per_key_gets=None,
    historical_boundary='[0,3]+new and1505+2+6810 apply only from original V3 stage start; earlier public acquisition attempts exist and their all-history counts remain unknown',
    carried_preservation_operations=6,new_body_retry_preservations_cap=4,abort_retained_parts_cap=4,
    preservation_operations_cap=14,successful_preservation_operations_cap=10,carried_failed_prefix_bytes=292278,
    prefix_cap_bytes=256*1024**2,maximum_body_bytes=64*1024**2,audit_reserved_bytes=64*1024**2,
    directory_cap_bytes=14*1024**3,minimum_e_free_bytes=3*1024**3,minimum_f_free_bytes=1024**3,
    body_policy='Exact official fixed200 URL, known length and valid16-byte Content-MD5; complete fresh GET only; no Range or reuse. Known ETag/MD5/length drift, HTTP/TLS/content/MD5/prefix errors reject without retry.',
    allowance_policy='Intentfsync/readback precedes opener; a failed/unknown intent consumes allowance; existing namespace rejects all automatic continuation/reset',
    completion_policy='Full5826 actual blob SHA, new MD5/typed journal/dispatch, unchanged3556 raw prefix, source pins, final full tree/envelope, observed sole writer and durable released lease before final proof; completion receipt published last',
    failure_policy='AllSettled before retain exact owned evidence and close lease; preserve all partial bytes; any unclosed namespace requires root archival/new authorization; never delete evidence to meet a counter',
    llm_called=False,candidate_run=False,network_executed=False,e_write_executed=False)
write_new(auth_path,auth)
paths=[PROJECT/'scripts/benchmark-repair/minif2f_public_cache_bulk.py',
       PROJECT/'scripts/benchmark-repair/minif2f_public_cache_bulk_stage.py',
       PROJECT/'scripts/benchmark-repair/minif2f_public_cache_bulk_stage.ps1',
       PROJECT/'test/benchmarks/minif2f_public_cache_bulk_test.py',auth_path]
new=[pin(p)for p in paths]
review=dict(protocol='public-cache-explicit-bulk-source-review-v1',validated=True,
    transport_protocol='explicit-root-new-key-complete-bulk-v1',real_acquisition_executed=False,real_gate_executed=False,
    root_must_independently_review_and_launch=True,
    base_helper_sha256='a02c3519b0ccba8a74e577991fedcf75f0c05fb181cfeb617b7e51b060384c2b',
    profile_sha256='f23ebc252a02cf9a407db4fb2045f6c8dba064e1706e97d28fc6ff96ac2a5fd3',
    authorization_sha256=pin(auth_path)['sha256'],new_sources=new,protected_sources=list(protected.values()),
    controls=dict(passed=12,failed=0,scope='Synthetic binary streams and actual F-only fsync/readback; no official body tested',
        python_ast_passed=True,powershell_stage_ast_errors=0,powershell_embedded_probe_ast_errors=0,
        network_calls=0,e_writes=0,model_calls=0,docker_calls=0,candidate_or_lean_runs=0,stderr_pin=pin(CONTROL/'run-1.stderr.txt')),
    limits=auth,
    compatibility='Original3556 raw receipts, V2/V3/carry sources and original journal remain immutable. New bulk rows have explicit namespace/window/unknown history fields and their own strict typed validator. Frozen fast-unpack required full5826 fields are retained.',
    source_review_note='Only these new F files are editable before root acceptance; every imported guard/carry/source/archive control is pinned. New64MiB audit allowance stays inside14GiB and E3/F1 reserves; no new global settings.')
out=DOC/'minif2f-public-cache-bulk-review.json';write_new(out,review)
print(json.dumps(dict(review=pin(out),sources=new,protected_count=len(protected))))
