"""Real original collection and 0/1/0 controls for independent Excel conversion."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import time
import uuid
from prepare import HOME,VENDOR,public,save,utc
from build_environment import DOCKER,ENV
from bounded_child import run
from ordinary_artifacts import Policy,parse_daemon_tar
from excel_conversion_protocol import PROFILES,decode

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--task',required=True,choices=PROFILES);a=parser.parse_args()
    bp=json.loads((HOME/'excel-environment-preparation'/a.task/'latest.json').read_bytes())['builtImagesPin'];assert public.pin(Path(bp['path']))==bp
    built=json.loads(Path(bp['path']).read_bytes());assert built['imagesBuilt'] and built['ownedContainersRemaining']==0
    assert all(public.pin(Path(p['path']))==p for p in built['sourcePins']);assert public.pin(Path(built['privateRunnerPin']['path']))==built['privateRunnerPin']
    home=HOME/'excel-grader-controls'/a.task/uuid.uuid4().hex;home.mkdir(parents=True);serial=0;owned=[];commands=[]
    e=built['originalResources']['environment'];verifier=built['originalResources']['verifier']['timeout_sec'];parent=built['artifactTmpfsParent'];path=PROFILES[a.task]['workbook']
    common=['--pull','never','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--memory',str(e['memory_mb']*1024**2),'--memory-swap',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus']),'--workdir',built['workingDirectory']]
    result={'protocol':'skillsbench-isolated-excel-grader-controls-v1','taskId':a.task,'createdAtUtc':utc(),'builtImagesPin':bp,'controlsPassed':False,'modelCalls':0,'formalScoreCertified':False,
        'sourcePins':[public.pin(Path(__file__)),public.pin(Path(__file__).with_name('excel_conversion_protocol.py'))],'evaluations':[]}
    def command(argv,timeout,body=None):
        nonlocal serial
        serial+=1;prefix=home/('command-%03d'%serial)
        outcome=run([DOCKER,*argv],ENV,prefix.with_suffix('.stdout'),prefix.with_suffix('.stderr'),timeout,body)
        pin=save(prefix.with_suffix('.json'),{'argv':[DOCKER,*argv],**outcome,'stdoutPin':public.pin(prefix.with_suffix('.stdout')),'stderrPin':public.pin(prefix.with_suffix('.stderr')),'modelCalls':0},True);commands.append(pin)
        if outcome['exitCode'] or outcome['faults']:raise RuntimeError('excel control operation failed: '+pin['path'])
        return prefix.with_suffix('.stdout').read_bytes()
    def create(image,role,readonly=True,mode=None,budget=None):
        argv=['create','-i',*common,'--label','objrun.skb.role='+role,'--label','objrun.skb.nonce='+home.name]
        network='bridge' if not readonly and e.get('network_mode')=='public' else 'none'
        argv[argv.index('--network')+1]=network
        if readonly:argv+=['--read-only','--tmpfs',parent+':rw,nosuid,nodev,noexec,size='+str(built['artifactTmpfsBytes']),'--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=64m','--tmpfs','/logs/verifier:rw,nosuid,nodev,noexec,size=64m']
        else:argv+=['--entrypoint','sleep']
        argv+=[image]
        if mode:argv+=[mode]
        if not readonly:argv+=['infinity']
        cid=command(argv,min(30,budget()) if budget else 30).decode().strip();assert len(cid)==64 and all(c in '0123456789abcdef' for c in cid);owned.append(cid)
        inspection=json.loads(command(['inspect',cid],min(30,budget()) if budget else 30))[0];host=inspection['HostConfig']
        assert inspection['Image']==image and host['NetworkMode']==network and not host.get('Binds') and not host.get('Mounts') and host['ReadonlyRootfs']==readonly
        return cid
    def remove(cid):command(['rm','-f',cid],30);owned.remove(cid)
    def private(mode,artifacts):
        began=time.monotonic()
        def remaining():
            value=verifier-(time.monotonic()-began)
            if value<=0:raise TimeoutError('original_combined_excel_verifier_budget')
            return value
        conversion=None
        if mode!='collect':
            cid=create(built['conversionImageId'],'full-f-excel-conversion-control',budget=remaining)
            raw=command(['start','-a','-i',cid],remaining(),json.dumps({'artifacts':artifacts}).encode())
            expected=artifacts[0]['sha256'] if artifacts else built['initialWorkbookSha256'];conversion=decode(raw,a.task,expected)
            assert conversion['converterSha256']==built['converterSha256'];remove(cid)
        cid=create(built['privateImageId'],'full-f-excel-private-control',mode='--collect' if mode=='collect' else None,budget=remaining)
        value=json.loads(command(['start','-a','-i',cid],remaining(),json.dumps({'artifacts':artifacts,'conversion':conversion}).encode()));remove(cid)
        assert value['taskId']==a.task and value['complete'] and not value['candidateExecutablesUsed'] and not value['candidateSnapshotUsed']
        elapsed=time.monotonic()-began;assert elapsed<=verifier
        pin=save(home/(mode+'.json'),{'evaluation':value,'conversion':conversion,'elapsedSeconds':elapsed,'modelCalls':0},True)
        result['evaluations'].append({'mode':mode,'resultPin':pin,'reward':value['reward'],'nodeIds':value['nodeIds']});return value
    try:
        collection=private('collect',[]);empty=private('empty',[])
        oracle=create(built['candidateImageId'],'full-f-excel-oracle-control',False);command(['start',oracle],30)
        source=VENDOR/'tasks'/a.task/'oracle';source_before=public.tree(source)
        command(['cp',str(source),oracle+':/oracle'],30)
        command(['exec',oracle,'bash','/oracle/solve.sh'],built['originalResources']['agent']['timeout_sec'])
        raw=command(['cp',oracle+':'+path,'-'],30);files=parse_daemon_tar(raw,Policy(path));assert len(files)==1
        artifacts=[{'path':f['path'],'base64':base64.b64encode(f['body']).decode(),'sha256':f['sha256']} for f in files];remove(oracle)
        correct=private('oracle',artifacts);wrong=private('wrong',[{'path':path,'base64':base64.b64encode(b'wrong workbook').decode(),'sha256':hashlib.sha256(b'wrong workbook').hexdigest()}])
        result.update(actualPytestCollection=collection['nodeIds'],decisions=[empty['reward'],correct['reward'],wrong['reward']],originalOracleTree=source_before,
            originalTestsUnchanged=public.tree(source)==source_before,namespaceSeparation=True)
        result['controlsPassed']=result['decisions']==[0,1,0] and all(v['nodeIds']==collection['nodeIds'] for v in (empty,correct,wrong)) and result['originalTestsUnchanged']
        assert result['controlsPassed'] and all(public.pin(Path(p['path']))==p for p in result['sourcePins'])
    except Exception as error:result['failure']={'type':type(error).__name__,'detail':str(error)};raise
    finally:
        for cid in owned[:]:
            try:remove(cid)
            except Exception:pass
        result.update(ownedContainersRemaining=len(owned),ownedContainerIds=owned,commandPins=commands)
        pin=save(home/'result.json',result,True);save(HOME/'excel-grader-controls'/a.task/'latest.json',{'controlPin':pin});print(json.dumps({'controlPin':pin,'controlsPassed':result['controlsPassed'],'modelCalls':0}))

if __name__=='__main__':main()
