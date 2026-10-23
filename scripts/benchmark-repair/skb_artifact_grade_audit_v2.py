"""Independent full private report/raw command/namespace/lease replay."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_transport_v2 as transport
import skb_artifact_ram_plan_v2 as ram
import skb_artifact_ram_executor_v2 as executor
import skb_artifact_native_identity_v2 as native


def validate_grade_report(descriptor_pin,owner_pin,require_actor_closed=False):
    d=task.read_json(descriptor_pin);task.validate_descriptor(d)
    owner=task.read_json(owner_pin);layout=task.read_json(owner['storageDescriptorPin']);storage.validate_descriptor(layout)
    box=Path(owner_pin['path']).parent;storage.ordinary(box,Path(layout['storePhysical']))
    task.demand(owner['protocol']==executor.PROTOCOL and owner['taskDescriptorPin']==descriptor_pin and owner['taskId']==d['taskId']
                and owner['operationNonce']==box.name.removeprefix('grade-') and owner['ownedClosed'] is True and owner['volumeRemoved'] is True
                and owner['fault'] is None and owner['cleanupFault'] is None and owner['sourceBeforeAfterEqual'] is True
                and owner['candidateProgramsExecuted'] is False and owner['hostBinds'] is False and owner['graderNetwork']=='none',
                'grade_owner','Actual complete source-bound grade namespace/owner required')
    pairs=owner['sourceSnapshots'];task.demand(len(pairs)==len(executor.sources()),'grade_source','Whole executed grader source set required')
    for pair,p in zip(pairs,executor.sources()):
        task.verify_pin(pair['snapshotPin']);task.demand(pair['originalPin']==p and pair['snapshotPin']['sha256']==p['sha256'],'grade_source','Current executed byte source closure differs')
    private=task.read_json(d['privateRuntimeProofPin']);plan=task.read_json(owner['ramPlanPin']);ram.validate_plan(plan,d,private)
    task.demand(plan['nonce']==owner['operationNonce'] and owner['volumeName']==plan['volumeName'],'grade_plan','Exact actual private RAM plan differs')
    storage.validate_instance_closure(owner['leaseClosurePin'],layout,plan['nonce'],owner['actorPid'],box)
    rows=[]
    for serial,entry in enumerate(owner['commandRecords'],1):
        task.demand(entry['argv'][:3]==[str(transport.DOCKER),'--host',transport.DOCKER_HOST],'grade_daemon','Unexpected private command client/daemon')
        record=transport.validate_command_record(entry['recordPin'],owner['actorPid'],serial,entry['argv'],box,entry['maximumStdoutBytes'])
        if require_actor_closed:native.closed_identity(record['pid'],task.read_json(record['childPin'])['atUnixMs'])
        rows.append((entry,record))
    roles={x['role']:x for x in owner['containers']}
    task.demand(set(roles)=={'grader','seeder'} and all(x['state']=='removed' for x in roles.values()),'grade_roles','Both exact owned roles must be removed')
    for role,item in roles.items():
        before=owner['namespaceBefore'][role];after=owner['namespaceAfter'][role]
        ram.validate_container(before,plan,role=='seeder');ram.validate_container(after,plan,role=='seeder')
        task.demand(before['Id']==after['Id']==item['containerID'] and before['State']['Running'] is True and after['State']['Running'] is True,'grade_roles','Actual role/CID changed while grading')
        inspects=[json.loads(Path(r['stdoutPin']['path']).read_bytes())[0] for a,r in rows
            if a['argv'][3:]==['container','inspect','--size',item['containerID']] and r['exitCode']==0]
        task.demand(before in inspects and after in inspects,'grade_namespace_raw','Claimed namespace before/after must join actual inspect raw bytes')
        creates=[r for a,r in rows if a['argv'][3:]==plan[role+'Create']]
        removals=[r for a,r in rows if a['argv'][3:]==['rm','-f',item['containerID']]]
        missing=[r for a,r in rows if a['argv'][3:]==['container','inspect',item['containerID']] and executor.missing_target(r['exitCode'],Path(r['stdoutPin']['path']).read_bytes(),Path(r['stderrPin']['path']).read_bytes(),'container',item['containerID'])]
        task.demand(len(creates)==len(removals)==len(missing)==1 and creates[0]['exitCode']==removals[0]['exitCode']==0,'grade_lifecycle','Exact role create/remove/absent graph missing')
    volume_missing=[r for a,r in rows if a['argv'][3:]==['volume','inspect',plan['volumeName']] and executor.missing_target(r['exitCode'],Path(r['stdoutPin']['path']).read_bytes(),Path(r['stderrPin']['path']).read_bytes(),'volume',plan['volumeName'])]
    task.demand(len(volume_missing)>=2 and any(a['argv'][3:]==['volume','rm',plan['volumeName']] and r['exitCode']==0 for a,r in rows),'grade_volume','Actual volume creation pre-absence/removal/post-absence required')
    for key,full in [('namespaceProbePin',owner['fullCapacityProbe']),('namespaceAfterProbePin',False)]:
        probe=task.read_json(owner[key]);ram.validate_mount_probe(probe,plan,full)
        argv=['exec',roles['grader']['containerID'],plan['trustedPythonPath'],'-I','-B','-c',ram.mount_probe_code(plan,full)]
        matches=[r for a,r in rows if a['argv'][3:]==argv and r['exitCode']==0]
        task.demand(matches and any({**json.loads(Path(r['stdoutPin']['path']).read_bytes()),'seederKernelMounts':probe['seederKernelMounts']}==probe for r in matches),
                    'grade_mount_raw','Namespace metadata does not join actual source-bound native probe output')
    ready=task.read_json(owner['seederReadyPin']);task.demand(len(ready)==7 and len({(x['fsid'],x['device']) for x in ready})==1
                    and all(x['ordinaryDirectory'] is True and x['capacityBytes']==ram.RAM for x in ready),'grade_seed_ready','Actual subpath readiness proof missing')
    memory=owner['memoryObservation'];need=plan['privateMemoryBytes']+plan['physicalExtraRamReservationBytes']+executor.HOST_RESERVE
    task.demand(owner['memoryProbeClosed'] is True and memory['requiredBytes']==need and memory['actualHostAvailableBytes']>=need
                    and memory['linuxVmMemory']['MemAvailable']>=need and memory['daemonMemTotal']>=need,'grade_memory','Recomputed host/VM RAM reservation differs')
    task.demand(task.read_json(memory['linuxVmMemoryRawPin'])==memory['linuxVmMemory'],'grade_memory','VM memory observation bytes differ')
    memory_name='objrun-skb-vm-memory-'+plan['nonce']
    made=[r for a,r in rows if a['argv'][3:]==executor.memory_probe_argv(plan,plan['nonce']) and r['exitCode']==0]
    inspected=[json.loads(Path(r['stdoutPin']['path']).read_bytes())[0] for a,r in rows
        if a['argv'][3:]==['container','inspect',memory_name] and r['exitCode']==0]
    task.demand(len(made)==len(inspected)==1,'grade_memory_raw','Exact memory namespace producer graph required')
    actual=inspected[0];executor.Executor.validate_memory_probe(type('Probe',(),{'plan':plan,'nonce':plan['nonce']})(),actual,memory_name)
    cid=actual['Id'];started=[r for a,r in rows if a['argv'][3:]==['start','--attach',cid] and r['exitCode']==0]
    removed=[r for a,r in rows if a['argv'][3:]==['rm','-f',cid] and r['exitCode']==0]
    absent=[r for a,r in rows if a['argv'][3:]==['container','inspect',cid] and executor.missing_target(r['exitCode'],
        Path(r['stdoutPin']['path']).read_bytes(),Path(r['stderrPin']['path']).read_bytes(),'container',cid)]
    task.demand(len(started)==len(removed)==len(absent)==1 and started[0]['stdoutPin']['sha256']==memory['linuxVmMemoryRawPin']['sha256'],
        'grade_memory_raw','Available RAM must join actual start output and exact probe closure')
    job=task.read_json(owner['jobPin']);task.demand(job['taskDescriptorSha256']==hashlib.sha256(task.canonical(d)).hexdigest() and job['mode']==owner['mode'],'grade_job','Actual source-bound descriptor/job differs')
    runs=[r for a,r in rows if a['argv'][3:]==['exec',roles['grader']['containerID'],plan['trustedPythonPath'],'-I','-B','/opt/objrun/private_eval.py','--job','/verifier/job.json','--job-sha256',owner['jobPin']['sha256']]]
    task.demand(len(runs)==1 and runs[0]['exitCode']==0,'grade_execution','Exact isolated trusted runner execution missing')
    transfers=[r for a,r in rows if a['argv'][3:]==['cp',roles['grader']['containerID']+':/logs/verifier/.','-']]
    task.demand(len(transfers)==1 and transfers[0]['exitCode']==0,'grade_logs','Actual complete private log TAR missing')
    bodies=executor.logs_from_tar(Path(transfers[0]['stdoutPin']['path']).read_bytes())
    task.demand(set(bodies)==set(owner['resultPins']),'grade_logs','Copied private result inventory differs')
    for name,raw in bodies.items():
        p=owner['resultPins'][name];task.verify_pin(p,16*1024**2)
        task.demand(Path(p['path'])==box/name and p['bytes']==len(raw) and p['sha256']==hashlib.sha256(raw).hexdigest(),'grade_logs','Parsed result is not the actual native TAR body')
    value=task.read_json(owner['resultPins']['private-result.json']);executor.validate_result(value,job)
    if require_actor_closed:native.closed_identity(owner['actorPid'],int(datetime.fromisoformat(owner['completedAtUtc']).timestamp()*1000))
    return {'owner':owner,'result':value,'job':job,'plan':plan,'actualRawGraphValidated':True,'scoreCertificate':False}
