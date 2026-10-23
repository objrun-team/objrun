"""Stopped full candidate replay with separate pristine original private tests.

No candidate image is used as the private interpreter. Full candidate dependencies
are kept by a committed execution-only snapshot. All Docker actors are owned.
Caller must hold the existing broker lease; this module never obtains paid work.
"""
import base64,hashlib,json,os,posixpath,subprocess,tarfile,time,uuid
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from build_environment import DOCKER,ENV
from bounded_child import run as bounded_run
from prepare import ROOT,public,save

HERE=Path(__file__).resolve().parent

def evaluate_snapshot(command,cid,nonce,proof,owner_pid,home):
    task=proof['taskId'];assert task in ('lean4-proof','react-performance-debugging')
    for pin in proof['sourcePins']+[proof['builtImagesPin']]:assert public.pin(Path(pin['path']))==pin
    built=json.loads(Path(proof['builtImagesPin']['path']).read_bytes());assert built['taskId']==task
    resources=built['originalResources'];e=resources['environment'];budget=resources['verifier']['timeout_sec'];began=time.monotonic()
    control=json.loads((ROOT/'docs/repair-2026-10-10/full-f-rerun/control.json').read_bytes());health=json.loads(Path(control['broker']['healthPath']).read_bytes())
    slots=[slot for slot in health['resourceSlots'] if slot['slug']=='skillsbench' and slot['pid']==owner_pid and slot['kind']=='heavy-container']
    assert health['pid']==control['broker']['pid'] and len(slots)==1 and slots[0]['memoryMb']>=2*e['memory_mb'] and slots[0]['plannedGrowthBytes']>=e['storage_mb']*1024**2,'original_broker_aggregate_lease_required'
    solver=json.loads(command(['inspect',cid],timeout=30))[0]
    assert solver['Id']==cid and not solver['State']['Running'] and solver['Image']==built['candidateImageId']
    assert solver['Config']['Labels']['objrun.skb.role']=='full-f-solver' and solver['Config']['Labels']['objrun.skb.nonce']==nonce
    assert not solver['Mounts'] and not solver['HostConfig'].get('Binds') and not solver['HostConfig']['Privileged']
    folder=Path(home)/('isolated-'+uuid.uuid4().hex);folder.mkdir();owned=[];image=None;baseline=None
    def remaining():
        value=budget-(time.monotonic()-began)
        if value<=0:raise TimeoutError('original_verifier_deadline')
        return value
    def create(args):
        actor=command(['create','--pull','never','--label','objrun.skb.role=group01-isolated-grade','--label','objrun.skb.owner='+folder.name,'--memory',str(e['memory_mb']*1024**2),'--memory-swap',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus']),'--cap-drop','ALL','--security-opt','no-new-privileges',*args],timeout=min(30,remaining())).decode().strip()
        assert len(actor)==64 and all(c in '0123456789abcdef' for c in actor);owned.append(actor);return actor
    def archive(actor,path,name):
        target=folder/(name+'.tar');outcome=bounded_run([DOCKER,'cp',actor+':'+path,'-'],ENV,target,folder/(name+'.stderr'),remaining(),stdout_limit=e['storage_mb']*1024**2,stderr_limit=65536)
        save(folder/(name+'.capture.json'),{**outcome,'path':path,'candidateContainerId':actor,'modelCalls':0})
        if outcome['faults'] or outcome['exitCode'] or not outcome['directChildClosed'] or not outcome['pipeReadersClosed']:raise RuntimeError('full_workspace_capture_fault')
        with tarfile.open(target,'r|*') as tar:
            for member in tar:
                parts=Path(member.name.replace('\\','/')).parts
                if not parts or parts[0] not in (Path(path).name,'.') or member.name.startswith('/') or '..' in parts or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):raise ValueError('unsafe_workspace_archive')
                if member.issym() or member.islnk():
                    link_target=posixpath.normpath(posixpath.join(posixpath.dirname(member.name),member.linkname)) if member.issym() else posixpath.normpath(member.linkname)
                    if member.linkname.startswith('/') or link_target.split('/')[0]!=parts[0] or '..' in link_target.split('/'):raise ValueError('escaping_workspace_link')
        return target
    def install_archive(target,actor,destination,name):
        # Stream opaque workspace data, never materialize candidate files on host.
        stdout=folder/(name+'.stdout');stderr=folder/(name+'.stderr')
        with target.open('rb') as data,stdout.open('wb') as out,stderr.open('wb') as err:
            process=subprocess.Popen([DOCKER,'cp','-',actor+':'+destination],env=ENV,stdin=data,stdout=out,stderr=err)
            try:code=process.wait(timeout=remaining())
            except BaseException:process.kill();process.wait();raise
        save(folder/(name+'.json'),{'exitCode':code,'stdoutPin':public.pin(stdout),'stderrPin':public.pin(stderr),'modelCalls':0})
        if code:raise RuntimeError('opaque_workspace_copy_fault')
    try:
        image=command(['commit','--pause=true','--change','LABEL objrun.skb.snapshot-owner='+folder.name,cid],timeout=min(60,remaining())).decode().strip();assert image.startswith('sha256:') and image not in (built['candidateImageId'],built['privateImageId'])
        execution=create(['--network',{'public':'bridge','no-network':'none'}[e['network_mode']],'--entrypoint','/bin/bash',image,'-c','exec sleep infinity'])
        command(['start',execution],timeout=min(30,remaining()))
        gid=create(['--read-only','--network','container:'+execution if task=='react-performance-debugging' else 'none','--tmpfs','/run:rw,nosuid,nodev,size=64m','--tmpfs','/tmp:rw,nosuid,nodev,size='+str(e['memory_mb'])+'m','--tmpfs','/logs/verifier:rw,nosuid,nodev,noexec,size=64m',*(['--tmpfs','/app/workspace:rw,nosuid,nodev,noexec,size='+str(e['storage_mb'])+'m'] if task=='lean4-proof' else []),'--entrypoint','/bin/bash',built['privateImageId'],'-c','exec sleep infinity'])
        private_inspect=json.loads(command(['inspect',gid],timeout=min(30,remaining())))[0]
        assert private_inspect['Image']==built['privateImageId'] and private_inspect['HostConfig']['ReadonlyRootfs'] and not private_inspect['HostConfig'].get('Binds') and not private_inspect['HostConfig']['Privileged']
        assert all(mount['Type']=='tmpfs' for mount in private_inspect['Mounts'])
        command(['start',gid],timeout=min(30,remaining()))
        if task=='react-performance-debugging':
            command(['cp',str(HERE/'react_service.sh'),execution+':/run/objrun-react.sh'],timeout=min(30,remaining()))
            command(['exec',execution,'bash','/run/objrun-react.sh'],timeout=remaining())
        else:
            full=archive(cid,'/app/workspace','candidate-workspace')
            install_archive(full,gid,'/app/','private-ordinary-workspace')
            # Restore pristine original baseline for clean compile in execution.
            baseline=create(['--network','none','--entrypoint','/bin/bash',built['candidateImageId'],'-c','exec sleep infinity'])
            original=archive(baseline,'/app/baseline','original-baseline')
            command(['exec',execution,'rm','-rf','/app/baseline'],timeout=min(30,remaining()))
            # The baseline is restored again immediately before the clean-tree call.
            install_archive(original,execution,'/app/','execution-baseline')
        # Start private pytest through framed stdout callbacks. Callback subprocess
        # runs in execution actor, never the private image or host interpreter.
        logs=folder/'private.stderr'
        with logs.open('wb') as error:
            child=subprocess.Popen([DOCKER,'exec','-i',gid,'/opt/objrun-verifier/bin/python','-I','-B','/opt/objrun/private_runner.py'],env=ENV,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=error)
            result=None;callbacks=0
            try:
                # A watchdog closes stalled pipes at the original verifier deadline.
                import threading
                timer=threading.Timer(remaining(),child.kill);timer.daemon=True;timer.start()
                while True:
                    line=child.stdout.readline(12*1024**2)
                    if not line:break
                    if not line.endswith(b'\n'):raise ValueError('private_frame_bound')
                    frame=json.loads(line)
                    if set(frame)=={'result'}:result=frame['result'];break
                    if set(frame)!={'callback'} or task!='lean4-proof':raise ValueError('private_frame_type')
                    request=frame['callback'];expected={'protocol':'lean-original-call-v1','epoch':built['epoch'],'index':callbacks,'mode':'workspace' if callbacks==0 else 'clean-baseline'}
                    if request!=expected or callbacks>=2:raise ValueError('private_original_call_join')
                    if callbacks==1:
                        command(['exec',execution,'rm','-rf','/app/baseline'],timeout=min(30,remaining()))
                        install_archive(original,execution,'/app/','execution-baseline-clean')
                    command_text='cd /app/workspace && lake env lean -DwarningAsError=true solution.lean' if callbacks==0 else 'tmp=$(mktemp -d); cp -a /app/baseline/. "$tmp/"; cp /app/workspace/solution.lean "$tmp/solution.lean"; cd "$tmp"; lake env lean -DwarningAsError=true solution.lean; code=$?; rm -rf "$tmp"; exit "$code"'
                    prefix=folder/('lean-call-'+str(callbacks))
                    outcome=bounded_run([DOCKER,'exec',execution,'bash','-lc',command_text],ENV,prefix.with_suffix('.stdout'),prefix.with_suffix('.stderr'),remaining(),stdout_limit=4*1024**2,stderr_limit=4*1024**2)
                    save(prefix.with_suffix('.json'),{**outcome,'request':request,'modelCalls':0})
                    if outcome['faults'] or not outcome['directChildClosed'] or not outcome['pipeReadersClosed']:raise RuntimeError('isolated_lean_execution_fault')
                    def blob(path):
                        body=path.read_bytes();return {'base64':base64.b64encode(body).decode(),'sha256':hashlib.sha256(body).hexdigest()}
                    child.stdin.write((json.dumps({'request':request,'status':'completed','returncode':outcome['exitCode'],'stdout':blob(prefix.with_suffix('.stdout')),'stderr':blob(prefix.with_suffix('.stderr'))})+'\n').encode());child.stdin.flush();callbacks+=1
                child.stdin.close();code=child.wait(timeout=remaining())
                if code or result is None or not result['complete']:raise RuntimeError('original_private_pytest_incomplete')
            finally:
                timer.cancel()
                if child.poll() is None:child.kill();child.wait()
        return {'result':result,'candidateExecutionImageId':image,'privateImageId':built['privateImageId'],'candidateSnapshotUsedForTrustedGrader':False,'privateNamespaces':{'privateGrader':gid,'candidateExecution':execution},'ownedContainersRemaining':0,'modelCalls':0,'evidenceDirectory':str(folder)}
    finally:
        cleanup_errors=[]
        for actor in reversed(owned):
            try:command(['rm','-f',actor],timeout=30)
            except BaseException as error:cleanup_errors.append({'actor':actor,'error':repr(error)})
        if image:
            try:
                image_inspect=json.loads(command(['image','inspect',image],timeout=30))[0]
                assert image_inspect['Id']==image and image_inspect['Config']['Labels']['objrun.skb.snapshot-owner']==folder.name
                command(['image','rm',image],timeout=30)
            except BaseException as error:cleanup_errors.append({'image':image,'error':repr(error)})
        save(folder/'cleanup.json',{'errors':cleanup_errors,'ownedContainersRemaining':len([x for x in cleanup_errors if 'actor' in x]),'modelCalls':0})
        if cleanup_errors:raise RuntimeError('isolated_owned_cleanup_incomplete:'+str(folder/'cleanup.json'))
