"""Bindings for the unchanged original full-F ordinary-data HTTP Stand.

Opaque reference artifacts are copied into the untrusted owned solver only.
Original collection, grading, output policies and verifier namespace stay in
full-F data_stand.py; no task runner, tests or scoring are implemented here.
"""
import json,pathlib,os
from native_process import pin
from original_sb_http_binding import bind_http_config,copy_runtime_asset

def read_checked(p):
    actual=pin(p['path']);assert (actual['bytes'],actual['sha256'])==(p['bytes'],p['sha256']),'ordinary_http_binding_pin_changed'
    return json.loads(pathlib.Path(p['path']).read_bytes())

def bind_config(config):
    assert len(config['schedule'])==1 and len(config['taskReadiness'])==1
    row=config['schedule'][0];proof=config['taskReadiness'][row['taskId']]
    assert proof.get('adapter') not in ('group01-adapter2-v1','group02-adapter2-v1','group02-adapter3-v1','acc-independent-v1'),'original_ordinary_data_scope_only'
    built=read_checked(proof['builtImagesPin']);controls=read_checked(proof['controlPin'])
    assert built['taskId']==controls['taskId']==row['taskId'] and controls['controlsPassed'] and controls['ownedContainersRemaining']==0
    assert built['outputPolicies'] and built['privateRunnerSourcePin']
    assert built['candidateImageId'] and built['privateImageId']
    assert controls['builtImagesPin']==proof['builtImagesPin']
    return bind_http_config(config)

def frozen_private_runner(runner,built,proof):
    actual=pin(runner);assert actual==built['privateRunnerSourcePin']
    original=read_checked(proof['originalBuiltImagesPin'])
    assert original['taskId']==built['taskId']
    for key in ('bytes','sha256'):assert actual[key]==original['privateRunnerSourcePin'][key]
    for key in ('originalResources','dataArtifactPolicy','workingDirectory','artifactTmpfsBytes','artifactTmpfsParent'):
        assert original[key]==built[key],'ordinary_original_private_contract_changed:'+key
    return True

def ordinary_worker_path():
    from bound_child_entry import checked_config
    _,mapping=checked_config();p=mapping['ordinaryHttpBinding']['workerPin']
    assert pin(p['path'])==p
    return p['path']

def ordinary_stop(value):
    assert value['ownedContainersRemaining']==0
    return value

def command_transport(output,resources):
    from bounded_child import run as bounded_run
    from build_environment import DOCKER,ENV
    from original_sb_transport import require_original_lease
    from docker_mutation_ack import require as mutation_ack
    output=pathlib.Path(output);output.mkdir(parents=True,exist_ok=False);serial=0
    def command(args,timeout=30,stdin=None,stdout_limit=16*1024**2):
        nonlocal serial
        require_original_lease(int(os.environ['NOVAEVE_RESOURCE_LEASE_PID']),resources)
        serial+=1;prefix=output/('command-%06d'%serial)
        row=bounded_run([DOCKER,*args],ENV,prefix.with_suffix('.stdout'),prefix.with_suffix('.stderr'),timeout,stdin,stdout_limit=stdout_limit)
        row.update(argv=[DOCKER,*args],stdoutPin=pin(prefix.with_suffix('.stdout')),stderrPin=pin(prefix.with_suffix('.stderr')),modelCalls=0)
        prefix.with_suffix('.json').write_text(json.dumps(row,indent=2)+'\n',encoding='utf8')
        assert row['exitCode']==0 and not row['faults'] and row['directChildClosed'] and row['pipeReadersClosed']
        raw=prefix.with_suffix('.stdout').read_bytes();mutation_ack(args,raw);return raw
    return command

def restore_original_opaque_reference(stand,command,reference_pin,built_pin,control_pin,transfer_seconds=3600):
    assert transfer_seconds==3600,'only_explicit_pure_transfer_window'
    reference=read_checked(reference_pin);built=read_checked(built_pin);control=read_checked(control_pin)
    assert reference['protocol']=='bench-original-qualified-reference-opaque-recovery-v1'
    assert reference['taskId']==built['taskId']==control['taskId']
    assert reference['candidateImageId']==built['candidateImageId'] and reference['privateImageId']==built['privateImageId']
    original=read_checked(reference['originalControlsResultPin']);read_checked(reference['originalControlsAcceptancePin'])
    assert original['controlsPassed'] and original['ownedContainersRemaining']==0
    assert original['builtImagesPin']['sha256']==built_pin['sha256'] and original['builtImagesPin']['bytes']==built_pin['bytes']
    assert reference['originalControlsResultPin']['sha256']==control_pin['sha256'] and reference['originalControlsResultPin']['bytes']==control_pin['bytes']
    assert stand.current and stand.current['running'];cid=stand.current['cid']
    policies={p['path']:p for p in built['outputPolicies']};assert len(reference['files'])==len(policies)
    command(['stop','-t','1',cid]);stand.current['running']=False
    receipts=[]
    for item in reference['files']:
        destination=pathlib.PurePosixPath(item['destination']);assert str(destination) in policies and destination.is_absolute() and '..' not in destination.parts
        policy=policies[str(destination)];assert policy['kind']=='file' and policy['maximumFiles']==1
        body=pin(item['bodyPin']['path']);assert body==item['bodyPin'] and body['sha256']==item['sha256'] and body['bytes']<=policy['maximumBytes']
        tar_pin=item['originalDaemonTarPin'];actual=pin(tar_pin['path']);assert actual==tar_pin and actual['bytes']<=policy['maximumBytes']+18432
        original_command=read_checked(item['originalCommandPin']);assert original_command['stdoutPin']==tar_pin
        # Use the exact original daemon TAR bytes, with no host deserialization or code execution.
        raw=pathlib.Path(tar_pin['path']).read_bytes()
        command(['cp','-',cid+':'+str(destination.parent)],stdin=raw,timeout=transfer_seconds)
        receipts.append({'destination':str(destination),'originalDaemonTarPin':tar_pin,'opaqueBodyPin':body})
    command(['start',cid]);stand.current['running']=True;stand.current['mutation']+=1;stand.latest=None
    return {'restored':True,'referenceRepeated':False,'modelCalls':0,'opaqueArtifacts':receipts,'pureTransferWindowSeconds':transfer_seconds}
