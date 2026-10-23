"""List archived paths or extract one verified file without restoring the collection."""
import argparse,gzip,hashlib,json,os,pathlib,shutil,subprocess,tarfile,uuid

def rows(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:
        for line in f: yield json.loads(line)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace',type=pathlib.Path,required=True)
    ap.add_argument('--name',required=True)
    modes=ap.add_subparsers(dest='mode',required=True)
    listing=modes.add_parser('list')
    listing.add_argument('--prefix',default='')
    listing.add_argument('--limit',type=int,default=50)
    extract=modes.add_parser('extract')
    extract.add_argument('--path',required=True)
    extract.add_argument('--output',type=pathlib.Path,required=True)
    extract.add_argument('--restic',type=pathlib.Path,required=True)
    args=ap.parse_args()
    root=args.workspace.resolve(strict=True)
    run=root/'_objrun-archive/collections'/args.name
    if run.parent!=root/'_objrun-archive/collections': raise ValueError('Invalid collection name')
    record=json.loads((run/'record.json').read_text(encoding='utf-8-sig'))
    if not record.get('restore_verified'): raise ValueError('Collection has not passed restoration verification')
    manifest=run/'files-sha256.jsonl.gz'
    if args.mode=='list':
        if args.limit<1: raise ValueError('Limit must be positive')
        count=0
        for row in rows(manifest):
            if row['path'].startswith(args.prefix):
                print(json.dumps(row,ensure_ascii=False));count+=1
                if count>=args.limit: break
        return
    wanted=next((x for x in rows(manifest) if x['path']==args.path),None)
    if not wanted or 'sha256' not in wanted: raise ValueError('Path is not an archived regular file')
    # A selected hardlink can refer to an earlier TAR entry outside its directory.
    # Any regular entry with this verified content hash supplies the exact bytes.
    equivalents={x['path'] for x in rows(manifest) if x.get('sha256')==wanted['sha256'] and x.get('bytes')==wanted['bytes']}
    dest=args.output.absolute()
    if dest.exists() or dest.is_symlink(): raise ValueError('Output already exists; refusing overwrite')
    if dest.resolve().is_relative_to(root/'_objrun-archive'): raise ValueError('Cannot extract over archive storage')
    dest.parent.mkdir(parents=True,exist_ok=True)
    temporary=dest.with_name(dest.name+'.'+uuid.uuid4().hex+'.partial')
    base=[str(args.restic),'--repo',str(root/'_objrun-archive/restic'),'--no-cache','--insecure-no-password']
    tar_transport=record.get('transport')=='tar'
    inside='/payload.tar' if tar_transport else '/' + pathlib.Path(record['source']).as_posix().replace(':','').strip('/') + '/' + args.path
    proc=None
    try:
        with open(run/'last-single-extract.stderr.txt','wb') as err:
            proc=subprocess.Popen(base+['dump',record['snapshot'],inside],stdout=subprocess.PIPE,stderr=err)
            with temporary.open('xb') as out:
                if tar_transport:
                    found=False
                    with tarfile.open(fileobj=proc.stdout,mode='r|',bufsize=1024*1024) as tar:
                        for entry in tar:
                            if entry.name in equivalents and entry.isfile():
                                if entry.size!=wanted['bytes']: raise ValueError('Archive entry length differs')
                                with tar.extractfile(entry) as content: shutil.copyfileobj(content,out,1024*1024)
                                found=True;break
                    if not found: raise ValueError('Matching file content is missing')
                    # This is an intentional partial read of an already verified archive.
                    proc.terminate();proc.wait()
                else:
                    shutil.copyfileobj(proc.stdout,out,1024*1024)
                    if proc.wait(): raise RuntimeError('Restic file extraction failed')
            with temporary.open('rb') as f: sha=hashlib.file_digest(f,'sha256').hexdigest()
            if temporary.stat().st_size!=wanted['bytes'] or sha!=wanted['sha256']: raise RuntimeError('Extracted bytes do not match the verified manifest')
            # Creating this name fails atomically if another file appeared meanwhile.
            os.link(temporary,dest)
            temporary.unlink()
            print(json.dumps(dict(path=args.path,output=str(dest),bytes=wanted['bytes'],sha256=sha,verified=True),ensure_ascii=False))
    finally:
        if proc and proc.poll() is None: proc.kill();proc.wait()
        if temporary.exists(): temporary.unlink()

if __name__=='__main__': main()
