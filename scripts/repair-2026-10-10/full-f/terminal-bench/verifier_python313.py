"""Staged interpreter-only transfer. No private tests or host archive extraction."""
import io,json,posixpath,re,tarfile
from pathlib import Path

def validate_runtime_archive(raw):
    if not raw or len(raw)>512*1024**2:raise ValueError('Interpreter archive bounds')
    count=0;total=0
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
        for member in archive:
            name=member.name.rstrip('/')
            if name.startswith('/') or posixpath.normpath(name)!=name or not(name=='tb-verifier-python' or name.startswith('tb-verifier-python/')):raise ValueError('Interpreter member path')
            count+=1;total+=member.size
            if count>30000 or total>512*1024**2:raise ValueError('Interpreter tree bounds')
            if member.isfile() or member.isdir():continue
            if member.issym():
                target=posixpath.normpath(posixpath.join(posixpath.dirname(name),member.linkname))
                if member.linkname.startswith('/') or not target.startswith('tb-verifier-python/'):raise ValueError('Interpreter link escape')
                continue
            raise ValueError('Interpreter special member')
    return {'members':count,'uncompressedBytes':total,'hostExtraction':False}

def prepare_runtime_transfer(native,proof_path,deadline):
    import time,hashlib
    if deadline<=time.monotonic():raise TimeoutError('Official verifier deadline exhausted before interpreter transfer')
    proof=json.loads(Path(proof_path).read_bytes())
    assert proof['complete'] and proof['actualDependencyBuildValidated'] and proof['officialPythonSelector']=='3.13'
    cid,initial,create=native.create('verifier-python313-source',proof['imageId'],'/bin/sh',['-c','exit 0'],network='none',readonly=True)
    try:
        remaining=deadline-time.monotonic();assert remaining>0
        path_receipt=native.checked(['cp',cid+':/opt/tb-verifier-python-path.txt','-'],timeout=remaining,stdout_limit=1024**2)
        with tarfile.open(fileobj=io.BytesIO(Path(path_receipt['stdout']['path']).read_bytes()),mode='r:') as archive:
            members=archive.getmembers();assert len(members)==1 and members[0].isfile() and members[0].size<4096
            interpreter=archive.extractfile(members[0]).read().decode('utf-8').strip()
        assert re.fullmatch(r'/opt/tb-verifier-python/cpython-3\.13\.\d+-linux-x86_64-gnu/bin/python3\.13',interpreter)
        remaining=deadline-time.monotonic();assert remaining>0
        receipt=native.checked(['cp',cid+':/opt/tb-verifier-python','-'],timeout=remaining,stdout_limit=512*1024**2)
        raw=Path(receipt['stdout']['path']).read_bytes();bounds=validate_runtime_archive(raw)
        removal,absence=native.remove(cid)
        return {'raw':raw,'interpreterDirectory':posixpath.dirname(interpreter),'proofPath':str(proof_path),
            'receipt':receipt,'pathReceipt':path_receipt,'archiveSha256':hashlib.sha256(raw).hexdigest(),'bounds':bounds,
            'sourceCreate':create,'sourceInitial':initial,'removal':removal,'absence':absence,'privateTestSourcesSupplied':0}
    except BaseException:
        native.remove(cid);raise

def install_runtime_transfer(native,worker,transfer,deadline):
    import time
    initial=native.assert_actor(worker);assert initial['State']['Status']=='created' and not initial['State']['Running']
    assert not initial['Mounts'],'Worker must not expose host or shared mounts'
    remaining=deadline-time.monotonic();assert remaining>0
    return native.checked(['cp','-',worker+':/opt'],stdin=transfer['raw'],timeout=remaining)
