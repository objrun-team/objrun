"""Actual frozen six-tool solver forwarding, no model or benchmark result."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import skb_artifact_task_v2 as task
from skb_artifact_solver_v2 import Solver
from skb_artifact_ram_executor_v2 import fresh


def main():
    p=argparse.ArgumentParser()
    for k in ('descriptor','storage'):
        p.add_argument('--'+k,type=Path,required=True);p.add_argument('--'+k+'-sha256',required=True)
    a=p.parse_args();pins=[]
    for k in ('descriptor','storage'):
        q=task.pin(getattr(a,k).resolve());task.demand(q['sha256']==getattr(a,k+'_sha256'),'six_pin','Exact source-bound ready task/store required');pins.append(q)
    dp,lp=pins;solver=Solver(dp,lp);fault=None;rows=[];cp=None
    fresh(solver.box/'six-tool-control-source.py',Path(__file__).read_bytes(),solver.root)
    path='/tmp/objrun-skb-six-tool-control.txt'
    actions=[('bash',{'command':'printf skb-runtime-before > '+path,'timeout_ms':10000}),('read',{'file_path':path}),
        ('write',{'file_path':path,'content':'skb-runtime-written'}),('edit',{'file_path':path,'old_string':'written','new_string':'edited'}),
        ('glob',{'pattern':'objrun-skb-six-tool-*','path':'/tmp'}),('grep',{'pattern':'skb-runtime-edited','path':path})]
    try:
        solver.create(True)
        for tool,args in actions:
            result=solver.call(tool,args,30);task.demand(not (isinstance(result,dict) and result.get('error')),'six_rpc','Actual frozen six-tool runtime returned error')
            rows.append({'tool':tool,'args':args,'result':result})
        task.demand('skb-runtime-before' in json.dumps(rows[1]['result']) and 'skb-runtime-edited' in json.dumps(rows[-1]['result'])
            and 'objrun-skb-six-tool-control.txt' in json.dumps(rows[-2]['result']),'six_effect','Actual read/edit/glob/grep effects differ')
        cp=solver.capture(True)
    except BaseException as e:fault={'type':type(e).__name__,'kind':getattr(e,'kind',None),'detail':str(e)[:512]}
    finally:closed=solver.close()
    out=fresh(solver.box/'six-tool-control.json',task.canonical({'protocol':'skillsbench-real-six-tool-control-v2','taskDescriptorPin':dp,'storageDescriptorPin':lp,
        'toolResults':rows,'capturePin':cp,'solverClosurePin':closed,'allSixActualEffectsMatched':fault is None and len(rows)==6,
        'fault':fault,'sourcePin':task.pin(__file__),'observedAtUtc':datetime.now(timezone.utc).isoformat(),'modelCalls':0,'paidReady':False}),solver.root)
    print(json.dumps({'sixToolControlPin':out,'allSixActualEffectsMatched':fault is None and len(rows)==6,'ownedClosed':solver.closed,'fault':fault,'modelCalls':0}),flush=True)
    raise SystemExit(0 if fault is None and solver.closed else 1)


if __name__=='__main__':main()
