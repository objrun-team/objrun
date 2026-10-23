"""Exact same-file NTFS transform for closed fixtures, preserving every link.

No links created/replaced/removed. Every current link name must be an ordinary
path in the exact owned fixture root. The v1 single-link worker is unchanged.
"""
import argparse,ctypes,hashlib,importlib.util,json,os,stat,uuid
from ctypes import wintypes
from pathlib import Path
BASE_PATH=Path(__file__).with_name('owned-evidence-ntfs-compression.py')
require=lambda v,m:None if v else (_ for _ in ()).throw(RuntimeError(m))
require(hashlib.sha256(BASE_PATH.read_bytes()).hexdigest()=='ee94d7290b98adb61a6f2914c244a6099bcbbb52f512d83b1e9cfdabb52c7d24','fixed v1 source changed')
spec=importlib.util.spec_from_file_location('ntfs_single_link_base',BASE_PATH);b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
CASE=b.ROOT/'.scratch/paid-resource-admission-v2'
CONTROL=b.ROOT/'.scratch/ntfs-hardlink-owned-controls'
K=b.K
K.FindFirstFileNameW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),wintypes.LPWSTR];K.FindFirstFileNameW.restype=wintypes.HANDLE
K.FindNextFileNameW.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD),wintypes.LPWSTR];K.FindNextFileNameW.restype=wintypes.BOOL
K.FindClose.argtypes=[wintypes.HANDLE];K.FindClose.restype=wintypes.BOOL

def names(p):
    size=wintypes.DWORD(32768);buffer=ctypes.create_unicode_buffer(32768);ctypes.set_last_error(0)
    h=K.FindFirstFileNameW(str(p),0,ctypes.byref(size),buffer)
    require(h!=ctypes.c_void_p(-1).value,'all native link names unavailable')
    rows=[]
    try:
        while True:
            require(buffer.value.startswith('\\') and ':' not in buffer.value,'unexpected native link name')
            rows.append(str(Path(p.drive+buffer.value)))
            require(len(rows)<=512,'link group exceeds bounded review')
            size.value=32768;ctypes.set_last_error(0)
            if not K.FindNextFileNameW(h,ctypes.byref(size),buffer):
                require(ctypes.get_last_error()==38,'native link enumeration incomplete');break
    finally:K.FindClose(h)
    require(len(rows)==len(set(rows)),'duplicate link names')
    return sorted(rows)

def group(p,scope):
    p=b.ordinary(p);scope=b.ordinary(scope);z=p.stat()
    require(stat.S_ISREG(z.st_mode) and 2<=z.st_nlink<=512,'a bounded shared ordinary file is required')
    links=names(p);require(len(links)==z.st_nlink,'link count/list mismatch')
    for path in links:
        q=b.ordinary(path);require(scope in q.parents,'a link escapes exact owned closed fixture root')
        a=q.stat();require(stat.S_ISREG(a.st_mode) and (a.st_ino,a.st_dev,a.st_size,a.st_mtime_ns,a.st_nlink)==(z.st_ino,z.st_dev,z.st_size,z.st_mtime_ns,z.st_nlink),'native links are not the same exact file')
    with p.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    require((p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_nlink)==(z.st_ino,z.st_size,z.st_mtime_ns,z.st_nlink),'shared source raced')
    return dict(path=str(p),bytes=z.st_size,sha256=sha,mtimeNs=z.st_mtime_ns,inode=z.st_ino,nlink=z.st_nlink,
        linkPaths=links,allocatedBytes=b.allocation(p),compressed=bool(getattr(z,'st_file_attributes',0)&0x800))
def identity(v):return{k:v[k] for k in ('path','bytes','sha256','mtimeNs','inode','nlink','linkPaths')}
def transform(p,want,scope):
    require(identity(group(p,scope))==identity(want),'reviewed group changed')
    h=K.CreateFileW(str(p),0x80000000|0x40000000,1,None,3,0,None)
    require(h!=ctypes.c_void_p(-1).value,'shared fixture cannot be exclusively written')
    try:
        require(identity(group(p,scope))==identity(want),'group changed before transform')
        form=ctypes.c_ushort(2);returned=wintypes.DWORD()
        require(K.DeviceIoControl(h,0x0009c040,ctypes.byref(form),2,None,0,ctypes.byref(returned),None),'native fixture compression failed')
        require(K.FlushFileBuffers(h),'native fixture flush failed')
        after=group(p,scope);require(identity(after)==identity(want) and after['compressed'],'compression changed any original byte/path/link identity/mtime')
        return dict(before=want,after=after,releasedBytes=want['allocatedBytes']-after['allocatedBytes'])
    finally:K.CloseHandle(h)

def control():
    b.ntfs();CONTROL.mkdir(exist_ok=True);home=CONTROL/uuid.uuid4().hex;home.mkdir();p=home/'first.json';q=home/'second.json'
    with p.open('xb') as f:f.write(b'owned shared fixture preserves both names\n'*70000);f.flush();os.fsync(f.fileno())
    os.link(p,q)
    before=group(p,home);result=transform(p,before,home);require(result['releasedBytes']>0,'shared fixture saved no allocation')
    output=b.DOC/('ntfs-hardlink-control-'+home.name+'.json')
    b.save_new(output,dict(protocol='owned-shared-fixture-ntfs-control-v1',validated=True,source=b.pin(Path(__file__)),baseSource=b.pin(BASE_PATH),
        observedAtUtc=b.now(),result=result,productionApply=False,modelCalls=0,originalFilesDeleted=0,originalLinksModified=0))
    print(json.dumps(dict(control=str(output),sha256=b.pin(output)['sha256'],releasedBytes=result['releasedBytes'],validated=True)))
def plan():
    b.ntfs();b.ordinary(CASE);rows=[];seen=set();escaped=0
    for parent,dirs,files in os.walk(CASE,followlinks=False):
        b.ordinary(parent);dirs[:]=[n for n in dirs if not getattr((Path(parent)/n).lstat(),'st_file_attributes',0)&0x400]
        for n in files:
            p=Path(parent)/n;z=p.lstat()
            if p.suffix!='.json' or not stat.S_ISREG(z.st_mode) or z.st_size<1024**2 or z.st_nlink<2 or getattr(z,'st_file_attributes',0)&(0x400|0x800):continue
            key=(z.st_dev,z.st_ino)
            if key in seen:continue
            seen.add(key)
            try:rows.append(group(p,CASE))
            except RuntimeError:escaped+=1
    require(rows and len(rows)<=80 and sum(r['bytes'] for r in rows)<=1024**3,'bounded shared fixture plan required')
    output=b.DOC/('ntfs-hardlink-plan-'+uuid.uuid4().hex+'.json')
    b.save_new(output,dict(protocol='owned-shared-fixture-ntfs-plan-v1',source=b.pin(Path(__file__)),baseSource=b.pin(BASE_PATH),
        observedAtUtc=b.now(),exactFixtureRoot=str(CASE),groups=rows,uniqueBytes=sum(r['bytes'] for r in rows),
        uniqueAllocatedBytes=sum(r['allocatedBytes'] for r in rows),excludedInvalidOrEscapedGroups=escaped,
        productionApply=False,modelCalls=0,originalFilesDeleted=0,originalLinksModified=0))
    print(json.dumps(dict(plan=str(output),sha256=b.pin(output)['sha256'],groups=len(rows),allocatedBytes=sum(r['allocatedBytes'] for r in rows),excluded=escaped)))
def apply(path,sha):
    b.ntfs();require(b.pin(path)['sha256']==sha,'explicit reviewed plan required');v=json.loads(path.read_bytes())
    require(v['protocol']=='owned-shared-fixture-ntfs-plan-v1' and b.identity(b.pin(Path(__file__)))==b.identity(v['source']) and b.identity(b.pin(BASE_PATH))==b.identity(v['baseSource']) and v['exactFixtureRoot']==str(CASE),'source/plan scope changed')
    rows=v['groups'];require(rows and len(rows)<=80 and sum(r['bytes'] for r in rows)<=1024**3,'shared batch exceeds reviewed bound')
    require(len(set(r['inode'] for r in rows))==len(rows),'duplicate shared file charge')
    for r in rows:require(identity(group(r['path'],CASE))==identity(r),'reviewed current shared group changed')
    output=b.DOC/('ntfs-hardlink-apply-'+uuid.uuid4().hex+'.json');done=[]
    try:
        for r in rows:done.append(transform(Path(r['path']),r,CASE))
        for r in rows:require(identity(group(r['path'],CASE))==identity(r),'final shared identity changed')
        b.save_new(output,dict(protocol='owned-shared-fixture-ntfs-apply-v1',validated=True,observedAtUtc=b.now(),planPin=b.pin(path),results=done,
            releasedBytes=sum(r['releasedBytes'] for r in done),modelCalls=0,originalFilesDeleted=0,originalLinksModified=0,contentChanged=False))
    except BaseException as e:
        b.save_new(output,dict(protocol='owned-shared-fixture-ntfs-apply-v1',validated=False,results=done,error=type(e).__name__+':'+str(e),partialCompressionAttributesRetained=True,originalLinksModified=0));raise
    print(json.dumps(dict(receipt=str(output),sha256=b.pin(output)['sha256'],groups=len(done),releasedBytes=sum(r['releasedBytes'] for r in done))))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['control','plan','apply']);p.add_argument('--plan',type=Path);p.add_argument('--sha');a=p.parse_args()
    if a.mode=='control':control()
    elif a.mode=='plan':plan()
    else:require(a.plan and a.sha,'explicit shared plan/sha required');apply(a.plan,a.sha)
