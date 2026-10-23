"""Bound raw child output before it reaches host disk or an in-memory TAR."""
import os
import subprocess
import threading

class OutputLimit(RuntimeError):pass

def run(argv,env,stdout_path,stderr_path,timeout,stdin_body=None,stdout_limit=16*1024**2,stderr_limit=1024**2):
    child=subprocess.Popen(argv,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.PIPE if stdin_body is not None else subprocess.DEVNULL)
    faults=[];sizes={'stdout':0,'stderr':0}
    def reader(stream,path,name,limit):
        try:
            with path.open('xb') as file:
                while True:
                    chunk=stream.read(65536)
                    if not chunk:break
                    room=max(0,limit-sizes[name])
                    if room:file.write(chunk[:room]);sizes[name]+=min(room,len(chunk))
                    if len(chunk)>room:
                        faults.append(name+'_limit');child.kill();break
                file.flush();os.fsync(file.fileno())
        except Exception as error:
            faults.append(name+'_'+type(error).__name__)
            if child.poll() is None:child.kill()
        finally:stream.close()
    threads=[threading.Thread(target=reader,args=(child.stdout,stdout_path,'stdout',stdout_limit),daemon=True),
             threading.Thread(target=reader,args=(child.stderr,stderr_path,'stderr',stderr_limit),daemon=True)]
    for thread in threads:thread.start()
    writer=None
    if stdin_body is not None:
        def write_input():
            try:child.stdin.write(stdin_body);child.stdin.close()
            except (BrokenPipeError,OSError):faults.append('stdin_closed')
        writer=threading.Thread(target=write_input,daemon=True);writer.start()
    try:
        try:code=child.wait(timeout=timeout)
        except subprocess.TimeoutExpired: faults.append('timeout');child.kill();code=child.wait(timeout=30)
    finally:
        for thread in threads:thread.join(timeout=5)
        if writer:writer.join(timeout=5)
    if any(thread.is_alive() for thread in threads):faults.append('pipe_reader_unclosed')
    if writer and writer.is_alive():faults.append('stdin_writer_unclosed')
    return {'pid':child.pid,'exitCode':code,'faults':faults,'stdoutBytes':sizes['stdout'],'stderrBytes':sizes['stderr'],
            'directChildClosed':child.poll() is not None,'pipeReadersClosed':not any(thread.is_alive() for thread in threads)}
