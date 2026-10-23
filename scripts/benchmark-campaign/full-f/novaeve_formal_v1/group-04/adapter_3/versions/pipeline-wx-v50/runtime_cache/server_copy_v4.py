"""Python 3.6-compatible server-local, hash-verified copy to exact owned CID."""
import base64,hashlib,json,os,pathlib,re,subprocess,time,uuid
BASE=pathlib.Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/runtime/immutable-files')
DOCKER=['/usr/bin/docker','-H','unix:///data/wpx/tgengin/run/docker.sock']
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for b in iter(lambda:stream.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def run(args,timeout=180):
 p=subprocess.run(DOCKER+args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=timeout)
 assert p.returncode==0,{'args':args,'exit':p.returncode,'stderr':p.stderr[-4096:]}
 return p.stdout.strip()
def actor(cid,labels):
 v=json.loads(run(['inspect',cid]))[0]
 assert v['Id']==cid and all(v['Config']['Labels'].get(k)==value for k,value in labels.items()),'exact_actor_labels_mismatch'
 assert not v['HostConfig'].get('Binds') and all(m['Type']=='tmpfs' for m in v['Mounts']),'host_mount_forbidden'
 return {'Id':v['Id'],'Image':v['Image'],'Labels':v['Config']['Labels'],'HostConfig':{k:v['HostConfig'][k] for k in ('Memory','MemorySwap','NanoCpus','NetworkMode')},'Mounts':v['Mounts']}
def main(request):
 start=time.monotonic();sha=request['sha256'];name=request['name'];cid=request['cid'];destination=request['destination'];labels=request['expectedLabels']
 assert re.match(r'^[a-f0-9]{64}$',sha) and re.match(r'^[a-f0-9]{64}$',cid)
 assert re.match(r'^[A-Za-z0-9_.+-]+$',name) and name not in ('.','..')
 assert destination.startswith('/') and '..' not in pathlib.PurePosixPath(destination).parts and ':' not in destination
 assert labels and len(labels)<=8 and all(isinstance(k,str) and isinstance(v,str) and v for k,v in labels.items())
 assert request['leasePid']>0 and request['leaseVerifiedWindows'] is True
 directory=BASE/sha;directory.mkdir(parents=True,exist_ok=True)
 assert directory.resolve()==directory and BASE.resolve()==BASE,'cache_symlink_forbidden'
 target=directory/name;cache_hit=target.exists()
 if not cache_hit:
  payload=request.get('smallFileBase64');assert payload is not None,'large_runtime_cache_missing_no_network_upload_fallback'
  data=base64.b64decode(payload);assert len(data)<=10*1024*1024 and len(data)==request['bytes'] and hashlib.sha256(data).hexdigest()==sha
  temp=directory/(name+'.partial-'+uuid.uuid4().hex)
  with temp.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.chmod(str(temp),0o444);temp.rename(target)
 assert target.is_file() and not target.is_symlink() and target.stat().st_size==request['bytes'] and digest(target)==sha,'nas_cache_content_mismatch'
 before=actor(cid,labels)
 run(['cp',str(target),cid+':'+destination])
 guest_hash=run(['exec',cid,'/usr/bin/sha256sum',destination]).split()[0]
 guest_bytes=int(run(['exec',cid,'/usr/bin/stat','-c','%s',destination]))
 assert guest_hash==sha and guest_bytes==request['bytes'],'guest_content_mismatch'
 after=actor(cid,labels)
 assert before==after,'actor_identity_changed'
 result={'protocol':'novaeve-server-local-runtime-copy-v4','complete':True,'modelCalls':0,'cacheHit':cache_hit,
  'sourcePath':str(target),'sha256':sha,'bytes':guest_bytes,'destination':destination,'cid':cid,
  'expectedLabels':labels,'before':before,'after':after,'guestSha256':guest_hash,'hostBindAdded':False,
  'serverLocalDockerCp':True,'remoteDockerUploadBytes':0,'smallCacheFillBytes':0 if cache_hit else guest_bytes,
  'elapsedSeconds':time.monotonic()-start,'originalTaskToolBudgetsChanged':False}
 print(json.dumps(result))
