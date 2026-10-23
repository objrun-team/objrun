"""Archive exact new bench command/source bytes before its actual direct child."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import uuid
import skb_artifact_task_v2 as task

ALLOWED={'skb_artifact_build_audit_v2.py','skb_artifact_ram_executor_v2.py','skb_artifact_solver_v2.py','skb-ten-build-history-readonly-v1.py','skb-ten-close-build-catalog-v2.py'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--script',choices=sorted(ALLOWED),required=True);p.add_argument('--timeout',type=int,default=60);p.add_argument('args',nargs=argparse.REMAINDER);a=p.parse_args()
    task.demand(1<=a.timeout<=2100,'evidence_timeout','Bounded direct child timeout required')
    args=a.args[1:] if a.args[:1]==['--'] else a.args
    script=Path(__file__).with_name(a.script);box=task.REPO/'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/command-runs'/uuid.uuid4().hex;box.mkdir(parents=True)
    src=box/'executed-source';src.mkdir();snapshots=[]
    for path in [Path(__file__),script,*Path(__file__).parent.glob('skb_artifact_*_v*.py')]:
        if (src/path.name).exists():continue
        raw=path.read_bytes();dest=src/path.name
        with dest.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        snapshots.append({'originalPin':task.pin(path),'snapshotPin':task.pin(dest)})
    argv=['D:/ProgramData/anaconda3/python.exe','-B','-X','utf8',str(script),*args]
    started=datetime.now(timezone.utc).isoformat();timed=False
    with (box/'stdout.txt').open('xb') as out,(box/'stderr.txt').open('xb') as err:
        child=subprocess.Popen(argv,cwd=task.REPO,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
        try:child.wait(timeout=a.timeout)
        except subprocess.TimeoutExpired:timed=True;child.kill();child.wait(timeout=10)
        out.flush();os.fsync(out.fileno());err.flush();os.fsync(err.fileno())
    value={'protocol':'skillsbench-source-bound-evidence-command-v1','actorPid':os.getpid(),'childPid':child.pid,'argv':argv,'cwd':str(task.REPO),
        'sourceSnapshots':snapshots,'directChildWaitReturned':True,'timedOut':timed,'exitCode':child.returncode,'startedAtUtc':started,'completedAtUtc':datetime.now(timezone.utc).isoformat(),
        'stdoutPin':task.pin(box/'stdout.txt'),'stderrPin':task.pin(box/'stderr.txt'),'modelCalls':0,'paidLockAcquired':False,'parentActorClosureRequired':True}
    path=box/'run.json'
    with path.open('xb') as f:f.write(task.canonical(value));f.flush();os.fsync(f.fileno())
    print(json.dumps({'runPin':task.pin(path),'exitCode':child.returncode,'childPid':child.pid}))
    print((box/'stdout.txt').read_text(encoding='utf-8')[-4000:])
    if child.returncode:print((box/'stderr.txt').read_text(encoding='utf-8')[-6000:])
    raise SystemExit(child.returncode or 0)


if __name__=='__main__':main()
