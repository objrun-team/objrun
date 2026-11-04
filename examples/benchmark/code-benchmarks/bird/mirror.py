"""Incremental evidence mirror into the authorized BIRD NAS directory; no secrets."""
import io, json, pathlib, subprocess, tarfile, time, os
root = pathlib.Path(__file__).resolve().parents[4]
out = root / 'docs/newbench-20261014/bird'
remote = '/mnt/aliyunsb/pingxingwang/tgengin-bench/newbench-20261014/bird/run-output'
seen = {}
while True:
    try:
        changed = []
        for p in out.rglob('*'):
            if not p.is_file() or p.name == 'mirror-status.json' or p.suffix in ('.tmp', '.sqlite') or p.name.endswith(('-wal', '-shm')):
                continue
            st = p.stat(); signature = (st.st_mtime_ns, st.st_size)
            if seen.get(str(p)) != signature: changed.append((p, signature))
        # Closed engine databases are copied only after their task result exists.
        for p in out.glob('*/tasks/objrun/*/engine/data/*.sqlite'):
            mode, tid = p.relative_to(out).parts[0], p.relative_to(out).parts[3]
            if not (out / mode / 'results/objrun' / (tid+'.json')).exists(): continue
            st=p.stat(); signature=(st.st_mtime_ns,st.st_size)
            if seen.get(str(p)) != signature: changed.append((p,signature))
        for p in out.glob('protocol-change-*/native-checkpoints/*/standalone/*.sqlite'):
            st=p.stat();signature=(st.st_mtime_ns,st.st_size)
            if seen.get(str(p)) != signature:changed.append((p,signature))
        if changed:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf,mode='w:gz') as tar:
                for p, sig in changed: tar.add(p,arcname=p.relative_to(out).as_posix(),recursive=False)
            proc=subprocess.run(['ssh','-o','BatchMode=yes','-o','ClearAllForwardings=yes','-o','ConnectTimeout=15','novaeve',f'mkdir -p {remote} && tar -xzf - -C {remote}'],input=buf.getvalue(),capture_output=True,timeout=180)
            if proc.returncode: raise RuntimeError(proc.stderr.decode(errors='replace')[-500:])
            for p,sig in changed: seen[str(p)]=sig
        state={'pid':os.getpid(),'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'stage':'running','lastBatchFiles':len(changed),'mirroredFiles':len(seen),'remoteRoot':remote}
    except Exception as e:
        state={'pid':os.getpid(),'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'stage':'error','error':str(e),'remoteRoot':remote}
    tmp=out/'mirror-status.tmp';tmp.write_text(json.dumps(state,indent=2),encoding='utf8');tmp.replace(out/'mirror-status.json')
    time.sleep(30)
