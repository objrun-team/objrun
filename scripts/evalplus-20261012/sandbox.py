"""Linux Landlock filesystem restrictions and seccomp for a Python function worker."""
import ctypes,errno,os,resource
def restrict(read_paths,write_path):
    libc=ctypes.CDLL(None,use_errno=True)
    abi=libc.syscall(444,0,0,1)
    if abi<1: raise RuntimeError('LandlockUnavailable')
    class Ruleset(ctypes.Structure): _fields_=[('handled_access_fs',ctypes.c_uint64)]
    class PathBeneath(ctypes.Structure):
        _pack_=1
        _fields_=[('allowed_access',ctypes.c_uint64),('parent_fd',ctypes.c_int)]
    handled=(1<<13)-1
    if abi>=2: handled|=1<<13
    if abi>=3: handled|=1<<14
    rules=Ruleset(handled);fd=libc.syscall(444,ctypes.byref(rules),ctypes.sizeof(rules),0)
    if fd<0: raise RuntimeError('LandlockCreateFailed')
    try:
        for path,access in [(p,(1<<0)|(1<<2)|(1<<3)) for p in read_paths if os.path.exists(p)]+[(write_path,handled)]:
            pfd=os.open(path,os.O_PATH|os.O_CLOEXEC)
            try:
                rule=PathBeneath(access,pfd)
                if libc.syscall(445,fd,1,ctypes.byref(rule),0)!=0: raise RuntimeError('LandlockRuleFailed')
            finally: os.close(pfd)
        if libc.prctl(38,1,0,0,0)!=0 or libc.syscall(446,fd,0)!=0: raise RuntimeError('LandlockEnforcementFailed')
    finally: os.close(fd)
    class Filter(ctypes.Structure): _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
    class Program(ctypes.Structure): _fields_=[('length',ctypes.c_ushort),('filter',ctypes.POINTER(Filter))]
    blocked=[41,42,43,49,50,53,56,57,58,59,101,165,166,272,288,308,310,311,321,322,435,438]
    instructions=[Filter(0x20,0,0,4),Filter(0x15,1,0,0xc000003e),Filter(0x06,0,0,0x80000000),Filter(0x20,0,0,0)]
    for nr in blocked: instructions.extend([Filter(0x15,0,1,nr),Filter(0x06,0,0,0x00050000|errno.EPERM)])
    instructions.append(Filter(0x06,0,0,0x7fff0000))
    array=(Filter*len(instructions))(*instructions);program=Program(len(instructions),array)
    if libc.prctl(22,2,ctypes.byref(program),0,0)!=0: raise RuntimeError('SeccompEnforcementFailed')
    resource.setrlimit(resource.RLIMIT_CPU,(70,70))
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE,(1024**2,1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
