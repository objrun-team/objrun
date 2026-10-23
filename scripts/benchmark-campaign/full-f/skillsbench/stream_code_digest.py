"""Hash opaque daemon TAR incrementally; never extract or execute its contents."""
import hashlib
import os
import subprocess
import tarfile
import threading
import time

class LimitedReader:
    def __init__(self,stream,limit):self.stream=stream;self.limit=limit;self.count=0;self.digest=hashlib.sha256()
    def read(self,size):
        if size<0 or size>1024**2:raise ValueError('unbounded_tar_read')
        body=self.stream.read(size);self.count+=len(body)
        if self.count>self.limit:raise ValueError('original_storage_stream_limit')
        self.digest.update(body);return body

def digest_tar(stream,maximum_bytes):
    assert isinstance(maximum_bytes,int) and maximum_bytes>0
    # The daemon emits a single fixed-name file; this allowance covers TAR
    # metadata/padding, not additional candidate file bytes.
    reader=LimitedReader(stream,maximum_bytes+1024**2);source=None
    with tarfile.open(fileobj=reader,mode='r|') as archive:
        for member in archive:
            if source is not None or member.name not in ('solution.py','./solution.py') or not member.isfile():raise ValueError('code_tar_scope_or_type')
            if not 0<=member.size<=maximum_bytes:raise ValueError('original_storage_source_limit')
            file=archive.extractfile(member);digest=hashlib.sha256();count=0
            while True:
                chunk=file.read(65536)
                if not chunk:break
                count+=len(chunk);digest.update(chunk)
            if count!=member.size:raise ValueError('code_tar_truncated')
            source={'sourceBytes':count,'sourceSha256':digest.hexdigest()}
    # Consume the daemon's remaining padding and bind its entire stream.
    while reader.read(65536):pass
    if source is None:raise ValueError('code_tar_missing')
    return {**source,'streamBytes':reader.count,'streamSha256':reader.digest.hexdigest()}

def capture(argv,env,stderr_path,timeout,maximum_bytes):
    began=time.monotonic();child=subprocess.Popen(argv,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL)
    faults=[];stderr_bytes=0;digest=None;parse_error=None
    def kill(reason):
        faults.append(reason)
        if child.poll() is None:child.kill()
    def stderr_reader():
        nonlocal stderr_bytes
        try:
            with stderr_path.open('xb') as file:
                while True:
                    chunk=child.stderr.read(65536)
                    if not chunk:break
                    room=max(0,1024**2-stderr_bytes);file.write(chunk[:room]);stderr_bytes+=min(room,len(chunk))
                    if len(chunk)>room:kill('stderr_limit');break
                file.flush();os.fsync(file.fileno())
        except Exception as error:kill('stderr_'+type(error).__name__)
        finally:child.stderr.close()
    thread=threading.Thread(target=stderr_reader,daemon=True);thread.start()
    timer=threading.Timer(timeout,lambda:kill('timeout'));timer.daemon=True;timer.start()
    try:
        try:digest=digest_tar(child.stdout,maximum_bytes)
        except Exception as error:
            parse_error={'type':type(error).__name__,'detail':str(error)}
            # EOF before a TAR header may be the daemon's exact absent-file
            # diagnostic; do not misclassify its nonzero exit as a parse fault.
            if not isinstance(error,tarfile.ReadError):kill('source_'+type(error).__name__)
        code=child.wait(timeout=max(1,timeout-(time.monotonic()-began)))
    except subprocess.TimeoutExpired:kill('timeout');code=child.wait(timeout=30)
    finally:
        timer.cancel();child.stdout.close();thread.join(timeout=5)
    if thread.is_alive():faults.append('stderr_reader_unclosed')
    return {'pid':child.pid,'exitCode':code,'faults':faults,'stderrBytes':stderr_bytes,'sourceDigest':digest,'parseError':parse_error,
        'originalStorageBytes':maximum_bytes,'elapsedSeconds':time.monotonic()-began,'directChildClosed':child.poll() is not None,'pipeReadersClosed':not thread.is_alive()}
