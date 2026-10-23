"""Read every archived file back through Restic and compare SHA-256 to its source.

Streams a TAR restore without allocating a second expanded copy. Never deletes
source files. Successful verification is required by retire_collection.ps1.
"""
import argparse, gzip, hashlib, json, pathlib, sqlite3, subprocess, tarfile, time
from archive_collection import manifest,same_file_inventory

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace',type=pathlib.Path,required=True)
    ap.add_argument('--name',required=True)
    ap.add_argument('--restic',type=pathlib.Path,required=True)
    args=ap.parse_args()
    workspace=args.workspace.resolve(strict=True)
    run=workspace/'_objrun-archive/collections'/args.name
    if run.parent != workspace/'_objrun-archive/collections': raise ValueError('Invalid name')
    record=json.loads((run/'record.json').read_text(encoding='utf-8'))
    if not record.get('coverage_verified') or not record.get('integrity_verified') or record.get('source_removed'):
        raise ValueError('Collection not ready for source comparison')
    source=pathlib.Path(record['source']).resolve(strict=True)
    if source==workspace or (not source.is_relative_to(workspace) and not record.get('external_readonly')): raise ValueError('Source outside workspace')
    before={}
    with gzip.open(run/'source-before.jsonl.gz','rt',encoding='utf-8') as f:
        for line in f:
            row=json.loads(line)
            if row['kind']!='dir': before[row['path']]=row
    cache=sqlite3.connect(workspace/'_objrun-archive/file-hash-cache.sqlite')
    cache.execute('create table if not exists hashes (identity text, size integer, mtime integer, sha256 text, primary key(identity,size,mtime))')
    archive_prefix='/' + source.as_posix().replace(':','').strip('/')
    base=[str(args.restic),'--repo',str(workspace/'_objrun-archive/restic'),'--no-cache','--insecure-no-password']
    seen={}
    total=0
    last=time.time()
    captured={}
    if record.get('transport')=='tar':
        with gzip.open(run/'captured-sha256.jsonl.gz','rt',encoding='utf-8') as f:
            for line in f:
                row=json.loads(line)
                if 'sha256' in row: captured[row['path']]=row['sha256']
    def source_hash(path, expected):
        p=source/path
        st=p.stat(follow_symlinks=False)
        if st.st_size!=expected['size'] or st.st_mtime_ns!=expected['mtime_ns'] or st.st_file_attributes & 1024:
            raise RuntimeError('Source changed: '+path)
        key=(f'{st.st_dev}:{st.st_ino}',st.st_size,st.st_mtime_ns)
        old=cache.execute('select sha256 from hashes where identity=? and size=? and mtime=?',key).fetchone()
        if old: return old[0]
        with p.open('rb') as f: sha=hashlib.file_digest(f,'sha256').hexdigest()
        now=p.stat(follow_symlinks=False)
        if (now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns)!=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns):
            raise RuntimeError('Changed during hash: '+path)
        cache.execute('insert into hashes values(?,?,?,?)',(*key,sha))
        return sha
    with open(run/'restore-stream.stderr.txt','wb') as err, gzip.open(run/'files-sha256.jsonl.gz','wt',encoding='utf-8',newline='\n') as hashes:
        dump=[record['snapshot'],'/payload.tar'] if record.get('transport')=='tar' else [record['snapshot']+':'+archive_prefix,'/']
        proc=subprocess.Popen(base+['dump']+dump,stdout=subprocess.PIPE,stderr=err)
        try:
            with tarfile.open(fileobj=proc.stdout,mode='r|',bufsize=1024*1024) as archive:
                for member in archive:
                    name=member.name.lstrip('/').removeprefix('./').rstrip('/')
                    if member.isdir(): continue
                    if name not in before or name in seen:
                        raise RuntimeError('Unexpected/repeated restored path: '+name)
                    expected=before[name]
                    if member.issym():
                        if expected['kind']!='link': raise RuntimeError('Unexpected symlink: '+name)
                        if member.linkname!=expected['target']: raise RuntimeError('Symlink target differs: '+name)
                        metadata={k:expected[k] for k in ('reparse_tag','reparse_data_b64') if k in expected}
                        for k,v in metadata.items():
                            if member.pax_headers.get('objrun.'+k)!=v: raise RuntimeError('Reparse metadata differs: '+name)
                        seen[name]=None
                        hashes.write(json.dumps(dict(path=name,kind='link',target=expected['target'],archived_target=member.linkname,**metadata),ensure_ascii=False)+'\n')
                        continue
                    if expected['kind']!='file': raise RuntimeError('Expected a link: '+name)
                    if member.islnk():
                        target=member.linkname.lstrip('/').removeprefix('./')
                        restored=seen.get(target)
                        if not restored: raise RuntimeError('Unknown restored hardlink: '+target)
                    elif member.isfile():
                        if member.size!=expected['size']: raise RuntimeError('Restored length differs: '+name)
                        with archive.extractfile(member) as f: restored=hashlib.file_digest(f,'sha256').hexdigest()
                    else:
                        raise RuntimeError('Unsupported restored file type: '+name)
                    original=captured[name] if record.get('transport')=='tar' else source_hash(name,expected)
                    if original!=restored: raise RuntimeError('Restored SHA-256 mismatch: '+name)
                    seen[name]=restored
                    total+=expected['size']
                    hashes.write(json.dumps(dict(path=name,bytes=expected['size'],sha256=restored),ensure_ascii=False,separators=(',',':'))+'\n')
                    if time.time()-last>20:
                        cache.commit()
                        print(json.dumps(dict(phase='restore-and-sha256',files=len(seen),total_files=len(before),bytes=total)),flush=True)
                        last=time.time()
            # Consume TAR padding so the child can exit normally.
            while proc.stdout.read(1024*1024): pass
            if proc.wait(): raise RuntimeError('Restic dump failed; see restore-stream.stderr.txt')
            if seen.keys()!=before.keys(): raise RuntimeError('Restore is missing source paths')
            cache.commit()
            after=manifest(source,run/'source-verified.jsonl.gz',record.get('excluded',[]))
            if after!=record['before'] and not same_file_inventory(run/'source-before.jsonl.gz',run/'source-verified.jsonl.gz'):
                raise RuntimeError('Source changed during verification')
            record.update(status='verified',restore_verified=True,restored_files=len(seen),restored_bytes=total,
                          verified_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
            (run/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(dict(phase='verified',name=args.name,files=len(seen),bytes=total)),flush=True)
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        finally:
            cache.close()

if __name__=='__main__': main()
