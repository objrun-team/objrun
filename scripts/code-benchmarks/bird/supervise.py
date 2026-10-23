"""Finish the bounded integration canary, then launch the authorized full four-arm run."""
import ctypes, datetime, json, os, pathlib, subprocess, time, shutil
root=pathlib.Path(__file__).resolve().parents[3]
out=root/'docs/newbench-20261014/bird'
bun=r'C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe'
entry='scripts/code-benchmarks/bird/run.ts'
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
launch=read(out/'launch.json')
def update(**kw):
    launch.update(kw,supervisorPid=os.getpid(),updatedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    tmp=out/'launch.tmp';tmp.write_text(json.dumps(launch,indent=2),encoding='utf8');tmp.replace(out/'launch.json')
def wait_pid(pid):
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.restype=ctypes.c_void_p
    api.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
    api.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
    api.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=api.OpenProcess(0x100000,False,pid)
    if handle:
        try:
            while api.WaitForSingleObject(handle,5000)==258: pass
        finally: api.CloseHandle(handle)
def start(mode,suffix=''):
    stdout=open(out/(mode+suffix+'.stdout.log'),'ab',buffering=0)
    stderr=open(out/(mode+suffix+'.stderr.log'),'ab',buffering=0)
    p=subprocess.Popen([bun,entry,mode],cwd=root,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
    update(phase=mode,**{mode+'Pid':p.pid},fullLaunched=mode=='full')
    return p
try:
    update(phase='canary_native',fullLaunched=False)
    wait_pid(launch['canaryPid'])
    for arm in ['baseline','objrun']:
        r=read(out/f'canary/results/{arm}/BIRD_1.json')
        if not r['grade']['valid'] or arm=='objrun' and r.get('candidateHow')!='submitted': raise RuntimeError('Initial canary did not complete '+arm)
    # The running first canary used revision 1. Keep its pinned source evidence and
    # valid baseline/native results; only matched-arm plumbing changes in revision 2.
    pin=out/'canary/source-pins.json'
    if pin.exists(): pin.rename(out/'canary/source-pins-revision-1.json')
    stop=out/'canary/stop-after-current-tasks.json'
    if stop.exists(): stop.rename(out/'canary/planned-integration-pause.json')
    revision={'atUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'preservedValidArms':['baseline','objrun'],'newModelCallsForPreservedArms':0,'changes':['Conservative reservation includes max_tokens digit overhead','Unknown costs consume retained upper bounds','Binary check ceiling matches native completed oracle evaluations; native c5 is per attempt','Canary matched arms bounded to two samples, excluded from full benchmark','Status records actual worker concurrency (one canary, two full)','Balance metadata omits account identity/credential label'],'modelProviderInputAndScoringUnchanged':True}
    (out/'canary/adapter-revision-2.json').write_text(json.dumps(revision,indent=2),encoding='utf8')
    p=start('canary','-resume');code=p.wait()
    s=read(out/'canary/status.json')
    if code or s['stage']!='complete': raise RuntimeError('Resumed canary failed: '+str(s.get('stopReason',s['stage'])))
    for arm in ['baseline','objrun','independent','binary']:
        r=read(out/f'canary/results/{arm}/BIRD_1.json')
        if not r['grade']['valid'] or r.get('modelCalls',0)<1: raise RuntimeError('Canary lacks valid actual model result for '+arm)
    # Save exact adapter files with results for the NAS evidence mirror.
    dest=out/'adapter-source';dest.mkdir(exist_ok=True)
    for path in pathlib.Path(__file__).parent.iterdir():
        if path.is_file(): shutil.copy2(path,dest/path.name)
    p=start('full');code=p.wait();s=read(out/'full/status.json')
    update(phase=s['stage'],fullExitCode=code)
except Exception as e:
    update(phase='needs_attention',error=str(e));raise
