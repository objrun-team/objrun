"""Exact Caffe commands in an untrusted snapshot; private assertions stay out."""
from pathlib import Path
import time

BINARIES=("/app/caffe/.build_release/tools/caffe.bin", "/app/caffe/build/tools/caffe")

def caffe_commands(binary):
    assert binary in BINARIES
    return [([binary,"--version"],None),
            ([binary,"test","-model","/app/caffe/examples/cifar10/cifar10_quick_train_test.prototxt",
              "-weights","/app/caffe/examples/cifar10/cifar10_quick_iter_500.caffemodel","-iterations","100"],"/app/caffe")]

def caffe_worker(native,candidate,task,capsule,deadline=None):
    binary=next((path for path in BINARIES if any(f['path']==path and f['exists'] for f in capsule['files'])),None)
    if binary is None:return {'protocol':'terminal-caffe-worker-data-v1','rows':[]},[]
    source=native.assert_actor(candidate);assert source['State']['Paused']
    image,commit=native.commit(candidate,'untrusted-caffe-worker')
    deadline=deadline if deadline is not None else time.monotonic()+task['verifierSeconds'];rows=[];receipts=[]
    for index,(argv,cwd) in enumerate(caffe_commands(binary)):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Official verifier budget exhausted in Caffe worker')
        # Shell and program run only in the untrusted island. No checker/test
        # files, host mounts, broker credentials, or result assertions go there.
        executable=argv[0];arguments=argv[1:]
        if cwd:
            executable='/bin/sh';arguments=['-c','cd /app/caffe && exec "$@"','worker',*argv]
        cid,initial,create=native.create('untrusted-caffe-'+str(index),image,executable,arguments,
            network='none',memory_mb=task['officialEnvironment']['memory_mb'],cpus=task['officialEnvironment']['cpus'])
        start=native.command(['start','-a',cid],timeout=remaining,stdout_limit=2*1024**2)
        final=native.assert_actor(cid);assert final['State']['Status']=='exited'
        stdout=Path(start['stdout']['path']).read_bytes().decode('utf-8')
        stderr=Path(start['stderr']['path']).read_bytes().decode('utf-8')
        removal,absence=native.remove(cid)
        rows.append({'argv':argv,'cwd':cwd,'exitCode':final['State']['ExitCode'],'stdout':stdout,'stderr':stderr})
        receipts.append({'cid':cid,'initial':initial,'create':create,'start':start,'final':final,
                         'removal':removal,'absence':absence,'sourceState':source,'snapshot':image,'commit':commit})
    return {'protocol':'terminal-caffe-worker-data-v1','rows':rows},receipts
