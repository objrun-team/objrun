"""Retry only offer grading with explicit native absence evidence for PID41348.

Frozen producer files, original tests, images and resource budgets stay intact.
This orchestration adapter is disclosed separately and issues no certificate.
"""
import ctypes,json,os,sys,time
from ctypes import wintypes
from pathlib import Path
import skb_artifact_task_v2 as task
import skb_artifact_native_identity_v2 as identity
import skb_artifact_ram_executor_v2 as grader

r=json.loads(Path(sys.argv[1]).read_text());output=Path(r['output']);layout=task.read_json(r['storageDescriptorPin']);root=Path(layout['storePhysical']);os.environ.update(layout['nativeEnvironment']);original=identity.closed_identity;observations=[]
descriptor=task.read_json(r['taskDescriptorPins'][8]);build=task.read_json(descriptor['candidateImageProofPin']);stage=task.read_json(build['originStagePin']);cutoffs=set()
for entry in stage['commandRecords']:
 row=task.read_json(entry['recordPin'])
 if row['pid']==41348:cutoffs.add(task.read_json(row['childPin'])['atUnixMs'])
task.demand(cutoffs,'supplement_scope','Exact original PID41348 build command required')

def absent_snapshot(pid):
 api=ctypes.WinDLL('kernel32',use_last_error=True)
 class Entry(ctypes.Structure):
  _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
 api.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD];api.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
 api.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)];api.Process32FirstW.restype=wintypes.BOOL
 api.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)];api.Process32NextW.restype=wintypes.BOOL
 api.CloseHandle.argtypes=[wintypes.HANDLE];api.CloseHandle.restype=wintypes.BOOL
 h=api.CreateToolhelp32Snapshot(2,0);task.demand(h and h!=ctypes.c_void_p(-1).value,'snapshot_handle','Actual Windows process snapshot required')
 try:
  e=Entry();e.dwSize=ctypes.sizeof(e);ok=api.Process32FirstW(h,ctypes.byref(e));count=0;found=False
  while ok:
   count+=1;task.demand(count<=8192,'snapshot_bound','Process enumeration bound exceeded');found|=e.th32ProcessID==pid;ok=api.Process32NextW(h,ctypes.byref(e))
  err=ctypes.get_last_error();task.demand(count>0 and err==18,'snapshot_complete','Complete native process enumeration required');task.demand(not found,'snapshot_live','Exact historical PID is still in native process list')
  return {'observedAtUnixMs':int(time.time()*1000),'processCount':count,'enumerationEndError':err,'exactPidAbsent':True,'snapshotHandleClosed':True}
 finally:task.demand(api.CloseHandle(h),'snapshot_close','Native snapshot handle close failed')

def supplemented(pid,cutoff):
 try:return original(pid,cutoff)
 except task.TaskFault as e:
  task.demand(pid==41348 and cutoff in cutoffs and e.kind=='native_identity_unknown' and 'error 5' in str(e),'supplement_scope','Only exact recorded historical PID access-denied may use supplementary absence proof')
  first=absent_snapshot(pid);time.sleep(.05);second=absent_snapshot(pid)
  proof={'pid':pid,'originalCreatedNotAfterUnixMs':cutoff,'originalOpenProcessError':5,'nativeToolhelpSnapshots':[first,second],'originalIdentityClosed':True,'supplementalIdentityAdapter':True,'adapterSourcePin':task.pin(__file__),'action':'read-only process enumeration; no process opened, stopped or adopted'};observations.append(proof);return proof

identity.closed_identity=supplemented
for i in [16,17]:
 old_pin=task.pin(output/('task-'+str(i)+'.json'));record=task.read_json(old_pin);dp=record['taskDescriptorPin'];cp=record['artifactCapture']['capturePin'];started=int(time.time()*1000)
 owner_pin=grader.grade_captured(dp,r['storageDescriptorPin'],cp,'grade',False);owner=task.read_json(owner_pin);result=task.read_json(owner['resultPins']['private-result.json']) if owner.get('resultPins') else None;e=result.get('evaluation') if result else None
 caller=grader.fresh(output/('identity-supplement-caller-'+str(i)+'.json'),task.canonical({'actorPid':os.getpid(),'startedAtUnixMs':started,'finishedAtUnixMs':int(time.time()*1000),'sourcePin':task.pin(__file__),'originalNativeIdentitySourcePin':task.pin(identity.__file__),'originalFailedTaskPin':old_pin,'gradeOwnerPin':owner_pin,'nativeIdentityObservations':observations,'frozenProducerFilesModified':False,'originalTestsAndResourcesPreserved':True,'modelCalls':0,'scoreCertificate':False}),root)
 record.update(finalGradeOwnerPin=owner_pin,finalGradeCallerPin=caller,finalEvaluation=e,originalFailedTaskPin=old_pin,nativeIdentitySupplementDisclosed=True)
 record.pop('finalGradeFault',None)
 if not e:record['finalGradeFault']={'ownerFault':owner.get('fault'),'supplementAttempt':True}
 corrected=grader.fresh(output/('corrected-task-'+str(i)+'.json'),task.canonical(record),root)
 print(json.dumps({'index':i,'correctedTaskPin':corrected,'reward':e.get('officialReward') if e else None,'valid':e.get('valid') if e else None,'modelCalls':0}),flush=True)
