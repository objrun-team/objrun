"""OS identity/error observation at the unchanged OwnedDocker Popen boundary."""
import datetime,json,pathlib,subprocess,traceback,os,ctypes
import psutil
from processes import incarnation

def spawn_owned(record,prefix,argv,**kwargs):
 path=pathlib.Path(str(prefix)+'.spawn.json');row={'argv':argv,'startedAtUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':None,'error':None}
 try:
  process=subprocess.Popen(argv,**kwargs)
 except BaseException as error:
  row['error']={'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()};row['finishedAtUtc']=datetime.datetime.now(datetime.timezone.utc).isoformat();path.write_text(json.dumps(row,indent=2)+'\n');raise
 row['pid']=process.pid;row['observationErrors']=[]
 try:
  if os.name=='nt':
   from ctypes import wintypes
   times=[wintypes.FILETIME() for _ in range(4)];kernel=ctypes.WinDLL('kernel32',use_last_error=True);get_times=kernel.GetProcessTimes;get_times.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)];get_times.restype=wintypes.BOOL
   if not get_times(int(process._handle),*[ctypes.byref(x) for x in times]):raise ctypes.WinError(ctypes.get_last_error())
   row['incarnation']=str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime);row['identitySource']='retained-Popen-Windows-handle'
  else:row['incarnation']=incarnation(process.pid)
 except BaseException as error:row['observationErrors'].append({'field':'incarnation','type':type(error).__name__,'message':str(error)})
 for field,method in [('actualExecutable','exe'),('actualArgv','cmdline'),('createdEpoch','create_time')]:
  try:row[field]=getattr(psutil.Process(process.pid),method)()
  except BaseException as error:row[field]=None;row['observationErrors'].append({'field':field,'type':type(error).__name__,'message':str(error)})
 record.update(row);path.write_text(json.dumps(row,indent=2)+'\n');return process
