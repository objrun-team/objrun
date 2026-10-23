"""Preserve every version/segment and its original failed audit in one archive."""
import hashlib,json,pathlib,tarfile
from support import CONTROL,ROOT,OUT,load
s=load(OUT/'status.json');assert s['stage'] in ['complete_with_exceptions','needs_attention','drained']
target=ROOT/('llm-srbench-v2-concurrency16-'+s['stage']+'-'+str(s['completed'])+'-results.tar.gz')
if not target.exists():
    with tarfile.open(target,'w:gz') as t:
        for name in ['package','outputs','data/manifest.json','data/public/catalog.json','inherited','analysis/package','analysis/outputs']:
            p=ROOT/name
            if p.exists():t.add(p,arcname=name,filter=lambda m:None if any(x in pathlib.PurePosixPath(m.name).parts for x in ['__pycache__','node_modules']) or m.name.endswith('.env') else m)
with target.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
meta={'path':str(target),'bytes':target.stat().st_size,'sha256':sha,'stage':s['stage'],'completeRecords':s['completed'],'executionSegment':'concurrency16'};(CONTROL/'archive.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta))
