"""Terminal immutable archive; caller reuses an existing identical archive."""
import tarfile
from shared import *
s=load(OUT/'status.json');assert s['stage'] in ['complete','needs_attention'] and not live(s['pid'],s['controllerEntry'])
target=ROOT/('llm-srbench-resume-v3-'+s['stage']+'-'+str(sum(s['completedByRound'].values()))+'.tar.gz')
if not target.exists():
    with tarfile.open(target,'w:gz') as t:
        for name in ['package','control','outputs','rounds','analysis','data/manifest.json','data/public/catalog.json']:
            p=ROOT/name
            if p.exists():t.add(p,arcname=name,filter=lambda m:None if m.issym() or m.islnk() or any(x in pathlib.PurePosixPath(m.name).parts for x in ['__pycache__','node_modules']) or m.name.endswith('.env') or m.name.endswith('.tar.gz') else m)
with target.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
meta={'path':str(target),'sha256':digest,'bytes':target.stat().st_size,'stage':s['stage'],'completedByRound':s['completedByRound'],'runId':load(CONTROL/'plan.json')['runId']};common.save(CONTROL/'archive.json',meta);print(json.dumps(meta))
