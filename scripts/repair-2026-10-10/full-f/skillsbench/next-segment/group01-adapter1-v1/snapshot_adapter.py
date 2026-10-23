"""Stopped complete candidate snapshot is used only for untrusted execution."""
import base64
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid
import tempfile
from bridge import LIMIT, pack, unpack
from build_environment import DOCKER, ENV
from prepare import HOME

TASKS={'data-to-d3','latex-formula-extraction','python-scala-translation','gravitational-wave-detection'}
def require_lease(owner, memory):
    control=json.loads((HOME.parent/'control.json').read_bytes())
    health=json.loads(Path(control['broker']['healthPath']).read_bytes())
    assert health['pid']==control['broker']['pid']
    assert any(r['slug']=='skillsbench' and r['pid']==owner and r['memoryMb']>=memory for r in health['resourceSlots']), 'original_shared_broker_lease_required'

def evaluate_snapshot(command,cid,nonce,built,owner,collect=False):
    task=built['taskId']; assert task in TASKS
    require_lease(owner,built['aggregateMemoryMb'])
    began=time.monotonic(); deadline=began+built['originalResources']['verifier']['timeout_sec']
    def remaining():
        value=deadline-time.monotonic()
        if value<=0: raise TimeoutError('original_combined_verifier_budget')
        return value
    observed=json.loads(command(['inspect',cid],timeout=remaining()))[0]
    assert not observed['State']['Running'] and observed['Image']==built['candidateImageId']
    assert observed['Config']['Labels']['objrun.skb.nonce']==nonce
    assert not observed['HostConfig'].get('Binds') and not observed['HostConfig'].get('Mounts') and not observed['HostConfig'].get('Privileged')
    # Full commit retains candidate-installed dependencies; it NEVER becomes the grader image.
    owned=[]; snapshot=None; network=None; proc=None; session=uuid.uuid4().hex
    e=built['originalResources']['environment']
    common=['--pull','never','--cap-drop','ALL','--security-opt','no-new-privileges','--memory',str(e['memory_mb']*1024**2),'--memory-swap',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus'])]
    def create(args):
        identity=command(['create',*common,*args],timeout=remaining()).decode().strip()
        assert len(identity)==64 and all(x in '0123456789abcdef' for x in identity)
        owned.append(identity); return identity
    try:
        # Candidate artifacts are captured as ordinary bytes without following symlinks.
        artifacts=[]
        from opaque_artifacts import parse_daemon_tar
        for output in built['outputPolicies']:
            try: raw=command(['cp',cid+':'+output['path'],'-'],timeout=remaining(),stdout_limit=output['maximumBytes']+(output['maximumFiles']+8)*2048)
            except RuntimeError as error:
                # Stand.command's recorded exact daemon diagnostic must certify absence.
                record_path=str(error).removeprefix('Owned Docker operation failed: ')
                if record_path==str(error): raise
                record=json.loads(Path(record_path).read_bytes()); diagnostic=Path(record['stderrPin']['path']).read_text().strip()
                if record['faults'] or diagnostic!='Error response from daemon: Could not find the file '+output['path']+' in container '+cid: raise
                continue
            # executable suffixes are admitted only to opaque parsing; browser/Scala run elsewhere.
            envelope=parse_daemon_tar(raw,output)
            artifacts += [{'path':f['destination'],**pack(f['body'])} for f in envelope['files']]
        if task in ('python-scala-translation','data-to-d3') and not collect:
            snapshot=command(['commit','--change','LABEL objrun.group01.owner='+session,cid],timeout=remaining()).decode().strip()
            assert snapshot.startswith('sha256:') and len(snapshot)==71 and snapshot!=built['privateImageId']
        endpoint=None
        if task=='data-to-d3' and not collect:
            network='objrun-g01-'+session
            command(['network','create',*(['--internal'] if e['network_mode']=='no-network' else []),network],timeout=remaining())
            browser=create(['--network',network,'--network-alias','browser','--workdir','/root','--entrypoint','/bin/bash',snapshot,'-c',
                'python3 -m http.server 8765 --directory /root/output & exec python3 -m playwright run-server --host 0.0.0.0 --port 9222'])
            # Only approved browser artifacts reach a pristine browser, never the private tests.
            import io,tarfile
            archive=io.BytesIO()
            with tarfile.open(fileobj=archive,mode='w') as tar:
                for artifact in artifacts:
                    body=unpack({k:artifact[k] for k in ('base64','sha256')}); entry=tarfile.TarInfo(artifact['path'].lstrip('/'));entry.size=len(body);entry.mode=0o644;tar.addfile(entry,io.BytesIO(body))
            command(['cp','-',browser+':/'],timeout=remaining(),stdin=archive.getvalue())
            command(['start',browser],timeout=remaining())
            # Host attests readiness by inspecting the daemon's actual listen log;
            # all waits consume the same original verifier deadline.
            while True:
                logs=command(['logs',browser],timeout=remaining()).decode(errors='replace')
                if 'Listening on ws://' in logs: break
                inspection=json.loads(command(['inspect',browser],timeout=remaining()))[0]
                if not inspection['State']['Running']: raise RuntimeError('browser_server_exit')
                time.sleep(min(.1,remaining()))
            endpoint='ws://browser:9222/'
        private_network=network or ('bridge' if task=='latex-formula-extraction' and e['network_mode']=='public' else 'none')
        # Latex's ORIGINAL renderer loads MathJax from its CDN. Its original
        # browser/model caches live at executable /opt/ms-playwright and
        # /opt/huggingface, outside the noexec artifact replay tmpfs.
        private=create(['-i','--read-only','--network',private_network,'--workdir',built['workingDirectory'],
            '--tmpfs','/root:rw,nosuid,nodev,noexec,size='+str(built['artifactTmpfsBytes']),
            '--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=256m','--tmpfs','/logs/verifier:rw,nosuid,nodev,noexec,size=64m',
            built['privateImageId'],*(['--collect'] if collect else [])])
        inspection=json.loads(command(['inspect',private],timeout=remaining()))[0]
        assert inspection['Image']==built['privateImageId'] and inspection['HostConfig']['ReadonlyRootfs'] and not inspection['HostConfig'].get('Binds')
        proc=subprocess.Popen([DOCKER,'start','-a','-i',private],env=ENV,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        messages=queue.Queue(); stderr=bytearray()
        def reader():
            try:
                while True:
                    line=proc.stdout.readline(256*1024**2+1)
                    if not line: break
                    if len(line)>256*1024**2 or not line.endswith(b'\n'): raise ValueError('bounded_callback_frame')
                    messages.put(json.loads(line))
            except Exception as error: messages.put(error)
            finally: messages.put(None)
        def error_reader():
            while True:
                part=proc.stderr.read(65536)
                if not part: return
                if len(stderr)<1024**2: stderr.extend(part[:1024**2-len(stderr)])
        out_thread=threading.Thread(target=reader,daemon=True);err_thread=threading.Thread(target=error_reader,daemon=True);out_thread.start();err_thread.start()
        proc.stdin.write((json.dumps({'session':session,'artifacts':artifacts,'browserEndpoint':endpoint})+'\n').encode());proc.stdin.flush()
        result=None; sequence=0
        while True:
            try: message=messages.get(timeout=remaining())
            except queue.Empty: raise TimeoutError('original_combined_verifier_budget')
            if message is None: break
            if isinstance(message,Exception): raise message
            if message.get('kind')=='result':
                if result is not None: raise ValueError('duplicate_result')
                result=message['result']; continue
            request=message['request']
            assert task=='python-scala-translation' and message['kind']=='callback' and result is None
            assert set(request)=={'session','sequence','kind','argv','timeout','project'} and request['session']==session and request['sequence']==sequence and request['kind']=='scala'
            assert request['argv'] in (['/usr/local/bin/sbt','compile'],['/usr/local/bin/sbt','test'])
            assert request['timeout']==(300 if request['argv'][-1]=='compile' else 600)
            sequence+=1
            execution=create(['--network','bridge' if e['network_mode']=='public' else 'none','--workdir','/root/localtest','--entrypoint','/bin/sleep',snapshot,'infinity'])
            command(['cp','-',execution+':/root/localtest'],timeout=remaining(),stdin=unpack(request['project']))
            command(['start',execution],timeout=remaining())
            from bounded_child import run
            from prepare import public,save
            with tempfile.TemporaryDirectory(prefix='g01-scala-capture-') as folder:
                capture=Path(folder)
                outcome=run([DOCKER,'exec',execution,'/root/.local/share/coursier/bin/sbt',request['argv'][-1]],ENV,capture/'stdout',capture/'stderr',min(remaining(),request['timeout']),stdout_limit=LIMIT,stderr_limit=LIMIT)
                if outcome['faults']==['timeout']:
                    response={'status':'timeout','returncode':None}
                elif outcome['faults'] or not outcome['directChildClosed'] or not outcome['pipeReadersClosed']:
                    raise RuntimeError('scala_capture_fault')
                else:
                    response={'status':'completed','returncode':outcome['exitCode'],'stdout':pack((capture/'stdout').read_bytes()),'stderr':pack((capture/'stderr').read_bytes())}
                response.update(session=session,sequence=request['sequence'])
            command(['rm','-f',execution],timeout=remaining());owned.remove(execution)
            proc.stdin.write((json.dumps(response)+'\n').encode());proc.stdin.flush()
        proc.stdin.close();exit_code=proc.wait(timeout=remaining());out_thread.join(timeout=2);err_thread.join(timeout=2)
        if exit_code or result is None or out_thread.is_alive() or err_thread.is_alive(): raise RuntimeError('private_process_fault:'+stderr.decode(errors='replace')[-1000:])
        assert result['taskId']==task and result['complete'] and result['candidateSnapshotUsed'] is False
        return {'result':result,'candidateSnapshotUsedForTrustedGrader':False,'candidateDependenciesRetained':snapshot is not None,
                'separateExecutionNamespace':task in ('data-to-d3','python-scala-translation'),'elapsedSeconds':time.monotonic()-began}
    finally:
        errors=[]
        if proc and proc.poll() is None:
            proc.kill();proc.wait(timeout=10)
        for identity in reversed(owned):
            try: command(['rm','-f',identity],timeout=30)
            except Exception as error: errors.append(str(error))
        if network:
            try: command(['network','rm',network],timeout=30)
            except Exception as error: errors.append(str(error))
        if snapshot:
            try:
                inspection=json.loads(command(['image','inspect',snapshot],timeout=30))[0]
                assert inspection['Config']['Labels']['objrun.group01.owner']==session
                command(['image','rm',snapshot],timeout=30)
            except Exception as error: errors.append(str(error))
        if errors: raise RuntimeError('owned_cleanup_failed:'+json.dumps(errors))
