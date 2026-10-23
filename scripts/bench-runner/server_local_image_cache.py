"""Hash all bytes of a server-local docker-save archive before actual image load."""
import base64,json,pathlib,re
from native_process import capture,pin
from remote_native_capture import REMOTE_CAPTURE

SERVER = r'''
import hashlib,json,pathlib,subprocess,time
def main(r):
 root=pathlib.Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/image-cache')
 root.mkdir(parents=True,exist_ok=True)
 assert root.resolve()==root
 image=r['image'];assert len(image)==71 and image.startswith('sha256:') and all(c in '0123456789abcdef' for c in image[7:])
 archive=root/(image[7:]+'.docker-save.tar');assert not archive.is_symlink()
 docker=['/usr/bin/docker','-H','unix:///data/wpx/tgengin/run/docker.sock']
 def run(a):
  return captured_remote(docker+a,600)
 before=json.loads(run(['image','inspect',image]))[0]
 if not archive.exists():
  partial=archive.with_suffix('.partial-'+str(r['leasePid']))
  assert not partial.exists();run(['image','save','--output',str(partial),image]);partial.rename(archive)
 h=hashlib.sha256()
 with archive.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 archivePin={'path':str(archive),'bytes':archive.stat().st_size,'sha256':h.hexdigest()}
 if r.get('serverArchivePin'):assert archivePin==r['serverArchivePin']
 run(['image','load','--input',str(archive)])
 after=json.loads(run(['image','inspect',image]))[0]
 assert all(before[k]==after[k] for k in ('Id','Config','RootFS','Os','Architecture'))
 print(json.dumps({'protocol':'bench-server-local-image-cache-result-v1','archivePin':archivePin,'image':image,'before':before,'after':after,'complete':True,'modelCalls':0}),flush=True)
'''

def prepare_and_load(ssh_pin,image,lease_pid,prefix,server_archive_pin=None):
 assert pin(ssh_pin['path'])==ssh_pin and re.fullmatch('sha256:[a-f0-9]{64}',image)
 request=dict(image=image,leasePid=lease_pid,serverArchivePin=server_archive_pin)
 program=REMOTE_CAPTURE+'\n'+SERVER+'\nmain(json.loads('+repr(json.dumps(request))+'))\n'
 execution=capture([ssh_pin['path'],'-T','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ClearAllForwardings=yes','novaeve','python3','-'],prefix,600,input_bytes=program.encode())
 assert execution['closeObserved'] and execution['exitCode']==0 and not execution['error'] and not execution['timedOut'],execution
 frames=[json.loads(x) for x in pathlib.Path(execution['stdoutPin']['path']).read_text().splitlines()]
 result=frames[-1];assert result['protocol']=='bench-server-local-image-cache-result-v1' and result['complete'] and result['image']==image
 return dict(process=execution,result=result)
