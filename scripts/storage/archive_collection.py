"""Create and verify a local Restic collection. Never deletes source files.

Requires restic >= 0.19.1. The local archive uses an empty password deliberately;
filesystem access controls apply just as they did to the original experiment files.
No network backend or upload is used.
"""
import argparse, gzip, hashlib, itertools, json, os, pathlib, shutil, subprocess, sys, time
from windows_reparse import read_link_metadata

def same_file_inventory(before_path,after_path):
    """Require identical paths/types/file metadata; directory mtime may settle later.

    Exact inventories remain on disk. Only directory timestamps are ignored here;
    file/link timestamps, lengths, targets and raw reparse metadata must all match.
    """
    with gzip.open(before_path,'rt',encoding='utf-8') as left,gzip.open(after_path,'rt',encoding='utf-8') as right:
        for a,b in itertools.zip_longest(left,right):
            if a is None or b is None:return False
            first=json.loads(a);second=json.loads(b)
            if first['kind']=='dir':first.pop('mtime_ns',None)
            if second['kind']=='dir':second.pop('mtime_ns',None)
            if first!=second:return False
    return True

def manifest(root, output, exclude=()):
    count = size = links = 0
    h = hashlib.sha256()
    with gzip.open(output, 'wt', encoding='utf-8', newline='\n') as out:
        def visit(directory):
            nonlocal count, size, links
            with os.scandir(directory) as it:
                entries = sorted(it, key=lambda e: e.name)
            for e in entries:
                rel = pathlib.Path(e.path).relative_to(root).as_posix()
                if rel in exclude: continue
                st = e.stat(follow_symlinks=False)
                reparse = bool(getattr(st, 'st_file_attributes', 0) & 1024)
                kind = 'link' if reparse else ('dir' if e.is_dir(follow_symlinks=False) else 'file')
                row = dict(path=rel, kind=kind, size=st.st_size if kind == 'file' else 0,
                           mtime_ns=st.st_mtime_ns)
                if kind == 'link':
                    row.update(read_link_metadata(e.path))
                    links += 1
                line = json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':')) + '\n'
                h.update(line.encode('utf-8'))
                out.write(line)
                if kind == 'file':
                    count += 1
                    size += st.st_size
                elif kind == 'dir':
                    visit(e.path)
        visit(root)
    return dict(files=count, bytes=size, links=links, manifest_sha256=h.hexdigest())

def command(argv, log, parse_summary=False):
    print(json.dumps(dict(phase='command', command=argv[argv.index('--insecure-no-password')+1:])),flush=True)
    summary = None
    last = 0
    with open(log,'w',encoding='utf-8') as out:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        for line in p.stdout:
            out.write(line)
            out.flush()
            try:
                row = json.loads(line)
            except ValueError:
                if 'error' in line.lower() or 'fatal' in line.lower():
                    print(line.rstrip(),flush=True)
                continue
            if row.get('message_type') == 'summary':
                summary = row
            if parse_summary and row.get('message_type')=='status' and shutil.disk_usage(pathlib.Path(argv[argv.index('--repo')+1])).free < 5*1024**3:
                p.terminate()
                p.wait()
                raise RuntimeError('Archive paused before exhausting disk space; source untouched')
            if time.time()-last > 20 or row.get('message_type') in ('summary','error'):
                print(json.dumps({k:v for k,v in row.items() if k not in ('current_files','item','during','seconds_remaining')},ensure_ascii=False),flush=True)
                last = time.time()
        rc = p.wait()
    if rc:
        raise RuntimeError(f'Command failed ({rc}); source remains untouched. See {log}')
    if parse_summary and not summary:
        raise RuntimeError('Successful backup did not return a snapshot summary')
    return summary

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace',required=True,type=pathlib.Path)
    ap.add_argument('--source',required=True,type=pathlib.Path)
    ap.add_argument('--name',required=True)
    ap.add_argument('--restic',required=True,type=pathlib.Path)
    ap.add_argument('--compression',default='max',choices=['auto','better','max'])
    ap.add_argument('--transport',default='tar',choices=['tar','files'])
    ap.add_argument('--exclude-relative',action='append',default=[])
    ap.add_argument('--keep-file',action='append',default=[])
    ap.add_argument('--external-readonly',action='store_true',help='Archive a source outside the workspace without making it eligible for source cleanup')
    args=ap.parse_args()
    workspace=args.workspace.resolve(strict=True)
    source=args.source.resolve(strict=True)
    for rel in args.exclude_relative+args.keep_file:
        q=pathlib.PurePosixPath(rel)
        if q.is_absolute() or '..' in q.parts or ':' in rel or '\\' in rel: raise ValueError('Expected a safe relative POSIX path')
    if source==workspace or (not source.is_relative_to(workspace) and not args.external_readonly):
        raise ValueError('Source must be a strict child of the workspace')
    if not source.is_dir() or args.source.is_symlink() or args.source.is_junction():
        raise ValueError('Source must be a real directory')
    if not args.name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in args.name):
        raise ValueError('Invalid collection name')
    archive=workspace/'_objrun-archive'
    if source.is_relative_to(archive):
        raise ValueError('Cannot archive the archive itself')
    run=archive/'collections'/args.name
    if run.exists():
        prior=json.loads((run/'record.json').read_text(encoding='utf-8-sig'))
        if prior.get('status')!='stopped' or prior.get('snapshot'):
            raise ValueError('Existing collection has a snapshot or is not a failed preparation')
        with (run/('failed-attempt-'+str(time.time_ns())+'.json')).open('x',encoding='utf-8') as f:
            json.dump(prior,f,ensure_ascii=False,indent=2)
    else:
        run.mkdir(parents=True,exist_ok=False)
    repo=archive/'restic'
    base=[str(args.restic),'--repo',str(repo),'--no-cache','--insecure-no-password']
    record=dict(name=args.name,source=str(source),source_relative=source.relative_to(workspace).as_posix() if source.is_relative_to(workspace) else None,
                started=time.strftime('%Y-%m-%dT%H:%M:%S%z'),status='preparing',uploaded=False,source_removed=False,
                format='restic-v2',compression=args.compression,transport=args.transport,
                excluded=args.exclude_relative,kept_files=args.keep_file,external_readonly=args.external_readonly)
    def save():
        (run/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:
        record['before']=manifest(source,run/'source-before.jsonl.gz',args.exclude_relative)
        save()
        print(json.dumps(dict(phase='source-inventory',**record['before'])),flush=True)
        backup=base+['backup','--json','--compression',args.compression,'--pack-size','128',
                   '--read-concurrency','4','--tag','objrun-20261023','--tag',args.name]
        if args.transport=='tar':
            backup+=['--stdin-from-command','--stdin-filename','payload.tar','--',sys.executable,
                     str(pathlib.Path(__file__).with_name('stream_source_tar.py')),
                     '--source',str(source),'--manifest',str(run/'source-before.jsonl.gz'),
                     '--hashes',str(run/'captured-sha256.jsonl.gz')]
        else:
            for rel in args.exclude_relative: backup+=['--exclude',str(source/rel)]
            backup+=[str(source)]
        record['backup']=command(backup,run/'backup.jsonl',True)
        record['snapshot']=record['backup']['snapshot_id']
        record['status']='backed_up'
        save()
        record['after']=manifest(source,run/'source-after.jsonl.gz',args.exclude_relative)
        if record['before']!=record['after']:
            if not same_file_inventory(run/'source-before.jsonl.gz',run/'source-after.jsonl.gz'):
                raise RuntimeError('Source changed during archive; no cleanup permitted')
            record['directory_mtime_only_changes']=True
        expected={}
        with gzip.open(run/'source-before.jsonl.gz','rt',encoding='utf-8') as f:
            for line in f:
                row=json.loads(line)
                if row['kind']!='dir': expected[row['path']]=(row['kind'],row['size'])
        # Restic's Windows snapshot paths use /F/path rather than F:\path.
        prefix='/' + source.as_posix().replace(':','').strip('/') + '/'
        observed={}
        with gzip.open(run/'snapshot-files.jsonl.gz','wt',encoding='utf-8',newline='\n') as out:
            p=subprocess.Popen(base+['ls','--json',record['snapshot']],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
            for line in p.stdout:
                out.write(line)
                row=json.loads(line)
                if row.get('type') in ('file','symlink') and args.transport=='files':
                    path=row['path']
                    if not path.startswith(prefix): raise RuntimeError('Unexpected snapshot path: '+path)
                    observed[path[len(prefix):]]=('file' if row['type']=='file' else 'link',row.get('size',0) if row['type']=='file' else 0)
            error=p.stderr.read()
            if p.wait(): raise RuntimeError(error)
        if args.transport=='tar':
            with gzip.open(run/'captured-sha256.jsonl.gz','rt',encoding='utf-8') as f:
                for line in f:
                    row=json.loads(line)
                    observed[row['path']]=('link' if row.get('kind')=='link' else 'file',row.get('bytes',0))
        if expected!=observed:
            mismatch=dict(missing=list(expected.keys()-observed.keys())[:20],extra=list(observed.keys()-expected.keys())[:20],
                          different=[k for k in expected.keys()&observed.keys() if expected[k]!=observed[k]][:20])
            (run/'coverage-errors.json').write_text(json.dumps(mismatch,ensure_ascii=False,indent=2),encoding='utf-8')
            raise RuntimeError('Snapshot path/type/size coverage differs from source')
        record['coverage_verified']=True
        command(base+['check'],run/'integrity-check.txt')
        record['integrity_verified']=True
        record['status']='verified_pending_restore'
        record['finished']=time.strftime('%Y-%m-%dT%H:%M:%S%z')
        save()
        print(json.dumps(record,ensure_ascii=False),flush=True)
    except BaseException as e:
        record['status']='stopped'
        record['error']=str(e)
        save()
        raise

if __name__=='__main__': main()
