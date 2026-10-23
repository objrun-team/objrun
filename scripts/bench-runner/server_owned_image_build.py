"""Guarded fixed-context server-local build, without qualification or grading."""
import base64,json,pathlib,re,os,time
from native_process import pin,capture
from remote_native_capture import REMOTE_CAPTURE
import _bench_original_owned_guard as guard

SERVER=r'''
import pathlib,json,base64,os,time,hashlib
def build(r):
 os.environ['DOCKER_BUILDKIT']='0'
 root=pathlib.Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/owned-build-contexts')/r['nonce'];root.mkdir(parents=True,exist_ok=False)
 docker=['/usr/bin/docker','-H','unix:///data/wpx/tgengin/run/docker.sock']
 def run(argv):return captured_remote(docker+argv,max(1,min(600,r['deadline']-time.time())))
 for f in r['files']:
  dest=root/f['relative'];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(base64.b64decode(f['base64']));assert dest.stat().st_size==f['bytes'] and hashlib.sha256(dest.read_bytes()).hexdigest()==f['sha256']
 base=json.loads(run(['image','inspect',r['baseImage']]))[0];assert base['Id']==r['baseImage']
 iid=root/'owned-image-id';run(['build','--network',r['network'],'--memory','2147483648','--cpu-period','100000','--cpu-quota','100000','--iidfile',str(iid),str(root)])
 image=iid.read_text().strip();assert image.startswith('sha256:') and image!=r['baseImage']
 proof=json.loads(run(['image','inspect',image]))[0];assert proof['Id']==image
 removed=False
 if r['neutralCleanup']:
  run(['image','rm','--no-prune',image]);removed=True
 print(json.dumps({'protocol':'bench-owned-server-image-build-result-v1','complete':True,'image':image,'identity':{k:proof[k] for k in ['Id','Config','RootFS','Os','Architecture']},'neutralImageRemoved':removed,'context':str(root),'modelCalls':0}),flush=True)
'''

def build_owned(request,prefix):
 guard.guard();guard.require_lease(2048,10737418240,'terminal-bench',1)
 assert re.fullmatch('[a-f0-9]{32}',request['nonce']) and re.fullmatch('sha256:[a-f0-9]{64}',request['baseImage'])
 assert request['network'] in ('none','default') and 0<request['deadline']-time.time()<=600
 files=[]
 for f in request['files']:
  relative=pathlib.PurePosixPath(f['relative']);assert not relative.is_absolute() and '..' not in relative.parts
  assert pin(f['pin']['path'])==f['pin'];files.append({'relative':str(relative),'bytes':f['pin']['bytes'],'sha256':f['pin']['sha256'],'base64':base64.b64encode(pathlib.Path(f['pin']['path']).read_bytes()).decode()})
 assert any(f['relative']=='Dockerfile' for f in files)
 ssh=request['sshPin'];assert pin(ssh['path'])==ssh
 r={**request,'files':files};program=REMOTE_CAPTURE+'\n'+SERVER+'\nbuild(json.loads('+repr(json.dumps(r))+'))\n'
 process=capture([ssh['path'],'-T','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ClearAllForwardings=yes','novaeve','python3','-'],prefix,max(1,request['deadline']-time.time()),input_bytes=program.encode())
 assert process['closeObserved'] and process['exitCode']==0 and not process['timedOut'] and not process['error'],process
 result=json.loads(pathlib.Path(process['stdoutPin']['path']).read_text().splitlines()[-1]);assert result['complete'] and result['protocol']=='bench-owned-server-image-build-result-v1'
 guard.guard();return {'process':process,'result':result}
