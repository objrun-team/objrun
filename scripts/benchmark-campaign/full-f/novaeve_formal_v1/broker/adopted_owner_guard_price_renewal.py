"""Common read-only adopted-owner bridge. Owner cash/native/time contracts stay separate."""
import ctypes,datetime,hashlib,json,os,subprocess,time,urllib.request,psutil
from ctypes import wintypes
from pathlib import Path
ROOT=Path(__file__).resolve().parents[5]
HOME=ROOT/'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013'
ACTIVATION=HOME/'activation-price-renewal.json'
CONTROL=HOME/'broker/control-price-renewal.private.json'
BRIDGE=Path(__file__).with_name('adopted-python-bridge-price-renewal.ts')
BUN=Path('C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe')
def demand(ok,code):
 if not ok:raise RuntimeError(code)
def read(path):return json.loads(Path(path).read_bytes())
def check_capacity_observation(observation,minimum_commit_bytes=512*1024**2,minimum_physical_bytes=256*1024**2,now=None):
 demand(type(minimum_commit_bytes) is int and minimum_commit_bytes>=512*1024**2 and type(minimum_physical_bytes) is int and minimum_physical_bytes>=256*1024**2,'capacity_policy_cannot_be_lowered')
 age=(datetime.datetime.now(datetime.timezone.utc).timestamp() if now is None else now)-datetime.datetime.fromisoformat(observation['observedAtUtc']).timestamp()
 demand(observation.get('protocol')=='windows-commit-capacity-readonly-v50' and 0<=age<=30 and observation.get('pagefileChanged') is False,'fresh_actual_windows_capacity_required')
 for key,minimum in [('commitAvailableBytes',minimum_commit_bytes),('physicalAvailableBytes',minimum_physical_bytes)]:demand(type(observation.get(key)) is int and observation[key]>=minimum,'windows_host_capacity_preflight_closed')
 return observation
def observe_host_capacity():
 class PERF(ctypes.Structure):
  _fields_=[('cb',wintypes.DWORD),('CommitTotal',ctypes.c_size_t),('CommitLimit',ctypes.c_size_t),('CommitPeak',ctypes.c_size_t),('PhysicalTotal',ctypes.c_size_t),('PhysicalAvailable',ctypes.c_size_t),('SystemCache',ctypes.c_size_t),('KernelTotal',ctypes.c_size_t),('KernelPaged',ctypes.c_size_t),('KernelNonpaged',ctypes.c_size_t),('PageSize',ctypes.c_size_t),('HandleCount',wintypes.DWORD),('ProcessCount',wintypes.DWORD),('ThreadCount',wintypes.DWORD)]
 p=PERF();p.cb=ctypes.sizeof(p)
 if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(p),p.cb):raise ctypes.WinError()
 return dict(protocol='windows-commit-capacity-readonly-v50',observedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),commitAvailableBytes=(p.CommitLimit-p.CommitTotal)*p.PageSize,physicalAvailableBytes=p.PhysicalAvailable*p.PageSize,pagefileChanged=False)
def require_host_capacity(**policy):return check_capacity_observation(observe_host_capacity(),**policy)
def verify_activation():
 for name,expected in [('NOVAEVE_ACTIVATION_PATH',ACTIVATION),('NOVAEVE_BROKER_CONTROL_PATH',CONTROL)]:
  if name in os.environ:demand(Path(os.environ[name]).resolve()==expected.resolve(),'explicit_adopted_path_required')
 child=subprocess.run([str(BUN),'--smol',str(BRIDGE),str(ACTIVATION)],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
 demand(child.returncode==0,'signed_actual_adopted_TS_guard_rejected')
 result=json.loads(child.stdout);demand(result.get('protocol')=='novaeve-redacted-python-consumer-bridge-v81' and result.get('healthy') is True and result.get('secretsPrinted') is False,'redacted_actual_bridge_result_required')
 age=time.time()-datetime.datetime.fromisoformat(result['checkedAtUtc']).timestamp();demand(0<=age<=30,'actual_bridge_observation_stale')
 demand(result['dockerHost']=='tcp://127.0.0.1:18750' and result['dataRoot']=='/data/wpx/tgengin/docker','original_server_scope_required')
 with urllib.request.urlopen('http://127.0.0.1:18750/info',timeout=5) as response:daemon=json.load(response)
 demand(daemon.get('ID')=='dc87b6a7-ed03-4ccf-8d26-89709287b80a' and daemon.get('DockerRootDir')=='/data/wpx/tgengin/docker','actual_original_private_docker_identity_required')
 disk=read(result['remoteDiskObservationPath']);age=time.time()*1000-disk['observedAtMs']
 demand(disk.get('protocol')=='novaeve-runtime-disk-v1' and disk.get('dataRoot')=='/data/wpx/tgengin/docker' and disk.get('probeExitCode')==0 and 0<=age<=10000 and disk['freeBytes']>=5*1024**3,'actual_fresh_remote_disk_floor_required')
 return result
def require_activation():
 verify_activation();require_host_capacity();return read(ACTIVATION)
def load_control(activation=None):
 verify_activation();return read(CONTROL)
def check_resource_lease(observed,pid,slug,memory_mb,growth_bytes,slots=1):
 matches=[r for r in observed['resourceSlots'] if r['kind']=='heavy-container' and r['slug']==slug and r['pid']==pid and r['tokenMatches'] and not r['adoptedOrphanHold'] and not r.get('inheritedResourceHold',False) and r.get('ownerIncarnationMatches') is True and r['slots']==slots and r['memoryMb']>=memory_mb and r.get('plannedGrowthBytes',0)>=growth_bytes]
 demand(len(matches)==1,'actual_live_new_resource_lease_required');return matches[0]
def require_lease(memory_mb,growth_bytes,slug='terminal-bench',slots=1):
 demand('NOVAEVE_RESOURCE_LEASE_PID' in os.environ and 'NOVAEVE_RESOURCE_TOKEN' in os.environ,'explicit_resource_identity_required')
 demand(type(memory_mb) is int and memory_mb>0 and type(growth_bytes) is int and growth_bytes>=0 and type(slots) is int and slots>0,'explicit_owner_resource_contract_required')
 observed=verify_activation();row=check_resource_lease(observed,int(os.environ['NOVAEVE_RESOURCE_LEASE_PID']),slug,memory_mb,growth_bytes,slots);demand(psutil.pid_exists(row['pid']),'resource_owner_process_not_live');demand(process_incarnation(row['pid'])==row['ownerIncarnation'],'actual_resource_owner_filetime_changed');capacity=require_host_capacity()
 return dict(verified=True,brokerPid=observed['brokerPid'],resourceLeasePid=row['pid'],resourceSlots=row['slots'],resourceMemoryMb=row['memoryMb'],resourcePlannedGrowthBytes=row['plannedGrowthBytes'],ownerIncarnation=row['ownerIncarnation'],resourceTokenSha256=row['resourceTokenSha256'],hostCapacity=capacity,modelCalls=0,newActors=0)
def guard():
 demand('NOVAEVE_RESOURCE_MEMORY_MB' in os.environ and 'NOVAEVE_RESOURCE_GROWTH_BYTES' in os.environ,'explicit_owner_resource_environment_required')
 return require_lease(memory_mb=int(os.environ['NOVAEVE_RESOURCE_MEMORY_MB']),growth_bytes=int(os.environ['NOVAEVE_RESOURCE_GROWTH_BYTES']),slug=os.environ.get('NOVAEVE_RESOURCE_BENCH','terminal-bench'),slots=int(os.environ.get('NOVAEVE_RESOURCE_SLOTS','1')))
def before_forward_guard(**policy):
 owned=guard();capacity=require_host_capacity(**policy);return dict(brokerPid=owned['brokerPid'],resourceLeasePid=owned['resourceLeasePid'],ownerIncarnation=owned['ownerIncarnation'],resourceTokenSha256=owned['resourceTokenSha256'],hostCapacity=capacity,modelForwarded=False)

def process_incarnation(pid):
 demand(type(pid) is int and pid>0,'actual_owner_pid_required')
 k=ctypes.WinDLL('kernel32',use_last_error=True)
 k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
 k.GetProcessTimes.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.FILETIME),ctypes.POINTER(wintypes.FILETIME),ctypes.POINTER(wintypes.FILETIME),ctypes.POINTER(wintypes.FILETIME)];k.GetProcessTimes.restype=wintypes.BOOL
 k.CloseHandle.argtypes=[wintypes.HANDLE];k.CloseHandle.restype=wintypes.BOOL
 handle=k.OpenProcess(0x1000,False,pid);demand(bool(handle),'actual_owner_openprocess_failed')
 try:
  creation,exit,kernel,user=(wintypes.FILETIME() for _ in range(4))
  demand(bool(k.GetProcessTimes(handle,ctypes.byref(creation),ctypes.byref(exit),ctypes.byref(kernel),ctypes.byref(user))),'actual_owner_getprocesstimes_failed')
  return str((creation.dwHighDateTime<<32)|creation.dwLowDateTime)
 finally:k.CloseHandle(handle)
