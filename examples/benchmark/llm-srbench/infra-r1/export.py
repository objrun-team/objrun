"""Complete supplemental archive, with original provenance references preserved."""
import tarfile
from shared import *
s=load(OUT/'status.json');assert s['stage'] in ['complete','complete_partial','needs_attention']
assert not live(s['pid'],s['controllerEntry']),'WaitForActualExitBeforeExport'
target=ROOT/('llm-srbench-infrastructure-r1-'+s['stage']+'-'+str(s['completed'])+'.tar.gz')
if not target.exists():
    with tarfile.open(target,'w:gz') as t:
        for name in ['package','control','outputs','inherited','data/manifest.json','data/public/catalog.json']:
            p=ROOT/name
            if p.exists():t.add(p,arcname=name,filter=lambda m:None if any(x in pathlib.PurePosixPath(m.name).parts for x in ['__pycache__','node_modules']) or m.name.endswith('.env') or m.name.endswith('.tar.gz') else m)
with target.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
meta={'path':str(target),'sha256':digest,'bytes':target.stat().st_size,'stage':s['stage'],'records':s['completed'],'roundId':load(CONTROL/'plan.json')['roundId']};common.save(CONTROL/'archive.json',meta);print(json.dumps(meta))
