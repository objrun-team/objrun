"""Git queries in isolated offline snapshots; all assertions remain private."""
from pathlib import Path
import re, time

BASE=[['git','-C','/app/repo','log','--all','--grep','secret\\[','--regexp-ignore-case'],
      ['git','-C','/app/repo','log','--all','-p','-S','secret['],
      ['git','-C','/app/repo','log','--oneline','--all'],
      ['git','-C','/app/repo','fsck','--lost-found']]
CHECKSUM=['sh','-c',"find /app/repo -type f -not -path '*/\\.*' -exec sha256sum {} + | sort | sha256sum"]


def git_leak_worker(native,candidate,task,deadline):
    source=native.assert_actor(candidate);assert source['State']['Paused']
    image,initial_commit=native.commit(candidate,'untrusted-git-leak');rows=[];receipts=[]
    operations=[*BASE,CHECKSUM];index=0
    while index<len(operations):
        argv=operations[index];remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Official Git verifier deadline exhausted')
        worker_image=image
        cid,initial,create=native.create('untrusted-git-leak-'+str(index),image,argv[0],argv[1:],cwd='/app',network='none',
            memory_mb=task['officialEnvironment']['memory_mb'],cpus=task['officialEnvironment']['cpus'])
        start=native.command(['start','-a',cid],timeout=remaining,stdout_limit=2*1024**2)
        final=native.assert_actor(cid);exception=None;next_commit=None
        fault=final['State'].get('Error','')
        if final['State']['Status']=='created' and 'executable file not found' in fault:exception='FileNotFoundError'
        else:assert final['State']['Status']=='exited'
        stdout=Path(start['stdout']['path']).read_bytes().decode('utf-8').replace('\r\n','\n').replace('\r','\n')
        stderr=Path(start['stderr']['path']).read_bytes().decode('utf-8').replace('\r\n','\n').replace('\r','\n')
        if exception is None:image,next_commit=native.commit(cid,'untrusted-git-leak-chain-'+str(index))
        rows.append({'argv':argv,'exitCode':final['State']['ExitCode'],'stdout':stdout,'stderr':stderr,'exception':exception})
        if argv==BASE[3] and exception is None and final['State']['ExitCode']==0:
            queries=[]
            for line in stdout.splitlines():
                if 'dangling' in line:
                    object_id=line.split()[-1]
                    if not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',object_id):raise RuntimeError('Invalid Git object ID from fsck')
                    queries.append(['git','-C','/app/repo','cat-file','-p',object_id])
            if len(queries)>10000:raise RuntimeError('Git object query bound exceeded')
            operations[index+1:index+1]=queries
        removal,absence=native.remove(cid)
        receipts.append({'cid':cid,'initial':initial,'create':create,'start':start,'final':final,'snapshot':worker_image,
                         'initialCommit':initial_commit,'nextImage':image,'nextCommit':next_commit,'sourceState':source,
                         'removal':removal,'absence':absence})
        index+=1
    return {'protocol':'terminal-git-leak-cli-data-v1','rows':rows},receipts
