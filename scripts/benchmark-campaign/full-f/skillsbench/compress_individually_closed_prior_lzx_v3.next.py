"""Bounded compression of individually native-closed, unreferenced priors."""
import json,sys,uuid,ctypes,hashlib,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import HOME,public,save,utc
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024**2),b''):h.update(b)
 return h.hexdigest()
def allocated(p):
 hi=ctypes.c_ulong();lo=ctypes.windll.kernel32.GetCompressedFileSizeW('\\\\?\\'+str(p),ctypes.byref(hi));assert lo!=0xffffffff
 return hi.value*2**32+(lo&0xffffffff)
c=json.loads((HOME.parent/'control.json').read_bytes());health=json.loads(Path(c['broker']['healthPath']).read_bytes())
owned={r['pid'] for r in health['resourceSlots'] if r['slug']=='skillsbench'}
live=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command',"@(Get-CimInstance Win32_Process -Filter \"Name='bun.exe'\"|Select-Object -ExpandProperty ProcessId)|ConvertTo-Json -Compress"],text=True));live=set(live if isinstance(live,list) else [live])
active_text=[];active_ids=set()
for pid in owned:
 for s in (HOME/'parallel-task-status').glob('*/'+str(pid)+'.json'):
  state=json.loads(s.read_bytes());out=Path(state.get('output',''))
  for name in ['source-archive.json','runtime-readiness.snapshot.json']:
   p=out/name
   if p.exists():active_text.append(p.read_text())
  for p in (out/'frozen-sources').glob('*-prior.snapshot.json'):active_ids.add(p.stat().st_ino)
seen_runs=set();seen_files=set();rows=[];closures=[];logical=0
for receipt in sorted((HOME/'private-native-closure-reviews').glob('*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:40]:
 r=json.loads(receipt.read_bytes())
 if r['runId'] in seen_runs or r['pid'] in live or r['pid'] in owned:continue
 seen_runs.add(r['runId']);assert r['resourceReleased'] and r['actualFinishedRequests']>0
 for k in ['accountingClosePin','cashClosePin']:assert public.pin(Path(r[k]['path']))==r[k]
 cash=json.loads(Path(r['cashClosePin']['path']).read_bytes());assert cash.get('pendingCount',cash.get('snapshot',{}).get('pendingCount',0))==0
 run=(HOME/'runs'/r['runId']).resolve();assert run.is_relative_to((HOME/'runs').resolve())
 for p in (run/'frozen-sources').glob('*-prior.snapshot.json'):
  p=p.resolve();st=p.stat();assert p.is_relative_to(run) and p.drive.upper()=='F:' and 10*1024**2<st.st_size<64*1024**2
  if st.st_ino in seen_files or st.st_ino in active_ids or any(str(p) in text or str(p).replace('\\','\\\\') in text for text in active_text):continue
  seen_files.add(st.st_ino)
  if len(rows)>=24 or logical+st.st_size>768*1024**2:continue
  logical+=st.st_size;before=allocated(p);digest=sha(p)
  result=subprocess.run(['compact.exe','/C','/F','/EXE:LZX','/I','/Q',str(p)],capture_output=True)
  assert result.returncode==0 and sha(p)==digest and p.stat().st_ino==st.st_ino and p.stat().st_size==st.st_size
  rows.append({'path':str(p),'sha256':digest,'bytes':st.st_size,'allocatedBefore':before,'allocatedAfter':allocated(p),'fileId':st.st_ino,'nativeClosedPid':r['pid']});closures.append(public.pin(receipt))
proof={'atUtc':utc(),'boundedNativeReviewMaximum':40,'modelCalls':0,'dockerCalls':0,'closurePins':closures,'rows':rows,'actualAllocatedBytesSaved':sum(r['allocatedBefore']-r['allocatedAfter'] for r in rows),'activeResourcesObserved':sorted(owned),'activeSourcesNotModified':True,'pathsBytesShaIdsPreserved':True,'foreignUserAssetsTouched':False}
pin=save(HOME/'individually-closed-prior-lzx-compression'/uuid.uuid4().hex/'result.json',proof,True)
s=json.loads((HOME/'status.json').read_bytes());s.update(individuallyClosedPriorLzxCompressionPin=pin,updatedAtUtc=utc());save(HOME/'status.json',s)
print(json.dumps({'resultPin':pin,'actualAllocatedBytesSaved':proof['actualAllocatedBytesSaved']}))
