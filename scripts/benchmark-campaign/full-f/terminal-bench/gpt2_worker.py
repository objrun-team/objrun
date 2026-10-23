"""Two original compiler/program operations; candidate code stays offline."""
from pathlib import Path
import base64
import time
from docker_owned import NativeFault

PLAN=[{'argv':['gcc','-O3','/app/gpt2.c','-lm'],'timeout':None},
      {'argv':['/app/a.out','gpt2-124M.ckpt','vocab.bpe',
               'THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT'],'timeout':90}]


def gpt2_worker(native,candidate,task,deadline,capsule):
    eligible=any(f['path']=='/app/gpt2.c' and f['exists'] and f['bytes']<5000 for f in capsule['files'])
    if not eligible:return {'protocol':'terminal-gpt2-cli-data-v1','rows':[]},[]
    source=native.assert_actor(candidate);assert source['State']['Paused']
    image,commit=native.commit(candidate,'untrusted-gpt2');rows=[];receipts=[]
    for index,operation in enumerate(PLAN):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Official GPT2 verifier deadline exhausted')
        timeout=min(remaining,operation['timeout']) if operation['timeout'] else remaining
        argv=operation['argv'];worker_image=image
        cid,initial,create=native.create('untrusted-gpt2-'+str(index),image,argv[0],argv[1:],
            network='none',cwd='/app',memory_mb=task['officialEnvironment']['memory_mb'],cpus=task['officialEnvironment']['cpus'])
        exception=None;next_commit=None
        try:start=native.command(['start','-a',cid],timeout=timeout,stdout_limit=2*1024**2)
        except NativeFault as exc:
            if not exc.receipt.get('timedOut') or exc.receipt.get('overflow') or exc.receipt.get('captureFaults'):raise
            # Only the original program invocation has its own subprocess timeout.
            if operation['timeout'] is None or remaining<operation['timeout']:raise TimeoutError('Official GPT2 verifier deadline exhausted') from exc
            start=exc.receipt;exception='TimeoutExpired'
        final=native.assert_actor(cid)
        fault=final['State'].get('Error','')
        missing='executable file not found' in fault or ('stat '+argv[0]+': no such file or directory') in fault
        if exception is None and final['State']['Status']=='created' and missing:exception='FileNotFoundError'
        elif exception is None:assert final['State']['Status']=='exited'
        raw={key:Path(start[key]['path']).read_bytes() for key in ['stdout','stderr']}
        # subprocess TimeoutExpired retains bytes even with text=True. No UTF-8
        # decoding takes place on that error path in the original invocation.
        stdout=raw['stdout'].decode('utf-8').replace('\r\n','\n').replace('\r','\n') if exception!='TimeoutExpired' else ''
        stderr=raw['stderr'].decode('utf-8').replace('\r\n','\n').replace('\r','\n') if exception!='TimeoutExpired' else ''
        if index==0 and exception is None and final['State']['ExitCode']==0:
            image,next_commit=native.commit(cid,'untrusted-gpt2-compiled')
        row={**operation,'exitCode':final['State']['ExitCode'],'stdout':stdout,'stderr':stderr,'exception':exception}
        if exception=='TimeoutExpired':row['timeoutStreams']={key:base64.b64encode(value).decode('ascii') for key,value in raw.items()}
        rows.append(row)
        removal,absence=native.remove(cid)
        receipts.append({'cid':cid,'initial':initial,'create':create,'start':start,'final':final,
                         'sourceState':source,'snapshot':worker_image,'initialCommit':commit,
                         'nextImage':image,'nextCommit':next_commit,'removal':removal,'absence':absence})
        if exception is not None or final['State']['ExitCode']!=0:break
    return {'protocol':'terminal-gpt2-cli-data-v1','rows':rows},receipts
