"""Append a verified export without replacing or repacking the existing packs."""
import argparse,collections,copy,gzip,json,os,pathlib,shutil
from export_records import PackStore,JsonShards,encoded
from records import Records,contents,database_exports

def problems(value,path=''):
    if isinstance(value,dict):
        if value.get('pending') or value.get('disposition')=='pending-database':
            yield dict(path=path,reason=value.get('pending','unexported nested database'))
        for k,v in value.items():yield from problems(v,path+'/'+str(k))
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from problems(v,path+'/'+str(i))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base',type=pathlib.Path,required=True);ap.add_argument('--supplement',type=pathlib.Path,required=True)
    ap.add_argument('--output',type=pathlib.Path,required=True);ap.add_argument('--label',required=True)
    ap.add_argument('--partial',nargs='*',default=[]);args=ap.parse_args()
    base=Records(args.base);supplement=Records(args.supplement);out=args.output.resolve()
    assert not out.exists();assert not out.is_relative_to(base.root) and not out.is_relative_to(supplement.root)
    assert not supplement.catalog.get('errors')
    out.mkdir(parents=True)
    for p in base.root.rglob('*'):
        rel=p.relative_to(base.root);target=out/rel
        if p.is_dir():target.mkdir(exist_ok=True)
        elif rel.parts[0]=='packs':os.link(p,target)
        else:shutil.copyfile(p,target)
    store=PackStore(out,prefix=args.label);store.level=6
    wanted={};streams={};runrows=collections.defaultdict(dict);counts=collections.defaultdict(collections.Counter)
    formats=collections.Counter();bycollection=collections.Counter();issues=[]
    dbproof=JsonShards(out,'database-audit-'+args.label);exclusions=JsonShards(out,'excluded-'+args.label)
    excluded_counts=collections.Counter();db_counts=collections.defaultdict(collections.Counter)
    original_names={c['collection'] for c in base.catalog['collections']}
    for e in supplement.entries():
        name=e['collection'];assert name not in original_names,'Cannot silently replace an existing collection'
        issue=list(problems(e))
        if issue:issues.append(dict(collection=name,path=e['path'],issues=issue));continue
        # A container archive is identified by its manifest contents, not extension.
        docker=False
        for m in e.get('members',[]):
            if m['path'].lstrip('./')=='manifest.json' and m.get('format')=='text':
                try:
                    value=json.loads(b''.join(supplement.parts(m['content'])))
                    docker=isinstance(value,list) and bool(value) and all(isinstance(x,dict) and 'Config' in x and isinstance(x.get('Layers'),list) for x in value)
                except (ValueError,UnicodeDecodeError):pass
        if docker or (e.get('format')=='archive-members' and not e.get('members')):
            reason='docker-image-resource' if docker else 'resource-only-archive'
            exclusions.write(dict(collection=name,path=e['path'],source_sha256=e['source_sha256'],source_bytes=e['source_bytes'],reason=reason))
            excluded_counts[reason]+=1;counts[e['bench']]['excluded_files']+=1;counts[e['bench']]['archived_candidate_entries']+=1;continue
        b=e['bench'];streams.setdefault(name,JsonShards(out,name)).write(e);formats[e['format']]+=1;bycollection[name]+=1
        counts[b]['retained_files']+=1;counts[b]['retained_source_bytes']+=e.get('source_bytes',0)
        for content in contents(e):
            for h in content['parts']:
                if h not in base.objects:wanted.setdefault(h,b)
        scope=runrows[b].setdefault(e['run_scope'],dict(run_scope=e['run_scope'],collection=name,files=0,status_fields=collections.Counter(),identifiers=set()))
        scope['files']+=1;scope['status_fields'].update(e.get('observed_status_fields',{}));scope['identifiers'].update(tuple(x) for x in e.get('identifiers',[]))
        for db in database_exports(e):
            db_counts[b]['database_exports']+=1
            for table in db['tables']:
                scope['status_fields'].update(table.get('observed_status_fields',{}))
                if not table.get('excluded'):db_counts[b]['tables']+=1;db_counts[b]['rows']+=table['exported_rows']
            dbproof.write(dict(collection=name,path=e['path'],database_sha256=db.get('source_database_sha256'),wal_sha256=db.get('wal_sha256'),integrity=db['integrity'],foreign_key_violation_count=db['foreign_key_violation_count'],tables=[{k:t.get(k) for k in ('name','source_rows','exported_rows','order','excluded')} for t in db['tables']]))
    if issues:
        (out/'reports/supplement-pending.json').write_bytes(encoded(issues))
        raise RuntimeError(str(len(issues))+' source entries require review; existing Git data remains untouched')
    groups=collections.defaultdict(set)
    for h in wanted:groups[supplement.objects[h]['pack']].add(h)
    for i,(name,hashes) in enumerate(groups.items()):
        supplement.load_pack(name)
        for h,data in supplement.cache.items():
            if h in hashes:store.put(data,wanted[h])
        if i%30==0:print(json.dumps(dict(repacked_source_packs=i+1,total=len(groups))),flush=True)
    store.finish()
    with gzip.open(out/'manifests/objects.jsonl.gz','wt',encoding='utf-8',compresslevel=9) as f:
        for h,obj in base.objects.items():f.write(json.dumps(obj,separators=(',',':'))+'\n')
        for h,obj in store.objects.items():f.write(json.dumps(dict(sha256=h,**obj),separators=(',',':'))+'\n')
    packs=list(base.packs.values())+store.packs;(out/'manifests/packs.json').write_bytes(encoded(packs))
    catalog=copy.deepcopy(base.catalog)
    for c in supplement.catalog['collections']:
        name=c['collection'];entry=copy.deepcopy(c);entry['manifest_shards']=streams[name].finish() if name in streams else []
        entry['selection_counts']={'selected_entries':bycollection[name]};entry['selection_scope']='requested-bench-subset' if name in args.partial else 'requested-collection'
        catalog['collections'].append(entry)
        for b,n in c['by_bench'].items():
            for key in ('discovered_files','discovered_bytes','excluded_files','database_sidecars'):counts[b][key]+=n.get(key,0)
    for b,scopes in runrows.items():
        counts[b]['run_scopes_retained']+=len(scopes)
        with (out/'runs'/f'{b}.jsonl').open('ab') as f:
            for s in scopes.values():
                s['status_fields']=dict(s['status_fields']);s['identifiers']=[list(x) for x in sorted(s['identifiers'])];f.write(encoded(s)+b'\n')
    for p in store.packs:
        total=sum(p['owner_raw_bytes'].values())
        for b,n in p['owner_raw_bytes'].items():counts[b]['attributed_pack_bytes']+=round(p['bytes']*n/total)
    for b,n in counts.items():
        values=collections.Counter(catalog['benches'].get(b,{}));values.update(n);catalog['benches'][b]=dict(values)
    oldformats=collections.Counter(catalog['formats']);oldformats.update(formats);catalog['formats']=dict(oldformats)
    full={c['collection'] for c in supplement.catalog['collections']}-set(args.partial)
    catalog['deferred_original_collections']=[n for n in catalog['deferred_original_collections'] if n not in full]
    catalog['missing_collections']=[n for n in catalog['deferred_original_collections'] if n not in args.partial];catalog['partial_collections']=args.partial
    catalog.update(collections_processed=len(catalog['collections']),collections_with_selected_records=sum(bool(c['manifest_shards']) for c in catalog['collections']),pack_count=len(packs),pack_bytes=sum(p['bytes'] for p in packs),unique_fragments=len(base.objects)+len(store.objects))
    report=dict(label=args.label,collections=[c['collection'] for c in supplement.catalog['collections']],partial_collections=args.partial,
                added_file_records=sum(formats.values()),formats=dict(formats),by_bench={b:dict(n) for b,n in counts.items()},database_counts=dict(db_counts),
                added_pack_count=len(store.packs),added_pack_bytes=sum(p['bytes'] for p in store.packs),new_fragments=len(store.objects),
                existing_packs_unchanged=True,pending=0,excluded_counts=dict(excluded_counts),excluded_manifest_shards=exclusions.finish(),database_audit_shards=dbproof.finish())
    (out/'reports'/('supplement-'+args.label+'.json')).write_bytes(encoded(report));(out/'catalog.json').write_bytes(encoded(catalog))
    print(json.dumps({k:v for k,v in report.items() if k not in ('by_bench','database_counts','database_audit_shards','excluded_manifest_shards')}))

if __name__=='__main__':main()
