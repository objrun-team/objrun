"""Binding and evidence for the unchanged SkillsBench bounded command protocol."""
import datetime,json,os,pathlib,time,urllib.request,urllib.error,re
import _bench_original_owned_guard as guard
from native_process import pin
from observed_owned_spawn import spawn_owned

def require_original_lease(owner_pid, resources):
    config=json.loads(pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']).read_bytes())
    bound=config['resource'];assert bound['bench']=='skillsbench'
    environment=resources['environment']
    assert bound['memoryMb']>=2*environment['memory_mb'], 'original_aggregate_broker_lease_required'
    assert bound['cpu']>=environment['cpus'] and bound['growthBytes']>=environment['storage_mb']*1024**2
    lease_pid=int(os.environ['NOVAEVE_RESOURCE_LEASE_PID'])
    assert int(owner_pid) in (lease_pid,os.getppid()), 'original_parent_or_verified_lease_owner_required'
    guard.require_lease(bound['memoryMb'],bound['growthBytes'],'skillsbench',1)
    check=globals().get('_bench_authorized_history');assert callable(check)
    task=config['historyPolicy']['taskKey'].split(':',1)[1];assert check(task) is True
    return {'originalOwnerPid':int(owner_pid),'verifiedLeasePid':lease_pid,'actualParentPid':os.getppid(),'resource':bound,'taskId':task}

def spawn_bounded(argv,env,stdout_path,stderr_path,stdin_body):
    import subprocess
    record={};prefix=pathlib.Path(stdout_path).with_suffix('')
    child=spawn_owned(record,prefix,argv,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.PIPE if stdin_body is not None else subprocess.DEVNULL)
    child._bench_bounded_record=record;child._bench_bounded_prefix=prefix;child._bench_bounded_tick=time.monotonic()
    return child

def complete_bounded(child,stdout_path,stderr_path,result):
    record=child._bench_bounded_record;assert result['pid']==child.pid
    record.update(finishedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),elapsedSeconds=time.monotonic()-child._bench_bounded_tick,exitCode=result['exitCode'],directChildClosed=result['directChildClosed'],pipeReadersClosed=result['pipeReadersClosed'],faults=result['faults'],stdoutPin=pin(stdout_path),stderrPin=pin(stderr_path))
    path=pathlib.Path(str(child._bench_bounded_prefix)+'.spawn.json');path.write_text(json.dumps(record,indent=2)+'\n')
    return {**result,'incarnation':record.get('incarnation'),'startedAtUtc':record['startedAtUtc'],'finishedAtUtc':record['finishedAtUtc'],'spawnPin':pin(path)}

def collect_bounded_command_evidence(output):
    output=pathlib.Path(output).resolve();rows=[]
    for path in sorted(output.rglob('command-*.json')):
        if path.name.endswith('.spawn.json'):continue
        row=json.loads(path.read_bytes());assert row['directChildClosed'] and row['pipeReadersClosed'] and not row['faults']
        assert type(row['exitCode']) is int and type(row['pid']) is int
        spawn_pin=row['spawnPin'];assert pin(spawn_pin['path'])==spawn_pin
        spawn=json.loads(pathlib.Path(spawn_pin['path']).read_bytes());assert spawn['pid']==row['pid'] and spawn['incarnation']==row['incarnation']
        assert spawn['argv']==row['argv'] and spawn['exitCode']==row['exitCode'] and spawn['directChildClosed'] and spawn['pipeReadersClosed'] and not spawn['faults']
        assert spawn['incarnation'] and spawn['startedAtUtc'] and spawn['finishedAtUtc']
        for key in ('stdout','stderr'):
            value=row[key+'Pin'];assert pin(value['path'])==value and value['bytes']==row[key+'Bytes']
            assert value==spawn[key+'Pin']
            assert pathlib.Path(value['path']).resolve().is_relative_to(output)
        rows.append({'commandPin':pin(path),'spawnPin':spawn_pin,'pid':row['pid'],'incarnation':row['incarnation'],'argv':row['argv'],'exitCode':row['exitCode'],'stdoutPin':row['stdoutPin'],'stderrPin':row['stderrPin']})
    assert rows,'actual_original_bounded_commands_required'
    created={};removed=set()
    for row in rows:
        args=row['argv'][1:]
        if args and args[0]=='create' and row['exitCode']==0:
            cid=pathlib.Path(row['stdoutPin']['path']).read_text().strip();assert re.fullmatch('[a-f0-9]{64}',cid);assert cid not in created;created[cid]=row['commandPin']
        if args and args[0]=='rm' and row['exitCode']==0:
            targets=[x for x in args[1:] if not x.startswith('-')];assert pathlib.Path(row['stdoutPin']['path']).read_text().strip().splitlines()==targets
            removed.update(targets)
    assert created and set(created)<=removed,'actual_created_actor_removal_required'
    absence=[];host=os.environ['DOCKER_HOST'].replace('tcp:','http:')
    for cid in created:
        try:urllib.request.urlopen(host+'/containers/'+cid+'/json',timeout=10);raise AssertionError('original_sb_actor_still_present')
        except urllib.error.HTTPError as error:assert error.code==404;absence.append(dict(kind='containers',id=cid,status=404,createPin=created[cid]))
    return {'commands':rows,'actorAbsences':absence}
