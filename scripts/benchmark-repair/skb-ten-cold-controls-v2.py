"""Complete all30 real cold controls in fixed ten-task order, never model trials."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import uuid
import skb_artifact_task_v2 as task
from skb_artifact_ram_executor_v2 import fresh


def main():
    p=argparse.ArgumentParser();p.add_argument('--collections',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--first-oracle',type=Path);p.add_argument('--first-oracle-sha256');a=p.parse_args()
    index_pin=task.pin(a.collections.resolve());task.demand(index_pin['sha256']==a.sha256,'cold_list_pin','Exact actual collection index required')
    index=task.read_json(index_pin);lp=index['storageDescriptorPin']
    task.demand(index['actualDistinctTaskCollections']==10,'cold_list_scope','All10 actual source-bound collections required')
    box=task.REPO/'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/cold-control-batches'/uuid.uuid4().hex;box.mkdir(parents=True)
    source=fresh(box/'driver-source.py',Path(__file__).read_bytes(),task.REPO);controls=[]
    for i,dp in enumerate(index['taskDescriptorPins']):
        d=task.read_json(dp)
        for mode in ('empty','oracle','wrong'):
            if i==0 and mode=='oracle' and a.first_oracle:
                cp=task.pin(a.first_oracle.resolve());task.demand(cp['sha256']==a.first_oracle_sha256,'cold_reuse','Exact real previous oracle required')
                task.demand(task.read_json(cp)['taskDescriptorPin']==dp,'cold_reuse','Previous oracle descriptor/source differs')
            else:
                argv=['D:/ProgramData/anaconda3/python.exe','-B','-X','utf8',str(Path(__file__).with_name('skb-ten-cold-control-v2.py')),
                    '--descriptor',dp['path'],'--descriptor-sha256',dp['sha256'],'--storage',lp['path'],'--storage-sha256',lp['sha256'],'--mode',mode]
                child=subprocess.Popen(argv,cwd=task.REPO,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
                out,err=child.communicate(timeout=d['originalResources']['agent']['timeout_sec']+d['originalResources']['verifier']['timeout_sec']+400)
                fresh(box/(d['taskId']+'-'+mode+'-caller.txt'),out+err,task.REPO)
                rows=[json.loads(x) for x in out.splitlines() if x.startswith(b'{')]
                task.demand(child.returncode==0 and rows and rows[-1].get('controlPin'),'cold_failed','Actual cold control failed or mismatched; original evidence retained')
                cp=rows[-1]['controlPin']
            value=task.read_json(cp);task.demand(value['controlMatched'] is True,'cold_mismatch','Expected strict original G control did not match')
            controls.append(cp)
            print(json.dumps({'phase':'real-cold-control-replayed','taskId':d['taskId'],'mode':mode,'strictG':value['strictG'],'officialReward':value['officialReward'],
                'fullCollectionValid':value['fullCollectionValid'],'controlPin':cp,'modelCalls':0}),flush=True)
    out=fresh(box/'index.json',task.canonical({'protocol':'skillsbench-ten-real-cold-control-index-v2','collectionIndexPin':index_pin,'controlPins':controls,
        'sourcePin':task.pin(__file__),'executedSourcePin':source,'completedAtUtc':datetime.now(timezone.utc).isoformat(),
        'actualDistinctTaskTriplets':10,'actualColdControls':30,'modelCalls':0,'paidReady':False,'scoreCertificate':False}),task.REPO)
    print(json.dumps({'coldControlsIndexPin':out,'actualDistinctTaskTriplets':10,'modelCalls':0,'paidReady':False}),flush=True)


if __name__=='__main__':main()
