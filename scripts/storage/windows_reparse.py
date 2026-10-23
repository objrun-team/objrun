"""Read ordinary links and preserve the raw metadata of WSL Linux symlinks."""
import base64,ctypes,os,struct

def read_link_metadata(path):
    try: return dict(target=os.readlink(path))
    except ValueError:
        st=os.lstat(path)
        if getattr(st,'st_reparse_tag',None)!=0xa000001d:
            raise ValueError('Unsupported reparse point: '+str(path))
    # FSCTL_GET_REPARSE_POINT opens the entry itself, never its target.
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.DeviceIoControl.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
    kernel.DeviceIoControl.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateFileW(str(path),0,7,None,3,0x02200000,None)
    if handle==ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
    try:
        buffer=ctypes.create_string_buffer(16384);returned=wintypes.DWORD()
        if not kernel.DeviceIoControl(handle,0x000900A8,None,0,buffer,len(buffer),ctypes.byref(returned),None):
            raise ctypes.WinError(ctypes.get_last_error())
        raw=buffer.raw[:returned.value]
    finally: kernel.CloseHandle(handle)
    tag,length,_=struct.unpack_from('<IHH',raw)
    if tag!=0xa000001d or len(raw)!=8+length or length<4: raise ValueError('Invalid WSL link metadata')
    target=raw[12:].decode('utf-8').rstrip('\0')
    if not target or '\0' in target: raise ValueError('Invalid WSL link target')
    return dict(target=target,reparse_tag=hex(tag),reparse_data_b64=base64.b64encode(raw).decode('ascii'))
