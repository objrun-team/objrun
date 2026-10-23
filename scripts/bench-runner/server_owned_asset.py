"""One guarded server-local asset interface: fixed-context build or trusted archive restore."""
import base64,hashlib,json,os,pathlib,re,time,tarfile,shutil
from native_process import pin,capture
from remote_native_capture import REMOTE_CAPTURE
import _bench_original_owned_guard as guard
SERVER=r"""
import pathlib,shutil,json,hashlib,base64,time,tarfile,os
def asset(r):
 root=pathlib.Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/owned-assets')/r['nonce']
 docker=['/usr/bin/docker','-H','unix:///data/wpx/tgengin/run/docker.sock']
 def run(args):
  remaining=r['deadline']-time.time();assert remaining>0,'original_asset_deadline';return captured_remote(docker+args,min(600,remaining))
 def filepin(path):
  h=hashlib.sha256()
  with path.open('rb') as stream:
   for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
  return dict(path=str(path),bytes=path.stat().st_size,sha256=h.hexdigest())
 result={'protocol':'bench-owned-server-asset-result-v1','operation':r['operation'],'complete':False,'modelCalls':0,'gradeCalls':0}
 if r['operation']=='prepare-upload':
  root.mkdir(parents=True,exist_ok=False);print(json.dumps({**result,'complete':True,'destination':str(root/'archive.tar')}),flush=True);return
 if r['operation']=='verify-upload':
  assert root.is_dir() and root.resolve()==root
  actual=filepin(root/'archive.tar');assert actual['bytes']==r['archivePin']['bytes'] and actual['sha256']==r['archivePin']['sha256']
  print(json.dumps({**result,'complete':True,'serverArchivePin':actual,'transferWindowSeconds':3600}),flush=True);return
 if r['operation']=='cleanup-upload':
  assert root.parent==pathlib.Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/owned-assets') and root.name==r['nonce']
  matches=[]
  if root.exists():
   assert root.resolve()==root and not root.is_symlink()
   for proc in pathlib.Path('/proc').iterdir():
    if not proc.name.isdigit() or proc.name==str(os.getpid()):continue
    try:
     if proc.stat().st_uid!=os.getuid():continue
     cmd=(proc/'cmdline').read_bytes().replace(bytes([0]),b' ').decode(errors='replace')
     linked=[]
     for f in (proc/'fd').iterdir():
      try:linked.append(os.readlink(str(f)))
      except OSError:pass
     try:linked.append(os.readlink(str(proc/'cwd')))
     except OSError:pass
     if str(root) in cmd or any(x==str(root) or x.startswith(str(root)+'/') for x in linked):matches.append({'pid':int(proc.name),'cmdline':cmd})
    except OSError:pass
   assert not matches,{'owned_upload_processes_still_open':matches}
   shutil.rmtree(root)
  print(json.dumps({**result,'complete':True,'temporaryContextRemoved':not root.exists(),'exactNonce':r['nonce'],'matchingProcesses':matches}),flush=True);return

 try:
  if r['operation']=='build':
   os.environ['DOCKER_BUILDKIT']='0'
   if r.get('uploadedContext'):
    assert root.is_dir() and root.resolve()==root
    archive=root/'archive.tar';actual=filepin(archive);assert actual['bytes']==r['archivePin']['bytes'] and actual['sha256']==r['archivePin']['sha256']
    build_root=root/'context';build_root.mkdir(exist_ok=False)
    expected={x['relative']:x for x in r['files']};seen=set()
    with tarfile.open(str(archive),'r:') as bundle:
     for member in bundle:
      assert member.isfile() and member.name in expected and member.name not in seen
      relative=pathlib.PurePosixPath(member.name);assert not relative.is_absolute() and '..' not in relative.parts
      seen.add(member.name);row=expected[member.name];assert member.size==row['bytes']
      target=build_root/member.name;target.parent.mkdir(parents=True,exist_ok=True)
      assert target.resolve().is_relative_to(build_root.resolve()) if hasattr(target.resolve(),'is_relative_to') else str(target.resolve()).startswith(str(build_root.resolve())+'/')
      with bundle.extractfile(member) as source,target.open('xb') as output:shutil.copyfileobj(source,output)
      assert filepin(target)['sha256']==row['sha256']
    assert seen==set(expected);archive.unlink()
   else:
    root.mkdir(parents=True,exist_ok=False);build_root=root
    for row in r['files']:
     target=root/row['relative'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(base64.b64decode(row['base64']))
     assert target.stat().st_size==row['bytes'] and filepin(target)['sha256']==row['sha256']
   before=json.loads(run(['image','inspect',r['baseImage']]))[0];assert before['Id']==r['baseImage']
   iid=root/'owned-image-id';resource=r['resource']
   build_stdout=run(['build','--network',r['network'],'--memory',str(resource['memoryMb']*1024**2),'--cpu-period','100000','--cpu-quota',str(int(resource['cpu']*100000)),'--iidfile',str(iid),str(build_root)])
   intermediate_ids=re.findall(rb'Running in ([a-f0-9]{12,64})',build_stdout);removed_ids=re.findall(rb'(?:Removing|Removed) intermediate container ([a-f0-9]{12,64})',build_stdout)
   if r.get('requireIntermediateContainer'):assert intermediate_ids,'actual_run_intermediate_container_required'
   assert set(intermediate_ids)<=set(removed_ids),'actual_build_intermediate_removal_missing'
   for cid in intermediate_ids:assert not run(['container','ls','--all','--no-trunc','--filter','id='+cid.decode(),'--format','{{.ID}}']).strip(),'owned_build_intermediate_still_present'
   result['intermediateContainers']=[x.decode() for x in intermediate_ids];result['removedIntermediateContainers']=[x.decode() for x in removed_ids]
   image=iid.read_text().strip();assert re.fullmatch('sha256:[a-f0-9]{64}',image) and image!=r['baseImage']
  else:
   assert r['operation']=='load' and root.is_dir();archive=root/'archive.tar';actual=filepin(archive)
   assert actual['bytes']==r['archivePin']['bytes'] and actual['sha256']==r['archivePin']['sha256']
   expected=r['expectedIdentity'];image=expected['Id']
   with tarfile.open(archive,'r:*') as bundle:
    rows=json.load(bundle.extractfile('manifest.json'));matches=[]
    for row in rows:
     body=bundle.extractfile(row['Config']).read()
     if 'sha256:'+hashlib.sha256(body).hexdigest()==image:matches.append(json.loads(body))
    assert len(matches)==1 and matches[0]['rootfs']['diff_ids']==expected['RootFS']['Layers']
    assert matches[0]['os']==expected['Os'] and matches[0]['architecture']==expected['Architecture']
   run(['image','load','--input',str(archive)]);result['serverArchivePin']=actual
  observed=json.loads(run(['image','inspect',image]))[0];assert observed['Id']==image
  identity={k:observed[k] for k in ['Id','Config','RootFS','Os','Architecture']}
  if r['operation']=='load':
   expected=r['expectedIdentity']
   assert all(identity[k]==expected[k] for k in ['Id','RootFS','Os','Architecture'])
   assert all(identity['Config'].get(k)==v for k,v in expected['Config'].items())
  removed=False
  if r.get('neutralCleanup'):
   assert r['operation']=='build';run(['image','rm','--no-prune',image]);removed=True
  result.update(complete=True,image=image,identity=identity,neutralImageRemoved=removed)
 finally:
  if root.exists():
   assert root.parent==pathlib.Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/owned-assets') and root.name==r['nonce'];shutil.rmtree(root)
  result['temporaryContextRemoved']=not root.exists()
 print(json.dumps(result),flush=True)
"""
def operate_owned_asset(request,prefix):
 resource=request['resource'];assert resource['bench'] in ('terminal-bench','skillsbench') and resource['slots']==1
 assert type(resource['memoryMb']) is int and resource['memoryMb']>0 and type(resource['growthBytes']) is int and resource['growthBytes']>0
 assert isinstance(resource['cpu'],(int,float)) and 0<resource['cpu']<=64
 guard.guard();guard.require_lease(resource['memoryMb'],resource['growthBytes'],resource['bench'],1)
 assert re.fullmatch('[a-f0-9]{32}',request['nonce']) and request['operation'] in ('build','load')
 if request.get('transferWindowSeconds') is not None:
  return _operate_transfer_asset(request,prefix)
 assert 0<request['deadline']-time.time()<=600 and type(request['neutralCleanup']) is bool
 ssh=request['sshPin'];assert pin(ssh['path'])==ssh;prefix=pathlib.Path(prefix);executions=[]
 def remote(r,label):
  guard.guard();guard.require_lease(resource['memoryMb'],resource['growthBytes'],resource['bench'],1)
  program=REMOTE_CAPTURE+'\nimport re\n'+SERVER+'\nasset(json.loads('+repr(json.dumps(r))+'))\n'
  remaining=request['deadline']-time.time();assert remaining>0,'original_asset_deadline'
  row=capture([ssh['path'],'-T','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ClearAllForwardings=yes','novaeve','python3','-'],str(prefix)+'-'+label,remaining,input_bytes=program.encode());executions.append(row)
  assert row['closeObserved'] and row['exitCode']==0 and not row['error'] and not row['timedOut'],row
  return json.loads(pathlib.Path(row['stdoutPin']['path']).read_text().splitlines()[-1])
 r={**request}
 if request['operation']=='build':
  assert request['network'] in ('none','default') and re.fullmatch('sha256:[a-f0-9]{64}',request['baseImage'])
  files=[];seen=set();dockerfile=None
  for f in request['files']:
   relative=pathlib.PurePosixPath(f['relative']);assert str(relative)==f['relative'] and not relative.is_absolute() and '..' not in relative.parts and str(relative) not in seen
   seen.add(str(relative));p=pathlib.Path(f['pin']['path']);assert p.is_file() and not p.is_symlink() and pin(p)==f['pin']
   raw=p.read_bytes();files.append({'relative':str(relative),'bytes':len(raw),'sha256':f['pin']['sha256'],'base64':base64.b64encode(raw).decode()})
   if str(relative)=='Dockerfile':dockerfile=raw.decode()
  assert dockerfile is not None
  froms=re.findall(r'(?im)^\s*FROM\s+(\S+)',dockerfile);assert froms==[request['baseImage']],'exact_single_original_base_binding'
  r['files']=files;result=remote(r,'build')
 else:
  assert request['neutralCleanup'] is False
  archive=pathlib.Path(request['archivePin']['path']);assert archive.is_file() and not archive.is_symlink() and pin(archive)==request['archivePin']
  assert request['archivePin']['bytes']<=resource['growthBytes'] and re.fullmatch('sha256:[a-f0-9]{64}',request['expectedIdentity']['Id'])
  scp=request['scpPin'];assert pin(scp['path'])==scp
  prepared=remote({**r,'operation':'prepare-upload'},'prepare')
  target=prepared['destination'];assert target=='/mnt/aliyunsb/pingxingwang/tgengin-bench/owned-assets/'+request['nonce']+'/archive.tar'
  remaining=request['deadline']-time.time();assert remaining>0,'original_asset_deadline'
  row=capture([scp['path'],'-q','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ClearAllForwardings=yes',str(archive),'novaeve:'+target],str(prefix)+'-scp',remaining);executions.append(row)
  assert row['closeObserved'] and row['exitCode']==0 and not row['error'] and not row['timedOut'],row
  assert pin(archive)==request['archivePin'];result=remote(r,'load')
 assert result['complete'] and result['temporaryContextRemoved'];guard.guard()
 return {'processes':executions,'result':result}


def _operate_transfer_asset(request,prefix):
 """Explicit 3600-second byte-transfer phase, then the unchanged 600-second Docker phase."""
 resource=request['resource'];prefix=pathlib.Path(prefix);prefix.parent.mkdir(parents=True,exist_ok=True)
 assert request['transferWindowSeconds']==3600 and request['originalOperationTimeoutSeconds']==600
 assert 0<request['absoluteDeadline']-time.time()<=4200 and 0<request['transferDeadline']-time.time()<=3600 and request['transferDeadline']<=request['absoluteDeadline']
 assert type(request['neutralCleanup']) is bool and (not request['neutralCleanup'] or request['operation']=='build')
 authority=request['transferAuthorityPin'];assert pin(authority['path'])==authority
 authorized=json.loads(pathlib.Path(authority['path']).read_bytes());assert authorized['maximumTransferSeconds']==3600 and authorized['scope']==['transfer','copy'] and authorized['originalOtherStageLimitsUnchanged'] is True
 ssh=request['sshPin'];scp=request['scpPin'];assert pin(ssh['path'])==ssh and pin(scp['path'])==scp
 executions=[];root='/mnt/aliyunsb/pingxingwang/tgengin-bench/owned-assets/'+request['nonce'];prepared=False;completed=False
 def remote(r,label,deadline):
  guard.guard();guard.require_lease(resource['memoryMb'],resource['growthBytes'],resource['bench'],1)
  remaining=deadline-time.time();assert remaining>0,'owned_transfer_phase_deadline'
  program=REMOTE_CAPTURE+'\nimport re\n'+SERVER+'\nasset(json.loads('+repr(json.dumps(r))+'))\n'
  row=capture([ssh['path'],'-T','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ClearAllForwardings=yes','novaeve','python3','-'],str(prefix)+'-'+label,remaining,input_bytes=program.encode());executions.append(row)
  assert row['closeObserved'] and row['exitCode']==0 and not row['error'] and not row['timedOut'],row
  return json.loads(pathlib.Path(row['stdoutPin']['path']).read_text().splitlines()[-1])
 r={**request};transfer_started=time.time();manifest=[]
 if request['operation']=='build':
  assert request['network'] in ('none','default') and re.fullmatch('sha256:[a-f0-9]{64}',request['baseImage'])
  archive=pathlib.Path(str(prefix)+'-context.tar');assert not archive.exists();seen=set();dockerfile=None
  with tarfile.open(archive,'w',format=tarfile.USTAR_FORMAT) as bundle:
   for f in request['files']:
    relative=pathlib.PurePosixPath(f['relative']);assert str(relative)==f['relative'] and relative.parts and not relative.is_absolute() and '..' not in relative.parts and str(relative) not in seen
    seen.add(str(relative));source=pathlib.Path(f['pin']['path']);assert source.is_file() and not source.is_symlink() and not source.is_junction() and pin(source)==f['pin']
    info=tarfile.TarInfo(str(relative));info.size=f['pin']['bytes'];info.mode=0o644;info.mtime=0
    with source.open('rb') as stream:bundle.addfile(info,stream)
    assert pin(source)==f['pin'];manifest.append(dict(relative=str(relative),bytes=f['pin']['bytes'],sha256=f['pin']['sha256']))
    if str(relative)=='Dockerfile':dockerfile=source.read_text()
  assert dockerfile is not None and re.findall(r'(?im)^\s*FROM\s+(\S+)',dockerfile)==[request['baseImage']],'exact_single_original_base_binding'
  archive_pin=pin(archive);r.update(files=manifest,uploadedContext=True,archivePin=archive_pin)
 else:
  assert request['operation']=='load' and request['neutralCleanup'] is False
  archive=pathlib.Path(request['archivePin']['path']);assert archive.is_file() and not archive.is_symlink() and pin(archive)==request['archivePin'];archive_pin=request['archivePin']
 assert archive_pin['bytes']<=resource['growthBytes']
 try:
  prep=remote({**r,'operation':'prepare-upload','deadline':request['transferDeadline']},'transfer-prepare',request['transferDeadline']);prepared=True
  assert prep['destination']==root+'/archive.tar'
  remaining=request['transferDeadline']-time.time();assert remaining>0
  row=capture([scp['path'],'-q','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ClearAllForwardings=yes',str(archive),'novaeve:'+prep['destination']],str(prefix)+'-scp',remaining);executions.append(row)
  assert row['closeObserved'] and row['exitCode']==0 and not row['error'] and not row['timedOut'],row
  assert pin(archive)==archive_pin
  verified=remote({**r,'operation':'verify-upload','deadline':request['transferDeadline']},'transfer-verify',request['transferDeadline'])
  assert verified['serverArchivePin']['bytes']==archive_pin['bytes'] and verified['serverArchivePin']['sha256']==archive_pin['sha256']
  transfer_finished=time.time();operation_deadline=min(request['absoluteDeadline'],transfer_finished+600);assert operation_deadline>transfer_finished
  result=remote({**r,'deadline':operation_deadline},request['operation'],operation_deadline);completed=True
  assert result['complete'] and result['temporaryContextRemoved'];guard.guard()
  return dict(processes=executions,result=result,transfer=dict(windowSeconds=3600,startedEpoch=transfer_started,finishedEpoch=transfer_finished,elapsedSeconds=transfer_finished-transfer_started,localArchivePin=archive_pin,serverArchivePin=verified['serverArchivePin'],contextManifest=manifest),operation=dict(originalTimeoutSeconds=600,startedEpoch=transfer_finished,absoluteDeadline=operation_deadline,finishedEpoch=time.time()))
 finally:
  if prepared and not completed:
   # Cleanup proves no nonce process/open file remains. Failure leaves the lease held by the caller.
   cleanup_deadline=min(request['absoluteDeadline'],time.time()+30)
   if cleanup_deadline>time.time():remote({**r,'operation':'cleanup-upload','deadline':cleanup_deadline},'failed-transfer-cleanup',cleanup_deadline)
