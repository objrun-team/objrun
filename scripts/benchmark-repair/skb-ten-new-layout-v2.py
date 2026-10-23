"""Prepare a fresh own layout using already frozen actual task/runtime evidence."""
import argparse
import json
from pathlib import Path
import uuid
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
from skb_artifact_ram_executor_v2 import fresh


def main():
    p=argparse.ArgumentParser();p.add_argument('--collections',type=Path,required=True);p.add_argument('--sha256',required=True);a=p.parse_args()
    q=task.pin(a.collections.resolve());task.demand(q['sha256']==a.sha256,'layout_pin','Exact real10 collection graph required');c=task.read_json(q)
    task.demand(c['actualDistinctTaskCollections']==10,'layout_scope','All10 collections required')
    box=task.REPO/'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/fresh-layouts'/uuid.uuid4().hex;box.mkdir(parents=True)
    lp=fresh(box/'storage-descriptor.json',task.canonical(storage.descriptor(uuid.uuid4().hex)),task.REPO)
    out=fresh(box/'preparation.json',task.canonical({'protocol':'skillsbench-ten-prepared-runtime-v1','taskDescriptorPins':c['taskDescriptorPins'],
        'collectionIndexPin':q,'storageDescriptorPin':lp,'sourcePins':[task.pin(__file__),task.pin(task.__file__),task.pin(storage.__file__)],
        'freshGeometryOnly':True,'imagesAndDepotReusedByExactClosedPins':True,'modelCalls':0,'DockerOperations':0,'paidReady':False}),task.REPO)
    print(json.dumps({'preparationPin':out,'storageDescriptorPin':lp,'modelCalls':0}),flush=True)


if __name__=='__main__':main()
