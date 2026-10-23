"""Internal TAR transport for Restic. Stdout is binary; never run in a console.

Preserves each file's bytes and path; hashes while reading. Hardlinks are emitted
only for the same current file identity, size and mtime within this collection.
"""
import argparse,collections,concurrent.futures,gzip,hashlib,io,json,os,pathlib,sys,tarfile
from windows_reparse import read_link_metadata

class HashReader:
    def __init__(self,f): self.f=f; self.h=hashlib.sha256()
    def read(self,n=-1):
        b=self.f.read(n);self.h.update(b);return b

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source',required=True,type=pathlib.Path)
    ap.add_argument('--manifest',required=True,type=pathlib.Path)
    ap.add_argument('--hashes',required=True,type=pathlib.Path)
    args=ap.parse_args()
    root=args.source.resolve(strict=True)
    seen={}
    def preload(row):
        p=root/row['path']
        with p.open('rb') as f:
            st=os.fstat(f.fileno())
            key=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
            if st.st_size!=row['size'] or st.st_mtime_ns!=row['mtime_ns']: raise RuntimeError('Source changed: '+row['path'])
            data=f.read()
            after=os.fstat(f.fileno())
            if len(data)!=row['size'] or (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=key:
                raise RuntimeError('Source changed during read: '+row['path'])
        return data,hashlib.sha256(data).hexdigest(),key,st.st_mode & 0o777,st.st_nlink
    def prefetched(rows):
        # Bounded small-file prefetch avoids serial Windows open/read latency.
        # At most 64 MiB of file contents can be queued, with 16 readers.
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            pending=collections.deque()
            def queue(line):
                row=json.loads(line)
                future=pool.submit(preload,row) if row['kind']=='file' and 0<row['size']<=1024*1024 else None
                pending.append((row,future))
            for _ in range(64):
                line=next(rows,None)
                if line is None: break
                queue(line)
            while pending:
                row,future=pending.popleft()
                yield row,future.result() if future else None
                line=next(rows,None)
                if line is not None: queue(line)
    with gzip.open(args.manifest,'rt',encoding='utf-8') as rows,gzip.open(args.hashes,'wt',encoding='utf-8',newline='\n') as hashes,tarfile.open(fileobj=sys.stdout.buffer,mode='w|',bufsize=1024*1024,copybufsize=1024*1024,format=tarfile.PAX_FORMAT) as tar:
        for row,preloaded in prefetched(iter(rows)):
            rel=pathlib.PurePosixPath(row['path'])
            if rel.is_absolute() or '..' in rel.parts: raise ValueError('Unsafe source path')
            p=root/rel
            info=tarfile.TarInfo(row['path'])
            info.mtime=row['mtime_ns']//1000000000
            info.pax_headers={'mtime':f"{info.mtime}.{row['mtime_ns']%1000000000:09d}"}
            info.mode=0o755 if row['kind']=='dir' else 0o644
            if row['kind']=='dir':
                info.type=tarfile.DIRTYPE;tar.addfile(info);continue
            if row['kind']=='link':
                metadata=read_link_metadata(p)
                if any(row.get(k)!=v for k,v in metadata.items()): raise RuntimeError('Link changed: '+row['path'])
                for key in ('reparse_tag','reparse_data_b64'):
                    if key in metadata: info.pax_headers['objrun.'+key]=metadata[key]
                info.type=tarfile.SYMTYPE;info.linkname=row['target'];tar.addfile(info)
                hashes.write(json.dumps(dict(path=row['path'],kind='link',**metadata),ensure_ascii=False)+'\n')
                continue
            if row['size']==0:
                info.size=0;tar.addfile(info)
                hashes.write(json.dumps(dict(path=row['path'],bytes=0,sha256=hashlib.sha256(b'').hexdigest()),ensure_ascii=False,separators=(',',':'))+'\n')
                continue
            if preloaded:
                data,sha,key,mode,nlink=preloaded
                info.mode=mode
                if key in seen:
                    info.type=tarfile.LNKTYPE;info.linkname=seen[key][0];tar.addfile(info)
                else:
                    info.size=row['size'];tar.addfile(info,io.BytesIO(data))
                    if nlink>1: seen[key]=(row['path'],sha)
                hashes.write(json.dumps(dict(path=row['path'],bytes=row['size'],sha256=sha),ensure_ascii=False,separators=(',',':'))+'\n')
                continue
            with p.open('rb') as f:
                st=os.fstat(f.fileno())
                info.mode=st.st_mode & 0o777
                if st.st_size!=row['size'] or st.st_mtime_ns!=row['mtime_ns']:
                    raise RuntimeError('File changed before archive: '+row['path'])
                key=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
                if key in seen:
                    link,sha=seen[key]
                    info.type=tarfile.LNKTYPE;info.linkname=link;tar.addfile(info)
                else:
                    reader=HashReader(f)
                    info.size=row['size'];tar.addfile(info,reader)
                    sha=reader.h.hexdigest()
                    if st.st_nlink>1: seen[key]=(row['path'],sha)
                after=os.fstat(f.fileno())
                if (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=key:
                    raise RuntimeError('File changed during archive: '+row['path'])
            hashes.write(json.dumps(dict(path=row['path'],bytes=row['size'],sha256=sha),ensure_ascii=False,separators=(',',':'))+'\n')

if __name__=='__main__': main()
