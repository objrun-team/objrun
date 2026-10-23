"""Same owner relay used by original cold controls and production Stand.
Only pristine sandbox Syzkaller receives rule/PCAP bytes; private pytest receives
ordinary process streams and EVE bytes. No host mount or Docker socket exposed.
"""
import json,queue,re,subprocess,threading,time,uuid,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent.parent))
from prepare import public,save
from build_environment import DOCKER,ENV
MAX=34*1024**2

def evaluate(built,artifacts,folder,command,timeout,mode='grade'):
    assert built['taskId']=='syzkaller-ppdev-syzlang' and built['separateSyzkallerSandbox'] is True
    for pin in built['syzlangSourcePins']:assert public.pin(Path(pin['path']))==pin
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    deadline=time.monotonic()+timeout;owned=[];commands=[];session=uuid.uuid4().hex
    e=built['originalResources']['environment']
    def create(image,role,private=False):
        argv=['create','-i','--pull','never','--read-only','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','256','--label','objrun.skb.role='+role,'--label','objrun.skb.syzlang-session='+session,'--memory',str(e['memory_mb']*1024**2),'--memory-swap',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus']),'--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=64m']
        if private:
            argv+=['--tmpfs','/logs/verifier:rw,nosuid,nodev,noexec,size=64m']
            argv += [a for parent in built['artifactTmpfsParents'] for a in ['--tmpfs',parent+':rw,nosuid,nodev,noexec,size='+str(built['artifactTmpfsBytes'])]]
        
        if not private:argv.remove('--read-only')
        argv+=['--workdir','/root',image]+(['--collect'] if private and mode=='collect' else [])
        cid=command(argv,30).decode().strip();assert re.fullmatch('[a-f0-9]{64}',cid);owned.append(cid)
        inspected=json.loads(command(['inspect',cid],30))[0];h=inspected['HostConfig']
        assert inspected['Image']==image and h['ReadonlyRootfs']==private and h['NetworkMode']=='none' and not h.get('Binds') and not h.get('Mounts') and not h.get('Privileged') and h['Memory']==e['memory_mb']*1024**2
        return cid
    def remove(cid):
        command(['rm','-f',cid],30);owned.remove(cid)
    proc=None;threads=[];stream_log=[]
    try:
        sid=create(built['sandboxImageId'],'syzlang-pristine-sandbox')
        command(['start',sid],30)
        gid=create(built['privateImageId'],'syzlang-private',True)
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
            remaining=deadline-time.monotonic();assert remaining>0,'original_verifier_deadline'
            line=messages.get(timeout=remaining)
            assert line is not None and not faults,'private_stream_closed_without_result'
            value=json.loads(line)
            if value.get('kind')=='syzlang_callback':
                assert set(value)=={'kind','request'};request=value['request']
                assert request['session']==session and type(request['serial']) is int and request['serial']==serial
                raw=json.dumps(request,separators=(',',':')).encode();assert len(raw)<=24*1024**2
                reply=command(['exec','-i',sid,'python3','-I','-B','-c',"import runpy,sys;sys.path.insert(0,'/opt/objrun-syzlang');runpy.run_path('/opt/objrun-syzlang/syzlang_sandbox_worker_adapter2_v1.py',run_name='__main__')"],min(request['timeout']+15,deadline-time.monotonic()),raw,stdout_limit=MAX)
                response=json.loads(reply)
                digest=hashlib.sha256(json.dumps(request,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                assert response['session']==session and response['serial']==serial and response['requestSha256']==digest
                serial+=1
                stream_log.append({'serial':request['serial'],'requestSha256':digest,'sandboxCid':sid,'responseSha256':hashlib.sha256(reply).hexdigest()})
                proc.stdin.write(json.dumps(response,separators=(',',':')).encode()+b'\n');proc.stdin.flush()
            else:
                assert value.get('taskId')=='syzkaller-ppdev-syzlang' and value.get('syzlangSeparateSandbox') is True
                result=value
        proc.stdin.close();code=proc.wait(timeout=max(1,deadline-time.monotonic()));assert code==0
        for thread in threads:thread.join(timeout=10)
        assert not faults and all(not t.is_alive() for t in threads)
        assert result['syzlangCallbackCount']==serial
        result['syzlangOwnerReceiptPin']=save(folder/'owner-receipt.json',{'session':session,'privateContainerId':gid,'privateImageId':built['privateImageId'],'sandboxImageId':built['sandboxImageId'],'callbacks':stream_log,'directChildExitCode':code,'directChildClosed':True,'modelCalls':0},True)
        remove(gid);remove(sid)
        return result
    finally:
        if proc and proc.poll() is None:proc.kill();proc.wait(timeout=10)
        for cid in owned[:]:
            try:remove(cid)
            except Exception:pass
        for thread in threads:thread.join(timeout=10)
        if proc:
            for stream in (proc.stdin,proc.stdout,proc.stderr):
                try:stream.close()
                except Exception:pass
        assert not owned,'syzlang_owned_container_cleanup_incomplete'
