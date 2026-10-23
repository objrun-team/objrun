"""Restore a collection into a new directory and verify every file's SHA-256.

No existing directory is overwritten. Symlinks/junctions are recorded separately
in restored-links.json; they are not followed or created outside the destination.
Use the original source location as destination when old absolute references are
required. An empty/missing source directory can be restored in place explicitly.
"""
import argparse,decimal,gzip,hashlib,json,os,pathlib,shutil,subprocess,tarfile

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace',type=pathlib.Path,required=True)
    ap.add_argument('--name',required=True)
    ap.add_argument('--restic',type=pathlib.Path,required=True)
    ap.add_argument('--destination',type=pathlib.Path,required=True)
    ap.add_argument('--merge-existing',action='store_true',help='Allow a nonempty destination; existing files must have the expected SHA-256')
    args=ap.parse_args()
    root=args.workspace.resolve(strict=True)
    run=root/'_objrun-archive/collections'/args.name
    if run.parent!=root/'_objrun-archive/collections': raise ValueError('Invalid collection name')
    record=json.loads((run/'record.json').read_text(encoding='utf-8-sig'))
    if not record.get('restore_verified'): raise ValueError('Archive has not been verified')
    dest=args.destination.resolve()
    if dest.exists() and (not dest.is_dir() or (any(dest.iterdir()) and not args.merge_existing)): raise ValueError('Destination must be new or empty unless --merge-existing is specified')
    if dest.is_relative_to(root/'_objrun-archive'): raise ValueError('Cannot restore over archive storage')
    dest.mkdir(parents=True,exist_ok=True)
    expected={}
    links={}
    link_metadata={}
    with gzip.open(run/'files-sha256.jsonl.gz','rt',encoding='utf-8') as f:
        for line in f:
            row=json.loads(line)
            if row.get('kind')=='link':
                links[row['path']]=row['target'];link_metadata[row['path']]=row
            else: expected[row['path']]=row
    for name,row in expected.items():
        p=dest/name
        if not p.resolve().is_relative_to(dest): raise ValueError('Existing path escapes destination')
        if p.exists():
            if not p.is_file() or p.is_symlink(): raise ValueError('Existing path has a different type')
            with p.open('rb') as f: sha=hashlib.file_digest(f,'sha256').hexdigest()
            if sha!=row['sha256']: raise ValueError('Existing file differs; refusing overwrite: '+name)
    base=[str(args.restic),'--repo',str(root/'_objrun-archive/restic'),'--no-cache','--insecure-no-password']
    if record.get('transport')!='tar':
        prefix='/' + pathlib.Path(record['source']).as_posix().replace(':','').strip('/')
        subprocess.run(base+['restore',record['snapshot']+':'+prefix,'--target',str(dest),'--overwrite','never','--verify'],check=True)
    else:
        with open(run/'last-restore.stderr.txt','wb') as err:
            proc=subprocess.Popen(base+['dump',record['snapshot'],'/payload.tar'],stdout=subprocess.PIPE,stderr=err)
            try:
                with tarfile.open(fileobj=proc.stdout,mode='r|',bufsize=1024*1024) as tar:
                    for entry in tar:
                        rel=pathlib.PurePosixPath(entry.name)
                        if rel.is_absolute() or '..' in rel.parts: raise ValueError('Unsafe archive path')
                        p=dest/rel
                        if not p.resolve().is_relative_to(dest): raise ValueError('Entry escaped destination')
                        if entry.isdir(): p.mkdir(parents=True,exist_ok=True);continue
                        if entry.issym():
                            if links.get(entry.name)!=entry.linkname: raise ValueError('Link manifest mismatch')
                            continue
                        if entry.name not in expected: raise ValueError('Unexpected archive file')
                        p.parent.mkdir(parents=True,exist_ok=True)
                        if p.exists(): continue
                        if entry.islnk():
                            link=pathlib.PurePosixPath(entry.linkname)
                            if link.is_absolute() or '..' in link.parts: raise ValueError('Unsafe hardlink')
                            target=(dest/link).resolve(strict=True)
                            if not target.is_relative_to(dest): raise ValueError('Hardlink escaped destination')
                            os.link(target,p)
                        elif entry.isfile():
                            with tar.extractfile(entry) as source,p.open('xb') as out: shutil.copyfileobj(source,out,1024*1024)
                        else: raise ValueError('Unsupported archive entry')
                        ns=int(decimal.Decimal(str(entry.pax_headers.get('mtime',entry.mtime)))*1000000000)
                        os.utime(p,ns=(ns,ns))
                        os.chmod(p,entry.mode)
                while proc.stdout.read(1024*1024): pass
                if proc.wait(): raise RuntimeError('Archive extraction failed')
            except BaseException:
                proc.kill();proc.wait();raise
    count=0
    for name,row in expected.items():
        p=dest/name
        if p.stat().st_size!=row['bytes']: raise RuntimeError('Restored length differs: '+name)
        with p.open('rb') as f: actual=hashlib.file_digest(f,'sha256').hexdigest()
        if actual!=row['sha256']: raise RuntimeError('Restored SHA-256 differs: '+name)
        count+=1
    if links:
        (run/'last-restored-links.json').write_text(json.dumps(dict(destination=str(dest),links=links,metadata=link_metadata),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(restored_files=count,sha256_verified=True,links_recorded=len(links),destination=str(dest))))

if __name__=='__main__': main()
