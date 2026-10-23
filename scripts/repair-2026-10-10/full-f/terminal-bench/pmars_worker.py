"""Four original pMARS shell operations; candidate output stays untrusted data."""
from pathlib import Path
import time

COMMANDS=("echo -e 's\\ns\\ns\\nq' | pmars -e rave.red",
          "echo -e 's\\ns\\ns\\nq' | pmars -e flashpaper.red",
          "pmars -b -r 50 -f flashpaper.red rave.red | tail -n 1",
          "ldd /usr/local/bin/pmars")

def pmars_worker(native,candidate,task,capsule,deadline):
    if not any(f['path']=='/usr/local/bin/pmars' and f['exists'] for f in capsule['files']):
        return {'protocol':'terminal-pmars-worker-data-v1','rows':[]},[]
    source=native.assert_actor(candidate);assert source['State']['Paused']
    image,commit=native.commit(candidate,'untrusted-pmars-worker');rows=[];receipts=[]
    for index,command in enumerate(COMMANDS):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Official pMARS verifier budget exhausted')
        cid,initial,create=native.create('untrusted-pmars-'+str(index),image,'/bin/sh',['-c','cd /app && '+command],
            network='none',memory_mb=task['officialEnvironment']['memory_mb'],cpus=task['officialEnvironment']['cpus'])
        start=native.command(['start','-a',cid],timeout=remaining,stdout_limit=2*1024**2)
        final=native.assert_actor(cid);assert final['State']['Status']=='exited'
        stdout=Path(start['stdout']['path']).read_bytes().decode('utf-8')
        stderr=Path(start['stderr']['path']).read_bytes().decode('utf-8')
        removal,absence=native.remove(cid)
        rows.append({'command':command,'exitCode':final['State']['ExitCode'],'stdout':stdout,'stderr':stderr})
        receipts.append({'cid':cid,'initial':initial,'create':create,'start':start,'final':final,
                         'removal':removal,'absence':absence,'sourceState':source,'snapshot':image,'commit':commit})
    return {'protocol':'terminal-pmars-worker-data-v1','rows':rows},receipts
