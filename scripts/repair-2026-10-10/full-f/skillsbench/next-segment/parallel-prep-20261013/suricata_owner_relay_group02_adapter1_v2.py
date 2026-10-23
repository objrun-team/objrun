"""Same owner relay used by original cold controls and production Stand.
Only pristine sandbox Suricata receives rule/PCAP bytes; private pytest receives
ordinary process streams and EVE bytes. No host mount or Docker socket exposed.
"""
import json,queue,re,subprocess,threading,time,uuid,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent.parent))
from prepare import public,save
from build_environment import DOCKER,ENV
MAX=34*1024**2

def evaluate(built,artifacts,folder,command,timeout,mode='grade'):
    assert built['taskId']=='suricata-custom-exfil' and built['separateSuricataSandbox'] is True
    for pin in built['suricataSourcePins']:assert public.pin(Path(pin['path']))==pin
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    deadline=time.monotonic()+timeout;owned=[];owned_images={};cleanup_errors=[];commands=[];session=uuid.uuid4().hex
    e=built['originalResources']['environment']
    def create(image,role,private=False):
        argv=['create','-i','--pull','never','--read-only','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','256','--label','objrun.skb.role='+role,'--label','objrun.skb.suricata-session='+session,'--memory',str(e['memory_mb']*1024**2),'--memory-swap',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus']),'--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=64m']
        if private:
            argv+=['--tmpfs','/logs/verifier:rw,nosuid,nodev,noexec,size=64m']
            argv += [a for parent in built['artifactTmpfsParents'] for a in ['--tmpfs',parent+':rw,nosuid,nodev,noexec,size='+str(built['artifactTmpfsBytes'])]]
        argv+=['--workdir','/root',image]+(['--collect'] if private and mode=='collect' else [])
        cid=command(argv,30).decode().strip();assert re.fullmatch('[a-f0-9]{64}',cid);owned.append(cid);owned_images[cid]=image
        inspected=json.loads(command(['inspect',cid],30))[0];h=inspected['HostConfig']
        assert inspected['Id']==cid and inspected['Config']['Labels'].get('objrun.skb.suricata-session')==session and inspected['Config']['Labels'].get('objrun.skb.role')==role
        assert inspected['Image']==image and h['ReadonlyRootfs'] and h['NetworkMode']=='none' and not h.get('Binds') and not h.get('Mounts') and not h.get('Privileged') and h['Memory']==e['memory_mb']*1024**2
        return cid
    def remove(cid):
        inspected=json.loads(command(['inspect',cid],30))[0]
        assert inspected['Id']==cid and inspected['Image']==owned_images[cid] and inspected['Config']['Labels'].get('objrun.skb.suricata-session')==session,'foreign_actor_cleanup_denied'
        command(['rm','-f',cid],30);owned.remove(cid);del owned_images[cid]
    proc=None;threads=[];stream_log=[];result=None
    try:
        gid=create(built['privateImageId'],'suricata-private',True)
        argv=[DOCKER,'start','-a','-i',gid]
        proc=subprocess.Popen(argv,env=ENV,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        messages=queue.Queue();stderr=bytearray();faults=[]
        def read_stdout():
            try:
                while True:
                    line=proc.stdout.readline(MAX+1)
                    if not line:break
                    if len(line)>MAX or not line.endswith(b'\n'):raise ValueError('bounded_private_frame')
                    messages.put(line)
            except BaseException as error:faults.append(type(error).__name__)
            finally:messages.put(None)
        def read_stderr():
            try:
                while body:=proc.stderr.read(65536):
                    if len(stderr)+len(body)>2*1024**2:raise ValueError('private_stderr_bound')
                    stderr.extend(body)
            except BaseException as error:faults.append(type(error).__name__)
        threads=[threading.Thread(target=read_stdout,daemon=True),threading.Thread(target=read_stderr,daemon=True)]
        for thread in threads:thread.start()
        proc.stdin.write(json.dumps({'artifacts':artifacts,'session':session},separators=(',',':')).encode()+b'\n');proc.stdin.flush()
        result=None;serial=0
        while result is None:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('original_verifier_deadline')
            try:line=messages.get(timeout=remaining)
            except queue.Empty as error:raise TimeoutError('original_verifier_deadline') from error
            assert line is not None and not faults,'private_stream_closed_without_result'
            value=json.loads(line)
            if value.get('kind')=='suricata_callback':
                assert set(value)=={'kind','request'};request=value['request']
                assert request['session']==session and type(request['serial']) is int and request['serial']==serial
                sid=create(built['sandboxImageId'],'suricata-pristine-sandbox')
                try:
                    raw=json.dumps(request,separators=(',',':')).encode();assert len(raw)<=24*1024**2
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('original_verifier_deadline')
                    reply=command(['start','-a','-i',sid],min(195,remaining),raw,stdout_limit=MAX)
                    response=json.loads(reply)
                    digest=hashlib.sha256(json.dumps(request,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                    assert response['session']==session and response['serial']==serial and response['requestSha256']==digest
                    serial+=1
                    stream_log.append({'serial':request['serial'],'requestSha256':digest,'sandboxCid':sid,'responseSha256':hashlib.sha256(reply).hexdigest()})
                    proc.stdin.write(json.dumps(response,separators=(',',':')).encode()+b'\n');proc.stdin.flush()
                finally:remove(sid)
            else:
                assert value.get('taskId')=='suricata-custom-exfil' and value.get('suricataSeparateSandbox') is True
                result=value
        proc.stdin.close()
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('original_verifier_deadline')
        try:code=proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:raise TimeoutError('original_verifier_deadline') from error
        assert code==0
        for thread in threads:thread.join(timeout=10)
        assert not faults and all(not t.is_alive() for t in threads)
        assert result['suricataCallbackCount']==serial
        result['suricataOwnerReceiptPin']=save(folder/'owner-receipt.json',{'session':session,'privateContainerId':gid,'privateImageId':built['privateImageId'],'sandboxImageId':built['sandboxImageId'],'callbacks':stream_log,'directChildExitCode':code,'directChildClosed':True,'modelCalls':0},True)
        remove(gid)
        return result
    finally:
        original_error=sys.exc_info()[1]
        if proc and proc.poll() is None:
            try:proc.kill();proc.wait(timeout=10)
            except Exception as error:cleanup_errors.append({'actor':'docker-attach','type':type(error).__name__,'detail':str(error)[:4096]})
        for cid in owned[:]:
            try:remove(cid)
            except Exception as error:cleanup_errors.append({'actor':cid,'type':type(error).__name__,'detail':str(error)[:4096]})
        for thread in threads:thread.join(timeout=10)
        if proc:
            for stream in (proc.stdin,proc.stdout,proc.stderr):
                try:stream.close()
                except Exception:pass
        closure={'session':session,'privateImageId':built['privateImageId'],'sandboxImageId':built['sandboxImageId'],'completed':original_error is None and not owned and not cleanup_errors and (proc is None or proc.poll() is not None) and all(not thread.is_alive() for thread in threads),'error':None if original_error is None else {'type':type(original_error).__name__,'detail':str(original_error)[:4096]},'ownedContainersRemaining':len(owned),'ownedContainerIds':owned[:],'cleanupErrors':cleanup_errors,'directChildClosed':proc is None or proc.poll() is not None,'pipeReadersClosed':all(not thread.is_alive() for thread in threads),'originalVerifierDeadlinePreserved':True,'originalVerifierSeconds':timeout,'modelCalls':0}
        closure_pin=save(folder/'owner-closure.json',closure,True)
        if result is not None:result['suricataOwnerClosurePin']=closure_pin
        assert not owned and not cleanup_errors and closure['directChildClosed'] and closure['pipeReadersClosed'],'suricata_owned_actor_cleanup_incomplete'
