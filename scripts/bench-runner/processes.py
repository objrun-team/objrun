"""One bounded, read-only snapshot of specified custody roots and their descendants."""
import ctypes,json,os,sys,datetime
from pathlib import Path
import psutil

def incarnation(pid):
    if os.name=='nt':
        from ctypes import wintypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];api.OpenProcess.restype=wintypes.HANDLE
        api.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)];api.GetProcessTimes.restype=wintypes.BOOL
        api.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=api.OpenProcess(0x1000,False,pid)
        if not handle:raise OSError(ctypes.get_last_error(),'OpenProcess')
        try:
            values=[wintypes.FILETIME() for _ in range(4)]
            if not api.GetProcessTimes(handle,*[ctypes.byref(v) for v in values]):raise OSError(ctypes.get_last_error(),'GetProcessTimes')
            return str((values[0].dwHighDateTime<<32)|values[0].dwLowDateTime)
        finally:api.CloseHandle(handle)
    stat=Path('/proc/'+str(pid)+'/stat').read_text();start=stat[stat.rfind(')')+2:].split()[19]
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()+':'+start

def snapshot(roots):
    if len(roots)>256 or any(not isinstance(p,int) or p<1 for p in roots):raise ValueError('bounded exact root PIDs required')
    rows={};errors=[]
    for pid in sorted(set(roots)):
        try:
            root=psutil.Process(pid);members=[root,*root.children(recursive=True)]
        except psutil.NoSuchProcess:rows[pid]={'pid':pid,'live':False};continue
        except Exception as ex:errors.append({'pid':pid,'error':type(ex).__name__+':'+str(ex)});continue
        if len(members)>4096:raise ValueError('descendant bound exceeded')
        for process in members:
            if process.pid in rows:continue
            try:
                ident=incarnation(process.pid)
                row={'pid':process.pid,'parentPid':process.ppid(),'live':process.is_running() and process.status()!=psutil.STATUS_ZOMBIE,'argv':process.cmdline(),'createdEpoch':process.create_time(),'incarnation':ident}
                if incarnation(process.pid)!=ident:raise ValueError('process reused during snapshot')
                rows[process.pid]=row
            except psutil.NoSuchProcess:rows[process.pid]={'pid':process.pid,'live':False}
            except Exception as ex:errors.append({'pid':process.pid,'error':type(ex).__name__+':'+str(ex)})
    return {'protocol':'bench-process-subtrees-readonly-v1','atUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'roots':sorted(set(roots)),'processes':list(rows.values()),'errors':errors}

if __name__=='__main__':
    request=json.load(sys.stdin);print(json.dumps(snapshot(request['roots'])))
