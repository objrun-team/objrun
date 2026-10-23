"""Preserve declared JPG runner/core/data/dependencies; never copy private controls."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[2]
output,store=map(Path,sys.argv[1:3]);source=json.loads((output/'source.json').read_text(encoding='utf-8'))
selected=[];references=[]
base=source.get('dependencyArchiveReference')
if not base:raise RuntimeError('Explicit immutable dependency archive reference is required')
base_path=Path(base['path'])
if hashlib.sha256(base_path.read_bytes()).hexdigest()!=base['sha256']:raise RuntimeError('Dependency archive reference changed')
cache=zipfile.ZipFile(base_path)
def dependency(name,path,raw):
 expected=hashlib.sha256(raw).hexdigest()
 try:cached=cache.read(name)
 except KeyError:raise RuntimeError('Public dependency cache member is missing: '+name)
 if hashlib.sha256(cached).hexdigest()!=expected:raise RuntimeError('Public dependency cache member changed: '+name)
 references.append({'name':name,'sourcePath':str(path),'sha256':expected,'bytes':len(raw)})
for item in source['files']+source['repairFiles']:
 name=item['path']
 if name.startswith('app/src/') or name in ['app/package.json','app/bun.lock','app/tsconfig.json','test/_lib.ts','scripts/phase1/source-snapshot.ts'] or name.startswith('scripts/repair-2026-10-08/'):
  raw=(ROOT/name).read_bytes()
  if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise RuntimeError('Changed executed source')
  selected.append((name,raw))
for item in source['artifacts']:
 if any(word in item['name'].lower() for word in ['secret','token','broker','.env','.pem','.key']):raise RuntimeError('Private asset cannot be archived')
 raw=Path(item['path']).read_bytes()
 if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise RuntimeError('Changed data/profile/runtime artifact')
 name='artifacts/'+item['name']
 if item['name'].startswith(('runtime/','grader-dependencies/')):dependency(name,Path(item['path']),raw)
 else:selected.append((name,raw))
for file in sorted((ROOT/'app/node_modules').rglob('*')):
 if file.is_file() and file.suffix in ['.js','.cjs','.mjs','.json','.wasm','.node','.ts'] and '.bin' not in file.parts:dependency(file.relative_to(ROOT).as_posix(),file,file.read_bytes())
cache.close()
if sum(len(raw)for _,raw in selected)>16*1024*1024:raise RuntimeError('New direct source/data archive exceeds its reserved16MiB boundary')
archive=store/'frozen-source.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6)as z:
 for name,raw in selected:z.writestr(name,raw)
members_sha=hashlib.sha256(json.dumps(references,sort_keys=True,separators=(',',':')).encode()).hexdigest()
value={'sourceExecutionDigest':source['executionDigest'],'archive':str(archive),'archiveSha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'archiveBytes':archive.stat().st_size,'members':len(selected),'dependencyReferences':{**base,'members':references,'membersSha256':members_sha},'scope':'Current JPG runner/grader/core and task/control source/data are directly archived. Exact public dependency members are referenced from the immutable base ZIP; older source and host-only task data inside that base are not used. Private config/API/grader headers excluded.'}
(output/'frozen-source.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');print(json.dumps(value))
