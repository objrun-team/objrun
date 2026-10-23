"""Archive actual read-only BuildKit records to resolve an interrupted owned build."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import uuid
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_transport_v2 as transport


def main():
    p=argparse.ArgumentParser();p.add_argument('--layout',type=Path,required=True);a=p.parse_args()
    lp=task.pin(a.layout);layout=task.read_json(lp);storage.validate_descriptor(layout)
    box=task.REPO/'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/build-history'/uuid.uuid4().hex;box.mkdir(parents=True)
    env=transport.sanitized_environment(layout,storage);env['DOCKER_HOST']=transport.DOCKER_HOST
    argv=['D:/Program/resources/cli-plugins/docker-buildx.exe','history','ls','--format=json','--no-trunc']
    def guard(amount):
        task.demand(shutil.disk_usage('F:/').free>=1024**3+amount and shutil.disk_usage('D:/').free>=storage.D_MIN,'history_reserve','Readonly capture reserve missing')
    row,out,err=transport.bounded_child(argv,env,box,1,guard,30,1024**2)
    rp=task.pin(box/'command-001.json');transport.validate_command_record(rp,os.getpid(),1,argv,box)
    value={'protocol':'skillsbench-build-history-readonly-v1','actorPid':os.getpid(),'layoutPin':lp,'commandRecordPin':rp,
           'sourcePin':task.pin(__file__),'buildxPin':task.pin(argv[0]),'observedAtUtc':datetime.now(timezone.utc).isoformat(),
           'modelCalls':0,'DockerMutations':0,'parentActorClosureRequired':True}
    path=box/'observation.json'
    with path.open('xb') as f:f.write(task.canonical(value));f.flush();os.fsync(f.fileno())
    print(json.dumps({'observationPin':task.pin(path),'stdoutPin':row['stdoutPin'],'exitCode':row['exitCode']}))
    rows=[json.loads(x) for x in out.splitlines() if x]
    selected=[x for x in rows if '3d-scan-calc' in json.dumps(x)]
    print(json.dumps({'selectedOwnedTaskHistory':selected[-8:]}))


if __name__=='__main__':main()
