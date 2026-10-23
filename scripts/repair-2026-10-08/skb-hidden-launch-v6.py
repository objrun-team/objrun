"""Durable hidden launcher for an authorized real-provider continuation."""
import json,os,subprocess,sys,time,ctypes,hashlib
from pathlib import Path
recipe=Path(sys.argv[1]);r=json.loads(recipe.read_text());layout=json.loads(Path(r['storageDescriptorPin']['path']).read_text());output=Path(r['output'])
env=os.environ.copy();env.update(layout['nativeEnvironment'])
argv=['C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe','scripts/repair-2026-10-08/skb-artifact-fast-resume-runtime-v6.ts',str(recipe)]
def save(name,value):
    with (output/name).open('x',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
with (output/'runtime.stdout.log').open('xb') as out,(output/'runtime.stderr.log').open('xb') as err:
    child=subprocess.Popen(argv,cwd=str(Path(__file__).resolve().parents[2]),env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
    save('hidden-launch.json',{'launcherPid':os.getpid(),'runtimePid':child.pid,'argv':argv,'startedAtUnixMs':int(time.time()*1000),'credentialsSerialized':False})
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),*[(k,ctypes.c_ulonglong) for k in ('total','available','totalPage','availPage','totalVirtual','availVirtual','extended')]]
    while True:
        m=Memory();m.length=ctypes.sizeof(m)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):raise OSError('Windows memory query failed')
        telemetry={'launcherPid':os.getpid(),'runtimePid':child.pid,'observedAtUnixMs':int(time.time()*1000),'availablePhysicalBytes':m.available,'availableCommitBytes':m.availPage,'commitLimitBytes':m.totalPage,'modelCalls':0}
        temporary=output/'commit-headroom.tmp';temporary.write_text(json.dumps(telemetry),encoding='utf8');os.replace(temporary,output/'commit-headroom.json')
        try:rc=child.wait(timeout=5);break
        except subprocess.TimeoutExpired:pass
    save('hidden-exit.json',{'runtimePid':child.pid,'exitCode':rc,'finishedAtUnixMs':int(time.time()*1000)})
