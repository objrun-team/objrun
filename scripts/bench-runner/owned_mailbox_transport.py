"""Read/write private checker tmpfs through its process namespace, without Docker archive copies."""
import base64, hashlib, json, math, re
from pathlib import Path
LIMIT=1024**3
READ_CODE=r'''
import base64,hashlib,json,os,re,stat,sys
from pathlib import Path
name,root=sys.argv[1:3];assert re.fullmatch(r'[0-9]+-1\.request\.json',name)
root=Path(root);assert not root.is_symlink();path=root/name;limit=1024**3
try:
 info=path.lstat()
 assert stat.S_ISREG(info.st_mode) and info.st_size<=limit,'bounded regular mailbox file required'
 fd=os.open(path,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0))
 with os.fdopen(fd,'rb') as f:
  before=os.fstat(f.fileno());assert (before.st_dev,before.st_ino)==(info.st_dev,info.st_ino),'mailbox identity changed before open'
  raw=f.read(limit+1);after=os.fstat(f.fileno())
 assert len(raw)<=limit and len(raw)==before.st_size,'mailbox data bound/size mismatch'
 assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'mailbox changed during read'
 value=json.loads(raw);assert value['id']==name[:-len('.request.json')] and value['operation']=='pipeline','mailbox identity/operation mismatch'
 result={'protocol':'pipeline-mailbox-namespace-read-v1','status':'ok','name':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'rawBase64':base64.b64encode(raw).decode()}
except FileNotFoundError:
 result={'protocol':'pipeline-mailbox-namespace-read-v1','status':'missing','name':name,'errno':'ENOENT'}
print(json.dumps(result,separators=(',',':')))
'''
WRITE_CODE=r'''
import hashlib,json,os,re,sys,uuid
from pathlib import Path
name,root=sys.argv[1:3];assert re.fullmatch(r'[0-9]+-1\.response\.json',name)
root=Path(root);assert root.is_dir() and not root.is_symlink();limit=1024**3
raw=sys.stdin.buffer.read(limit+1);assert len(raw)<=limit,'mailbox message exceeds transport limit'
value=json.loads(raw);assert value['id']==name[:-len('.response.json')] and ('error' in value or 'value' in value),'response identity/shape mismatch'
path=root/name;temp=root/(name+'.transport-'+uuid.uuid4().hex+'.new')
try:
 with temp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 os.replace(temp,path)
 assert not path.is_symlink() and path.read_bytes()==raw,'atomic response readback mismatch'
 print(json.dumps({'protocol':'pipeline-mailbox-namespace-write-v1','status':'ok','name':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},separators=(',',':')))
finally:
 if temp.exists():temp.unlink()
'''
def _timeout(remain):
    remaining=remain()
    if remaining<=0:raise TimeoutError('Original verifier deadline exhausted')
    return max(.001,min(60,remaining))
def _frame(receipt,native):
    if receipt['exitCode']!=0:raise RuntimeError('Private mailbox namespace command failed: '+str(receipt['index']))
    assert receipt['closeObserved'] and not receipt.get('timedOut') and not receipt.get('overflow') and not receipt.get('captureFaults')
    return json.loads(native.text(receipt))
def _owned_terminal_race(receipt,native,checker):
    # Only the daemon's exact not-running response can be a terminal lifecycle race.
    if receipt['exitCode']!=1:return False
    assert receipt['closeObserved'] and not receipt.get('timedOut') and not receipt.get('overflow') and not receipt.get('captureFaults')
    if Path(receipt['stdout']['path']).read_bytes():return False
    error=Path(receipt['stderr']['path']).read_text(encoding='utf8').strip()
    if error!='Error response from daemon: container '+checker+' is not running':return False
    actual=native.assert_actor(checker)
    if actual['State']['Running'] or actual['State']['Status']!='exited':return False
    receipt['mailboxTerminalObservation']={'protocol':'bench-owned-mailbox-terminal-race-v1','status':'checker-exited-before-mailbox-operation','actualOwnedState':actual,'originalNativeFailurePreserved':True,'noReplyFabricated':True,'requiresOriginalFinalFrame':True}
    path=native.directory/'mailbox-lifecycle';path.mkdir(exist_ok=True)
    (path/('command-'+str(receipt['index'])+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    return True

def capture_request(native,checker,name,output,remain):
    assert re.fullmatch(r'[0-9]+-1\.request\.json',name)
    receipt=native.command(['exec',checker,'/opt/checker/bin/python','-c',READ_CODE,name,'/tmp/pipeline-mailbox'],timeout=_timeout(remain),stdout_limit=4*((LIMIT+2)//3)+8192)
    if _owned_terminal_race(receipt,native,checker):return None,receipt
    frame=_frame(receipt,native)
    assert frame['protocol']=='pipeline-mailbox-namespace-read-v1' and frame['name']==name
    if frame['status']=='missing':
        assert frame['errno']=='ENOENT'
        return None,receipt
    assert frame['status']=='ok'
    raw=base64.b64decode(frame['rawBase64'],validate=True)
    assert len(raw)==frame['bytes'] and len(raw)<=LIMIT and hashlib.sha256(raw).hexdigest()==frame['sha256']
    request=json.loads(raw);assert request['id']==name[:-len('.request.json')] and request['operation']=='pipeline'
    path=Path(output)/name
    if path.exists():assert not path.is_symlink() and path.read_bytes()==raw
    else:
        with path.open('xb') as f:f.write(raw)
    remain()
    return request,receipt
def deliver_response(native,checker,name,response,remain):
    assert re.fullmatch(r'[0-9]+-1\.response\.json',name)
    raw=json.dumps(response,separators=(',',':'),allow_nan=False).encode()
    assert len(raw)<=LIMIT and response['id']==name[:-len('.response.json')]
    receipt=native.command(['exec','-i',checker,'/opt/checker/bin/python','-c',WRITE_CODE,name,'/tmp/pipeline-mailbox'],timeout=_timeout(remain),stdout_limit=8192,stdin=raw)
    if _owned_terminal_race(receipt,native,checker):return receipt
    frame=_frame(receipt,native)
    assert frame['protocol']=='pipeline-mailbox-namespace-write-v1' and frame['status']=='ok' and frame['name']==name and frame['bytes']==len(raw) and frame['sha256']==hashlib.sha256(raw).hexdigest()
    remain()
    return receipt
