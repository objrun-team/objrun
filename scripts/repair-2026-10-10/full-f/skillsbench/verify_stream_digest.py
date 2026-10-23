"""Local stream boundary/deadline controls; no model or private grader."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import uuid
from prepare import HOME,public,save
import stream_code_digest as digest

def main():
    home=HOME/'stream-digest-controls'/uuid.uuid4().hex;home.mkdir(parents=True);cases=[]
    body=b'# opaque source padding\n'*65536
    def archive(name='solution.py',kind=tarfile.REGTYPE,duplicate=False):
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w') as tar:
            member=tarfile.TarInfo(name);member.type=kind;member.size=len(body) if kind==tarfile.REGTYPE else 0
            tar.addfile(member,io.BytesIO(body) if member.size else None)
            if duplicate:tar.addfile(member,io.BytesIO(body))
        return out.getvalue()
    raw=archive();value=digest.digest_tar(io.BytesIO(raw),10*1024**3)
    assert value['sourceBytes']==len(body)>512*1024 and value['sourceSha256']==hashlib.sha256(body).hexdigest()
    assert value['streamSha256']==hashlib.sha256(raw).hexdigest();cases.append('opaque_source_above_old_limit_and_full_stream_binding')
    for name,data,limit in [('traversal',archive('../solution.py'),10*1024**3),('foreign',archive('helper.py'),10*1024**3),
        ('symlink',archive(kind=tarfile.SYMTYPE),10*1024**3),('hardlink',archive(kind=tarfile.LNKTYPE),10*1024**3),
        ('duplicate',archive(duplicate=True),10*1024**3),('original_storage_limit',raw,512*1024),('truncated',raw[:1024],10*1024**3)]:
        try:digest.digest_tar(io.BytesIO(data),limit)
        except (ValueError,tarfile.TarError):cases.append(name)
        else:raise AssertionError('unrejected_'+name)
    result=digest.capture([sys.executable,'-B','-c','import time; time.sleep(30)'],None,home/'timeout.stderr',.25,10*1024**3)
    assert 'timeout' in result['faults'] and result['directChildClosed'] and result['pipeReadersClosed'];cases.append('blocked_stream_deadline_and_closed_child')
    save(home/'timeout.json',result,True)
    proof={'protocol':'skillsbench-stream-digest-local-controls-v1','verified':True,'cases':cases,'modelCalls':0,'realGraderExecuted':False,
        'scoreCertificate':False,'sourcePins':[public.pin(Path(digest.__file__)),public.pin(Path(__file__))]}
    pin=save(home/'result.json',proof,True);save(HOME/'stream-digest-controls/latest.json',{'resultPin':pin});print(json.dumps({'resultPin':pin,'verified':True,'cases':len(cases)}))

if __name__=='__main__':main()
