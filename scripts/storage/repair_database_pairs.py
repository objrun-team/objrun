"""Re-export explicitly evidenced SQLite pairs whose archive names lost WAL ownership."""
import argparse,copy,gzip,json,os,pathlib,shutil
from records import Records,database_exports
from export_records import Exporter,JsonShards,encoded,file_sha

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','work','workspace','blobs','pairs'):ap.add_argument('--'+name,type=pathlib.Path,required=True)
    a=ap.parse_args();r=Records(a.source);pairs=json.loads(a.pairs.read_text(encoding='utf-8'));assert not a.output.exists()
    x=Exporter(argparse.Namespace(workspace=a.workspace,output=a.output,work=a.work,compression_level=9));x.store.prefix='paired-db'
    replacements={};sidecars={};audit=[]
    wanted={(p['collection'],p[k]) for p in pairs for k in ('main','wal') if p.get(k)}
    entries={(e['collection'],e['path']):e for e in r.entries() if (e['collection'],e['path']) in wanted}
    assert len(entries)==len(wanted),'Pair map references absent records'
    for pair in pairs:
        collection=pair['collection'];main=entries[(collection,pair['main'])];wal=entries[(collection,pair['wal'])] if pair.get('wal') else None
        for entry in (main,wal):
            if entry is None:continue
            h=entry['source_sha256'];source=a.blobs/h;assert source.is_file() and file_sha(source)==h
            dest=x.db_blobs/h
            if not dest.exists():os.link(source,dest)
        result=x.database(collection,main['path'],dict(sha256=main['source_sha256'],bytes=main['source_bytes']),dict(sha256=wal['source_sha256'],bytes=wal['source_bytes']) if wal else None,main['bench'])
        assert result.get('integrity')=='ok' and not result.get('foreign_key_violation_count'),(main['path'],result.get('pending'))
        replacement={k:main[k] for k in ('collection','path','bench','run_scope','source_sha256','source_bytes')}
        replacement.update(result);replacement['pairing_evidence']=pair['evidence'];key=(collection,main['path'])
        if key in replacements:
            previous=replacements[key]
            def state(entry):
                return {k:v for k,v in entry.items() if k not in ('collection','path','bench','run_scope')}|{'path':'wal-'+str(entry.get('wal_sha256','none'))}
            if previous.get('format')!='archive-members':
                wrapper={k:main[k] for k in ('collection','path','bench','run_scope','source_sha256','source_bytes')}
                wrapper.update(disposition='retained',format='archive-members',members=[state(previous)],transformations={'sqlite_multiple_wal_states':True})
                replacements[key]=previous=wrapper
            member=state(replacement)
            if not any(m['path']==member['path'] for m in previous['members']):previous['members'].append(member)
        else:replacements[key]=replacement
        for path in [pair.get('wal')]+pair.get('shm',[]):
            if path:sidecars[(collection,path)]=main['path']
        audit.append(dict(collection=collection,main=main['path'],source_database_sha256=main['source_sha256'],wal_sha256=wal['source_sha256'] if wal else None,tables=len(result['tables']),rows=sum(t.get('exported_rows',0) for t in result['tables']),integrity='ok',foreign_key_violations=0,evidence=pair['evidence']))
    expected={(p['collection'],p['main'],entries[(p['collection'],p['wal'])]['source_sha256'] if p.get('wal') else None) for p in pairs}
    actual={(collection,path,db.get('wal_sha256')) for (collection,path),entry in replacements.items() for db in database_exports(entry)}
    assert actual==expected,'A main snapshot lost one of its evidenced WAL states'
    streams={}
    for e in r.entries():
        key=(e['collection'],e['path'])
        if key in replacements:e=replacements[key]
        elif key in sidecars:e={k:e[k] for k in ('collection','path','bench','run_scope','source_sha256','source_bytes')}|dict(disposition='retained',format='sqlite-sidecar-reference',paired_with=sidecars[key])
        streams.setdefault(e['collection'],JsonShards(a.output,e['collection'])).write(e)
    x.store.finish()
    for name in r.packs:os.link(r.root/name,a.output/name)
    (a.output/'manifests/packs.json').write_bytes(encoded(list(r.packs.values())+x.store.packs))
    with gzip.open(a.output/'manifests/objects.jsonl.gz','wb') as f:
        for h,v in r.objects.items():f.write(encoded(v)+b'\n')
        for h,v in x.store.objects.items():
            if h not in r.objects:f.write(encoded(dict(sha256=h,**v))+b'\n')
    catalog=copy.deepcopy(r.catalog)
    for c in catalog['collections']:c['manifest_shards']=streams[c['collection']].finish()
    (a.output/'catalog.json').write_bytes(encoded(catalog));(a.output/'reports/database-pair-repair.json').write_bytes(encoded(audit))
    print(json.dumps(dict(pairs=len(audit),rows=sum(v['rows'] for v in audit),sidecars=len(sidecars))))

if __name__=='__main__':main()
