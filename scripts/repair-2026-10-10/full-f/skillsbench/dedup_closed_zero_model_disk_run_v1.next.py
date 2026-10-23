"""Retain duplicate priors of an admitted, disk-queued, zero-model closed run."""
import sys,json,uuid,os,ctypes,subprocess,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import HOME,public,save,utc
run=HOME/'runs/repair-2026-10-11T11-50-05-363Z-13-2026-10-11T17-09-56-567Z'
stage=HOME/'parallel-scheduler-staging/60903ec5-d926-4331-924c-0022821ccb50'
close=json.loads((run/'accounting-close.json').read_bytes());assert close['brokerClose']['closed']
cash=json.loads(Path(close['cashPin']['path']).read_bytes());assert cash['snapshot']['pendingCount']==0 and cash['snapshot']['billedUsd']==0 and cash['snapshot']['newUnknownCount']==0
assert (run/'journal/api-events.jsonl').stat().st_size==0 and not list(run.glob('task-*.json'))
pending=json.loads((run/'physical-disk-pending-12.json').read_bytes());assert pending['taskId']=='dialogue-parser' and pending['originalBudgetRetained']
processes=[json.loads((run/n).read_bytes()) for n in ['parent-process.json','bridge-process.json']]
raw=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command',"@(Get-CimInstance Win32_Process -Filter \"Name='bun.exe'\"|Select-Object -ExpandProperty ProcessId)|ConvertTo-Json -Compress"],text=True));live=set(raw if isinstance(raw,list) else [raw])
assert all(p['pid'] not in live for p in processes)
q=json.loads((stage/'queue.json').read_bytes());assert q['parentPid'] not in live
c=json.loads((HOME.parent/'control.json').read_bytes());health=json.loads(Path(c['broker']['healthPath']).read_bytes());assert not any(r['pid']==processes[0]['pid'] for r in health['resourceSlots'])
source=HOME/'parallel-scheduler-staging/5cc63f94-9f6a-4ea7-99be-977eeff5862d/prior.snapshot.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def allocated(p):
 hi=ctypes.c_ulong();lo=ctypes.windll.kernel32.GetCompressedFileSizeW('\\\\?\\'+str(p),ctypes.byref(hi));assert lo!=0xffffffff;return hi.value*2**32+(lo&0xffffffff)
archive=run/'source-archive.json';archivepin=public.pin(archive);a=json.loads(archive.read_bytes())
targets=[Path(e['snapshotPin']['path']) for e in a['entries'] if e['snapshotPin']['bytes']==source.stat().st_size and e['snapshotPin']['sha256']==sha(source)]+[stage/'prior.snapshot.json']
assert len(targets)==2;rows=[]
for target in targets:
 target=target.resolve();assert target.is_relative_to(HOME.resolve()) and target.drive.upper()=='F:' and sha(target)==sha(source)
 st=target.stat()
 if st.st_nlink!=1:continue
 before=allocated(target);tmp=target.with_name(target.name+'.own-link-'+uuid.uuid4().hex)
 try:
  os.link('\\\\?\\'+str(source),'\\\\?\\'+str(tmp));assert sha(tmp)==sha(source)
  os.replace('\\\\?\\'+str(tmp),'\\\\?\\'+str(target));assert sha(target)==sha(source)
  rows.append({'path':str(target),'sha256':sha(target),'bytes':st.st_size,'actualUniqueAllocatedBytesReleased':before,'oldFileId':st.st_ino,'newFileId':target.stat().st_ino})
 finally:
  if tmp.exists():tmp.unlink()
assert public.pin(archive)==archivepin
proof={'atUtc':utc(),'nativeZeroModelAccountingPin':public.pin(run/'accounting-close.json'),'physicalDiskPendingPin':public.pin(run/'physical-disk-pending-12.json'),'rows':rows,'actualUniqueAllocatedBytesReleased':sum(x['actualUniqueAllocatedBytesReleased'] for x in rows),'models':0,'dockerCalls':0,'pathsBytesShaRetained':True,'foreignUserAssetsTouched':False}
pin=save(HOME/'closed-zero-model-disk-run-dedup'/uuid.uuid4().hex/'result.json',proof,True);s=json.loads((HOME/'status.json').read_bytes());s.update(closedZeroModelDiskRunDedupPin=pin,updatedAtUtc=utc());save(HOME/'status.json',s);print(json.dumps({'resultPin':pin,'actualUniqueAllocatedBytesReleased':proof['actualUniqueAllocatedBytesReleased']}))
