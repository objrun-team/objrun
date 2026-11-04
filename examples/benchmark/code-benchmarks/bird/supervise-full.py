import datetime,json,os,pathlib,shutil,subprocess
root=pathlib.Path(__file__).resolve().parents[4];out=root/'docs/newbench-20261014/bird'
entry='examples/benchmark/code-benchmarks/bird/run.ts'
launch=json.loads((out/'launch.json').read_text(encoding='utf8'))
dest=out/'adapter-source-v4';dest.mkdir(exist_ok=True)
for p in pathlib.Path(__file__).parent.iterdir():
    if p.is_file():shutil.copy2(p,dest/p.name)
stdout=open(out/'full-v4.stdout.log','ab',buffering=0);stderr=open(out/'full-v4.stderr.log','ab',buffering=0)
p=subprocess.Popen([r'C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe',entry,'full'],cwd=root,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
def save(**kw):
    launch.update(kw,updatedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat());tmp=out/'launch-v3.tmp';tmp.write_text(json.dumps(launch,indent=2),encoding='utf8');tmp.replace(out/'launch.json')
save(phase='full',fullLaunched=True,fullPid=p.pid,supervisorPid=os.getpid(),workerPoolSize=32,initialFullConcurrency=32,protocolVersion='count-bounded-independent-ex-stop-v4',independentPolicy='EX early stop, at most five fresh contexts; first correct else fifth',fullExitCode=None,perQuestionDollarCap=None,independentSamples=5,binaryMaxChecks=5)
code=p.wait()
s=json.loads((out/'full/status.json').read_text(encoding='utf8'));save(phase=s['stage'],fullExitCode=code)
