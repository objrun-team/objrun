"""Native reversible compression for exact owned, stopped experiment evidence.

No move/delete/link replacement, model, network, Docker, SQLite or source edit.
Production mode only consumes a reviewed list of single-link ordinary JSON/DB
files in fixed evidence directories; every byte/path/identity/mtime is checked.
"""
import argparse, ctypes, hashlib, json, os, stat, uuid
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/repair-2026-10-08'
FIXTURE=ROOT/'.scratch/ntfs-compression-owned-controls'
ALLOW=[ROOT/'.scratch/paid-resource-admission-v2',ROOT/'.scratch/science1220-oom-readonly-snapshot',
       ROOT/'.scratch/scientific-journal-preparations',ROOT/'.scratch/scientific-native-four-engine-24d25857-4de7-4a74-81de-0c23ddd9452e',
       DOC/'campaigns']
MAX=1024**3
K=ctypes.WinDLL('kernel32',use_last_error=True)
K.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
K.CreateFileW.restype=wintypes.HANDLE
K.CloseHandle.argtypes=[wintypes.HANDLE];K.CloseHandle.restype=wintypes.BOOL
K.DeviceIoControl.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
K.DeviceIoControl.restype=wintypes.BOOL
K.GetCompressedFileSizeW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(wintypes.DWORD)];K.GetCompressedFileSizeW.restype=wintypes.DWORD
K.FlushFileBuffers.argtypes=[wintypes.HANDLE];K.FlushFileBuffers.restype=wintypes.BOOL
K.GetVolumeInformationW.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(wintypes.DWORD),wintypes.LPWSTR,wintypes.DWORD]

def require(v,m):
    if not v:raise RuntimeError(m)
def now():return datetime.now(timezone.utc).isoformat()
def ordinary(p):
    p=Path(os.path.abspath(p));require(p==ROOT or ROOT in p.parents,'not workspace-owned')
    at=p
    while True:
        z=at.lstat();require(not getattr(z,'st_file_attributes',0)&0x400 and not at.is_symlink(),'reparse path refused')
        if at==ROOT:break
        at=at.parent
    require(p.resolve()==p,'resolved path changed');return p
def allocation(p):
    hi=wintypes.DWORD();ctypes.set_last_error(0);lo=K.GetCompressedFileSizeW(str(p),ctypes.byref(hi))
    require(lo!=0xffffffff or ctypes.get_last_error()==0,'compressed allocation query failed')
    return lo+(hi.value<<32)
def pin(p):
    p=ordinary(p);z=p.stat();require(stat.S_ISREG(z.st_mode) and z.st_nlink==1,'single-link regular file required')
    with p.open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
    a=p.stat();require((z.st_ino,z.st_size,z.st_mtime_ns)==(a.st_ino,a.st_size,a.st_mtime_ns),'input raced')
    return dict(path=str(p),bytes=z.st_size,sha256=h,mtimeNs=z.st_mtime_ns,inode=z.st_ino,nlink=z.st_nlink,
                allocatedBytes=allocation(p),compressed=bool(getattr(z,'st_file_attributes',0)&0x800))
def identity(v):return{k:v[k] for k in ('path','bytes','sha256','mtimeNs','inode','nlink')}
def save_new(p,v):
    raw=(json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
    with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    require(p.read_bytes()==raw,'receipt readback failed');return str(p)
def ntfs():
    fs=ctypes.create_unicode_buffer(64);name=ctypes.create_unicode_buffer(64);serial=wintypes.DWORD();maxlen=wintypes.DWORD();flags=wintypes.DWORD()
    require(K.GetVolumeInformationW('F:\\',name,64,ctypes.byref(serial),ctypes.byref(maxlen),ctypes.byref(flags),fs,64),'volume query failed')
    require(fs.value=='NTFS' and flags.value&0x10,'NTFS file compression unavailable')
def compress(p,want):
    require(identity(pin(p))==identity(want),'reviewed file changed')
    handle=K.CreateFileW(str(p),0x80000000|0x40000000,1,None,3,0,None)
    require(handle!=ctypes.c_void_p(-1).value,'owned file is not exclusively writable')
    try:
        # Share-read only: existing/future writers and path replacement excluded.
        require(identity(pin(p))==identity(want),'file changed before native transform')
        form=ctypes.c_ushort(2);returned=wintypes.DWORD()
        require(K.DeviceIoControl(handle,0x0009c040,ctypes.byref(form),2,None,0,ctypes.byref(returned),None),'FSCTL_SET_COMPRESSION failed')
        require(K.FlushFileBuffers(handle),'native FlushFileBuffers failed')
        after=pin(p);require(identity(after)==identity(want),'compression changed bytes or identity/mtime')
        require(after['compressed'],'NTFS compression attribute absent')
        return dict(before=want,after=after,releasedAllocationBytes=want['allocatedBytes']-after['allocatedBytes'])
    finally:K.CloseHandle(handle)

def control():
    ntfs();FIXTURE.mkdir(exist_ok=True);home=FIXTURE/uuid.uuid4().hex;home.mkdir()
    target=home/'controlled-evidence.json';payload=(b'{"owned_native_control":"preserve exact bytes and timestamps"}\n'*70000)
    with target.open('xb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
    before=pin(target);result=compress(target,before)
    require(result['releasedAllocationBytes']>0,'native control did not release allocation')
    output=DOC/('ntfs-owned-control-'+home.name+'.json')
    save_new(output,dict(protocol='owned-native-ntfs-control-v1',validated=True,source=pin(Path(__file__)),
        observedAtUtc=now(),control=result,modelCalls=0,DockerMutations=0,filesMoved=0,filesDeleted=0))
    print(json.dumps(dict(control=str(output),releasedBytes=result['releasedAllocationBytes'],validated=True)))

def plan():
    ntfs();rows=[];skippedHardlinks=0
    for root in ALLOW:
        if not root.exists():continue
        ordinary(root)
        for parent,dirs,names in os.walk(root,followlinks=False):
            ordinary(parent)
            dirs[:]=[n for n in dirs if not (Path(parent)/n).is_symlink() and not getattr((Path(parent)/n).lstat(),'st_file_attributes',0)&0x400]
            for name in names:
                p=Path(parent)/name
                if p.suffix.lower() not in ('.json','.db','.sqlite') or name=='config.json':continue
                z=p.lstat()
                if not stat.S_ISREG(z.st_mode) or getattr(z,'st_file_attributes',0)&(0x400|0x800) or z.st_size<1024*1024:continue
                if z.st_nlink!=1:skippedHardlinks+=1;continue
                rows.append(pin(p))
    require(sum(r['bytes'] for r in rows)<=MAX,'bounded plan exceeds1GiB')
    output=DOC/('ntfs-owned-plan-'+uuid.uuid4().hex+'.json')
    save_new(output,dict(protocol='owned-native-ntfs-plan-v1',source=pin(Path(__file__)),observedAtUtc=now(),files=rows,
        allowedRoots=list(map(str,ALLOW)),logicalBytes=sum(r['bytes'] for r in rows),
        currentAllocatedBytes=sum(r['allocatedBytes'] for r in rows),skippedHardlinkFiles=skippedHardlinks,
        bytesAndPathsMustStayIdentical=True,productionApply=False,modelCalls=0,filesMoved=0,filesDeleted=0))
    print(json.dumps(dict(plan=str(output),sha256=pin(output)['sha256'],files=len(rows),allocatedBytes=sum(r['allocatedBytes'] for r in rows),skippedHardlinkFiles=skippedHardlinks)))

def apply(path,sha):
    ntfs();require(pin(path)['sha256']==sha,'explicit reviewed plan SHA required');v=json.loads(path.read_bytes())
    require(v['protocol']=='owned-native-ntfs-plan-v1' and identity(pin(Path(__file__)))==identity(v['source']),'plan/source changed')
    rows=v['files'];require(rows and len(rows)<=160 and sum(r['bytes'] for r in rows)<=MAX,'bounded exact file plan required')
    for r in rows:
        p=ordinary(r['path']);require(any(a==p.parent or a in p.parents for a in ALLOW),'not exact evidence scope')
        require(p.suffix.lower() in ('.json','.db','.sqlite') and identity(pin(p))==identity(r),'file plan changed')
    receipt=DOC/('ntfs-owned-apply-'+uuid.uuid4().hex+'.json');done=[]
    try:
        for r in rows:done.append(compress(Path(r['path']),r))
        for r in rows:require(identity(pin(r['path']))==identity(r),'final byte/identity proof changed')
        save_new(receipt,dict(protocol='owned-native-ntfs-apply-v1',validated=True,observedAtUtc=now(),planPin=pin(path),results=done,
            releasedAllocationBytes=sum(x['releasedAllocationBytes'] for x in done),modelCalls=0,filesMoved=0,filesDeleted=0,originalContentChanged=False))
    except BaseException as e:
        save_new(receipt,dict(protocol='owned-native-ntfs-apply-v1',validated=False,observedAtUtc=now(),results=done,error=type(e).__name__+':'+str(e),
            partialTransformsRetained=True,modelCalls=0,filesMoved=0,filesDeleted=0));raise
    print(json.dumps(dict(receipt=str(receipt),sha256=pin(receipt)['sha256'],files=len(done),releasedBytes=sum(x['releasedAllocationBytes'] for x in done))))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['control','plan','apply']);parser.add_argument('--plan',type=Path);parser.add_argument('--sha');args=parser.parse_args()
    if args.mode=='control':control()
    elif args.mode=='plan':plan()
    else:require(args.plan and args.sha,'explicit plan/sha required');apply(args.plan,args.sha)
