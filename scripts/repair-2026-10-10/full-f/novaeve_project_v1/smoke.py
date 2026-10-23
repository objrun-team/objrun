"""Small benign Docker smoke test. No benchmark, solver or model calls."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
from manage import NAS, DATA, CONFIG, SOCKET, environment, globals_snapshot, info, write_json, stamp

HERE=Path(__file__).resolve().parent

def main():
    run='smoke-'+stamp()+'-'+uuid.uuid4().hex[:8]
    folder=NAS/'evidence'/run;folder.mkdir(parents=True)
    label='tgengin.smoke='+run;containers=[];images=[];receipts=[];checks={};fault=None
    def docker(args,timeout=30):
        number=len(receipts)+1;start=time.monotonic()
        proc=subprocess.Popen([sys.executable,'-B',str(HERE/'project_docker.py')]+args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        expired=False
        try:out,err=proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            expired=True;proc.kill();out,err=proc.communicate(timeout=10)
        prefix=folder/('%03d'%number)
        prefix.with_suffix('.stdout').write_bytes(out);prefix.with_suffix('.stderr').write_bytes(err)
        receipt={'args':args,'exitCode':proc.returncode,'timedOut':expired,'seconds':time.monotonic()-start,
                 'stdout':str(prefix.with_suffix('.stdout')),'stderr':str(prefix.with_suffix('.stderr'))}
        receipts.append(receipt)
        if expired:raise TimeoutError('smoke_command_deadline')
        if proc.returncode:raise RuntimeError('smoke_command_failed:'+str(number))
        return out
    def create(image,args,network='none'):
        cid=docker(['create','--label',label,'--network',network,'--cap-drop','ALL','--security-opt','no-new-privileges','--entrypoint','/bin/sh',image,'-c',args]).decode().strip()
        containers.append(cid);return cid
    def remove(cid):
        metadata=json.loads(docker(['inspect',cid]))[0]
        assert metadata['Config']['Labels'].get('tgengin.smoke')==run
        docker(['rm','-f',cid]);containers.remove(cid)
    try:
        metadata=info();write_json(folder/'docker-info.json',metadata)
        checks['privateDaemonRoot']=metadata['DockerRootDir']==str(DATA/'docker')
        base=json.loads(docker(['image','inspect','busybox:1.36.1']))[0]
        write_json(folder/'base-image.json',base)
        cid=create(base['Id'],'printf "tgengin-started\\n"; printf "container-to-nas\\n" >/tmp/output.txt; sleep 300')
        docker(['start',cid]);assert docker(['exec',cid,'/bin/sh','-c','printf "exec-ok"'])==b'exec-ok'
        checks['createStartExec']=True
        isolated=json.loads(docker(['inspect',cid]))[0]
        assert isolated['HostConfig']['NetworkMode']=='none' and not isolated['Mounts']
        assert isolated['HostConfig']['Memory']==0 and isolated['HostConfig']['NanoCpus']==0
        checks['noResourceQuotas']=True;checks['noHostMountsOrNetwork']=True
        output=folder/'container-output.txt';docker(['cp',cid+':/tmp/output.txt',str(output)])
        assert output.read_bytes()==b'container-to-nas\n';checks['containerToNasCopy']=True
        input_file=folder/'input.txt';input_file.write_bytes(b'nas-to-container\n')
        docker(['cp',str(input_file),cid+':/tmp/input.txt'])
        assert docker(['exec',cid,'cat','/tmp/input.txt'])==input_file.read_bytes();checks['nasToContainerCopy']=True
        snapshot=docker(['commit','--pause=true',cid],60).decode().strip();images.append(snapshot)
        snap=create(snapshot,'cat /tmp/input.txt');assert docker(['start','-a',snap])==input_file.read_bytes();remove(snap)
        checks['commitSnapshotReplay']=True
        context=folder/'build-context';context.mkdir();(context/'payload.txt').write_bytes(b'built-locally\n')
        assert base['RepoDigests'], 'immutable_base_digest_required'
        (context/'Dockerfile').write_text('FROM '+base['RepoDigests'][0]+'\nCOPY payload.txt /payload.txt\nRUN test -s /payload.txt\n')
        iidfile=folder/'built-image-id.txt';docker(['build','--network','none','--pull=false','--iidfile',str(iidfile),str(context)],60)
        built=iidfile.read_text().strip();images.append(built)
        bid=create(built,'cat /payload.txt');assert docker(['start','-a',bid])==b'built-locally\n';remove(bid)
        checks['localImageBuild']=True
        server=create(base['Id'],'mkdir -p /tmp/web; printf "isolated-http-ok" >/tmp/web/index.html; exec httpd -f -p 127.0.0.1:18080 -h /tmp/web')
        docker(['start',server])
        transport=create(base['Id'],'wget -qO- http://127.0.0.1:18080/',network='container:'+server)
        assert docker(['start','-a',transport])==b'isolated-http-ok'
        remove(transport);remove(server);checks['isolatedLoopbackTransport']=True
        logs=docker(['logs',cid]);assert b'tgengin-started' in logs;checks['containerLogsCaptured']=True
        try:docker(['exec',cid,'sleep','30'],2)
        except TimeoutError:checks['execTimeoutObserved']=True
        else:raise AssertionError('timeout_not_triggered')
        remove(cid)  # Remove whole actor, including exec left after client timeout.
        checks['timedOutActorRemoved']=True
    except BaseException as error:
        fault={'type':type(error).__name__,'detail':str(error)}
    finally:
        cleanup=[]
        for cid in list(containers):
            try:remove(cid)
            except Exception as error:cleanup.append(str(error))
        for image in images:
            try:docker(['image','rm',image])
            except Exception as error:cleanup.append(str(error))
        remaining=docker(['ps','-aq','--filter','label='+label]).decode().split()
        before=json.loads((NAS/'runtime/global-config-before.json').read_text())
        checks['globalConfigurationUnchanged']=globals_snapshot()==before
        checks['ownedContainersClosed']=not remaining and not cleanup
        write_json(folder/'commands.json',receipts)
        result={'runId':run,'completed':fault is None and all(checks.values()),'checks':checks,'failure':fault,
                'cleanupErrors':cleanup,'remainingContainerIds':remaining,'dockerRoot':str(DATA/'docker'),
                'socket':str(SOCKET),'evidenceDirectory':str(folder),'formalBenchmark':False,'modelCalls':0,
                'scope':'rootful project Docker, no per-container resource quotas; network none; benign smoke only'}
        write_json(folder/'result.json',result)
        files=[]
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                raw=path.read_bytes();files.append({'path':str(path.relative_to(folder)),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
        write_json(folder/'manifest.json',{'runId':run,'files':files})
        print(json.dumps(result,sort_keys=True))
    return 0 if result['completed'] else 1

if __name__=='__main__':sys.exit(main())
