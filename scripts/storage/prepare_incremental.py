"""Prepare a source export for append-only ingestion, with explicit unreadable evidence."""
import argparse,copy,json,os,pathlib,collections,gzip,shutil,re
from records import Records,contents,database_exports
from append_records import problems
from export_records import JsonShards,encoded,reviewed_resource_match

def key(collection,path):return json.dumps([collection,path],separators=(',',':'))

def export_signature(entry):
    return (entry.get('format'),tuple((d.get('source_database_sha256'),d.get('wal_sha256')) for d in database_exports(entry)),tuple((c['sha256'],c['bytes']) for c in contents(entry)))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('base','export','output'):ap.add_argument('--'+name,type=pathlib.Path,required=True)
    ap.add_argument('--label',required=True);ap.add_argument('--resource-hashes',type=pathlib.Path);ap.add_argument('--rules',type=pathlib.Path);args=ap.parse_args()
    base=Records(args.base);source=Records(args.export);out=args.output.resolve()
    assert not out.exists() and not out.is_relative_to(source.root) and not out.is_relative_to(base.root)
    for name in ('packs','manifests','reports','runs','summaries'):(out/name).mkdir(parents=True,exist_ok=True)
    known={};existing={c['collection'] for c in base.catalog['collections']}
    origins={c.get('source_collection',c['collection']) for c in source.catalog['collections']}
    for c in base.catalog['collections']:
        if c.get('source_collection',c['collection']) not in origins:continue
        for e in base.entries(c['collection']):known[key(e.get('source_collection',e['collection']),e['path'])]=(e.get('source_sha256'),bool(list(problems(e))),e['collection'],export_signature(e))
    streams={};counts=collections.Counter();skipped=collections.Counter();overrides={};gaps=[];excluded=[]
    resources=json.loads(args.resource_hashes.read_text(encoding='utf-8')) if args.resource_hashes else {}
    rules=json.loads(args.rules.read_text(encoding='utf-8')) if args.rules else []
    for rule in rules:rule['_regex']=re.compile(rule['pattern'],re.I)
    def clean(value,origin,location):
        if isinstance(value,dict):
            for rule in rules:
                if (not rule.get('collection') or rule['collection']==origin) and rule['_regex'].search(location) and ('content' in value or 'members' in value or 'tables' in value or value.get('pending')):
                    excluded.append(dict(collection=origin,path=location,source_sha256=value.get('source_sha256'),source_bytes=value.get('source_bytes'),evidence={k:v for k,v in rule.items() if k!='_regex'}))
                    return {k:v for k,v in value.items() if k in ('path','source_sha256','source_bytes')}|{'disposition':'excluded','format':'resource-reference','reason':rule['reason']}
            if reviewed_resource_match(value,resources):
                excluded.append(dict(collection=origin,path=location,source_sha256=value['source_sha256'],source_bytes=value.get('source_bytes'),evidence=resources[value['source_sha256']]))
                return {k:v for k,v in value.items() if k in ('path','source_sha256','source_bytes')}|{'disposition':'excluded','format':'resource-reference','reason':'content-reviewed exclusion; see preparation report'}
            if value.get('pending') or value.get('disposition')=='pending-database':
                gaps.append(dict(collection=origin,path=location,reason=value.get('pending','nested database not exported'),source_sha256=value.get('source_sha256'),source_bytes=value.get('source_bytes')))
                return {k:v for k,v in value.items() if k in ('path','source_sha256','source_bytes')}|{'disposition':'unreadable','format':'unavailable-source','reason':'See reports/incremental-preparation.json; original preserved'}
            return {k:clean(v,origin,location+('!/'+v.get('path','') if isinstance(v,dict) else '')) for k,v in value.items()}
        if isinstance(value,list):return [clean(x,origin,location+('!/'+x.get('path','') if isinstance(x,dict) else '')) for x in value]
        return value
    for entry in source.entries():
        original=entry['collection'];lookup=key(original,entry['path']);prior=known.get(lookup)
        e=clean(copy.deepcopy(entry),original,entry['path'])
        if prior and prior[0]==entry.get('source_sha256') and not prior[1] and prior[3]==export_signature(e):skipped[original]+=1;continue
        if not list(contents(e)) and not list(database_exports(e)) and e.get('format')!='sqlite-sidecar-reference':
            if e.get('format')=='archive-members':excluded.append(dict(collection=original,path=e['path'],source_sha256=e.get('source_sha256'),source_bytes=e.get('source_bytes'),evidence={'reason':'resource-only or empty archive; no selected record body','excluded_member_counts':e.get('excluded_member_counts',{})}))
            skipped[original]+=1;continue
        name=original+'-supplement-'+args.label if original in existing else original
        e['collection']=name;e['source_collection']=original
        streams.setdefault(name,JsonShards(out,name)).write(e);counts[name]+=1
        if prior:overrides[key(prior[2],e['path'])]=[name,e['path']]
    catalog=copy.deepcopy(source.catalog);catalog['collections']=[];catalog['errors']=[];catalog['pending']=0
    for c in source.catalog['collections']:
        original=c['collection'];name=original+'-supplement-'+args.label if original in existing else original
        new=copy.deepcopy(c);new['collection']=name;new['source_collection']=original;new['manifest_shards']=streams[name].finish() if name in streams else []
        catalog['collections'].append(new)
    for sub in ('packs','manifests'):
        for p in (source.root/sub).iterdir():
            if sub=='manifests' and p.name not in ('packs.json','objects.jsonl.gz'):continue
            os.link(p,out/sub/p.name)
    if not (out/'manifests/objects.jsonl.gz').exists():
        with gzip.open(out/'manifests/objects.jsonl.gz','wb') as f:
            for obj in source.objects.values():f.write(encoded(obj)+b'\n')
    report=dict(label=args.label,selected=dict(counts),already_retained_or_no_readable_content=dict(skipped),entry_overrides=overrides,unreadable=gaps,resource_exclusions=excluded,failed_sources=source.catalog.get('errors',[]),originals_preserved=True)
    (out/'catalog.json').write_bytes(encoded(catalog));(out/'reports/incremental-preparation.json').write_bytes(encoded(report))
    recovery=source.root/'reports/tar-recovery.json'
    if recovery.exists():(out/'reports/tar-recovery.json').write_bytes(recovery.read_bytes())
    for report_name in ('database-pair-repair','embedded-payload-curation'):
        p=source.root/'reports'/(report_name+'.json')
        if not p.exists():continue
        shutil.copyfile(p,out/'reports'/p.name);value=json.loads(p.read_text(encoding='utf-8'))
        if isinstance(value,dict):
            for shard in value.get('transformation_shards',[]):shutil.copyfile(source.root/shard['path'],out/shard['path'])
    print(json.dumps({k:v for k,v in report.items() if k not in ('entry_overrides','unreadable','resource_exclusions')}|{'override_count':len(overrides),'unreadable_count':len(gaps),'resource_exclusion_count':len(excluded)}))

if __name__=='__main__':main()
