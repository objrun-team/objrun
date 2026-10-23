"""Preserve original make commands and real native outcomes in another island."""
import base64,hashlib,json,subprocess
from pathlib import Path
LIMIT=8*1024**2
PATHS=['/opt/syzkaller/sys/linux/dev_ppdev.txt','/opt/syzkaller/sys/linux/dev_ppdev.txt.const']
def pack(body):
    assert type(body) is bytes and len(body)<=LIMIT
    return dict(base64=base64.b64encode(body).decode(),sha256=hashlib.sha256(body).hexdigest())
def unpack(value):
    assert type(value) is dict and set(value)=={'base64','sha256'}
    body=base64.b64decode(value['base64'],validate=True)
    assert len(body)<=LIMIT and hashlib.sha256(body).hexdigest()==value['sha256']
    return body
class Bridge:
    def __init__(self,callback,session):self.callback=callback;self.session=session;self.serial=0;self.original=None
    def run(self,args,*pos,**kwargs):
        assert not pos and args in (['make','descriptions'],['make','generate'],['make','all'])
        assert kwargs['cwd']=='/opt/syzkaller' and kwargs['capture_output'] is True and kwargs['text'] is True
        target=args[1];timeout=600 if target=='all' else 300
        assert kwargs['timeout']==timeout and set(kwargs)==({'cwd','capture_output','text','timeout','env'} if target=='all' else {'cwd','capture_output','text','timeout'})
        if target=='all':assert kwargs['env']['TARGETOS']=='linux' and kwargs['env']['TARGETARCH']=='amd64'
        files={p:pack(Path(p).read_bytes()) for p in PATHS if Path(p).is_file()}
        request=dict(session=self.session,serial=self.serial,target=target,files=files,timeout=timeout)
        response=self.callback(request)
        digest=hashlib.sha256(json.dumps(request,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        assert response['session']==self.session and response['serial']==self.serial and response['requestSha256']==digest
        self.serial+=1
        stdout=unpack(response['stdout']).decode();stderr=unpack(response['stderr']).decode()
        if response.get('exception')=='TimeoutExpired':raise subprocess.TimeoutExpired(args,timeout,stdout,stderr)
        assert response.get('exception') is None and type(response['returncode']) is int
        return subprocess.CompletedProcess(args,response['returncode'],stdout,stderr)
    def __enter__(self):self.original=subprocess.run;subprocess.run=self.run;return self
    def __exit__(self,*error):subprocess.run=self.original;self.original=None
