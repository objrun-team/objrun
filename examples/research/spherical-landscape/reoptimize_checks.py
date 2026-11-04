import os,threading,time,json,sys
os.environ['OPENBLAS_NUM_THREADS']='1'
import numpy as np
from pathlib import Path
from scipy.linalg import eigh,norm
from checker import evaluate,spaces,energy
from search_support import optimize,atomic
run=Path(sys.argv[1]);end=json.loads((run/'deadline.json').read_text())['deadline_epoch']
def watchdog():time.sleep(max(0,end-time.time()));os._exit(124)
threading.Thread(target=watchdog,daemon=True).start()
raw=json.loads((run/'work/host-certificate-exact.refined.json').read_text());x=np.array(raw['vectors'],float);x/=norm(x,axis=1)[:,None]
_,_,H=evaluate(x);T,Q,_,_=spaces(x);B=T@Q;vals,U=eigh(B.T@H@B)
rng=np.random.default_rng(45237671);directions=[('soft',k,U[:,k]) for k in range(5)]+[('random',k,rng.normal(size=105)) for k in range(8)]
rows=[];k=0
for kind,index,c in directions:
    c/=norm(c);d=(B@c).reshape(24,6);speed=norm(d,axis=1)
    for step in [-.1,-.01,.01,.1]:
        y=x*np.cos(step*speed)[:,None]+d*(step*np.sinc(step*speed/np.pi))[:,None]
        name=run/f'work/candidates/host-reopt-{k:03d}'
        atomic(str(name)+'.initial.json',{'vectors':y.tolist(),'direction':[kind,index],'step':step,'seed':45237671})
        z,info=optimize(y,end,str(name)+'.trace.json')
        atomic(str(name)+'.json',{'vectors':z.tolist(),'direction':[kind,index],'step':step,'seed':45237671,'search_info':info})
        rows.append({'file':str(name)+'.json','direction':[kind,index],'step':step,'perturbed_energy':energy(y),'final_energy':energy(z),'gradient_norm':info['gradient_norm']});k+=1
        atomic(run/'host-reoptimization-check.json',{'complete':False,'runs':rows,'minimum_energy':min(r['final_energy'] for r in rows)})
atomic(run/'host-reoptimization-check.json',{'complete':True,'reference_candidate_energy':energy(x),'runs':rows,'minimum_energy':min(r['final_energy'] for r in rows),'descent_beyond_tolerance':any(r['final_energy']<energy(x)-1e-9 for r in rows)})
