"""Split the complete object index into independently verified small Git files."""
import argparse,gzip,hashlib,json,pathlib,re
from records import Records
from export_records import encoded

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=pathlib.Path,required=True);a=ap.parse_args();r=Records(a.root);folder=r.root/'manifests';shards=[];buffer=bytearray();rows=0
    previous={p.resolve() for p in folder.iterdir() if re.fullmatch(r'objects-\d{5}(?:-[0-9a-f]{16})?\.jsonl\.gz',p.name)}
    def flush():
        nonlocal buffer,rows
        if not buffer:return
        data=gzip.compress(buffer,compresslevel=9,mtime=0);assert len(data)<=25*1024*1024
        digest=hashlib.sha256(data).hexdigest();name='manifests/objects-'+str(len(shards)).zfill(5)+'-'+digest[:16]+'.jsonl.gz';target=r.root/name
        if target.exists():assert hashlib.sha256(target.read_bytes()).hexdigest()==digest
        else:target.write_bytes(data)
        shards.append(dict(path=name,bytes=len(data),sha256=digest,rows=rows));buffer=bytearray();rows=0
    for obj in r.objects.values():
        line=encoded(obj)+b'\n'
        if buffer and len(buffer)+len(line)>32*1024*1024:flush()
        buffer.extend(line);rows+=1
    flush();index=dict(format_version=1,objects=len(r.objects),shards=shards)
    temporary=folder/'object-index.json.partial';temporary.write_bytes(encoded(index));temporary.replace(folder/'object-index.json')
    # Only derived index files in this exact records directory are replaced.
    active={(r.root/s['path']).resolve() for s in shards}
    for p in previous-active:
        assert p.parent==folder.resolve();p.unlink()
    legacy=folder/'objects.jsonl.gz'
    if legacy.exists():legacy.unlink()
    checked=Records(r.root);assert checked.objects==r.objects
    print(json.dumps(dict(objects=len(r.objects),shards=len(shards),bytes=sum(s['bytes'] for s in shards),maximum_shard_bytes=max((s['bytes'] for s in shards),default=0),roundtrip_verified=True)))

if __name__=='__main__':main()
