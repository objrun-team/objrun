"""Single owned local follower: mirror status, retrieve on completion, verify delivery."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
from ops import LOCAL,REPO

def main():
    lock=(LOCAL/'follower.lock').open('a+b')
    if os.name=='nt':
        import msvcrt
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    launch=LOCAL/'follower-launch.json'
    with launch.open('x',encoding='utf-8') as f:json.dump({'pid':os.getpid(),'startedEpoch':time.time(),'script':str(Path(__file__).resolve())},f,indent=2)
    script=Path(__file__).parent;errors=0
    def run(name,*args,timeout=90):
        p=subprocess.run([sys.executable,str(script/name),*args],cwd=REPO.parent,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
        if p.returncode:raise RuntimeError(p.stderr[-2000:]+p.stdout[-1000:])
        return p.stdout
    while True:
        try:
            run('ops.py','pull');errors=0
            status= json.loads((LOCAL/'status.json').read_text(encoding='utf-8')) if (LOCAL/'status.json').exists() else {}
            state={'pid':os.getpid(),'atEpoch':time.time(),'phase':status.get('stage','zero_model_acceptance'),'arms':status.get('arms',{})}
            (LOCAL/'follower-status.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8')
            if status.get('stage')=='needs_attention':
                (LOCAL/'FOLLOWER_ATTENTION.json').write_text(json.dumps(status,indent=2)+'\n',encoding='utf-8');return
            if status.get('stage') in ['complete','complete_with_exceptions']:
                # Unknown export/transfer results are inspected, never blindly retried.
                receipt=run('ops.py','retrieve',timeout=1500)
                verification=run('verify_local.py',timeout=600)
                (LOCAL/'DELIVERY.json').write_text(json.dumps({'delivered':True,'verified':True,'atEpoch':time.time(),'retrieval':json.loads(receipt.strip()),'verification':json.loads(verification.strip())},indent=2)+'\n',encoding='utf-8')
                return
        except Exception as e:
            errors+=1
            (LOCAL/'follower-error.json').write_text(json.dumps({'atEpoch':time.time(),'consecutiveErrors':errors,'error':str(e)},indent=2)+'\n',encoding='utf-8')
            if (LOCAL/'status.json').exists() and json.loads((LOCAL/'status.json').read_text(encoding='utf-8')).get('stage') in ['complete','complete_with_exceptions']:return
        time.sleep(60)

if __name__=='__main__':main()
