"""Actual task-specific offline RAM grader. No Docker/model calls on import."""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import threading
import time
import uuid
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_transport_v2 as transport
import skb_artifact_ram_plan_v2 as ram
import skb_artifact_capture_v2 as capture
import skb_artifact_private_eval_v2 as evaluator
import skb_artifact_build_storage_v1 as build_storage

PROTOCOL='skillsbench-task-private-shared-ram-executor-v2'
OP_CAP=96*1024**2
HOST_RESERVE=1024**3
VM_MEMORY_CODE="import json;rows=dict((x.split(':',1)[0],int(x.split(':',1)[1].split()[0])*1024) for x in open('/proc/meminfo') if x.split(':',1)[0] in ('MemTotal','MemAvailable'));print(json.dumps(rows))"


def memory_probe_argv(plan,nonce):
    return ['create','--name','objrun-skb-vm-memory-'+nonce,'--pull','never','--label',ram.LABEL+'='+nonce,'--label','objrun.skb.role=vm-memory-probe',
        '--read-only','--network','none','--log-driver','none','--memory',str(64*1024**2),'--memory-swap',str(64*1024**2),'--cpus','1',
        '--cap-drop','ALL','--security-opt','no-new-privileges','--entrypoint',plan['trustedPythonPath'],plan['imageId'],'-I','-B','-c',VM_MEMORY_CODE]


def sources():
    extra=['skb_artifact_ready_v2.py','skb_artifact_grade_audit_v2.py','skb_artifact_build_audit_v2.py','skb_artifact_native_identity_v2.py']
    return [task.pin(x.__file__) for x in (task,storage,transport,ram,capture,evaluator,build_storage)]+[task.pin(__file__),
        *(task.pin(Path(__file__).with_name(name)) for name in extra),*transport.component_pins()]


def fresh(path,raw,boundary):
    storage.ordinary(Path(path).parent,boundary)
    with Path(path).open('xb') as f:
        task.demand(f.write(raw)==len(raw),'ram_write','Evidence write incomplete');f.flush();os.fsync(f.fileno())
    p=task.pin(path);task.demand(p['bytes']==len(raw) and p['sha256']==hashlib.sha256(raw).hexdigest(),'ram_readback','Evidence readback differs')
    return p


def missing_target(rc,out,err,kind,target):
    if rc!=1 or len(out)>64 or len(err)>2048:return False
    try:
        if out.strip() and json.loads(out)!=[]:return False
        lines=err.decode('utf-8',errors='strict').splitlines()
    except (ValueError,UnicodeError):return False
    if len(lines)!=1:return False
    prefixes=['Error response from daemon: No such '+kind+': ','Error: No such '+kind+': ','Error: No such object: ']
    if kind=='volume' and re.fullmatch('(?i:Error response from daemon: get )'+re.escape(target)+'(?i:: no such volume)',lines[0].strip()):return True
    return any(re.fullmatch('(?i:'+re.escape(p)+')'+re.escape(target),lines[0].strip()) for p in prefixes)


def logs_from_tar(raw):
    task.demand(len(raw)<=32*1024**2,'private_log_cap','Full private logs exceed fixed32MiB')
    result={}
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
        for member in archive.getmembers():
            name=member.name.removeprefix('./').removeprefix('verifier/')
            if member.isdir():
                task.demand(name in ('.','', 'verifier'),'private_log_scope','Unexpected log directory');continue
            task.demand(name in ('private-result.json','ctrf.json') and name not in result and member.isfile() and not member.islnk()
                        and 0<=member.size<=16*1024**2,'private_log_kind','Only bounded trusted result and CTRF regular files allowed')
            body=archive.extractfile(member).read(member.size+1)
            task.demand(len(body)==member.size,'private_log_incomplete','Result TAR body truncated');result[name]=body
    task.demand('private-result.json' in result,'private_result_missing','Actual private result missing')
    return result


class Executor:
    def __init__(self,descriptor_pin,layout_pin,mode,capture_pin,full_capacity):
        self.dp,self.lp,self.mode,self.cp,self.full=descriptor_pin,layout_pin,mode,capture_pin,full_capacity
        self.descriptor=task.read_json(descriptor_pin);task.validate_descriptor(self.descriptor)
        self.graph=task.validate_ready_graph(self.descriptor,require_collection=mode=='grade')
        self.layout=task.read_json(layout_pin);storage.validate_descriptor(self.layout)
        self.root=Path(self.layout['storePhysical']);self.nonce=uuid.uuid4().hex
        self.plan=ram.plan(self.descriptor,self.graph['private'],self.nonce)
        self.box=Path(self.layout['directories']['private-logs'])/('grade-'+self.nonce)
        storage.ordinary(self.box.parent,self.root);task.demand(not self.box.exists(),'ram_fresh','Fresh owned grade leaf required')
        self.box.mkdir();self.before=sources();self.snapshots=[]
        src=self.box/'executed-source';src.mkdir()
        for p in self.before:self.snapshots.append({'originalPin':p,'snapshotPin':fresh(src/Path(p['path']).name,Path(p['path']).read_bytes(),self.root)})
        self.plan_pin=fresh(self.box/'ram-plan.json',task.canonical(self.plan),self.root)
        self.client=task.pin(transport.DOCKER);task.demand(self.client['sha256']==transport.DOCKER_SHA,'ram_client','Fixed actual Docker client required')
        self.env=transport.sanitized_environment(self.layout,storage)
        self.lease=storage.InstanceLease(self.layout,self.nonce,self.box)
        self.serial=0;self.records=[];self.pending=[];self.identities={};self.closed=False;self.volume_removed=False
        self.lock=threading.RLock();self.scan_time=0;self.observed=None;self.command_reserve=0;self.samples=[]
        self.inputs=next(x['inputs'] for x in task.trusted_input_manifest()['tasks'] if x['taskId']==self.descriptor['taskId']).copy()
        self.capture=None;self.solver_size=0;self.solver_present=False
        if capture_pin:
            self.capture=capture.validate_capture_receipt(descriptor_pin,capture_pin)
            task.demand(self.capture['state'] in ('regular','absent'),'ram_candidate','Private grader accepts only captured regular or genuinely missing output')
        task.demand(mode in ('grade','collect') and (mode=='grade' or capture_pin is None),'ram_mode','Collection bootstrap cannot consume candidate output')

    def guard(self,amount=0,closing=False):
        if not closing:self.lease.assert_owned()
        with self.lock:
            now=time.monotonic()
            if self.observed is None or now-self.scan_time>=.5:
                self.observed=build_storage.observe(self.layout);self.scan_time=time.monotonic()
            pending=max(amount,self.command_reserve)
            task.demand(self.observed['allocatedEnvelopeBytes']+pending<=storage.STORE_CAP-(0 if closing else 2*1024**2),'ram_store_cap','Shared D evidence envelope exceeded')
            unit=storage.cluster_size(self.root)
            total=sum(max(unit,(p.stat().st_size+unit-1)//unit*unit) for p in self.box.rglob('*') if p.is_file())
            task.demand(total+pending<=OP_CAP,'ram_operation_cap','One private operation exceeds96MiB evidence')
            free={k:shutil.disk_usage(k+':/').free for k in ('C','D','F')}
            task.demand(free['D']>=storage.D_MIN+pending,'ram_D_floor','Bounded evidence cannot preserve D floor')
            if not closing:
                value=storage.assess_resources(self.layout,free,self.solver_present,self.solver_size,
                    solver_writable_limit=self.descriptor['solverWritableBudgetBytes'] if self.solver_present else None)
                task.demand(value['admitted'],'ram_resources','Actual task-specific C/D/F resources fail')
            if len(self.samples)>=256:self.samples.pop(0)
            self.samples.append({'atUnixMs':int(time.time()*1000),'volumeFreeBytes':free,'ownedAllocatedEnvelopeBytes':self.observed['allocatedEnvelopeBytes'],'reservedCaptureBytes':pending})

    def command(self,*args,timeout=30,cap=1024**2,checked=True,closing=False):
        self.serial+=1;task.demand(self.serial<=96,'ram_commands','Bounded operation cannot exceed96 commands')
        if not closing:task.demand(sources()==self.before,'ram_source','Executed sources changed');task.verify_pin(self.dp);task.verify_pin(self.lp);task.verify_pin(self.client,64*1024**2)
        with self.lock:self.command_reserve=cap+256*1024+16384;self.observed=None
        argv=[str(transport.DOCKER),'--host',transport.DOCKER_HOST,*args]
        try:
            row,out,err=transport.bounded_child(argv,self.env,self.box,self.serial,lambda n:self.guard(n,closing),timeout,cap)
        finally:
            path=self.box/('command-%03d.json'%self.serial)
            if path.exists():self.records.append({'recordPin':task.pin(path),'argv':argv,'maximumStdoutBytes':cap,'closing':closing})
        transport.validate_command_record(self.records[-1]['recordPin'],os.getpid(),self.serial,argv,self.box,cap)
        if checked:task.demand(row['exitCode']==0,'ram_docker','Actual private Docker operation failed; raw retained')
        return row,out,err

    def json(self,*args,**kwargs):
        _,raw,_=self.command(*args,**kwargs);return json.loads(raw)

    def begin(self):
        self.lease.acquire();self.guard(32768)
        daemon=self.json('info','--format','{{json .}}')
        task.demand(daemon['OSType']=='linux' and daemon['NCPU']>=self.plan['privateCPUs'],'ram_daemon','Actual Linux daemon CPU budget unavailable')
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),*[(k,ctypes.c_ulonglong) for k in ('total','available','totalPage','availPage','totalVirtual','availVirtual','extended')]]
        m=Memory();m.length=ctypes.sizeof(m)
        task.demand(ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)),'ram_host_memory','Actual host available RAM query failed')
        need=self.plan['privateMemoryBytes']+self.plan['physicalExtraRamReservationBytes']+HOST_RESERVE
        task.demand(m.available>=need and daemon['MemTotal']>=need,'ram_host_memory','Task RAM plus shared/seeder/kernel/headroom unavailable')
        self.memory={'actualHostAvailableBytes':m.available,'requiredBytes':need,'daemonMemTotal':daemon['MemTotal']}
        image=self.json('image','inspect',self.plan['imageId'])
        task.demand(len(image)==1 and image[0]['Id']==self.plan['imageId'],'ram_image','Private immutable runtime substituted')
        self.observe_vm_memory(need)
        if self.capture:
            cid=self.capture['ownedContainerID'];row,out,err=self.command('container','inspect','--size',cid,checked=False)
            if row['exitCode']==0:
                values=json.loads(out);task.demand(len(values)==1,'ram_solver','Single solver required')
                self.solver_size=capture.validate_solver_inspect(values[0],self.descriptor,task.read_json(self.capture['ownerPin']));self.solver_present=True
            else:task.demand(missing_target(row['exitCode'],out,err,'container',cid),'ram_solver','Captured solver identity ambiguous')
        for kind,name in [('volume',self.plan['volumeName']),('container','objrun-skb-ram-seeder-'+self.nonce),('container','objrun-skb-private-'+self.nonce)]:
            row,out,err=self.command(kind,'inspect',name,checked=False)
            task.demand(missing_target(row['exitCode'],out,err,kind,name),'ram_not_fresh','Exact new owned namespace already exists or absence ambiguous')

    def validate_memory_probe(self,actual,name):
        h=actual['HostConfig'];c=actual['Config']
        task.demand(actual['Name']=='/'+name and actual['Image']==c['Image']==self.plan['imageId']
                    and c['Labels'].get(ram.LABEL)==self.nonce and c['Labels'].get('objrun.skb.role')=='vm-memory-probe'
                    and not h.get('Binds') and not h.get('Mounts') and h['ReadonlyRootfs'] is True and h['NetworkMode']=='none'
                    and h['Memory']==h['MemorySwap']==64*1024**2 and h['NanoCpus']==10**9 and h['CapDrop']==['ALL']
                    and not h['Privileged'] and not h.get('PidMode') and h['LogConfig']['Type']=='none','ram_memory_probe','Exact small owned VM memory observation namespace required')

    def observe_vm_memory(self,required):
        name='objrun-skb-vm-memory-'+self.nonce
        row,out,err=self.command('container','inspect',name,checked=False)
        task.demand(missing_target(row['exitCode'],out,err,'container',name),'ram_memory_probe','Fresh exact memory probe required')
        self.pending.append(('memory',name))
        self.command(*memory_probe_argv(self.plan,self.nonce))
        actual=self.json('container','inspect',name)[0];self.validate_memory_probe(actual,name)
        _,raw,_=self.command('start','--attach',actual['Id'])
        observed=json.loads(raw)
        task.demand(all(type(observed.get(k)) is int and observed[k]>0 for k in ('MemTotal','MemAvailable'))
                    and observed['MemAvailable']<=observed['MemTotal'],'ram_vm_memory','Actual Linux VM available memory missing')
        self.memory['linuxVmMemory']=observed
        self.memory['linuxVmMemoryRawPin']=fresh(self.box/'vm-available-memory.json',raw,self.root)
        self.command('rm','-f',actual['Id'],closing=True)
        row,out,err=self.command('container','inspect',actual['Id'],checked=False,closing=True)
        task.demand(missing_target(row['exitCode'],out,err,'container',actual['Id']),'ram_memory_probe','Owned tiny observation probe remains')
        self.memory_probe_closed=True
        task.demand(observed['MemAvailable']>=required,'ram_vm_memory','Actual VM available RAM cannot reserve task grader/shared/seeder/kernel/headroom')

    def make(self):
        self.pending.append(('volume',self.plan['volumeName']));self.command(*self.plan['volumeCreate'])
        self.volume=self.json('volume','inspect',self.plan['volumeName'])[0];ram.validate_volume(self.volume,self.plan)
        for role in ('seeder','grader'):
            name=('objrun-skb-ram-seeder-' if role=='seeder' else 'objrun-skb-private-')+self.nonce
            self.pending.append(('container',name));self.command(*self.plan[role+'Create'])
            actual=self.json('container','inspect','--size',name)[0];ram.validate_container(actual,self.plan,role=='seeder')
            self.identities[role]={'name':name,'containerID':actual['Id'],'role':role,'state':'created'};self.command('start',actual['Id'])
            if role=='seeder':self.wait_seeded_subpaths()
        self.namespace_before=self.inspect_roles()

    def wait_seeded_subpaths(self):
        code="""import json,os,stat,time
paths=['/objrun','/objrun/home','/objrun/workspace','/objrun/tests','/objrun/logs','/objrun/logs/verifier','/objrun/tmp']
end=time.monotonic()+5
while not all(os.path.isdir(p) for p in paths):
 if time.monotonic()>end:raise RuntimeError('Exact shared subpaths did not become ready')
 time.sleep(.01)
rows=[]
for p in paths:
 s=os.lstat(p);v=os.statvfs(p)
 rows.append({'path':p,'ordinaryDirectory':stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode),'device':str(s.st_dev),'fsid':str(v.f_fsid),'capacityBytes':v.f_frsize*v.f_blocks})
print(json.dumps(rows))
"""
        actual=self.json('container','inspect','--size',self.identities['seeder']['containerID'])[0]
        ram.validate_container(actual,self.plan,True)
        task.demand(actual['State']['Running'] is True,'ram_seed_ready','Exact seeder must actually be running')
        _,raw,_=self.command('exec',actual['Id'],self.plan['trustedPythonPath'],'-I','-B','-c',code,timeout=10)
        rows=json.loads(raw);paths=['/objrun','/objrun/home','/objrun/workspace','/objrun/tests','/objrun/logs','/objrun/logs/verifier','/objrun/tmp']
        task.demand(isinstance(rows,list) and [x['path'] for x in rows]==paths and all(x['ordinaryDirectory'] is True and x['capacityBytes']==ram.RAM for x in rows)
                    and len({(x['device'],x['fsid']) for x in rows})==1,'ram_seed_ready','Exact ordinary shared512MiB subpaths must exist before mounting grader')
        self.seeder_ready_pin=fresh(self.box/'seeder-subpaths-ready.json',raw,self.root)

    def inspect_roles(self):
        result={}
        for role,item in self.identities.items():
            actual=self.json('container','inspect','--size',item['containerID'])[0];ram.validate_container(actual,self.plan,role=='seeder')
            task.demand(actual['Id']==item['containerID'] and actual['State']['Running'] is True and type(actual.get('SizeRw')) is int and 0<=actual['SizeRw']<=1024**2,
                        'ram_idle','Trusted private idle role has unexpected rootfs writes/state')
            result[role]=actual
        return result

    def probe(self,full,phase):
        task.demand(phase in ('before','after'),'ram_probe_phase','Exact distinct before/after probe required')
        _,raw,_=self.command('exec',self.identities['grader']['containerID'],self.plan['trustedPythonPath'],'-I','-B','-c',ram.mount_probe_code(self.plan,full),timeout=60)
        value=json.loads(raw);ram.validate_mount_probe(value,self.plan,full)
        if full:task.demand(0<value['capacityBytesWritten']<=ram.RAM,'ram_capacity','Actual ENOSPC capacity boundary missing')
        code="import json,os;print(json.dumps({'devBytes':os.statvfs('/dev').f_frsize*os.statvfs('/dev').f_blocks,'shmBytes':os.statvfs('/dev/shm').f_frsize*os.statvfs('/dev/shm').f_blocks}))"
        _,raw,_=self.command('exec',self.identities['seeder']['containerID'],self.plan['trustedPythonPath'],'-I','-B','-c',code)
        kernel=json.loads(raw);task.demand(type(kernel['devBytes']) is int and 0<=kernel['devBytes']<=64*1024**2 and kernel['shmBytes']==ram.SHM,'ram_kernel','Seeder auxiliary RAM budget differs')
        value['seederKernelMounts']=kernel
        return fresh(self.box/('namespace-'+phase+'-probe.json'),task.canonical(value),self.root)

    def seed(self):
        for row in [*self.descriptor['verifierFilePins'],*self.descriptor['privatePublicFixturePins']]:
            p=row['sourcePin'];task.verify_pin(p,64*1024**2)
            self.command('cp',p['path'],self.identities['grader']['containerID']+':'+row['containerPath']);task.verify_pin(p,64*1024**2)
        if self.capture and self.capture['state']=='regular':
            p=self.capture['artifactPin'];task.verify_pin(p,task.MAX_ARTIFACT)
            path=self.descriptor['outputArtifacts'][0]['containerPath']
            self.command('cp',p['path'],self.identities['grader']['containerID']+':'+path);task.verify_pin(p,task.MAX_ARTIFACT)
            self.inputs.append({'path':path,'bytes':p['bytes'],'sha256':p['sha256'],'role':'candidate-data'})
        self.job=task.private_job(self.descriptor,self.inputs,self.mode)
        self.job_pin=fresh(self.box/'job.json',task.canonical(self.job),self.root)
        self.command('cp',self.job_pin['path'],self.identities['grader']['containerID']+':/verifier/job.json')

    def evaluate(self):
        self.command('exec',self.identities['grader']['containerID'],self.plan['trustedPythonPath'],'-I','-B','/opt/objrun/private_eval.py',
            '--job','/verifier/job.json','--job-sha256',self.job_pin['sha256'],timeout=self.plan['originalVerifierSeconds'],cap=16*1024**2)
        _,raw,_=self.command('cp',self.identities['grader']['containerID']+':/logs/verifier/.','-',cap=32*1024**2)
        logs=logs_from_tar(raw);self.log_pins={name:fresh(self.box/name,body,self.root) for name,body in logs.items()}
        value=task.read_json(self.log_pins['private-result.json']);validate_result(value,self.job)
        self.result=value;self.namespace_after=self.inspect_roles();self.probe_after=self.probe(False,'after')

    def cleanup(self):
        faults=[]
        name='objrun-skb-vm-memory-'+self.nonce
        if ('memory',name) in self.pending and not getattr(self,'memory_probe_closed',False):
            try:
                row,out,err=self.command('container','inspect',name,checked=False,closing=True)
                if row['exitCode']!=0:task.demand(missing_target(row['exitCode'],out,err,'container',name),'ram_close','Memory probe absence ambiguous')
                else:
                    actual=json.loads(out)[0];self.validate_memory_probe(actual,name);self.command('rm','-f',actual['Id'],closing=True)
                    row,out,err=self.command('container','inspect',actual['Id'],checked=False,closing=True)
                    task.demand(missing_target(row['exitCode'],out,err,'container',actual['Id']),'ram_close','Owned memory probe still exists')
                self.memory_probe_closed=True
            except BaseException as e:faults.append({'role':'memory','kind':getattr(e,'kind',type(e).__name__)})
        for role in ('grader','seeder'):
            name=('objrun-skb-private-' if role=='grader' else 'objrun-skb-ram-seeder-')+self.nonce
            if ('container',name) not in self.pending:continue
            try:
                row,out,err=self.command('container','inspect',name,checked=False,closing=True)
                if row['exitCode']!=0:
                    task.demand(missing_target(row['exitCode'],out,err,'container',name),'ram_close','Owned create attempt has ambiguous absence');continue
                values=json.loads(out);task.demand(len(values)==1,'ram_close','Single exact close target required');actual=values[0]
                ram.validate_container(actual,self.plan,role=='seeder')
                task.demand(role not in self.identities or self.identities[role]['containerID']==actual['Id'],'ram_close','Owned CID replaced')
                self.command('rm','-f',actual['Id'],closing=True)
                row,out,err=self.command('container','inspect',actual['Id'],checked=False,closing=True)
                task.demand(missing_target(row['exitCode'],out,err,'container',actual['Id']),'ram_close','Exact owned CID still exists')
                self.identities[role]={'role':role,'name':name,'containerID':actual['Id'],'state':'removed'}
            except BaseException as e:faults.append({'role':role,'kind':getattr(e,'kind',type(e).__name__)})
        if ('volume',self.plan['volumeName']) in self.pending and not faults:
            try:
                row,out,err=self.command('volume','inspect',self.plan['volumeName'],checked=False,closing=True)
                if row['exitCode']!=0:task.demand(missing_target(row['exitCode'],out,err,'volume',self.plan['volumeName']),'ram_close','Owned volume absence ambiguous')
                else:
                    actual=json.loads(out)[0];ram.validate_volume(actual,self.plan)
                    task.demand(not hasattr(self,'volume') or actual['Mountpoint']==self.volume['Mountpoint'],'ram_close','Owned volume backing replaced')
                    self.command('volume','rm',self.plan['volumeName'],closing=True)
                    row,out,err=self.command('volume','inspect',self.plan['volumeName'],checked=False,closing=True)
                    task.demand(missing_target(row['exitCode'],out,err,'volume',self.plan['volumeName']),'ram_close','Owned volume still exists')
                self.volume_removed=True
            except BaseException as e:faults.append({'role':'volume','kind':getattr(e,'kind',type(e).__name__)})
        task.demand(not faults,'ram_cleanup','Owned cleanup failed; native lease retained')
        self.closed=True


def validate_result(value,job):
    fields={'taskDescriptorSha256','runnerSourceSha256','pythonPath','pythonVersion','pythonSha256','dependencies','taskId','mode'}
    task.demand(value.get('protocol')==evaluator.PROTOCOL and all(value.get(k)==job[k] for k in fields)
                and value.get('sourceInputsBefore')==value.get('sourceInputsAfter')==job['inputs']
                and value.get('actualCollectionExecuted') is True and value.get('actualTestsExecuted')==(job['mode']=='grade'),
                'private_result','Actual result source/interpreter/inputs/mode differs')
    if job['mode']=='grade':
        expected=evaluator.score_result(job,value['nodeIds'],value['reports'],value['pytestExitCode'],value['collectionErrors'],value['summaryCounts'])
        task.demand(value.get('evaluation')==expected,'private_score','Actual raw outcomes do not join official reward/strict validity')
    else:
        valid=value['pytestExitCode']==0 and not value['reports'] and not value['collectionErrors'] and 0<len(value['nodeIds'])<=4096 and len(set(value['nodeIds']))==len(value['nodeIds'])
        task.demand(value.get('collectionValid')==valid and value.get('evaluation') is None,'private_collection','Actual collection validity differs')


def grade_captured(descriptor_pin,layout_pin,capture_pin=None,mode='grade',full_capacity=False):
    runner=Executor(descriptor_pin,layout_pin,mode,capture_pin,full_capacity);fault=None;cleanup_fault=None;closure=None
    try:
        runner.begin();runner.make();runner.probe_pin=runner.probe(full_capacity,'before');runner.seed();runner.evaluate()
    except BaseException as e:fault={'type':type(e).__name__,'kind':getattr(e,'kind',None),'detail':str(e)[:1024]}
    finally:
        try:
            runner.cleanup()
            if runner.lease.held:closure=runner.lease.release();storage.validate_instance_closure(closure,runner.layout,runner.nonce,os.getpid(),runner.box)
        except BaseException as e:
            cleanup_fault={'type':type(e).__name__,'kind':getattr(e,'kind',None)};runner.lease.retain_after_failure()
    owner={'protocol':PROTOCOL,'taskId':runner.descriptor['taskId'],'taskDescriptorPin':descriptor_pin,'storageDescriptorPin':layout_pin,
        'capturePin':capture_pin,'mode':mode,'fullCapacityProbe':full_capacity,'actorPid':os.getpid(),'operationNonce':runner.nonce,'ramPlanPin':runner.plan_pin,
        'sourceSnapshots':runner.snapshots,'sourceBeforeAfterEqual':sources()==runner.before,'dockerClientPin':runner.client,
        'commandRecords':runner.records,'containers':list(runner.identities.values()),'volumeName':runner.plan['volumeName'],
        'ownedClosed':runner.closed,'volumeRemoved':runner.volume_removed,'leaseClosurePin':closure,'fault':fault,'cleanupFault':cleanup_fault,
        'namespaceBefore':getattr(runner,'namespace_before',None),'namespaceAfter':getattr(runner,'namespace_after',None),
        'namespaceProbePin':getattr(runner,'probe_pin',None),'namespaceAfterProbePin':getattr(runner,'probe_after',None),
        'seederReadyPin':getattr(runner,'seeder_ready_pin',None),
        'jobPin':getattr(runner,'job_pin',None),'resultPins':getattr(runner,'log_pins',None),'memoryObservation':getattr(runner,'memory',None),
        'memoryProbeClosed':getattr(runner,'memory_probe_closed',False),
        'resourceSamples':runner.samples,'parentActorClosureRequired':True,'completedAtUtc':datetime.now(timezone.utc).isoformat(),
        'modelCalls':0,'candidateProgramsExecuted':False,'hostBinds':False,'graderNetwork':'none','paidReady':False,'scoreCertificate':False}
    return fresh(runner.box/'grade-owner.json',task.canonical(owner),runner.root)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('task-descriptor','storage-descriptor'):
        p.add_argument('--'+k,type=Path,required=True);p.add_argument('--'+k+'-sha256',required=True)
    p.add_argument('--capture',type=Path);p.add_argument('--capture-sha256');p.add_argument('--mode',choices=('collect','grade'),default='grade')
    p.add_argument('--full-capacity',action='store_true');a=p.parse_args();pins=[]
    for k in ('task_descriptor','storage_descriptor'):
        item=task.pin(getattr(a,k).resolve());task.demand(item['sha256']==getattr(a,k+'_sha256'),'ram_cli','Explicit source-bound CLI pin required');pins.append(item)
    cp=task.pin(a.capture.resolve()) if a.capture else None
    task.demand(cp is None or cp['sha256']==a.capture_sha256,'ram_cli','Exact capture pin required')
    out=grade_captured(*pins,cp,a.mode,a.full_capacity);value=task.read_json(out)
    print(json.dumps({'gradeOwnerPin':out,'ownedClosed':value['ownedClosed'],'fault':value['fault'],'cleanupFault':value['cleanupFault'],'modelCalls':0}),flush=True)
    raise SystemExit(1 if value['fault'] or value['cleanupFault'] else 0)


if __name__=='__main__':main()
