"""Offline compiler/run chain; binary existence is native archive evidence."""
from pathlib import Path
import time
from artifacts import capture_file
from docker_owned import NativeFault


def compiler(build):
    flags=['-g','-O0'] if build=='debug' else ['-O2','-DNDEBUG']
    lib='/usr/local/gcc-custom-'+build+'/lib64'
    return ['g++','-std=c++17','-o','/app/'+build,'/app/main.cpp','/app/user.cpp',*flags,
            '-L'+lib,'-Wl,-Bstatic','-lstdc++','-Wl,-Bdynamic','-lm']


PLAN=[{'kind':'compile','argv':compiler('debug'),'timeout':None,'binary':'/app/debug'},
      {'kind':'compile','argv':compiler('release'),'timeout':None,'binary':'/app/release'},
      {'kind':'compile','argv':compiler('debug'),'timeout':None,'binary':'/app/debug'},
      {'kind':'run','argv':'/app/debug','timeout':10},
      {'kind':'compile','argv':compiler('release'),'timeout':None,'binary':'/app/release'},
      {'kind':'run','argv':'/app/release','timeout':10},
      {'kind':'compile','argv':compiler('release'),'timeout':None,'binary':'/app/release'},
      {'kind':'run','argv':['valgrind','--leak-check=full','--error-exitcode=1',
                          '--errors-for-leak-kinds=definite','--quiet','/app/release'],'timeout':30}]


def heap_worker(native,candidate,task,deadline,output):
    source=native.assert_actor(candidate);assert source['State']['Paused']
    image,commit=native.commit(candidate,'untrusted-heap');rows=[];receipts=[];compile_ok=False
    for index,op in enumerate(PLAN):
        if op['kind']=='run' and not compile_ok:continue
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Official heap verifier deadline exhausted')
        argv=op['argv'] if isinstance(op['argv'],list) else [op['argv']]
        cid,initial,create=native.create('untrusted-heap-'+str(index),image,argv[0],argv[1:],cwd='/app',network='none',
            memory_mb=task['officialEnvironment']['memory_mb'],cpus=task['officialEnvironment']['cpus'])
        exception=None;artifact=None;next_commit=None;worker_image=image;pause=None
        try:start=native.command(['start','-a',cid],timeout=min(remaining,op['timeout']) if op['timeout'] else remaining,stdout_limit=2*1024**2)
        except NativeFault as exc:
            if not op['timeout'] or not exc.receipt.get('timedOut') or exc.receipt.get('overflow') or exc.receipt.get('captureFaults'):raise
            start=exc.receipt;exception='TimeoutExpired'
        final=native.assert_actor(cid);fault=final['State'].get('Error','')
        if exception is None:
            missing='executable file not found' in fault or ('stat '+argv[0]+': no such file or directory') in fault
            if final['State']['Status']=='created' and missing:exception='FileNotFoundError'
            else:assert final['State']['Status']=='exited'
        if exception is None:
            if op['kind']=='compile':artifact=capture_file(native,cid,op['binary'],128*1024**2,Path(output)/str(index))
            image,next_commit=native.commit(cid,'untrusted-heap-chain-'+str(index))
        elif exception=='TimeoutExpired':
            pause=native.pause(cid)
            image,next_commit=native.commit(cid,'untrusted-heap-timeout-chain-'+str(index))
        row={**op,'exitCode':final['State']['ExitCode'],'exception':exception,
             'stdout':Path(start['stdout']['path']).read_bytes().decode('utf-8').replace('\r\n','\n').replace('\r','\n'),
             'stderr':Path(start['stderr']['path']).read_bytes().decode('utf-8').replace('\r\n','\n').replace('\r','\n')}
        if op['kind']=='compile':
            row['binaryExists']=artifact['exists'] if artifact else False
            compile_ok=exception is None and row['exitCode']==0
        rows.append(row);removal,absence=native.remove(cid)
        receipts.append({'cid':cid,'initial':initial,'create':create,'start':start,'final':final,'artifact':artifact,
                         'snapshot':worker_image,'commit':commit,'nextImage':image,'nextCommit':next_commit,
                         'sourceState':source,'timeoutPause':pause,'removal':removal,'absence':absence})
    return {'protocol':'terminal-heap-cli-data-v1','rows':rows},receipts
