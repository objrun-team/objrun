"""Serialize original shells as each exact current cold oracle becomes available."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid
from importlib.util import spec_from_file_location,module_from_spec
import skb_artifact_task_v2 as task
from skb_artifact_ram_executor_v2 import fresh


def main():
    p=argparse.ArgumentParser();p.add_argument('--collections',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--first',type=Path);p.add_argument('--first-sha256');p.add_argument('--reuse-completed',action='store_true');a=p.parse_args()
    q=task.pin(a.collections.resolve());task.demand(q['sha256']==a.sha256,'shell_batch_pin','Exact current original collections required');index=task.read_json(q);lp=index['storageDescriptorPin']
    home=task.REPO/'docs/repair-2026-10-08/skillsbench-ten-takeover-v1';box=home/'original-shell-batches'/uuid.uuid4().hex;box.mkdir(parents=True)
    fresh(box/'batch-source.py',Path(__file__).read_bytes(),task.REPO);proofs=[]
    spec=spec_from_file_location('skb_shell_independent_replay',Path(__file__).with_name('audit-skb-artifact-readiness-v2.py'));audit=module_from_spec(spec);spec.loader.exec_module(audit)
    for i,dp in enumerate(index['taskDescriptorPins']):
        reused=None
        if a.reuse_completed:
            for path in Path(task.read_json(lp)['directories']['stand']).glob('solver-*/original-shell-comparison.json'):
                candidate=task.pin(path);value=task.read_json(candidate)
                if value.get('fault') is None and value.get('proof',{}).get('taskDescriptorPin')==dp:
                    audit.validate_shell(candidate);reused=candidate;break
        if reused:
            proofs.append(reused);print(json.dumps({'phase':'actual-original-shell-comparison-replayed','taskId':task.read_json(dp)['taskId'],'comparisonPin':reused,'modelCalls':0}),flush=True);continue
        if i==0 and a.first:
            pp=task.pin(a.first.resolve());task.demand(pp['sha256']==a.first_sha256,'shell_batch_first','Exact real first shell comparison required')
            task.demand(task.read_json(pp)['proof']['taskDescriptorPin']==dp,'shell_batch_first','First source/task identity differs')
        else:
            end=time.monotonic()+7200;control=None;printed=False
            while time.monotonic()<end:
                for path in (home/'actual-cold-controls').glob('*/control.json'):
                    v=json.loads(path.read_bytes())
                    if v['taskDescriptorPin']==dp and v['mode']=='oracle' and v['controlMatched'] is True:
                        control=task.pin(path);break
                if control:break
                if not printed:print(json.dumps({'phase':'original-shell-awaiting-current-real-oracle','taskId':task.read_json(dp)['taskId'],'modelCalls':0}),flush=True);printed=True
                time.sleep(3)
            task.demand(control,'shell_batch_oracle','No exact current all-pass oracle became available')
            argv=['D:/ProgramData/anaconda3/python.exe','-B','-X','utf8',str(Path(__file__).with_name('skb-ten-original-shell-v2.py')),
                '--control',control['path'],'--control-sha256',control['sha256'],'--storage',lp['path'],'--storage-sha256',lp['sha256']]
            d=task.read_json(dp);child=subprocess.Popen(argv,cwd=task.REPO,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
            out,err=child.communicate(timeout=d['originalResources']['verifier']['timeout_sec']+240)
            caller=fresh(box/(d['taskId']+'-caller.json'),task.canonical({'argv':argv,'childPid':child.pid,'exitCode':child.returncode,'directWaitReturned':True,'stdout':out.decode('utf8','replace'),'stderr':err.decode('utf8','replace'),'modelCalls':0}),task.REPO)
            rows=[json.loads(x) for x in out.splitlines() if x.startswith(b'{')]
            task.demand(child.returncode==0 and rows and rows[-1]['matched'] is True,'shell_batch_failed','Actual original shell mismatch/failure retained')
            pp=rows[-1]['originalShellComparisonPin']
        proofs.append(pp);print(json.dumps({'phase':'actual-original-shell-comparison-closed','taskId':task.read_json(dp)['taskId'],'comparisonPin':pp,'modelCalls':0}),flush=True)
    result=fresh(box/'index.json',task.canonical({'protocol':'skillsbench-ten-actual-original-shell-index-v2','collectionIndexPin':q,'comparisonPins':proofs,'actualOriginalShellComparisons':10,'sourcePin':task.pin(__file__),'modelCalls':0}),task.REPO)
    print(json.dumps({'originalShellIndexPin':result,'modelCalls':0}),flush=True)


if __name__=='__main__':main()
