"""Scan actual host secret values in ordinary owned evidence and expanded archives."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import zipfile
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
from skb_artifact_ram_executor_v2 import fresh


def main():
    p=argparse.ArgumentParser();p.add_argument('--storage',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    lp=task.pin(a.storage.resolve());task.demand(lp['sha256']==a.sha256,'secret_store','Exact own storage required');d=task.read_json(lp);storage.validate_descriptor(d);root=Path(d['storePhysical'])
    values=json.loads(sys.stdin.buffer.read(64*1024));task.demand(isinstance(values,list) and values and all(isinstance(x,str) and 6<=len(x)<=4096 for x in values),'secret_values','Actual bounded retained host secret values required')
    needles=[x.encode() for x in values];maximum=max(map(len,needles));files=[];expanded=[]
    def check(stream):
        carry=b'';size=0
        while chunk:=stream.read(1024**2):
            size+=len(chunk);task.demand(size<=storage.STORE_CAP,'secret_expansion','Expanded source/evidence cap exceeded')
            block=carry+chunk;task.demand(not any(x in block for x in needles),'secret_in_evidence','An actual host secret appears in exportable owned evidence')
            carry=block[-maximum+1:]
    for path in sorted(root.rglob('*')):
        if path.is_dir():continue
        storage.ordinary(path.parent,root);task.demand(path.is_file() and not path.is_symlink() and path.stat().st_nlink==1,'secret_file','Only ordinary owned evidence files')
        q=task.pin(path);task.demand(not path.name.endswith('config.yaml'),'secret_private_config','Private engine config remains in evidence')
        with path.open('rb') as f:check(f)
        if path.suffix=='.gz':
            with gzip.open(path,'rb') as f:check(f)
            expanded.append(str(path))
        elif path.suffix=='.zip':
            with zipfile.ZipFile(path) as archive:
                for item in archive.infolist():
                    task.demand(not item.is_dir() and item.file_size<=storage.STORE_CAP,'secret_zip','Bounded source ZIP member required')
                    with archive.open(item) as f:check(f)
            expanded.append(str(path))
        task.demand(task.pin(path)==q,'secret_source_changed','Evidence changed while scanning actual values');files.append(q)
    out=fresh(a.output.resolve(),task.canonical({'protocol':'skillsbench-ten-actual-secret-audit-v2','storageDescriptorPin':lp,'actualSecretValueCount':len(needles),
        'secretValueHashes':[{'sha256':hashlib.sha256(x).hexdigest(),'bytes':len(x)} for x in needles],'secretValuesSerialized':False,
        'scannedFiles':files,'expandedArchives':expanded,'noActualSecretValueFound':True,'noPrivateEngineConfigsRemain':True,'modelCalls':0,'sourcePin':task.pin(__file__)}),root)
    print(json.dumps({'secretAuditPin':out,'actualSecretValueCount':len(needles),'modelCalls':0}),flush=True)


if __name__=='__main__':main()
