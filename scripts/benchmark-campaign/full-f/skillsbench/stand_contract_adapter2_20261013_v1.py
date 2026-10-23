"""Real dedicated Stand + frozen six-tool controls; reuses saved reference.

No oracle, model, scheduler or registration operation is performed. Invoke
through prepare launcher --stage stand --execute under original broker lease.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import time
import uuid
from adapter2_20261013_v1 import descriptor, public, save, assert_lease, OUTPUTS
from pipeline_adapter2_20261013_v1 import Transport
from data_stand_adapter2_20261013_v1 import Stand

def contract(task,home,owner):
    home=Path(home);row=descriptor(task);assert_lease(owner,row['originalResources'])
    control_pin=public.pin(home/'controls.json');control=json.loads((home/'controls.json').read_bytes())
    assert control['controlsPassed'] and control['decisions']==[0,1,0] and control['ownedContainersRemaining']==0
    built_pin=control['builtImagesPin'];assert public.pin(Path(built_pin['path']))==built_pin
    built=json.loads(Path(built_pin['path']).read_bytes())
    names=['stand_contract_adapter2_20261013_v1.py','data_stand_adapter2_20261013_v1.py','adapter2_20261013_v1.py','runtime_private_task_adapter2_20261013_v1.ts','pipeline_adapter2_20261013_v1.py','next-segment/private_task_worker_entry_adapter2_20261013_v1.ts']
    source_pins=[public.pin(Path(__file__).parent/name) for name in names]
    existing=home/'stand-contract.json'
    if existing.exists():
        prior=json.loads(existing.read_bytes())
        if prior['verified'] and prior['controlPin']==control_pin and prior['sourcePins']==source_pins:
            for pin in prior['gradeOwnerPins']+prior['toolReceiptPins']:assert public.pin(Path(pin['path']))==pin
            return {'standContractPin':public.pin(existing),'reused':True,'modelCalls':0}
    reference=json.loads((home/'reference-checkpoint.json').read_bytes());assert reference['candidateImageId']==built['candidateImageId']
    run=home/('stand-'+uuid.uuid4().hex);run.mkdir();nonce=uuid.uuid4().hex;place='skb:adapter2-'+nonce
    config={'output':str(run),'runId':'adapter2-native-'+nonce,'resourceOwnerPid':owner,
      'schedule':[{**row,'id':'adapter2-'+nonce}],
      'taskReadiness':{task:{'adapter':'group01-adapter2-v1','builtImagesPin':built_pin,'controlPin':control_pin}}}
    old=os.environ.get('TGENGIN_GRADER_TOKEN');os.environ['TGENGIN_GRADER_TOKEN']=uuid.uuid4().hex
    stand=Stand(config);transport=Transport(stand.home,owner,row['originalResources']);owned=[];tool_pins=[];grade_pins=[]
    def command(args,*positional,**kwargs):
        if positional:kwargs['timeout']=positional[0]
        try:return transport.command(args,**kwargs)
        finally:stand.serial=transport.serial
    stand.command=command
    try:
        stand.create({'place':place});assert stand.current and stand.current['running']
        file='/tmp/adapter2-contract.txt'
        requests=[('bash',{'command':'printf contract-ready'}),('write',{'file_path':file,'content':'before'}),
          ('read',{'file_path':file}),('edit',{'file_path':file,'old_string':'before','new_string':'after'}),
          ('glob',{'pattern':'adapter2-contract.txt','path':'/tmp'}),('grep',{'pattern':'after','path':file})]
        assert set(stand.assets['toolNames'])=={tool for tool,args in requests}
        for tool,args in requests:
            response=stand.call({'place':place,'tool':tool,'args':args});assert not response.get('isError'),response
            tool_pins.append(save(run/(tool+'-receipt.json'),{'tool':tool,'request':args,'response':response,'nativeDocker':True,'modelCalls':0}))
        first=stand.grade({'place':place,'said':'missing'},'verified');assert first['valid'] and not first['passed'];grade_pins.append(first['gradeOwnerPin'])
        cached=stand.grade({'place':place,'said':'missing'},'passed');assert cached['gradeOwnerPin']==first['gradeOwnerPin']
        e=row['originalResources']['environment']
        ref=command(['create','--pull','never','--network','none','--entrypoint','/bin/bash',reference['referenceImageId'],'-c','sleep infinity']).decode().strip();owned.append(ref)
        cid=stand.current['cid'];command(['stop','-t','1',cid]);stand.current['running']=False
        paths=['/app/.'] if task=='fix-visual-stability' else OUTPUTS[task]
        for path in paths:
            # Opaque daemon tar goes to an untrusted solver container, never
            # into host filesystem or the trusted verifier.
            raw=command(['cp',ref+':'+path,'-'],stdout_limit=e['storage_mb']*1024**2+18432)
            target='/app' if path=='/app/.' else str(Path(path).parent).replace('\\','/')
            command(['cp','-',cid+':'+target],stdin=raw)
        command(['start',cid]);stand.current['running']=True;stand.current['mutation']+=1;stand.latest=None
        second=stand.grade({'place':place,'said':'saved-reference'},'verified');assert second['valid'] and second['passed'];grade_pins.append(second['gradeOwnerPin'])
        assert stand.grade({'place':place,'said':'saved-reference'},'passed')['gradeOwnerPin']==second['gradeOwnerPin']
        if task=='fix-visual-stability':
            script="from pathlib import Path; Path('/app/src/app/page.tsx').write_text('export default function Page(){return <main>Wrong</main>}')"
        elif task=='reserves-at-risk-calc':
            script="from openpyxl import load_workbook\np='/root/output/rar_result.xlsx';w=load_workbook(p)\nfor s in w:\n for r in s:\n  for c in r:\n   if c.data_type=='f':c.value=0\nw.save(p)"
        else:script="from pathlib import Path;Path('/outputs/report.json').write_text('{}')"
        response=stand.call({'place':place,'tool':'bash','args':{'command':'python3 -c '+shlex.quote(script)}});assert not response.get('isError')
        third=stand.grade({'place':place,'said':'deliberately-wrong'},'verified');assert third['valid'] and not third['passed'];grade_pins.append(third['gradeOwnerPin'])
        assert len({pin['path'] for pin in grade_pins})==3
        for pin in grade_pins:assert public.pin(Path(pin['path']))==pin
        assert [json.loads(Path(p['path']).read_bytes())['result']['reward'] for p in grade_pins]==[0,1,0]
    finally:
        try:stand.stop()
        finally:
            try:
                for cid in reversed(owned):command(['rm','-f',cid])
            finally:
                if old is None:os.environ.pop('TGENGIN_GRADER_TOKEN',None)
                else:os.environ['TGENGIN_GRADER_TOKEN']=old
    proof={'protocol':'group01-adapter2-native-stand-contract-v1','taskId':task,'verified':True,'nativeDocker':True,'sixToolsVerified':True,
      'toolNames':[tool for tool,args in requests],'toolReceiptPins':tool_pins,'gradeOwnerPins':grade_pins,'decisions':[0,1,0],
      'controlPin':control_pin,'builtImagesPin':built_pin,'sourcePins':source_pins,'ownedContainersRemaining':0,'modelCalls':0,
      'actions':['create','place-six-tools','verified','passed-immediate-cache','reference-refresh','wrong-refresh','close'],
      'oracleRepeated':False,'readyRegistered':False,'native_ready':False,'engineGatewayNativeVerified':False}
    save(existing,proof);return {'standContractPin':public.pin(existing),'modelCalls':0,'registered':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--task',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--resource-owner-pid',type=int,required=True);a=p.parse_args()
    print(json.dumps(contract(a.task,a.output,a.resource_owner_pid)))
