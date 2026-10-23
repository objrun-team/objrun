"""One pinned original Python stage under the caller's actual owned lease.

The entry, argv, mapping, output and original limits are signed data. This
module does not implement task tests, reference solutions or score semantics.
"""
import json, os, pathlib, sqlite3, time, urllib.request, urllib.error
import _bench_original_owned_guard as guard
from native_process import capture, pin

def checked(value):
    actual=pin(value['path'])
    assert actual==value, 'native_stage_pin_changed'
    return pathlib.Path(actual['path'])

def absent(kind, identity):
    try:
        urllib.request.urlopen(os.environ['DOCKER_HOST'].replace('tcp:','http:')+'/'+kind+'/'+identity+'/json',timeout=10)
    except urllib.error.HTTPError as error:
        assert error.code==404
        return {'kind':kind,'id':identity,'status':404}
    raise AssertionError('native_stage_actor_still_present')

def run_stage(plan, output):
    job=json.loads(checked(plan['stageRequestPin']).read_bytes())
    assert job['protocol']=='bench-pinned-native-stage-v1'
    assert job['taskId']==plan['policyTaskId'] and job['bench']==plan['resource']['bench']
    assert job['resource']==plan['resource'] and job['modelCalls']==0
    if plan['noBenchContent']:
        assert job['neutralNoBench'] is True and job['authorizedGradeCalls']==0 and job['authorizedReferenceCalls']==0
    r=job['resource'];guard.require_lease(r['memoryMb'],r['growthBytes'],r['bench'],1)
    _bench_authorized_history(job['taskId'])
    limit=json.loads((pathlib.Path(plan['output'])/'absolute-deadline.json').read_bytes())
    assert limit['pid']==int(os.environ['NOVAEVE_RESOURCE_LEASE_PID'])
    remaining=limit['deadline']/1000-time.time();assert remaining>0
    output=pathlib.Path(output);output.mkdir(parents=True,exist_ok=False)
    mapping=checked(job['mappingPin'])
    assert str(mapping.resolve())==str(pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']).resolve())
    assert pin(mapping)['sha256']==os.environ['NOVAEVE_PYTHON_MAPPING_SHA256']
    config=json.loads(mapping.read_bytes());entry=checked(job['entryPin'])
    assert job['entryPin'] in [config['originalStandPin'],*config.get('allowedEntryPins',[])]
    for value in job['inputPins']:checked(value)
    staged=[]
    for item in job.get('inputFiles',[]):
        source=checked(item['pin']);assert not source.is_symlink() and not source.is_junction()
        relative=pathlib.PurePosixPath(item['relative'])
        assert not relative.is_absolute() and '..' not in relative.parts and relative.parts
        target=output/'inputs'/str(relative);assert target.resolve().is_relative_to((output/'inputs').resolve())
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write(source.read_bytes())
        assert pin(target)['bytes']==item['pin']['bytes'] and pin(target)['sha256']==item['pin']['sha256']
        checked(item['pin']);staged.append({'sourcePin':item['pin'],'stagedPin':pin(target),'relative':str(relative)})
    replacements={'{STAGE_OUTPUT}':str(output/'original'),'{STAGE_INPUTS}':str(output/'inputs'), '{PARENT_PID}':str(os.getpid())}
    argv=[]
    for argument in job['argv']:
        assert isinstance(argument,str)
        for key,value in replacements.items():argument=argument.replace(key,value)
        assert '{' not in argument and '}' not in argument
        argv.append(argument)
    child_argv=[str(checked(job['pythonPin'])),'-B','-X','utf8',str(checked(job['bootstrapPin'])),'--config',str(mapping),'--original-script',str(entry),'--',*argv]
    child=capture(child_argv,output/'original-stage-process',remaining,env=dict(os.environ),cwd=plan['root'])
    assert child['closeObserved'] and not child['timedOut'] and child['error'] is None,'native_stage_process_not_closed'
    databases=[];actors=[];commands=[]
    for path in sorted(output.rglob('owned-native.sqlite')):
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        try:
            rows=db.execute('select cid,closed from actor').fetchall()
            for cid,closed in rows:
                assert closed==1,'native_stage_owned_actor_open'
                actors.append(absent('containers',cid))
            for raw, in db.execute('select json from command order by id'):
                row=json.loads(raw);assert row['closeObserved'] and row['exitCode'] is not None
                assert not row.get('timedOut',False) and not row.get('captureFaults')
                for key in ['stdout','stderr']:
                    if key in row:
                        stream=row[key];assert stream['bytesStored']==stream['bytesObserved'] and not row.get('overflow',False)
                        checked({'path':stream['path'],'bytes':stream['bytesStored'],'sha256':stream['sha256']})
                commands.append(row)
            databases.append(pin(path))
        finally:db.close()
    if job.get('evidenceSchema')=='skillsbench-bounded-command-files-v1':
        assert not databases and not actors and not commands,'original_sb_evidence_not_sqlite'
        from original_sb_transport import collect_bounded_command_evidence
        bounded=collect_bounded_command_evidence(output)
        commands=bounded['commands'];actors=bounded['actorAbsences']
        databases=[row['commandPin'] for row in commands]
    assert databases and actors and commands,'actual_owned_native_stage_evidence_required'
    result_path=(output/'original'/job['resultRelativePath']).resolve()
    assert result_path.is_relative_to((output/'original').resolve())
    original=json.loads(result_path.read_bytes())
    assertions=[]
    for item in job['resultAssertions']:
        value=original
        for key in item['path']:value=value[key]
        assert value==item['equals'], 'original_stage_result_assertion_failed'
        assertions.append(item)
    assert child['exitCode']==0,'original_stage_failed'
    return {'complete':True,'actorClosed':True,'actualProcess':child,'stagedInputFiles':staged,'ledgerPins':databases,'actorAbsences':actors,'nativeCommandCount':len(commands),'originalResultPin':pin(result_path),'originalResultAssertions':assertions,'modelCalls':0,'gradeCalls':job['authorizedGradeCalls'],'referenceCalls':job['authorizedReferenceCalls'],'formalReady':False}
