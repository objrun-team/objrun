"""Original shell compilers then checked program runs, in an offline chain."""
from pathlib import Path
import time

PLAN=[{'kind':'popen','command':'rustc /app/polyglot/main.rs -o /app/polyglot/main'},
      {'kind':'popen','command':'g++ -x c++ /app/polyglot/main.rs -o /app/polyglot/cmain'}]
for value in ['0','1','2','10','42']:
    PLAN.extend([{'kind':'run','argv':['/app/polyglot/main',value]},
                 {'kind':'run','argv':['/app/polyglot/cmain',value]}])


def rust_polyglot_worker(native,candidate,task,deadline,capsule):
    if not any(f['path']=='/app/polyglot/main.rs' and f['exists'] for f in capsule['files']):
        return {'protocol':'terminal-rust-polyglot-cli-data-v1','rows':[]},[]
    source=native.assert_actor(candidate);assert source['State']['Paused']
    image,initial_commit=native.commit(candidate,'untrusted-rust-polyglot');rows=[];receipts=[]
    for index,op in enumerate(PLAN):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Official Rust polyglot verifier deadline exhausted')
        argv=['/bin/sh','-c',op['command']] if op['kind']=='popen' else op['argv']
        worker_image=image
        cid,initial,create=native.create('untrusted-rust-polyglot-'+str(index),image,argv[0],argv[1:],cwd='/app',network='none',
            memory_mb=task['officialEnvironment']['memory_mb'],cpus=task['officialEnvironment']['cpus'])
        start=native.command(['start','-a',cid],timeout=remaining,stdout_limit=2*1024**2)
        final=native.assert_actor(cid);exception=None;next_commit=None
        fault=final['State'].get('Error','')
        missing='executable file not found' in fault or ('stat '+argv[0]+': no such file or directory') in fault
        if final['State']['Status']=='created' and missing:exception='FileNotFoundError'
        else:assert final['State']['Status']=='exited'
        stdout=Path(start['stdout']['path']).read_bytes().decode('utf-8').replace('\r\n','\n').replace('\r','\n')
        stderr=Path(start['stderr']['path']).read_bytes().decode('utf-8').replace('\r\n','\n').replace('\r','\n') if op['kind']=='run' else None
        # os.popen compiler exits are not checked by the frozen official test.
        if exception is None:
            image,next_commit=native.commit(cid,'untrusted-rust-polyglot-chain-'+str(index))
        rows.append({**op,'exitCode':final['State']['ExitCode'],'stdout':stdout,'stderr':stderr,'exception':exception})
        removal,absence=native.remove(cid)
        receipts.append({'cid':cid,'initial':initial,'create':create,'start':start,'final':final,'sourceState':source,
                         'snapshot':worker_image,'initialCommit':initial_commit,'nextImage':image,'nextCommit':next_commit,
                         'removal':removal,'absence':absence})
        if exception is not None or (op['kind']=='run' and final['State']['ExitCode']!=0):break
    return {'protocol':'terminal-rust-polyglot-cli-data-v1','rows':rows},receipts
