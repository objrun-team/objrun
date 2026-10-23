"""Retry a source using content-addressed staging exports as a read-only cache.

The result is an export staging directory. Append/curate it before publishing:
cached physical packs can contain unreferenced fragments and overlapping copies.
"""
import argparse,copy,gzip,json,os,pathlib,gc
from export_records import Exporter,magic
from records import Records,contents
from append_records import problems

def unavailable(v):
    if isinstance(v,dict):return v.get('format')=='unavailable-source' or any(unavailable(x) for x in v.values())
    if isinstance(v,list):return any(unavailable(x) for x in v)
    return False

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('workspace','restic','output','work'):ap.add_argument('--'+name,type=pathlib.Path,required=True)
    ap.add_argument('--reuse-records',type=pathlib.Path,nargs='+',required=True);ap.add_argument('--only',nargs='+',required=True);ap.add_argument('--compression-level',type=int,default=9)
    a=ap.parse_args();a.workers=1;a.small_first=False;a.skip=None;a.benches=None
    wanted=set()
    for name in a.only:
        with gzip.open(a.workspace/'_objrun-archive/collections'/name/'files-sha256.jsonl.gz','rt',encoding='utf-8') as f:
            for line in f:
                row=json.loads(line)
                if row.get('sha256'):wanted.add(row['sha256'])
    x=Exporter(a);x.store.prefix='retry';readers=[];stats=[]
    fields={'collection','path','bench','run_scope','source_sha256','source_bytes','source_collection'}
    for i,folder in enumerate(a.reuse_records):
        r=Records(folder);readers.append(r);names={}
        for name,proof in r.packs.items():
            target='packs/reuse'+str(i)+'-'+pathlib.PurePosixPath(name).name
            os.link(r.root/name,x.root/target);p=copy.deepcopy(proof);p['path']=target;x.store.packs.append(p);names[name]=target
        for h,obj in r.objects.items():x.store.objects.setdefault(h,dict(pack=names[obj['pack']],bytes=obj['bytes']))
        before=len(x.cache)
        for e in r.entries():
            h=e.get('source_sha256')
            if h not in wanted or h in x.cache or e.get('format')=='sqlite-tables' or list(problems(e)) or unavailable(e):continue
            if any(part not in x.store.objects for c in contents(e) for part in c['parts']):continue
            x.cache[h]={k:v for k,v in e.items() if k not in fields}
        stats.append(dict(root=str(folder),reused_source_payloads=len(x.cache)-before))
    # Small untransformed text files can be recovered directly by their original
    # content hash even if writing their source manifest was interrupted.
    recovered=0
    for r in readers:
        groups={}
        for h in wanted & r.objects.keys():
            if h not in x.cache:groups.setdefault(r.objects[h]['pack'],set()).add(h)
        for name,hashes in groups.items():
            r.load_pack(name)
            for h in hashes:
                data=r.cache[h]
                if magic(data[:4096])!='text':continue
                x.cache[h]=dict(disposition='retained',**x.transform_text(data,'shared-or-unassigned'));recovered+=1
    (x.root/'reports/retry-cache.json').write_text(json.dumps(dict(reuse=stats,recovered_original_small_texts=recovered,staging_requires_append_before_publication=True),indent=2),encoding='utf-8')
    print(json.dumps(dict(reused_payloads=len(x.cache),recovered_original_small_texts=recovered)),flush=True)
    # Reader decompression caches are no longer needed during the sequential
    # source pass; release them before opening potentially large archive members.
    for reader in readers:reader.lru.clear();reader.cache.clear();reader.objects.clear()
    readers.clear();r=None;reader=None;wanted.clear();groups.clear();gc.collect()
    x.run()

if __name__=='__main__':main()
