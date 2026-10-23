"""Observe exact original Windows identity closure without stopping reused PIDs."""
import ctypes
from ctypes import wintypes
from datetime import datetime,timezone
import os
import skb_artifact_task_v2 as task


def closed_identity(pid,original_created_not_after_unix_ms):
    task.demand(os.name=='nt' and type(pid) is int and pid>0 and type(original_created_not_after_unix_ms) is int,
                'native_identity','Exact positive original PID and source-bound creation cutoff required')
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];api.OpenProcess.restype=wintypes.HANDLE
    api.CloseHandle.argtypes=[wintypes.HANDLE];api.CloseHandle.restype=wintypes.BOOL
    ctypes.set_last_error(0);handle=api.OpenProcess(0x1000,False,pid)
    now=datetime.now(timezone.utc).isoformat()
    if not handle:
        code=ctypes.get_last_error();task.demand(code==87,'native_identity_unknown','Native actor query denied or ambiguous: PID '+str(pid)+', error '+str(code))
        return {'pid':pid,'actualNativeOpenProcessAbsent':True,'win32Error':code,'originalIdentityClosed':True,'observedAtUtc':now}
    try:
        api.GetProcessTimes.argtypes=[wintypes.HANDLE,*[ctypes.POINTER(wintypes.FILETIME)]*4];api.GetProcessTimes.restype=wintypes.BOOL
        birth,exit_time,kernel,user=[wintypes.FILETIME() for _ in range(4)]
        task.demand(api.GetProcessTimes(handle,ctypes.byref(birth),ctypes.byref(exit_time),ctypes.byref(kernel),ctypes.byref(user)),'native_identity_unknown','Native birth/exit time query failed')
        created_100ns=(birth.dwHighDateTime<<32)|birth.dwLowDateTime
        created_ms=(created_100ns-116444736000000000)//10000
        exit_100ns=(exit_time.dwHighDateTime<<32)|exit_time.dwLowDateTime
        terminated=exit_100ns>0
        # Original c004 child was created before its source-bound child receipt;
        # a currently live process born later cannot be that original identity.
        reused=created_ms>original_created_not_after_unix_ms+1000
        task.demand(terminated or reused,'native_identity_live','Original identity may still be live; never stop or adopt it')
        return {'pid':pid,'actualNativeOpenProcessAbsent':False,'actualCreationFiletime100ns':str(created_100ns),'actualCreationUnixMs':created_ms,
            'actualExitFiletime100ns':str(exit_100ns),'originalCreatedNotAfterUnixMs':original_created_not_after_unix_ms,
            'currentProcessIsLaterPidReuse':reused,'nativeProcessSignaledExited':terminated,'originalIdentityClosed':True,'observedAtUtc':now,
            'querySourcePin':task.pin(__file__),'action':'observation only; no process stopped, signalled or adopted'}
    finally:task.demand(api.CloseHandle(handle),'native_identity_handle','Native query handle did not close')
