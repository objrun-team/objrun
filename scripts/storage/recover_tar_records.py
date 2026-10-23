"""Recover available members from damaged TAR transports, recording source truncation."""
import argparse,collections,copy,gzip,io,json,os,pathlib,tarfile,zlib
from records import Records
from export_records import Exporter,JsonShards,encoded,sha,magic,is_tar_header,path_policy

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','work','workspace','originals'):ap.add_argument('--'+name,type=pathlib.Path,required=True)
    ap.add_argument('--resource-hashes',type=pathlib.Path)
    a=ap.parse_args();r=Records(a.source);out=a.output.resolve();assert not out.exists()
    resources=json.loads(a.resource_hashes.read_text(encoding='utf-8')) if a.resource_hashes else {}
    x=Exporter(argparse.Namespace(workspace=a.workspace,output=out,work=a.work,compression_level=9));x.store.prefix='recovered-tar'
    manifests={};audit=[]
    for entry in r.entries():
        e=copy.deepcopy(entry)
        if e.get('pending') and e.get('format') in ('archive-review-required','partial-archive-review-required') and e.get('source_sha256') not in resources:
            original=a.originals/e['source_sha256']
            blob=b''.join(r.parts(e['content'])) if 'content' in e else original.read_bytes() if original.exists() else None
            issues=[];compression=None
            if blob is not None:
                assert sha(blob)==e['source_sha256']
                if blob.startswith(b'\x1f\x8b'):
                    compression='gzip';decoder=zlib.decompressobj(31);chunks=[]
                    try:
                        for start in range(0,len(blob),1024*1024):chunks.append(decoder.decompress(blob[start:start+1024*1024]))
                        chunks.append(decoder.flush())
                        if not decoder.eof:issues.append(dict(compression_error='truncated-gzip'))
                    except zlib.error as ex:issues.append(dict(compression_error=str(ex)))
                    blob=b''.join(chunks)
            if blob is not None and is_tar_header(blob):
                members=[];excluded=collections.Counter()
                try:
                    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:',ignore_zeros=True) as tar:
                        for m in tar:
                            if not m.isfile():continue
                            available=max(0,min(m.size,len(blob)-m.offset_data));partial=available<m.size
                            raw=blob[m.offset_data:m.offset_data+available]
                            reason=path_policy(e['collection'],m.name)
                            if reason:excluded[reason]+=1
                            else:
                                result=x.process_payload(raw,e['collection'],e['path']+'!/'+m.name,e['bench'])
                                if result.get('disposition')=='excluded':excluded[result['reason']]+=1
                                else:
                                    member=dict(path=m.name,source_bytes=len(raw),source_sha256=sha(raw),**result)
                                    if partial:member['source_truncation']=dict(declared_bytes=m.size,available_bytes=available,complete=False)
                                    members.append(member)
                            if partial:issues.append(dict(member=m.name,declared_bytes=m.size,available_bytes=available,kind=magic(raw[:4096])));break
                except (tarfile.TarError,EOFError,OSError) as ex:issues.append(dict(parser_error=type(ex).__name__))
                result=x.finish_archive(members,e['collection'],e['path'],e['bench'],'tar-with-damaged-header-recovery',excluded)
                for k in ('pending','content','format','disposition','transformations'):e.pop(k,None)
                e.update(result);e['source_transport_recovery']=dict(original_export_error=entry['pending'],ignore_invalid_tar_headers=True,source_complete=not issues,compression=compression,issues=issues)
                audit.append(dict(collection=e['collection'],path=e['path'],source_sha256=e['source_sha256'],retained_members=len(members),excluded=dict(excluded),issues=issues))
            else:audit.append(dict(collection=e['collection'],path=e['path'],recovery='not_attempted',reason='original unavailable or not an uncompressed TAR'))
        manifests.setdefault(e['collection'],JsonShards(out,e['collection'])).write(e)
    x.store.finish()
    for name in r.packs:os.link(r.root/name,out/name)
    packs=list(r.packs.values())+x.store.packs;(out/'manifests/packs.json').write_bytes(encoded(packs))
    with gzip.open(out/'manifests/objects.jsonl.gz','wt',encoding='utf-8') as f:
        for h,v in r.objects.items():f.write(json.dumps(v)+'\n')
        for h,v in x.store.objects.items():
            if h not in r.objects:f.write(json.dumps(dict(sha256=h,**v))+'\n')
    # Shared old fragments remain authoritative; redundant newly recovered copies
    # are pruned by the following append step, which stores only referenced hashes.
    catalog=copy.deepcopy(r.catalog)
    for c in catalog['collections']:c['manifest_shards']=manifests[c['collection']].finish()
    (out/'catalog.json').write_bytes(encoded(catalog));(out/'reports/tar-recovery.json').write_bytes(encoded(audit))
    print(json.dumps(dict(transports=len(audit),retained_members=sum(v.get('retained_members',0) for v in audit),incomplete_transports=sum(bool(v.get('issues')) for v in audit))))

if __name__=='__main__':main()
