"""Apply reviewed resource rules and compact only unpublished record fragments."""
import argparse,collections,copy,gzip,json,os,pathlib,re,shutil
from records import Records,contents,database_exports
from export_records import JsonShards,PackStore,encoded,COLLECTION_BENCH,reviewed_resource_match

WORDNET_DATASET_COLUMNS = {'adjpositions': ['positionid', 'position'], 'casedwords': ['casedwordid', 'wordid', 'casedword'], 'domains': ['domainid', 'domain', 'domainname', 'posid'], 'ilis': ['ili', 'synsetid'], 'lexes': ['luid', 'posid', 'wordid', 'casedwordid'], 'lexes_morphs': ['luid', 'wordid', 'posid', 'morphid'], 'lexes_pronunciations': ['luid', 'wordid', 'posid', 'pronunciationid', 'variety'], 'lexrelations': ['synset1id', 'lu1id', 'word1id', 'synset2id', 'lu2id', 'word2id', 'relationid'], 'morphs': ['morphid', 'morph'], 'poses': ['posid', 'pos'], 'pronunciations': ['pronunciationid', 'pronunciation'], 'relations': ['relationid', 'relation', 'recurses'], 'samples': ['sampleid', 'sample', 'source', 'synsetid', 'luid', 'wordid'], 'semrelations': ['synset1id', 'synset2id', 'relationid'], 'senses': ['senseid', 'sensekey', 'synsetid', 'luid', 'wordid', 'casedwordid', 'lexid', 'sensenum', 'tagcount'], 'senses_adjpositions': ['synsetid', 'luid', 'wordid', 'positionid'], 'senses_vframes': ['synsetid', 'luid', 'wordid', 'frameid'], 'senses_vtemplates': ['synsetid', 'luid', 'wordid', 'templateid'], 'synsets': ['synsetid', 'posid', 'domainid', 'definition'], 'usages': ['usageid', 'usagenote', 'synsetid', 'luid', 'wordid'], 'vframes': ['frameid', 'frame'], 'vtemplates': ['templateid', 'template'], 'wikidatas': ['wikidata', 'synsetid'], 'words': ['wordid', 'word']}

def exclude_wordnet_tables(value):
    """Keep dictionary schema/counts and non-corpus tables; remove dataset rows."""
    if value.get('format')!='sqlite-tables':return []
    tables={t['name']:t for t in value.get('tables',[])}
    if not all(tables.get(n,{}).get('columns')==WORDNET_DATASET_COLUMNS[n] for n in ('words','synsets','senses')):return []
    removed=[]
    for name,table in tables.items():
        if table.get('columns')!=WORDNET_DATASET_COLUMNS.get(name) or 'content' not in table:continue
        content=table.pop('content');removed.append(dict(table=name,rows=table['source_rows'],content_sha256=content['sha256'],content_bytes=content['bytes']))
        table.update(excluded=True,reason='WordNet dictionary dataset rows',source_exported_rows=table.get('exported_rows'),exported_rows=0,excluded_content_sha256=content['sha256'],excluded_content_bytes=content['bytes'])
    if removed:value.setdefault('transformations',{})['wordnet_dataset_tables_removed']=len(removed)
    return removed

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('base','source','output','rules'):ap.add_argument('--'+name,type=pathlib.Path,required=True)
    ap.add_argument('--resource-hashes',type=pathlib.Path)
    args=ap.parse_args();base=Records(args.base);source=Records(args.source);out=args.output.resolve()
    assert not out.exists() and not out.is_relative_to(source.root) and not out.is_relative_to(base.root)
    rules=json.loads(args.rules.read_text(encoding='utf-8'))
    resources=json.loads(args.resource_hashes.read_text(encoding='utf-8')) if args.resource_hashes else {}
    for rule in rules:rule['_regex']=re.compile(rule['pattern'],re.I)
    old_names={c['collection'] for c in base.catalog['collections']}
    rewrite={c['collection'] for c in source.catalog['collections']}-old_names
    skip={s['path'] for c in source.catalog['collections'] if c['collection'] in rewrite for s in c['manifest_shards']}
    for p in source.root.rglob('*'):
        rel=p.relative_to(source.root)
        if rel.parts[0]=='packs' or rel.as_posix() in skip or rel.as_posix()=='manifests/objects.jsonl.gz':continue
        target=out/rel
        if p.is_dir():target.mkdir(parents=True,exist_ok=True)
        else:target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
    (out/'packs').mkdir(exist_ok=True)
    for name in base.packs:os.link(base.root/name,out/name)
    prefix='curated'
    while any(p.startswith('packs/'+prefix+'-') for p in source.packs) or (out/'reports'/('finalization-'+prefix+'.json')).exists():prefix+='x'
    previous=None
    if (out/'reports/incremental-finalization.json').exists():
        previous='reports/finalization-before-'+prefix+'.json'
        shutil.copyfile(out/'reports/incremental-finalization.json',out/previous)
    excluded=JsonShards(out,prefix+'-resource-exclusions');excluded_counts=collections.Counter();streams={};wanted={}
    counts=collections.defaultdict(collections.Counter);runrows=collections.defaultdict(dict);formats=collections.Counter();sources=collections.Counter()
    def clean(value,origin,path,bench):
        if isinstance(value,dict):
            if reviewed_resource_match(value,resources):
                evidence=resources[value['source_sha256']];reason=evidence.get('reason','Content-reviewed resource') if isinstance(evidence,dict) else str(evidence)
                excluded.write(dict(collection=origin,path=path,bench=bench,source_sha256=value['source_sha256'],source_bytes=value.get('source_bytes'),rule='content-reviewed-hash',reason=reason,evidence=evidence));excluded_counts['content-reviewed-hash']+=1
                return {k:v for k,v in value.items() if k in ('path','source_sha256','source_bytes')}|dict(disposition='excluded',format='resource-reference',reason=reason)
            for table in exclude_wordnet_tables(value):
                excluded.write(dict(collection=origin,path=path+'!table/'+table['table'],bench=bench,source_sha256=value.get('source_sha256'),rule='wordnet-dataset-table',reason='Schema-identified WordNet corpus; non-corpus tables and schema metadata retained',**table));excluded_counts['wordnet-dataset-table']+=1
            for rule in rules:
                if (not rule.get('collection') or rule['collection']==origin) and rule['_regex'].search(path) and ('content' in value or 'members' in value or 'tables' in value):
                    excluded.write(dict(collection=origin,path=path,bench=bench,source_sha256=value.get('source_sha256'),source_bytes=value.get('source_bytes'),rule=rule['id'],reason=rule['reason']))
                    excluded_counts[rule['id']]+=1
                    return {k:v for k,v in value.items() if k in ('path','source_sha256','source_bytes')}|dict(disposition='excluded',format='resource-reference',reason=rule['reason'])
            result={}
            for k,v in value.items():
                if k=='members':result[k]=[clean(m,origin,path+'!/'+m['path'],bench) for m in v]
                else:result[k]=v
            return result
        return value
    for e in source.entries():
        original=e.get('source_collection',e['collection'])
        if e['collection'] in rewrite:
            if original in COLLECTION_BENCH:e['bench']=COLLECTION_BENCH[original]
            if e['bench']=='shared-or-unassigned':
                p=e['path'].lower()
                if original=='docs-repair-2026-10-09' and p.startswith('tb12-'):e['bench']='terminal-bench'
                elif 'reshard-c4-data/' in p or 'c4-grader-tree-upload-v1/' in p:e['bench']='terminal-bench'
                elif 'lab-bench' in p:e['bench']='labbench'
                elif 'atomworld' in p:e['bench']='atomworld'
                elif 'astrovisbench' in p:e['bench']='astrovisbench'
            prior=e;e=clean(e,original,e['path'],e['bench'])
            if not list(contents(e)) and not list(database_exports(e)) and e.get('format')!='sqlite-sidecar-reference':
                excluded.write({k:prior.get(k) for k in ('collection','path','bench','run_scope','source_sha256','source_bytes')}|dict(rule='resource-only-outer-record',reason='No readable record payload remains after content-reviewed resource exclusions'))
                excluded_counts['resource-only-outer-record']+=1;continue
            streams.setdefault(e['collection'],JsonShards(out,e['collection'])).write(e)
            for c in contents(e):
                for h in c['parts']:
                    if h not in base.objects:wanted.setdefault(h,e['bench'])
        b=e['bench'];counts[b]['retained_files']+=1;counts[b]['retained_source_bytes']+=e.get('source_bytes',0);formats[e['format']]+=1;sources[original]+=1
        scope=runrows[b].setdefault((e['collection'],e['run_scope']),dict(collection=e['collection'],run_scope=e['run_scope'],files=0,status_fields=collections.Counter(),identifiers=set()))
        scope['files']+=1;scope['status_fields'].update(e.get('observed_status_fields',{}));scope['identifiers'].update(tuple(v) for v in e.get('identifiers',[]))
        for database in database_exports(e):
            for table in database['tables']:scope['status_fields'].update(table.get('observed_status_fields',{}))
    groups=collections.defaultdict(set)
    for h in wanted:groups[source.objects[h]['pack']].add(h)
    members=collections.defaultdict(set)
    for h,obj in source.objects.items():
        if obj['pack'] in groups:members[obj['pack']].add(h)
    retained_packs=[];retained_objects={}
    for name in list(groups):
        if groups[name]!=members[name]:continue
        os.link(source.root/name,out/name);proof=copy.deepcopy(source.packs[name]);owners=collections.Counter()
        for h in groups[name]:owners[wanted[h]]+=source.objects[h]['bytes']
        proof['owner_raw_bytes']=dict(owners);retained_packs.append(proof)
        for h in groups.pop(name):retained_objects[h]=source.objects[h]
    store=PackStore(out,prefix=prefix);store.level=12
    for i,(name,hashes) in enumerate(groups.items()):
        source.load_pack(name)
        # Preserve the source TAR order: related fragments compress together and
        # deterministic ordering avoids needless changes between reproductions.
        for h,data in source.cache.items():
            if h in hashes:store.put(data,wanted[h])
        if i%30==0:print(json.dumps(dict(repacked_source_packs=i+1,total=len(groups))),flush=True)
    store.finish()
    with gzip.open(out/'manifests/objects.jsonl.gz','wt',encoding='utf-8',compresslevel=9) as f:
        for obj in base.objects.values():f.write(json.dumps(obj,separators=(',',':'))+'\n')
        for obj in retained_objects.values():f.write(json.dumps(obj,separators=(',',':'))+'\n')
        for h,obj in store.objects.items():f.write(json.dumps(dict(sha256=h,**obj),separators=(',',':'))+'\n')
    packs=list(base.packs.values())+retained_packs+store.packs;(out/'manifests/packs.json').write_bytes(encoded(packs))
    catalog=copy.deepcopy(source.catalog)
    for c in catalog['collections']:
        name=c['collection']
        c.pop('scopes',None)  # The current run index below contains these rows.
        if name in rewrite:c['manifest_shards']=streams[name].finish() if name in streams else []
    for b,scopes in runrows.items():
        counts[b]['run_scopes_retained']=len(scopes)
        with (out/'runs'/f'{b}.jsonl').open('wb') as f:
            for scope in scopes.values():
                scope['status_fields']=dict(scope['status_fields']);scope['identifiers']=[list(v) for v in sorted(scope['identifiers'])];f.write(encoded(scope)+b'\n')
    for p in packs:
        total=sum(p['owner_raw_bytes'].values())
        for b,n in p['owner_raw_bytes'].items():counts[b]['attributed_pack_bytes']+=round(p['bytes']*n/total)
    catalog.update(benches={b:dict(v) for b,v in counts.items()},formats=dict(formats),pack_count=len(packs),pack_bytes=sum(p['bytes'] for p in packs),unique_fragments=len(base.objects)+len(retained_objects)+len(store.objects))
    (out/'catalog.json').write_bytes(encoded(catalog))
    report=dict(source_files=dict(sources),resource_rules=[{k:v for k,v in x.items() if k!='_regex'} for x in rules],resource_exclusion_counts=dict(excluded_counts),resource_exclusion_shards=excluded.finish(),new_packs=len(retained_packs)+len(store.packs),new_pack_bytes=sum(p['bytes'] for p in retained_packs+store.packs),unchanged_unpublished_packs=len(retained_packs),repacked_unpublished_packs=len(store.packs),baseline_pack_bytes_unchanged=True,baseline_packs_retained=len(base.packs),physical_bytes_are_not_original_logical_size_or_push_traffic=True)
    report['previous_finalization_report']=previous
    (out/'reports'/('finalization-'+prefix+'.json')).write_bytes(encoded(report))
    (out/'reports/incremental-finalization.json').write_bytes(encoded(report));print(json.dumps(report))

if __name__=='__main__':main()
