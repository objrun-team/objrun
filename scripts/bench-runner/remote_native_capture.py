"""Python 3.6-compatible actual subprocess evidence, embedded by the signed caller."""
REMOTE_CAPTURE = r'''
def captured_remote(argv,timeout):
 import base64,datetime,hashlib,json,os,pathlib,subprocess,time,traceback,uuid
 root=pathlib.Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/process-receipts');root.mkdir(parents=True,exist_ok=True)
 assert root.resolve()==root
 prefix=root/uuid.uuid4().hex;stdout=pathlib.Path(str(prefix)+'.stdout');stderr=pathlib.Path(str(prefix)+'.stderr')
 start=time.monotonic();row={'protocol':'bench-actual-remote-process-v1','argv':argv,'startedAtUtc':datetime.datetime.utcnow().isoformat()+'Z','pid':None,'incarnation':None,'closeObserved':False,'exitCode':None,'timedOut':False,'error':None};p=None
 def save():pathlib.Path(str(prefix)+'.json').write_text(json.dumps(row))
 save()
 with stdout.open('xb') as so,stderr.open('xb') as se:
  try:
   p=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=so,stderr=se);row['pid']=p.pid
   stat=pathlib.Path('/proc/'+str(p.pid)+'/stat').read_text();ticks=stat[stat.rfind(')')+2:].split()[19]
   row['incarnation']=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()+':'+ticks
   row['actualExecutable']=os.readlink('/proc/'+str(p.pid)+'/exe');row['actualArgv']=pathlib.Path('/proc/'+str(p.pid)+'/cmdline').read_bytes().decode().split(chr(0))[:-1];save()
   try:p.wait(timeout=timeout)
   except subprocess.TimeoutExpired:row['timedOut']=True;p.kill();p.wait(timeout=15)
   row.update(exitCode=p.returncode,closeObserved=True)
  except BaseException as e:
   row['error']={'type':type(e).__name__,'message':str(e),'traceback':traceback.format_exc()}
   if p is not None:
    if p.poll() is None:p.kill()
    try:p.wait(timeout=15);row.update(exitCode=p.returncode,closeObserved=True)
    except BaseException as close:row['closeError']=str(close)
  finally:so.flush();se.flush();os.fsync(so.fileno());os.fsync(se.fileno())
 for name,path in [('stdout',stdout),('stderr',stderr)]:
  raw=path.read_bytes();row[name]={'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'rawBase64':base64.b64encode(raw).decode()}
 row.update(finishedAtUtc=datetime.datetime.utcnow().isoformat()+'Z',elapsedSeconds=time.monotonic()-start);save();print(json.dumps({'remoteCommand':row}),flush=True)
 assert row['closeObserved'] and not row['timedOut'] and row['error'] is None and row['exitCode']==0,{'remote_command_failed':str(prefix)+'.json'}
 return stdout.read_bytes()
'''
