"""Original subprocess.run callback; Suricata executes in a separate sandbox.
No rule filtering, private child execution, or candidate config is accepted.
"""
import base64, hashlib, subprocess
from pathlib import Path
LIMIT=8*1024**2
def pack(body):
    assert type(body) is bytes and len(body)<=LIMIT
    return {'base64':base64.b64encode(body).decode(),'sha256':hashlib.sha256(body).hexdigest()}
def unpack(value):
    assert type(value) is dict and set(value)=={'base64','sha256'}
    assert type(value['base64']) is str and len(value['base64'])<=(LIMIT+2)//3*4
    body=base64.b64decode(value['base64'],validate=True)
    assert len(body)<=LIMIT and hashlib.sha256(body).hexdigest()==value['sha256']
    return body
class Bridge:
    def __init__(self,callback,session):
        assert type(session) is str and session.isalnum() and len(session)<=128
        self.callback=callback;self.session=session;self.serial=0;self.original=None
    def run(self,args,*pos,**kwargs):
        assert not pos and kwargs=={'capture_output':True,'text':True,'timeout':180}
        assert type(args) is list and len(args)==13
        assert args[:7]==['suricata','--runmode','single','-c','/root/suricata.yaml','-S','/root/local.rules']
        assert args[7:10]==['-k','none','-r'] and args[11]=='-l'
        pcap=Path(args[10]);log=Path(args[12])
        assert pcap.is_file() and not pcap.is_symlink()
        assert log.is_dir() and not log.is_symlink()
        rules=Path('/root/local.rules')
        assert rules.is_file() and not rules.is_symlink()
        request={'session':self.session,'serial':self.serial,'pcap':pack(pcap.read_bytes()),'rules':pack(rules.read_bytes()),'timeout':180}
        response=self.callback(request)
        assert type(response) is dict and set(response)=={'session','serial','requestSha256','returncode','stdout','stderr','eve'}
        from json import dumps
        digest=hashlib.sha256(dumps(request,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        assert response['session']==self.session and type(response['serial']) is int and response['serial']==self.serial and response['requestSha256']==digest
        assert type(response['returncode']) is int
        stdout=unpack(response['stdout']).decode();stderr=unpack(response['stderr']).decode()
        eve=unpack(response['eve']) if response['eve'] is not None else None
        target=log/'eve.json';assert not target.is_symlink()
        if eve is None:target.unlink(missing_ok=True)
        else:target.write_bytes(eve)
        self.serial+=1
        return subprocess.CompletedProcess(args,response['returncode'],stdout,stderr)
    def __enter__(self):
        assert self.original is None
        self.original=subprocess.run;subprocess.run=self.run;return self
    def __exit__(self,*error):
        subprocess.run=self.original;self.original=None
