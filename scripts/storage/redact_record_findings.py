"""Redact flagged export content; finalize again to remove superseded pack bytes."""
import argparse,collections,copy,gzip,json,os,pathlib,shutil
from records import Records
from export_records import Exporter,JsonShards,encoded

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','workspace','work','findings'):ap.add_argument('--'+name,type=pathlib.Path,required=True)
    a=ap.parse_args();r=Records(a.source);assert not a.output.exists()
    targets={v['object_sha256'] for v in json.loads(a.findings.read_text(encoding='utf-8'))}
    x=Exporter(argparse.Namespace(workspace=a.workspace,output=a.output,work=a.work,compression_level=6));x.store.prefix='credential-redacted'
    cache={};audit=[];streams={};rewritten=set();changes_by_path={}
    def rewrite(v,bench):
        if isinstance(v,dict):
            if {'bytes','sha256','parts'}<=v.keys():
                if not targets.intersection(v['parts']):return v
                key=(v['sha256'],v['bytes'],tuple(v['parts']))
                if key not in cache:
                    raw=b''.join(r.parts(v));text=raw.decode('utf-8');updated,changes,_=x.scrub.text(text)
                    assert updated!=text and changes.get('credential_redaction',0)>0,'Finding needs explicit review rather than silent dismissal'
                    assert not any(p.search(updated) for p in x.scrub.patterns)
                    cache[key]=(x.store.put(updated.encode('utf-8'),bench),changes)
                result,changes=cache[key];return copy.deepcopy(result)
            return {k:rewrite(value,bench) for k,value in v.items()}
        if isinstance(v,list):return [rewrite(value,bench) for value in v]
        return v
    for e in r.entries():
        new=rewrite(e,e['bench'])
        if new!=e:
            new.setdefault('transformations',{})['credential_redaction_after_verification']=True
            audit.append(dict(collection=e['collection'],path=e['path'],reason='credential-pattern verification finding; no credential value recorded'))
            rewritten.add(e['collection']);changes_by_path[(e['collection'],e['path'])]=new
    for name in rewritten:
        stream=streams[name]=JsonShards(a.output,name)
        for e in r.entries(name):stream.write(changes_by_path.get((name,e['path']),e))
    x.store.finish()
    source_shards={s['path'] for c in r.catalog['collections'] if c['collection'] in rewritten for s in c['manifest_shards']}
    object_index=r.root/'manifests/object-index.json'
    if object_index.exists():source_shards.update(s['path'] for s in json.loads(object_index.read_text(encoding='utf-8'))['shards'])
    for p in r.root.rglob('*'):
        rel=p.relative_to(r.root);target=a.output/rel
        if p.is_dir():target.mkdir(exist_ok=True);continue
        if rel.as_posix() in source_shards or rel.as_posix() in ('catalog.json','manifests/packs.json','manifests/objects.jsonl.gz','manifests/object-index.json') or p.name.startswith('object-index-'):continue
        if rel.parts[0]=='packs':os.link(p,target)
        else:shutil.copyfile(p,target)
    (a.output/'manifests/packs.json').write_bytes(encoded(list(r.packs.values())+x.store.packs))
    with gzip.open(a.output/'manifests/objects.jsonl.gz','wb') as f:
        for h,v in r.objects.items():f.write(encoded(v)+b'\n')
        for h,v in x.store.objects.items():
            if h not in r.objects:f.write(encoded(dict(sha256=h,**v))+b'\n')
    catalog=copy.deepcopy(r.catalog)
    for c in catalog['collections']:
        if c['collection'] in streams:c['manifest_shards']=streams[c['collection']].finish()
    (a.output/'catalog.json').write_bytes(encoded(catalog))
    report=dict(file_references=audit,unique_contents=[dict(previous_export_sha256=k[0],exported_sha256=v[0]['sha256'],changes=v[1]) for k,v in cache.items()],staging_requires_finalization_to_remove_superseded_pack_bytes=True)
    (a.output/'reports/verification-redactions.json').write_bytes(encoded(report));print(json.dumps(dict(file_references=len(audit),unique_contents=len(cache))))

if __name__=='__main__':main()
