"""No-Bench fixture for the original adapter2 HTTP child and runtime transport."""
import argparse,hashlib,json,os,pathlib,uuid
from native_process import pin

def deploy(command,cid,task_id,output):
    assert task_id=='zero-model-owned-sb-asset'
    receipt=command(['exec',cid,'/bin/sh','-c','printf neutral-public-skill > /app/neutral-public-skill.txt'])
    return {'protocol':'bench-neutral-public-skill-fixture-v1','taskId':task_id,'actualDockerWrite':True,'modelCalls':0}

def main():
    from http_stand_client_v1 import HttpStand
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--resource-owner-pid',required=True,type=int);a=p.parse_args()
    out=pathlib.Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True);task='zero-model-owned-sb-asset';nonce=uuid.uuid4().hex
    base='sha256:69f919497cada9a8611f3de61df902d9f94bf20f84552ef5bd93125c38608ef9'
    def save(name,value):q=out/name;q.write_text(json.dumps(value,indent=2)+'\n');return pin(q)
    built=save('neutral-built-fixture.json',dict(protocol='bench-no-task-content-http-fixture-v1',taskId=task,candidateImageId=base,noBenchContent=True,qualificationProof=False))
    control=save('neutral-control-shape-fixture.json',dict(protocol='bench-no-task-content-http-fixture-v1',taskId=task,builtImagesPin=built,controlsPassed=True,ownedContainersRemaining=0,noBenchContent=True,qualificationProof=False))
    resource=dict(environment=dict(memory_mb=4096,cpus=2,storage_mb=10240,network_mode='no-network'))
    row=dict(taskId=task,id='neutral-http-'+nonce,originalResources=resource,workdir='/app',taskSeconds=180)
    config=dict(output=str(out/'actual-http'),runId='neutral-http-'+nonce,resourceOwnerPid=a.resource_owner_pid,schedule=[row],taskReadiness={task:dict(adapter='group01-adapter2-v1',builtImagesPin=built,controlPin=control)})
    pathlib.Path(config['output']).mkdir();stand=HttpStand(config,uuid.uuid4().hex);place='skb:'+row['id'];created=None;closed=None;shutdown=None
    try:
        ping=stand.request('/place',dict(place=place,op='ping'),180);assert ping['alive'];created=ping['ownedContainerID']
        result=stand.request('/place',dict(place=place,tool='bash',args=dict(command='printf neutral-original-http; /rt-node --version',timeout=10000)),30)
        assert 'neutral-original-http' in json.dumps(result) and 'v22.22.2' in json.dumps(result)
        copies=list((stand.home/'server-local-runtime-cache').glob('*.json'));verified=[]
        for q in copies:
            value=json.loads(q.read_bytes())
            if value.get('protocol')=='bench-original-sb-http-runtime-copy-v1':
                assert value['result']['guestSha256']==value['canonicalSourcePin']['sha256'];verified.append(pin(q))
        assert len(verified)==4
        closed=stand.stop();shutdown=stand.shutdown();assert closed['ownedContainersRemaining']==closed['ownedNativeChildrenRemaining']==0 and shutdown['workerProcessClosed']
        save('result.json',dict(complete=True,actorClosed=True,actualHttp=True,explicitOriginalChild=True,createdCid=created,runtimeCopyPins=verified,toolResult=result,stop=closed,shutdown=shutdown,originalWorkerPid=stand.worker_pid,modelCalls=0,gradeCalls=0,referenceCalls=0,noBenchContent=True,qualificationProof=False))
    finally:
        if stand.proc.poll() is None:
            stand.stop();stand.shutdown()
if __name__=='__main__':main()
