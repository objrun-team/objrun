"""Export only this finished run; never package credentials or dependency caches."""
import hashlib,json,pathlib,tarfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
state=json.loads((ROOT/'outputs/status.json').read_text());assert state['stage'] in ['complete','complete_with_exceptions','needs_attention']
target=ROOT/('llm-srbench-release240-v2-'+state['stage']+'-'+str(state['completed'])+'-results.tar.gz')
if not target.exists():
    with tarfile.open(target,'w:gz') as tar:
        for name in ['package','outputs','data/manifest.json','data/public/catalog.json','inherited','analysis/package','analysis/outputs']:
            p=ROOT/name
            if not p.exists():continue
            tar.add(p,arcname=name,filter=lambda m:None if 'node_modules' in pathlib.PurePosixPath(m.name).parts or '__pycache__' in pathlib.PurePosixPath(m.name).parts or m.name.endswith('.env') else m)
with target.open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
meta={'path':str(target),'bytes':target.stat().st_size,'sha256':h,'stage':state['stage'],'completeRecords':state['completed']};(ROOT/'archive.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta))
