"""Exact task-specific five-subpath private512MiB RAM plan and validators."""
from __future__ import annotations
import hashlib
from pathlib import Path
import re
import skb_artifact_task_v2 as task

PROTOCOL = 'skillsbench-private-shared-ram-plan-v2'
RAM = 512*1024**2
SHM = 8*1024**2
SEEDER_MEMORY = 256*1024**2
MOUNTS = {'/root':'home','/app/workspace':'workspace','/verifier':'tests','/logs':'logs','/tmp':'tmp'}
LABEL = 'objrun.skb.private-ram-owner'
OPTIONS = {'type':'tmpfs','device':'tmpfs','o':'size=536870912,mode=0700,nosuid,nodev'}
ENV = {'HOME':'/root','PATH':'/opt/objrun-verifier/bin:/usr/bin:/bin','LC_ALL':'C.UTF-8',
       'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','PYTHONPATH':'','PYTHONHOME':'','PYTHONSTARTUP':'',
       'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTEST_ADDOPTS':'','PYTEST_PLUGINS':'',
       'LD_PRELOAD':'','LD_LIBRARY_PATH':'','TEMP':'/tmp','TMP':'/tmp','TMPDIR':'/tmp'}


def plan(descriptor, runtime, nonce):
    task.validate_descriptor(descriptor)
    task.demand(isinstance(nonce,str) and re.fullmatch('[0-9a-f]{32}',nonce), 'ram_nonce', 'Fresh exact operation nonce required')
    task.demand(runtime.get('protocol')=='skillsbench-sealed-private-runtime-v1'
                and re.fullmatch('sha256:[0-9a-f]{64}',runtime.get('imageId',''))
                and runtime.get('runnerSourcePin')==descriptor['runnerSourcePin']
                and runtime.get('trustedManifestSha256')==descriptor['trustedManifestSha256'],
                'ram_runtime','Exact current sealed private image/runner/trusted manifest required')
    image=runtime['imageId']; volume='objrun-skb-ram-'+nonce
    resources=descriptor['originalResources']['environment']; memory=resources['memory_mb']*1024**2; cpus=resources['cpus']
    common=['--pull','never','--label',LABEL+'='+nonce,'--read-only','--network','none','--log-driver','none',
            '--user','0:0','--shm-size',str(SHM),'--cap-drop','ALL','--security-opt','no-new-privileges','--entrypoint','/bin/bash']
    seeder=['create','--name','objrun-skb-ram-seeder-'+nonce,*common,'--memory',str(SEEDER_MEMORY),
            '--memory-swap',str(SEEDER_MEMORY),'--cpus','1','--workdir','/',
            '--mount','type=volume,source='+volume+',target=/objrun,volume-nocopy',image,'-c',
            'set -e; mkdir -p /objrun/home /objrun/workspace /objrun/tests /objrun/logs/verifier /objrun/tmp; exec /bin/sleep infinity']
    grader=['create','--name','objrun-skb-private-'+nonce,*common,'--memory',str(memory),'--memory-swap',str(memory),
            '--cpus',str(cpus),'--workdir','/root']
    for target,subpath in MOUNTS.items():
        grader+=['--mount','type=volume,source='+volume+',target='+target+',volume-subpath='+subpath+',volume-nocopy']
    for name,value in ENV.items(): grader+=['--env',name+'='+value]
    grader+=[image,'-c','exec /bin/sleep infinity']
    return {'protocol':PROTOCOL,'taskId':descriptor['taskId'],'nonce':nonce,'imageId':image,'volumeName':volume,
            'volumeCreate':['volume','create','--driver','local','--label',LABEL+'='+nonce,'--opt','type=tmpfs','--opt','device=tmpfs','--opt','o='+OPTIONS['o'],volume],
            'seederCreate':seeder,'graderCreate':grader,'mountSubpaths':MOUNTS,'privateEnvironment':ENV,
            'privateMemoryBytes':memory,'privateCPUs':cpus,'originalVerifierSeconds':descriptor['originalResources']['verifier']['timeout_sec'],
            'privateSharedRamMaximumBytes':RAM,'sharedMemoryBytesEachRole':SHM,'seederMemoryMaximumBytes':SEEDER_MEMORY,
            'perRoleDevTmpfsMaximumBytes':64*1024**2,'physicalExtraRamReservationBytes':RAM+SEEDER_MEMORY+2*SHM+2*64*1024**2,
            'trustedPythonPath':runtime['pythonPath'],'trustedPythonSha256':runtime['pythonSha256'],'trustedPythonVersion':runtime['pythonVersion'],
            'sourcePin':task.pin(__file__),'hostBinds':[],'tmpfsMemoryChargedToPrivateCgroupProven':False,
            'actualReady':False,'DockerMutations':0,'modelCalls':0}


def validate_plan(value, descriptor, runtime):
    task.demand(value==plan(descriptor,runtime,value.get('nonce')), 'ram_plan', 'Task-specific RAM resources/argv/source differ')


def validate_volume(actual,value):
    task.demand(actual.get('Name')==value['volumeName'] and actual.get('Driver')=='local' and actual.get('Options')==OPTIONS
                and (actual.get('Labels') or {}).get(LABEL)==value['nonce'],'ram_volume','Exact owned shared512MiB volume differs')


def validate_container(actual,value,seeder=False):
    role='objrun-skb-ram-seeder-' if seeder else 'objrun-skb-private-'
    h=actual.get('HostConfig',{});c=actual.get('Config',{});required={'/objrun':''} if seeder else MOUNTS
    memory=SEEDER_MEMORY if seeder else value['privateMemoryBytes'];cpus=1 if seeder else value['privateCPUs']
    task.demand(re.fullmatch('[0-9a-f]{64}',actual.get('Id','')) and actual.get('Name')=='/'+role+value['nonce']
                and actual.get('Image')==c.get('Image')==value['imageId'] and (c.get('Labels') or {}).get(LABEL)==value['nonce'],
                'ram_container','Exact immutable private/seeder role/CID/image/nonce differs')
    task.demand(h.get('ReadonlyRootfs') is True and h.get('NetworkMode')=='none' and not h.get('Binds') and not h.get('Tmpfs')
                and h.get('Privileged') is False and not h.get('PidMode') and h.get('IpcMode')=='private'
                and not h.get('CapAdd') and not h.get('Devices') and not h.get('DeviceRequests') and not h.get('DeviceCgroupRules')
                and not h.get('UsernsMode') and not h.get('UTSMode') and c.get('User')=='0:0'
                and h.get('Memory')==h.get('MemorySwap')==memory and h.get('NanoCpus')==cpus*10**9 and h.get('ShmSize')==SHM
                and h.get('CapDrop')==['ALL'] and h.get('SecurityOpt') in (['no-new-privileges'],['no-new-privileges:true'])
                and h.get('LogConfig',{}).get('Type')=='none','ram_namespace','Private namespace/security/task-specific resources differ')
    mounts=h.get('Mounts',[]); actual_mounts=actual.get('Mounts',[])
    task.demand(len(mounts)==len(actual_mounts)==len(required),'ram_mounts','Unexpected private mount')
    seen=set()
    for m in mounts:
        target=m.get('Target'); options=m.get('VolumeOptions') or {}
        task.demand(target in required and target not in seen and m.get('Type')=='volume' and m.get('Source')==value['volumeName']
                    and m.get('ReadOnly',False) is False and options.get('NoCopy') is True and options.get('Subpath','')==required[target],
                    'ram_mounts','Every private path must use its exact owned shared-volume subpath')
        seen.add(target)
    seen=set()
    for m in actual_mounts:
        target=m.get('Destination')
        task.demand(target in required and target not in seen and m.get('Type')=='volume' and m.get('Name')==value['volumeName']
                    and m.get('Driver')=='local' and m.get('RW') is True,'ram_mounts','Actual daemon mount identity differs')
        seen.add(target)
    rows=c.get('Env',[])
    task.demand(all(isinstance(x,str) and '=' in x for x in rows) and len(rows)==len({x.split('=',1)[0] for x in rows}), 'ram_env','Duplicate private environment key')
    env=dict(x.split('=',1) for x in rows)
    task.demand(not any(k in env for k in ('TGENGIN_GRADER_TOKEN','DEEPSEEK_API_KEY','TGENGIN_CONFIG','OBJRUN_SKB_MOCK_KEY')),
                'ram_credentials','Host credential entered private image')
    if not seeder: task.demand(all(env.get(k)==v for k,v in ENV.items()),'ram_env','Private isolated interpreter/PATH/plugin environment differs')
    expected_cmd=value['seederCreate'][-2:] if seeder else ['-c','exec /bin/sleep infinity']
    task.demand(c.get('WorkingDir')==('/' if seeder else '/root') and c.get('Entrypoint')==['/bin/bash'] and c.get('Cmd')==expected_cmd,
                'ram_command','Idle/seeding trusted command differs')


def mount_probe_code(value, full_capacity):
    task.demand(type(full_capacity) is bool,'ram_probe_mode','Exact capacity mode required')
    return '''import errno,hashlib,json,os,sys
paths='''+repr(list(MOUNTS))+'''
rows=[];mounts=open('/proc/self/mountinfo').read().splitlines()
for path in paths:
 s=os.statvfs(path);matches=[l for l in mounts if l.split()[4]==path]
 rows.append({'path':path,'filesystem':matches[0].split(' - ',1)[1].split()[0] if len(matches)==1 else 'ambiguous','fsid':str(s.f_fsid),'device':str(os.stat(path).st_dev),'blockSize':s.f_frsize,'totalBlocks':s.f_blocks})
readonly=False
try:
 fd=os.open('/opt/objrun-root-ro-'''+value['nonce']+'''',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
except OSError as e:readonly=e.errno==errno.EROFS
full='''+repr(full_capacity)+'''
capacity=False;filled=0
if full:
 path='/tmp/objrun-capacity-'''+value['nonce']+'''';fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 try:
  block=b'x'*1048576
  while filled<=536870912:
   try:filled+=os.write(fd,block)
   except OSError as e:
    if e.errno==errno.ENOSPC:capacity=True;break
    raise
 finally:os.close(fd);os.unlink(path)
dev=os.statvfs('/dev');shm=os.statvfs('/dev/shm')
print(json.dumps({'protocol':''' + repr(PROTOCOL+'-native-mount-probe')+''','nonce':'''+repr(value['nonce'])+''','imageId':'''+repr(value['imageId'])+''','pythonPath':sys.executable,'pythonVersion':sys.version.split()[0],'pythonSha256':hashlib.sha256(open(sys.executable,'rb').read()).hexdigest(),'paths':rows,'rootReadonlyWriteRejected':readonly,'capacityProbeExecuted':full,'capacityBoundaryReachedAndRejected':capacity,'capacityBytesWritten':filled,'devTmpfsBytes':dev.f_frsize*dev.f_blocks,'shmTmpfsBytes':shm.f_frsize*shm.f_blocks,'namespaces':{n:os.readlink('/proc/self/ns/'+n) for n in ['pid','mnt','net']}}))
'''


def validate_mount_probe(probe,value,full_capacity):
    task.demand(probe.get('protocol')==PROTOCOL+'-native-mount-probe' and probe.get('nonce')==value['nonce'] and probe.get('imageId')==value['imageId']
                and probe.get('pythonPath')==value['trustedPythonPath'] and probe.get('pythonVersion')==value['trustedPythonVersion']
                and probe.get('pythonSha256')==value['trustedPythonSha256'] and probe.get('rootReadonlyWriteRejected') is True
                and probe.get('capacityProbeExecuted')==full_capacity,'ram_probe','Actual readonly/image/interpreter/capacity-mode graph differs')
    rows=probe.get('paths');task.demand(isinstance(rows,list) and len(rows)==len(MOUNTS),'ram_probe','All five RAM paths must be observed')
    identities=set();seen=set()
    for row in rows:
        task.demand(row.get('path') in MOUNTS and row['path'] not in seen and row.get('filesystem')=='tmpfs'
                    and re.fullmatch('[0-9]+',row.get('fsid','')) and re.fullmatch('[0-9]+',row.get('device',''))
                    and type(row.get('blockSize')) is int and type(row.get('totalBlocks')) is int
                    and row['blockSize']*row['totalBlocks']==RAM,'ram_backing','Actual shared512MiB backing differs')
        identities.add((row['fsid'],row['device']));seen.add(row['path'])
    task.demand(len(identities)==1 and (not full_capacity or probe.get('capacityBoundaryReachedAndRejected') is True)
                and type(probe.get('devTmpfsBytes')) is int and 0<=probe['devTmpfsBytes']<=64*1024**2
                and probe.get('shmTmpfsBytes')==SHM,'ram_capacity','Same-superblock/actual capacity/kernel mount proof incomplete')
