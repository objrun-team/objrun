"""Bounded own pre-model closed-stage copies, preserving every path and SHA."""
import json,sys,os,uuid,hashlib,ctypes,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import HOME,public,save,utc
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024**2),b''):h.update(b)
 return h.hexdigest()
def allocated(p):
 hi=ctypes.c_ulong();lo=ctypes.windll.kernel32.GetCompressedFileSizeW('\\\\?\\'+str(p),ctypes.byref(hi));assert lo!=0xffffffff;return hi.value*2**32+(lo&0xffffffff)
raw=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command',"@(Get-CimInstance Win32_Process -Filter \"Name='bun.exe'\"|Select-Object -ExpandProperty ProcessId)|ConvertTo-Json -Compress"],text=True));live=set(raw if isinstance(raw,list) else [raw])
c=json.loads((HOME.parent/'control.json').read_bytes());h=json.loads(Path(c['broker']['healthPath']).read_bytes());owned={r['pid'] for r in h['resourceSlots']}
source=HOME/'parallel-scheduler-staging/5cc63f94-9f6a-4ea7-99be-977eeff5862d/prior.snapshot.json';digest=sha(source);rows=[]
for stage in sorted((HOME/'parallel-scheduler-staging').iterdir(),key=lambda p:p.stat().st_mtime,reverse=True)[:60]:
 if len(rows)>=8:break
 queue=stage/'queue.json';target=stage/'prior.snapshot.json'
 if not queue.exists() or not target.exists():continue
 q=json.loads(queue.read_bytes())
 if q['parentPid'] in live or q['parentPid'] in owned:continue
 closes=list(stage.glob('*/process-close.json'))
 if len(closes)!=1:continue
 close=json.loads(closes[0].read_bytes());pid=close['pid'];task=close['taskId']
 if close['exitCode']!=0 or pid in live or pid in owned:continue
 status=HOME/'parallel-task-status'/task/(str(pid)+'.json')
 if not status.exists():continue
 s=json.loads(status.read_bytes())
 if s.get('phase')!='physical_disk_queue_pending_preparation' or s.get('backgroundPaidProcessPid') is not None or s.get('output') or s.get('runId'):continue
 if not any(x['taskId']==task and x['originalBudgetRetained'] for x in s['physicalDiskPending']):continue
 for k in ['stdoutPin','stderrPin']:assert public.pin(Path(close[k]['path']))==close[k]
 target=target.resolve();assert target.is_relative_to((HOME/'parallel-scheduler-staging').resolve()) and target.drive.upper()=='F:'
 st=target.stat()
 if st.st_nlink!=1 or st.st_ino==source.stat().st_ino or st.st_size!=source.stat().st_size or sha(target)!=digest:continue
 before=allocated(target);temporary=target.with_name(target.name+'.own-link-'+uuid.uuid4().hex)
 try:
  os.link('\\\\?\\'+str(source),'\\\\?\\'+str(temporary));assert sha(temporary)==digest
  os.replace('\\\\?\\'+str(temporary),'\\\\?\\'+str(target));assert sha(target)==sha(source)==digest
  rows.append({'retainedPath':str(target),'sourcePath':str(source),'sha256':digest,'bytes':st.st_size,'actualUniqueAllocatedBytesReleased':before,'oldFileId':st.st_ino,'newFileId':target.stat().st_ino,'closurePin':public.pin(closes[0]),'nativeStatusPin':public.pin(status)})
 finally:
  if temporary.exists():temporary.unlink()
proof={'atUtc':utc(),'boundedStages':60,'maximumHardlinks':8,'rows':rows,'actualUniqueAllocatedBytesReleased':sum(r['actualUniqueAllocatedBytesReleased'] for r in rows),'models':0,'dockerCalls':0,'pathsBytesShaPreserved':True,'onlyClosedPreModelTargets':True,'foreignUserAssetsTouched':False}
pin=save(HOME/'closed-pre-model-prior-dedup'/uuid.uuid4().hex/'result.json',proof,True);s=json.loads((HOME/'status.json').read_bytes());s.update(closedPreModelPriorDedupPin=pin,updatedAtUtc=utc());save(HOME/'status.json',s);print(json.dumps({'resultPin':pin,'actualUniqueAllocatedBytesReleased':proof['actualUniqueAllocatedBytesReleased']}))
