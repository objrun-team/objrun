"""Chained offline compiler/program operations without private assertions."""
from pathlib import Path
import time

PLAN=[{'argv':['gcc','/app/polyglot/main.py.c','-o','/app/polyglot/cmain'],'capture':False}]
for value in ['42','10','0']:
    PLAN.extend([{'argv':['python3','/app/polyglot/main.py.c',value],'capture':True},
                 {'argv':['/app/polyglot/cmain',value],'capture':True}])


def _legacy_polyglot_worker(native,candidate,task,deadline,capsule):
    if not any(f['path']=='/app/polyglot/main.py.c' and f['exists'] for f in capsule['files']):
        return {'protocol':'terminal-polyglot-cli-data-v1','rows':[]},[]
    source=native.assert_actor(candidate);assert source['State']['Paused']
    image,initial_commit=native.commit(candidate,'untrusted-polyglot');rows=[];receipts=[]
    for index,operation in enumerate(PLAN):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Official polyglot verifier deadline exhausted')
        argv=operation['argv'];worker_image=image
        cid,initial,create=native.create('untrusted-polyglot-'+str(index),image,argv[0],argv[1:],network='none',cwd='/app',
            memory_mb=task['officialEnvironment']['memory_mb'],cpus=task['officialEnvironment']['cpus'])
        start=native.command(['start','-a',cid],timeout=remaining,stdout_limit=2*1024**2)
        final=native.assert_actor(cid);exception=None;next_commit=None
        fault=final['State'].get('Error','')
        missing='executable file not found' in fault or ('stat '+argv[0]+': no such file or directory') in fault
        if final['State']['Status']=='created' and missing:exception='FileNotFoundError'
        else:assert final['State']['Status']=='exited'
        stdout=Path(start['stdout']['path']).read_bytes().decode('utf-8').replace('\r\n','\n').replace('\r','\n') if operation['capture'] else None
        stderr=Path(start['stderr']['path']).read_bytes().decode('utf-8').replace('\r\n','\n').replace('\r','\n') if operation['capture'] else None
        if exception is None and final['State']['ExitCode']==0:
            image,next_commit=native.commit(cid,'untrusted-polyglot-chain-'+str(index))
        rows.append({**operation,'exitCode':final['State']['ExitCode'],'stdout':stdout,'stderr':stderr,'exception':exception})
        removal,absence=native.remove(cid)
        receipts.append({'cid':cid,'initial':initial,'create':create,'start':start,'final':final,
                         'sourceState':source,'snapshot':worker_image,'initialCommit':initial_commit,
                         'nextImage':image,'nextCommit':next_commit,'removal':removal,'absence':absence})
        # Every original operation has check=True; no subsequent operation follows failure.
        if exception is not None or final['State']['ExitCode']!=0:break
    return {'protocol':'terminal-polyglot-cli-data-v1','rows':rows},receipts


def polyglot_worker(native,candidate,task,deadline,capsule):
    dependency=task.get('verifierDependencyProofPath')
    if dependency:
        from polyglot_python313_worker import python313_polyglot_worker
        return python313_polyglot_worker(native,candidate,task,deadline,capsule,dependency)
    return _legacy_polyglot_worker(native,candidate,task,deadline,capsule)
