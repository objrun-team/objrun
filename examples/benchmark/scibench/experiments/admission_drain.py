"""Drain a legacy controller without editing its sources or interrupting its work.

An explicit pre-start filesystem fence stops admission. A ptrace signal guard
suppresses the legacy finally block's premature SIGTERM to its own grader.
The grader is released only after all starts are terminal and calls receipted.
No model calls, task recovery, clock changes, or process-memory writes occur.
"""
from pathlib import Path
import argparse
import ctypes
import errno
import hashlib
import json
import os
import signal
import threading
import time

ap=argparse.ArgumentParser()
ap.add_argument('--root',type=Path,required=True)
ap.add_argument('--fixture',action='store_true')
args=ap.parse_args()
root=args.root.resolve();out=root/'outputs/canonical';ops=root/'ops/switch32'
if args.fixture:
    assert root.name.startswith('drain-fixture-') and 'scibench-switch32-lab-' in str(root)
else:
    assert str(root)=='/mnt/aliyunsb/pingxingwang/tgengin-bench/scibench-formal-20261016-v1'
ops.mkdir(parents=True,exist_ok=True)
assert not (ops/'guard.json').exists(),'ExistingGuardInspectFirst'
read=lambda p:json.loads(p.read_text())
def save(p,v):
    t=p.with_suffix('.'+str(os.getpid())+'.tmp');t.write_text(json.dumps(v,indent=2)+'\n');t.replace(p)
def event(name,**kw):
    with (ops/'events.jsonl').open('a') as f:
        f.write(json.dumps({'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'event':name,**kw})+'\n');f.flush();os.fsync(f.fileno())
def proc(pid):
    p=Path('/proc')/str(pid)
    try:
        cmd=p.joinpath('cmdline').read_bytes().replace(b'\0',b' ').decode()
        st=dict(x.split(':',1) for x in p.joinpath('status').read_text().splitlines() if ':' in x)
        return {'live':bool(cmd),'cmdline':cmd,'ppid':int(st['PPid']),'tracer':int(st['TracerPid'])}
    except FileNotFoundError:return {'live':False}
status=read(out/'status.json');pid=status['pid'];launch=read(out/'launch.json')
grader=read(out/'grader-process.json')['pid']
assert launch['pid']==pid and launch['root']==str(root)
assert str(root/'package/run.ts') in proc(pid)['cmdline']
assert str(root/'package/stand.py') in proc(grader)['cmdline'] and proc(grader)['ppid']==pid
assert proc(grader)['tracer']==0
cfg=read(root/'package/experiment.json');catalog=read(root/'data'/cfg['catalog'])
jobs=[(cfg['arms'][(i+j)%len(cfg['arms'])],t['id']) for i,t in enumerate(catalog[1:]) for j in range(len(cfg['arms']))]
pins=read(out/'source-pins.json')['files']
def verify_pins():
    assert all(hashlib.sha256(Path(x['path']).read_bytes()).hexdigest()==x['sha256'] for x in pins),'SourcePinMismatch'
verify_pins()
libc=ctypes.CDLL(None,use_errno=True)
libc.ptrace.restype=ctypes.c_long
def ptrace(request,tid,addr=0,data=0):
    ctypes.set_errno(0)
    v=libc.ptrace(ctypes.c_uint(request),ctypes.c_int(tid),ctypes.c_void_p(addr),ctypes.c_void_p(data))
    if v==-1:
        e=ctypes.get_errno();raise OSError(e,os.strerror(e))
    return v
SEIZE=0x4206;CONT=7;GETSIGINFO=0x4202;GETEVENTMSG=0x4201
TRACECLONE=8;TRACEEXIT=64;WALL=0x40000000
attached=set();ready=threading.Event();kill_seen=threading.Event();finished=threading.Event()
allow_shutdown=threading.Event();failure=[];state={};fence=None
for _ in range(3):
    for t in (Path('/proc')/str(grader)/'task').iterdir():
        tid=int(t.name)
        if tid in attached:continue
        try:ptrace(SEIZE,tid,0,TRACECLONE|TRACEEXIT);attached.add(tid)
        except OSError as e:
            if e.errno==errno.ESRCH:continue
            if e.errno==errno.EPERM and proc(tid).get('tracer')==os.getpid():attached.add(tid)
            else:raise
    time.sleep(.01)
assert grader in attached
state={'pid':os.getpid(),'controllerPid':pid,'graderPid':grader,'phase':'guard_ready','fixture':args.fixture,'root':str(root)}
save(ops/'guard.json',state);event('guard_ready',tids=sorted(attached))
ready.set()

def monitor():
    global fence
    try:
        # The fixture uses the original controller and must exercise a drain
        # with several live jobs, rather than its initial all-arm canary.
        if args.fixture:
            until=time.monotonic()+15
            while True:
                snapshot=read(out/'status.json')
                if snapshot['stage']=='running' and len(snapshot['active'])==4:break
                assert time.monotonic()<until,'FixtureDidNotReachRunning';time.sleep(.005)
        for arm,tid in jobs:
            d=out/'tasks'/arm/tid
            if (out/'results'/arm/(tid+'.json')).exists() or d.exists():continue
            d.parent.mkdir(parents=True,exist_ok=True)
            marker={'type':'operational_admission_fence','arm':arm,'id':tid,'guardPid':os.getpid(),'notATaskStart':True}
            try:
                fd=os.open(d,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            except FileExistsError:continue
            with os.fdopen(fd,'w') as f:f.write(json.dumps(marker)+'\n');f.flush();os.fsync(f.fileno())
            fence=d;save(ops/'fence.json',{**marker,'path':str(d)})
            event('admission_fenced',identity=arm+'/'+tid,path=str(d));break
        assert fence is not None,'NoUnstartedAdmissionAvailable'
        state.update(phase='draining',fence=str(fence));save(ops/'guard.json',state)
        stable=None;until=time.monotonic()+900
        while True:
            s=read(out/'status.json')
            records=list((out/'results').rglob('*.json'))
            pending=[p for p in (out/'calls').rglob('dispatch.json') if not p.with_name('receipt.json').exists()]
            unended=[p for p in (out/'tasks').glob('*/*/started.json') if not (out/'results'/p.parent.parent.name/(p.parent.name+'.json')).exists()]
            ok=kill_seen.is_set() and s['stage']=='needs_attention' and str(fence) in str(s.get('stopReason')) and not s['active'] and not pending and not unended
            if ok:
                if stable is None:stable=time.monotonic()
                if time.monotonic()-stable>=2:break
            else:stable=None
            if time.monotonic()>until:
                event('drain_needs_attention',active=s['active'],pending=len(pending),unended=len(unended))
                state.update(phase='needs_attention_keep_guard',reason='Original tasks did not drain within 900 seconds');save(ops/'guard.json',state)
                # Preserve the live grader and evidence; do not expire or reset work.
                until=time.monotonic()+900
            time.sleep(.15 if args.fixture else .3)
        verify_pins()
        # Native children must already have exited through their normal finally.
        for p in (out/'tasks').glob('*/*/engine-process.json'):
            e=read(p);v=proc(e['pid'])
            if v['live']:
                env=Path('/proc',str(e['pid']),'environ').read_bytes().split(b'\0')
                assert b'TGENGIN_CONFIG='+str(p.parent/'engine/config.yaml').encode() not in env,'OwnedNativeStillLive'
        event('all_tasks_drained',records=len(records),unreceipted=0,unfinishedStarts=0)
        allow_shutdown.set();os.kill(grader,signal.SIGTERM)
        event('grader_shutdown_released')
        until=time.monotonic()+20
        while proc(pid)['live'] or proc(grader)['live']:
            assert time.monotonic()<until,'ControllerDidNotExitAfterDrain';time.sleep(.05)
        assert not (out/'runner-lock.json').exists(),'LegacyLockRemains'
        verify_pins()
        destination=ops/'ADMISSION_FENCE.marker'
        assert not destination.exists();fence.rename(destination)
        state.update(phase='drain_complete',completedRecords=len(list((out/'results').rglob('*.json'))),oldControllerLive=False,graderLive=False,sourcePinsUnchanged=True,unknownFeesPreserved=True,fenceArchived=str(destination))
        save(ops/'guard.json',state);event('drain_complete',records=state['completedRecords'])
    except BaseException as e:
        failure.append(repr(e));state.update(phase='needs_attention_keep_guard',reason=repr(e));save(ops/'guard.json',state);event('guard_monitor_error',error=repr(e))
    finally:finished.set()

thread=threading.Thread(target=monitor,daemon=True);thread.start()
while attached:
    try:tid,st=os.waitpid(-1,WALL)
    except ChildProcessError:break
    if os.WIFEXITED(st) or os.WIFSIGNALED(st):attached.discard(tid);continue
    if not os.WIFSTOPPED(st):continue
    sig=os.WSTOPSIG(st);kind=st>>16
    if kind==3:
        child=ctypes.c_ulong();ptrace(GETEVENTMSG,tid,0,ctypes.addressof(child));attached.add(child.value)
    deliver=0 if kind else sig
    if sig==signal.SIGTERM and not kind and not allow_shutdown.is_set():
        info=ctypes.create_string_buffer(128);ptrace(GETSIGINFO,tid,0,ctypes.addressof(info))
        sender=ctypes.c_int.from_buffer(info,16).value
        event('premature_grader_sigterm_suppressed',senderPid=sender,expectedController=sender==pid)
        kill_seen.set();deliver=0
    try:ptrace(CONT,tid,0,deliver)
    except OSError as e:
        if e.errno!=errno.ESRCH:raise
        attached.discard(tid)
thread.join(25)
assert finished.is_set() and not failure and state['phase']=='drain_complete',str(failure)
print(json.dumps(state),flush=True)
