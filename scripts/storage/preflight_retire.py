"""Recheck a verified collection immediately before a separate PowerShell cleanup."""
import argparse,gzip,json,pathlib
from archive_collection import manifest,same_file_inventory

ap=argparse.ArgumentParser()
ap.add_argument('--workspace',type=pathlib.Path,required=True)
ap.add_argument('--name',required=True)
a=ap.parse_args()
root=a.workspace.resolve(strict=True)
run=root/'_objrun-archive/collections'/a.name
assert run.parent==root/'_objrun-archive/collections'
r=json.loads((run/'record.json').read_text(encoding='utf-8'))
assert not r.get('external_readonly'), 'External read-only archives are never eligible for cleanup'
assert r['status']=='verified' and r['restore_verified'] and r['integrity_verified'] and not r['source_removed']
p=pathlib.Path(r['source'])
assert p==p.resolve(strict=True) and p.is_relative_to(root) and p!=root and not p.is_junction()
allowed=('objrun/runs','objrun/work','objrun/.phase1-data','objrun/.scratch','objrun/tmp','objrun/docs/', 'tmp/',
         'notes/paper-revisions','work/remaining12-parallel-20261018',
         'objrun/scripts/benchmark-campaign/full-f/chembench/runtime',
         'objrun/scripts/benchmark-campaign/full-f/gpqa/.runtime',
         'objrun/examples/benchmark/code-benchmarks/runtime-snapshot',
         'objrun/scripts/benchmark-campaign/full-f/novaeve_formal_v1',
         'objrun/scripts/benchmark-campaign/full-f/terminal-bench',
         'objrun/scripts/benchmark-campaign/full-f/skillsbench/next-segment',
         'objrun/scripts/bench-runner/release','objrun/scripts/historical-root')
rel=p.relative_to(root).as_posix()
if rel=='objrun/paper':
    # Only historical material is eligible; the manuscript and entry points stay.
    assert {'current','full-v6.25-short-abstract-20261021','README.md','versions.json'} <= set(r.get('excluded',[]))
elif rel=='objrun/scripts/benchmark-campaign/full-f/novaeve_formal_v1/sb':
    # Retire only the three archived executables; all executed sources stay.
    keep=set(r.get('kept_files',[]))
    with gzip.open(run/'source-before.jsonl.gz','rt',encoding='utf-8') as rows:
        for line in rows:
            item=json.loads(line)
            if item['kind']=='file':
                assert item['path'] in keep or item['path'] in {'docker-shim-v2.exe','docker-shim-v3.exe','docker-shim-v4.exe'}
else:
    assert any(rel==x.rstrip('/') or rel.startswith(x.rstrip('/')+'/') for x in allowed), rel
for forbidden in ('objrun/docs/architecture','objrun/docs/provenance','objrun/docs/reproducibility'):
    assert not rel.startswith(forbidden)
current=manifest(p,run/'source-pre-delete.jsonl.gz',r.get('excluded',[]))
assert current==r['before'] or same_file_inventory(run/'source-before.jsonl.gz',run/'source-pre-delete.jsonl.gz'), 'Source changed after verification'
for rel in r.get('kept_files',[]):
    q=p/rel
    assert q.is_file() and q.resolve().is_relative_to(p)
with gzip.open(run/'source-before.jsonl.gz','rt',encoding='utf-8') as rows,gzip.open(run/'retirement-input.tsv.gz','wt',encoding='utf-8',newline='\n') as out:
    for line in rows:
        row=json.loads(line)
        assert not any(c in row['path'] for c in '\t\r\n'), 'Unsupported control character in path'
        out.write(f"{row['kind']}\t{row['path']}\t{row['size']}\t{row['mtime_ns']}\n")
print(json.dumps(dict(status='preflight_passed',source=str(p),files=r['before']['files'])))
