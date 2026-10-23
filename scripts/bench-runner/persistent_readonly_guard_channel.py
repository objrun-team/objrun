"""Drop-in read-only guard capture successor; one owned stdio Bun child per Python PID."""
import atexit,datetime,hashlib,hmac,json,os,pathlib,queue,secrets,subprocess,threading,time,uuid
from native_process import pin
from observed_owned_spawn import spawn_owned
_CHANNEL=None
_OWNER=os.getpid()
_LOCK=threading.Lock()
def _now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def _save(path,value):
 with pathlib.Path(path).open('x',encoding='utf8') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def _samepin(p):
 a=pin(p['path']);assert pathlib.Path(a['path']).resolve()==pathlib.Path(p['path']).resolve() and a['bytes']==p['bytes'] and a['sha256']==p['sha256'],'persistent_guard_pin_changed'
def _contract():
 assert os.getpid()==_OWNER,'persistent_guard_fork_not_allowed'
 path=pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']).resolve();raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest();assert digest==os.environ['NOVAEVE_PYTHON_MAPPING_SHA256']
 config=json.loads(raw);c=config['adoptedGuardCapture'];p=c['persistentReadonlyChannel']
 assert c['protocol']=='bench-adopted-guard-process-capture-v1' and p['protocol']=='bench-persistent-readonly-guard-channel-v1'
 assert c['bridgePin']['sha256']==p['originalBridgePin']['sha256']=='86420ff8d6058ada967a50c07587f825fe720795615c67f806d4addd269e7bb8'
 assert pathlib.Path(p['clientPin']['path']).resolve()==pathlib.Path(__file__).resolve()
 for x in [p['clientPin'],p['serverPin'],p['originalBridgePin']]:_samepin(x)
 root=pathlib.Path(c['root']).resolve();directory=pathlib.Path(config['childEvidenceRoot']).resolve()/'persistent-readonly-guard'
 assert (root/'docs/repair-2026-10-10/full-f-rerun').resolve() in directory.parents;directory.mkdir(parents=True,exist_ok=True)
 return c,p,path,digest,directory
class _Channel:
 def __init__(self,c,p,mapping,sha,directory,activation):
  self.owner=os.getpid();self.mapping=str(mapping);self.mappingSha=sha;self.activation=str(pathlib.Path(activation).resolve());self.secret=secrets.token_hex(32);self.seq=0;self.closed=False;self.failed=False
  self.prefix=directory/(str(self.owner)+'-'+uuid.uuid4().hex);self.row={};self.started=time.monotonic();self.queue=queue.Queue(maxsize=2);self.readerError=None
  _samepin(c['bunPin']);_samepin(p['loaderPin']);_samepin(p['sourceConfigPin']);_samepin(p['activationPin'])
  self.stderrPath=pathlib.Path(str(self.prefix)+'.stderr');self.stderrFile=self.stderrPath.open('xb')
  argv=[str(c['bunPin']['path']),'--smol',str(p['serverPin']['path']),self.activation];env=dict(os.environ,NOVAEVE_GUARD_CHANNEL_SECRET=self.secret)
  self.process=spawn_owned(self.row,self.prefix,argv,cwd=c['root'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
  if not self.row.get('incarnation') or self.row.get('observationErrors'):
   self.process.stdin.close()
   try:self.process.wait(timeout=3)
   except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=15)
   self.stderrFile.close();self.row.update(closeObserved=self.process.poll() is not None,exitCode=self.process.returncode,identityRejected=True)
   _save(str(self.prefix)+'.identity-rejected-close.json',self.row)
   raise AssertionError('persistent_guard_child_identity_unproven')
  self.stdoutThread=threading.Thread(target=self._stdout,name='guard-readonly-stdout',daemon=True);self.stderrThread=threading.Thread(target=self._stderr,name='guard-readonly-stderr',daemon=True);self.stdoutThread.start();self.stderrThread.start()
 def _stdout(self):
  try:
   while True:
    b=self.process.stdout.readline(8*1024*1024+1)
    if not b:break
    assert len(b)<=8*1024*1024 and b.endswith(b'\n'),'persistent_guard_response_overflow'
    self.queue.put(b,timeout=15)
  except BaseException as e:self.readerError=repr(e)
  finally:
   try:self.queue.put(None,timeout=15)
   except queue.Full:self.readerError='persistent_guard_unconsumed_responses'
 def _stderr(self):
  try:
   while True:
    b=self.process.stderr.read1(65536)
    if not b:break
    self.stderrFile.write(b);self.stderrFile.flush();os.fsync(self.stderrFile.fileno())
  except BaseException as e:self.readerError=repr(e)
 def get(self,deadline):
  assert not self.readerError,self.readerError
  b=self.queue.get(timeout=max(.001,deadline-time.monotonic()));assert b is not None,'persistent_guard_child_exited'
  return b
 def ready(self,deadline):
  raw=self.get(deadline);v=json.loads(raw);assert v['protocol']=='bench-persistent-readonly-guard-ready-v1' and v['pid']==self.process.pid and v['incarnation']==self.row['incarnation'] and v['parentPid']==self.owner and v['mappingSha256']==self.mappingSha
  self.ownerIncarnation=v['parentIncarnation'];pathlib.Path(str(self.prefix)+'.ready.stdout').write_bytes(raw)
 def request(self,deadline):
  assert not self.closed and not self.failed and self.process.poll() is None and os.getpid()==self.owner
  self.seq+=1;nonce=uuid.uuid4().hex
  body=dict(protocol='bench-persistent-readonly-guard-request-v1',op='verify',sequence=self.seq,nonce=nonce,callerPid=self.owner,callerIncarnation=self.ownerIncarnation,mappingSha256=self.mappingSha,activationPath=self.activation,deadlineUnixMs=int(time.time()*1000+max(0,deadline-time.monotonic())*1000))
  auth=hmac.new(self.secret.encode(),json.dumps(body,separators=(',',':'),ensure_ascii=False).encode(),hashlib.sha256).hexdigest();request={**body,'auth':auth};raw=(json.dumps(request,separators=(',',':'),ensure_ascii=False)+'\n').encode()
  prefix=pathlib.Path(str(self.prefix)+'.request-'+str(self.seq));pathlib.Path(str(prefix)+'.stdin').write_bytes(raw)
  started=time.monotonic();self.process.stdin.write(raw);self.process.stdin.flush();out=self.get(deadline);pathlib.Path(str(prefix)+'.stdout').write_bytes(out)
  response=json.loads(out);assert response['protocol']=='bench-persistent-readonly-guard-response-v1' and response['sequence']==self.seq and response['nonce']==nonce
  receipt=dict(protocol='bench-persistent-readonly-guard-request-receipt-v1',pid=self.process.pid,incarnation=self.row['incarnation'],requestOwnerPid=self.owner,sequence=self.seq,nonce=nonce,atUtc=_now(),elapsedSeconds=time.monotonic()-started,requestPin=pin(str(prefix)+'.stdin'),responsePin=pin(str(prefix)+'.stdout'),ok=response['ok'],processClosed=False,eachRequestFreshOriginalVerification=response.get('freshOriginalVerification',False),noCachedLeaseOrHealth=True)
  _save(str(prefix)+'.json',receipt)
  if not response['ok']:return subprocess.CompletedProcess([],1,b'',(json.dumps(response['error'])+'\n').encode())
  assert response['freshOriginalVerification'] is True
  return subprocess.CompletedProcess([],0,(json.dumps(response['value'])+'\n').encode(),b'')
 def close(self):
  if self.closed:return
  self.closed=True;intentional=False
  try:
   self.process.stdin.close()
   try:self.process.wait(timeout=3)
   except subprocess.TimeoutExpired:intentional=True;self.process.kill();self.process.wait(timeout=15)
  finally:
   self.stdoutThread.join(16);self.stderrThread.join(16);self.stderrFile.flush();os.fsync(self.stderrFile.fileno());self.stderrFile.close()
   self.row.update(protocol='bench-persistent-readonly-guard-process-closure-v1',finishedAtUtc=_now(),elapsedSeconds=time.monotonic()-self.started,closeObserved=self.process.poll() is not None,exitCode=self.process.returncode,intentionalKill=intentional,readerError=self.readerError,stdoutReaderClosed=not self.stdoutThread.is_alive(),stderrReaderClosed=not self.stderrThread.is_alive(),stderrPin=pin(self.stderrPath),requests=self.seq)
   _save(str(self.prefix)+'.close.json',self.row)
def close_channel():
 global _CHANNEL
 with _LOCK:
  if _CHANNEL is not None:_CHANNEL.close();_CHANNEL=None
atexit.register(close_channel)
def run_guard_bridge(argv,**kwargs):
 global _CHANNEL
 started=time.monotonic();deadline=started+15
 if not _LOCK.acquire(timeout=15):raise subprocess.TimeoutExpired(argv,15)
 try:
  c,p,mapping,sha,directory=_contract()
  assert len(argv)==4 and pathlib.Path(argv[0]).resolve()==pathlib.Path(c['bunPin']['path']).resolve() and argv[1]=='--smol' and pathlib.Path(argv[2]).resolve()==pathlib.Path(c['bridgePin']['path']).resolve()
  activation=str(pathlib.Path(argv[3]).resolve());assert activation in [str(pathlib.Path(x).resolve()) for x in c['allowedActivationPaths']]
  assert pathlib.Path(kwargs['cwd']).resolve()==pathlib.Path(c['root']).resolve() and kwargs['timeout']==15 and kwargs['stdin']==subprocess.DEVNULL and kwargs['stdout']==kwargs['stderr']==subprocess.PIPE
  if _CHANNEL is None:
   _CHANNEL=_Channel(c,p,mapping,sha,directory,activation);_CHANNEL.ready(deadline)
  assert _CHANNEL.mapping==str(mapping) and _CHANNEL.mappingSha==sha and _CHANNEL.activation==activation,'persistent_guard_binding_changed'
  result=_CHANNEL.request(deadline);result.args=argv;return result
 except (queue.Empty,subprocess.TimeoutExpired):
  if _CHANNEL is not None:_CHANNEL.failed=True;_CHANNEL.close()
  raise subprocess.TimeoutExpired(argv,15)
 except BaseException:
  if _CHANNEL is not None:_CHANNEL.failed=True;_CHANNEL.close()
  raise
 finally:_LOCK.release()
