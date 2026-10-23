"""Independent large-stream fixture through unchanged production SSH and remote/native capture."""
import argparse,pathlib,json,hashlib,base64,urllib.request,urllib.error,sys
from native_process import capture,pin
from remote_native_capture import REMOTE_CAPTURE
from docker_owned import OwnedDocker
import _bench_original_owned_guard as guard
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False)
assert _bench_authorized_history('zero-model-owned-sb-asset') is True
guard.guard();guard.require_lease(2048,10737418240,'skillsbench',1)
n=OwnedDocker(out/'owned-native');cid=None
try:
 cid,create_receipt=n.create('neutral-large-streams','sha256:69f919497cada9a8611f3de61df902d9f94bf20f84552ef5bd93125c38608ef9','/bin/sh',['-c','sleep 300'],network='none',memory_mb=2048,cpus=1,readonly=True);n.start(cid);n.assert_actor(cid)
 shell="head -c 1048576 /dev/zero | tr '\\000' 'S'; head -c 1048576 /dev/zero | tr '\\000' 'E' >&2"
 argv=['/usr/bin/docker','-H','unix:///data/wpx/tgengin/run/docker.sock','exec',cid,'/bin/sh','-c',shell]
 program=REMOTE_CAPTURE+"\nimport sys,base64,json\n"+"raw=captured_remote("+repr(argv)+",120)\n"+"assert len(raw)==1048576 and raw==b'S'*1048576\n"+"sys.stderr.buffer.write(b'E'*1048576);sys.stderr.buffer.flush()\n"
 guard.guard();guard.require_lease(2048,10737418240,'skillsbench',1)
 r=capture(['C:/Windows/System32/OpenSSH/ssh.exe','-T','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ClearAllForwardings=yes','novaeve','python3','-'],out/'ssh-large-streams',150,input_bytes=program.encode())
 assert r['closeObserved'] and r['exitCode']==0 and not r['timedOut'] and r['error'] is None,r
 records=[json.loads(line)['remoteCommand'] for line in pathlib.Path(r['stdoutPin']['path']).read_text().splitlines() if 'remoteCommand' in json.loads(line)];assert len(records)==1
 remote=records[0];assert remote['closeObserved'] and remote['exitCode']==0 and not remote['timedOut'] and remote['error'] is None
 for stream,byte in [('stdout',b'S'),('stderr',b'E')]:
  actual=base64.b64decode(remote[stream]['rawBase64']);assert len(actual)==1048576 and actual==byte*1048576 and hashlib.sha256(actual).hexdigest()==remote[stream]['sha256'];(out/('remote-'+stream+'.raw')).write_bytes(actual)
 assert pathlib.Path(r['stderrPin']['path']).read_bytes()==b'E'*1048576
 result=dict(complete=True,largeStreamsPassed=True,remoteProcessNaturalExit=True,sshNaturalExit=True,remoteStdoutBytes=1048576,remoteStderrBytes=1048576,sshStdoutBytes=r['stdoutPin']['bytes'],sshStderrBytes=r['stderrPin']['bytes'],remoteReceipt=remote,sshReceipt=r,actualContainer=cid,originalRemoteCaptureUnchanged=True,modelCalls=0,gradeCalls=0,referenceCalls=0)
finally:
 if cid:n.remove(cid)
 n.close()
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
