"""Inventory pinned software-benchmark sources without creating environments."""
import hashlib
import json
from pathlib import Path
import tomllib
import yaml
ROOT=Path(__file__).resolve().parents[2]
result={}
for slug in ['deepswe','terminal-bench','skillsbench']:
    home=ROOT/'.phase1-data'/slug
    source=json.loads((home/'source.json').read_text(encoding='utf-8'))
    roots=list((home/'vendor').glob('*'))
    if len(roots)!=1: raise ValueError('Expected exactly one pinned source checkout')
    files=sorted((roots[0]/'tasks').glob('*/task.md' if slug=='skillsbench' else '*/task.toml'))
    if not files: raise ValueError('Task format not recognized; never report an empty corpus as verified')
    tasks=[]
    for f in files:
        text=f.read_text(encoding='utf-8')
        if f.suffix=='.toml': cfg=tomllib.loads(text)
        else:
            parts=text.split('---',2)
            if len(parts)!=3: raise ValueError('Missing task frontmatter')
            cfg=yaml.safe_load(parts[1]) or {}
        tasks.append({'id':f.parent.name,'definitionFormat':f.suffix,'definitionSha256':hashlib.sha256(f.read_bytes()).hexdigest(),'verifierEnvironmentMode':(cfg.get('verifier') or {}).get('environment_mode'),'referencePresent':any((f.parent/n).is_dir() for n in ['solution','oracle']),'graderPresent':any((f.parent/n).is_dir() for n in ['tests','verifier'])})
    result[slug]={'source':source,'tasks':len(tasks),'taskManifest':tasks,'status':'Source inventory only; no official environment/reference/model pilot completed.'}
output=ROOT/'docs/phase1/software-source-inventory.json'
output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v['tasks'] for k,v in result.items()}))
