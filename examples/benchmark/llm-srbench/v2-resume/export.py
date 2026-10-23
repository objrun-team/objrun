"""Export this approved segment without replacing the earlier 54-record archive."""
import hashlib,json,pathlib,tarfile
CONTROL=pathlib.Path(__file__).resolve().parent;ROOT=CONTROL.parents[1]
s=json.loads((ROOT/'outputs/status.json').read_text());assert s['stage'] in ['complete_with_exceptions','complete','needs_attention']
target=ROOT/('llm-srbench-v2-approved429-'+s['stage']+'-'+str(s['completed'])+'-results.tar.gz')
if not target.exists():
    with tarfile.open(target,'w:gz') as t:
        for name in ['package','outputs','data/manifest.json','data/public/catalog.json','inherited','analysis/package','analysis/outputs']:
            p=ROOT/name
            if p.exists():t.add(p,arcname=name,filter=lambda m:None if any(x in pathlib.PurePosixPath(m.name).parts for x in ['__pycache__','node_modules']) or m.name.endswith('.env') else m)
with target.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
meta={'path':str(target),'bytes':target.stat().st_size,'sha256':sha,'stage':s['stage'],'completeRecords':s['completed'],'executionSegment':'approved-429'}
(CONTROL/'archive.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta))
