"""Actual bounded owned D allocation and original task reserve observation."""
import argparse
import json
from pathlib import Path
import shutil
import time
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_build_storage_v1 as build_storage


def main():
    p=argparse.ArgumentParser();p.add_argument('--storage',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--reserve',type=int,required=True);a=p.parse_args()
    lp=task.pin(a.storage.resolve());task.demand(lp['sha256']==a.sha256 and 0<=a.reserve<=512*1024**2,'resource_pin','Exact bounded current storage/reservation required')
    d=task.read_json(lp);storage.validate_descriptor(d);owned=build_storage.observe(d);free={k:shutil.disk_usage(k+':/').free for k in ('C','D','F')}
    minimum={'C':storage.C_MIN,'D':storage.D_MIN+a.reserve,'F':storage.F_MIN+storage.F_POINTER_CAP+storage.DOCKER_METADATA_RESERVE+storage.F_STOP_BUFFER+10*1024**3}
    admitted=owned['allocatedEnvelopeBytes']+a.reserve<=storage.STORE_CAP and all(free[k]>=minimum[k] for k in minimum)
    print(json.dumps({'protocol':'skillsbench-actual-resource-observation-v2','storageDescriptorPin':lp,'atUnixMs':int(time.time()*1000),'ownedAllocatedEnvelopeBytes':owned['allocatedEnvelopeBytes'],
        'reserveBytes':a.reserve,'storeCapBytes':storage.STORE_CAP,'volumeFreeBytes':free,'requiredVolumeFreeBytes':minimum,'admitted':admitted,'modelCalls':0,
        'sourcePins':[task.pin(__file__),task.pin(storage.__file__),task.pin(build_storage.__file__)]}),flush=True)
    raise SystemExit(0 if admitted else 1)


if __name__=='__main__':main()
