import ctypes,datetime,json,os,pathlib,shutil,subprocess,time
root=pathlib.Path(__file__).resolve().parents[4];out=root/'docs/newbench-20261014/bird';diag=out/'diagnosis-authorizer';bun=r'C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,v):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(v,indent=2),encoding='utf8');tmp.replace(p)
state={'pid':os.getpid(),'startedAtUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'stage':'draining','oldRunnerPid':read(out/'launch.json')['fullPid']}
def status(**kw):state.update(kw,updatedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat());save(diag/'recovery-status.json',state)
try:
    status()
    api=ctypes.WinDLL('kernel32',use_last_error=True);api.OpenProcess.restype=ctypes.c_void_p;api.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];api.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];api.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=api.OpenProcess(0x100000,False,state['oldRunnerPid'])
    if handle:
        try:
            drain_deadline=time.monotonic()+2400
            while api.WaitForSingleObject(handle,5000)==258:
                if time.monotonic()>drain_deadline:raise RuntimeError('Active-work drain exceeded its bounded 40-minute recovery window; original processes/evidence retained')
        finally:api.CloseHandle(handle)
    # Let the old waiting supervisor finish its final metadata write before replacement.
    time.sleep(2);status(stage='regrading')
    with open(diag/'repair.stdout.log','ab',buffering=0) as stdout,open(diag/'repair.stderr.log','ab',buffering=0) as stderr:
        r=subprocess.run([bun,'examples/benchmark/code-benchmarks/bird/repair-authorizer.ts'],cwd=root,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode:raise RuntimeError('Authorizer recovery script failed; inspect repair.stderr.log')
    full=out/'full';pin=full/'source-pins.json'
    if pin.exists():pin.rename(full/'source-pins-before-countstar-repair.json')
    stop=full/'stop-after-current-tasks.json'
    if stop.exists():stop.rename(full/'stop-for-countstar-repair.json')
    dest=out/'adapter-source-countstar-repair';dest.mkdir(exist_ok=True)
    for p in pathlib.Path(__file__).parent.iterdir():
        if p.is_file():shutil.copy2(p,dest/p.name)
    with open(diag/'restart-supervisor.stdout.log','ab',buffering=0) as stdout,open(diag/'restart-supervisor.stderr.log','ab',buffering=0) as stderr:
        p=subprocess.Popen([r'D:/ProgramData/anaconda3/python.exe','examples/benchmark/code-benchmarks/bird/supervise-full.py'],cwd=root,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
    status(stage='restarted',newSupervisorPid=p.pid)
except Exception as e:status(stage='needs_attention',error=str(e));raise
