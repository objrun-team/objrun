"""Actual bounded subprocess execution, with durable raw streams and OS identity."""
import datetime, hashlib, json, os, pathlib, shutil, subprocess, time, traceback
import psutil
from processes import incarnation

def pin(path):
 p=pathlib.Path(path);h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=h.hexdigest())

def capture(argv,prefix,timeout,input_bytes=None,env=None,cwd=None):
 prefix=pathlib.Path(prefix);prefix.parent.mkdir(parents=True,exist_ok=True)
 argv=list(map(str,argv))
 started=time.perf_counter();row=dict(protocol='bench-actual-native-process-v1',argv=argv,executablePin=None,startedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),pid=None,incarnation=None,closeObserved=False,exitCode=None,timedOut=False,error=None)
 out=pathlib.Path(str(prefix)+'.stdout');err=pathlib.Path(str(prefix)+'.stderr');receipt=pathlib.Path(str(prefix)+'.json')
 def save():
  receipt.write_text(json.dumps(row,indent=2)+'\n',encoding='utf8')
 save();process=None
 with out.open('xb') as stdout,err.open('xb') as stderr:
  try:
   exe=shutil.which(argv[0]);assert exe,'native_executable_missing'
   argv=[str(pathlib.Path(exe).resolve()),*argv[1:]];row.update(argv=argv,executablePin=pin(argv[0]));save()
   process=subprocess.Popen(argv,stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,stdout=stdout,stderr=stderr,env=env,cwd=cwd,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
   row['pid']=process.pid;row['incarnation']=incarnation(process.pid)
   observed=psutil.Process(process.pid);row['actualExecutable']=observed.exe();row['actualArgv']=observed.cmdline();row['createdEpoch']=observed.create_time();save()
   try:process.communicate(input=input_bytes,timeout=timeout)
   except subprocess.TimeoutExpired:
    row['timedOut']=True;process.kill();process.communicate(timeout=15)
   row.update(exitCode=process.returncode,closeObserved=process.returncode is not None)
  except BaseException as e:
   row['error']=dict(type=type(e).__name__,message=str(e),traceback=traceback.format_exc())
   if process is not None:
    if process.poll() is None:process.kill()
    try:process.communicate(timeout=15);row.update(exitCode=process.returncode,closeObserved=True)
    except BaseException as close:row['closeError']=str(close)
  finally:
   stdout.flush();stderr.flush();os.fsync(stdout.fileno());os.fsync(stderr.fileno())
 row.update(finishedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),elapsedSeconds=time.perf_counter()-started,stdoutPin=pin(out),stderrPin=pin(err));save()
 return row
