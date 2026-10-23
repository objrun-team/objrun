"""Exact original Coq/R operations, with no test source in worker islands."""
from pathlib import Path
import time
from docker_owned import NativeFault

PLANS={
    'prove-plus-comm':[{'argv':['coqc','plus_comm.v'],'cwd':None,'timeout':None}],
    'rstan-to-pystan':[{'argv':['R','--version'],'cwd':'/app','timeout':30},
                       {'argv':['R','--slave','-e','library(rstan)'],'cwd':'/app','timeout':30}],
    'winning-avg-corewars':[{'argv':['pmars','-b','-r','100','-f','/app/my_warrior.red','/app/warriors/'+name],
                            'cwd':None,'timeout':None}
                           for name in ['stone.red','vampire.red','paper.red','snake.red','g2-clear.red']],
}

def fixed_cli_worker(native,candidate,task,deadline):
    source=native.assert_actor(candidate);assert source['State']['Paused']
    image,commit=native.commit(candidate,'untrusted-fixed-cli');rows=[];receipts=[]
    for index,operation in enumerate(PLANS[task['taskId']]):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Official verifier deadline exhausted in fixed CLI worker')
        timeout=min(remaining,operation['timeout']) if operation['timeout'] else remaining
        cid,initial,create=native.create('untrusted-fixed-cli-'+str(index),image,operation['argv'][0],operation['argv'][1:],
            network='none',memory_mb=task['officialEnvironment']['memory_mb'],cpus=task['officialEnvironment']['cpus'],cwd='/app')
        exception=None
        try:start=native.command(['start','-a',cid],timeout=timeout,stdout_limit=2*1024**2)
        except NativeFault as exc:
            if not exc.receipt.get('timedOut') or exc.receipt.get('overflow') or exc.receipt.get('captureFaults'):raise
            start=exc.receipt;exception='TimeoutExpired'
        final=native.assert_actor(cid)
        if exception is None and final['State']['Status']=='created':
            fault=final['State'].get('Error','')
            if 'executable file not found' in fault:exception='FileNotFoundError'
            else:raise RuntimeError('Unrecognized worker startup fault: '+fault)
        elif exception is None:assert final['State']['Status']=='exited'
        stdout=Path(start['stdout']['path']).read_bytes().decode('utf-8')
        stderr=Path(start['stderr']['path']).read_bytes().decode('utf-8')
        next_commit=None;worker_image=image
        if task['taskId']=='winning-avg-corewars' and exception is None:
            # Preserve offline command side effects across the original five battles.
            image,next_commit=native.commit(cid,'untrusted-corewars-chain-'+str(index))
        removal,absence=native.remove(cid)
        rows.append({**operation,'exitCode':final['State']['ExitCode'],'stdout':stdout,'stderr':stderr,'exception':exception})
        receipts.append({'cid':cid,'initial':initial,'create':create,'start':start,'final':final,'removal':removal,
                         'absence':absence,'sourceState':source,'snapshot':worker_image,'commit':commit,
                         'nextImage':image,'nextCommit':next_commit})
        if task['taskId']=='winning-avg-corewars' and (exception is not None or final['State']['ExitCode']!=0):
            # The original per-battle assertion/exception stops this test here.
            break
    return {'protocol':'terminal-fixed-cli-data-v1','taskId':task['taskId'],'rows':rows},receipts
