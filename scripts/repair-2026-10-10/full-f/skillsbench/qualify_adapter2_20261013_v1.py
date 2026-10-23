"""Qualification entry for the existing broker owner's admitted transport.

Transport must export command, missing_artifact and
assert_active_original_broker_lease(taskId, originalResources). It must retain
the lease through this call and release it in its coordinator finally block.
This entry never obtains a second lease, starts a scheduler or publishes.
"""
import argparse
import importlib.util
import json
from pathlib import Path
from adapter2_20261013_v1 import descriptor, qualify, public

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--admitted-transport',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();request=json.loads(args.request.read_bytes())
    pin=request['transportSourcePin'];assert public.pin(args.admitted_transport)==pin
    built=request['built'];row=descriptor(built['taskId'])
    assert built['originalResources']==row['originalResources']
    assert len(request['controls'])==3 and [c['kind'] for c in request['controls']]==['empty','oracle','wrong']
    spec=importlib.util.spec_from_file_location('adapter2_admitted_transport',args.admitted_transport)
    transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(transport)
    transport.assert_active_original_broker_lease(built['taskId'],row['originalResources'])
    controls=[(c['cid'],c['nonce'],transport.missing_artifact) for c in request['controls']]
    value=qualify(transport.command,built,controls,args.output,request['resourceOwnerPid'])
    print(json.dumps({'controlPin':public.pin(args.output),'modelCalls':0,'registered':False,'native_ready':False}))

if __name__=='__main__':main()
