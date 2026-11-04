"""Project-owned remote Docker adapter. No daemon, image or container discovery cleanup."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
import time

ROOT = (Path(__file__).resolve().parents[4] / 'scripts')
PROJECT = ROOT.parents[1]
RUNTIME = json.loads((ROOT / 'control/remote-runtime.json').read_text())
RUN = RUNTIME['run']
DB = sqlite3.connect(str(ROOT / 'outputs/resource-ledger.sqlite'))
DB.execute('create table if not exists leases(id text primary key, acquired real, released real)')
DB.execute('create table if not exists containers(cid text primary key, session text, created real, disposed real, record text)')
DB.execute('create table if not exists events(at real, kind text, record text)')
DB.execute('create table if not exists networks(id text primary key, session text, created real, removed real)')
DB.commit()

def event(kind, record):
    DB.execute('insert into events values(?,?,?)', (time.time(), kind, json.dumps(record)))
    DB.commit()

def admission(op, data):
    active = DB.execute('select count(*) from leases where released is null').fetchone()[0]
    if op == 'release':
        DB.execute('update leases set released=? where id=? and released is null', (time.time(), data['lease']))
        DB.commit(); event('release', data)
        return {'released': True}
    mem = dict((k, int(v.split()[0])*1024) for k,v in (x.split(':',1) for x in Path('/proc/meminfo').read_text().splitlines()))
    disk = shutil.disk_usage(RUNTIME['dockerRoot'])
    # Hold a full quota even when its writable layer is still mostly empty.
    disk_slots = max(0, int((disk.free - 12*1024**3) // (10*1024**3)))
    memory_slots = max(0, int((mem['MemAvailable'] - 16*1024**3) // (4*1024**3)))
    cpu_slots = max(0, int((os.cpu_count()-os.getloadavg()[0]-16)//2))
    capacity = min(32, disk_slots, memory_slots, cpu_slots)
    record = {'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()), 'active':active,'capacity':capacity,'taskCap':32,'modelCap':32,
              'diskFreeBytes':disk.free,'memAvailableBytes':mem['MemAvailable'],'load1':os.getloadavg()[0],
              'perTask':{'cpus':2,'memoryMiB':4096,'storageMiB':10240},'diskReserveGiB':12}
    if op == 'admit':
        # Count all live leases conservatively against free disk and memory.
        if active >= capacity:
            return {**record,'admitted':False}
        DB.execute('insert into leases values(?,?,null)', (data['lease'],time.time())); DB.commit()
        event('admit', {**record, **data, 'activeAfter':active+1})
        return {**record,'admitted':True}
    return record

class EnvironmentConfig:
    def __init__(self, **kw): self.__dict__.update(kw)

class TrialPaths:
    def __init__(self, path): self.trial_dir = Path(path)
    def mkdir(self): self.trial_dir.mkdir(parents=True, exist_ok=True)

async def docker(*args, timeout=120):
    env = {k:v for k,v in os.environ.items() if not k.endswith('_API_KEY')}
    env['DOCKER_HOST'] = RUNTIME['dockerHost']
    p = await asyncio.create_subprocess_exec('/usr/local/bin/docker', *map(str,args), cwd=PROJECT, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(p.communicate(),timeout)
    except BaseException:
        p.kill(); await p.wait(); raise
    if p.returncode:
        raise RuntimeError('OwnedDockerCommandFailed:'+str(args[0])+':'+err.decode(errors='replace')[-1200:])
    return out.decode(errors='replace')

class DockerEnvironment:
    def __init__(self, environment_dir, environment_name, session_id, trial_paths, task_env_config):
        self.sid=session_id; self.paths=trial_paths; self.resources=task_env_config
        self.directory=Path(environment_dir); self.cid=None;self.network=None
    async def owned(self):
        if not self.cid: raise RuntimeError('NoOwnedContainer')
        info=json.loads(await docker('inspect',self.cid))[0]
        labels=info['Config']['Labels'] or {}
        if labels.get('tpe.run')!=RUN or labels.get('tpe.session')!=self.sid or info['Id']!=self.cid:
            raise RuntimeError('ContainerOwnershipMismatch')
        return info
    async def start(self, force_build=False):
        resources=vars(self.resources)
        if (resources['cpus'],resources['memory_mb'],resources['storage_mb'])!=(2,4096,10240):
            raise RuntimeError('UnexpectedOfficialResourceQuota')
        info=json.loads(await docker('info','--format','{{json .}}'))
        if info['DockerRootDir']!=RUNTIME['dockerRoot'] or info['Driver']!='overlay2':
            raise RuntimeError('WrongPrivateDockerDaemon')
        dockerfile=hashlib.sha256((self.directory/'Dockerfile').read_bytes()).hexdigest()
        pin=RUNTIME['images'][self.directory.parent.name]
        if pin['dockerfileSha256']!=dockerfile:raise RuntimeError('FrozenDockerfileMismatch')
        image=pin['imageId']
        self.network=(await docker('network','create','--driver','bridge','--label','tpe.run='+RUN,
            '--label','tpe.session='+self.sid,self.sid+'-net')).strip()
        DB.execute('insert into networks values(?,?,?,null)',(self.network,self.sid,time.time()));DB.commit()
        self.cid=(await docker('create','--name',self.sid,'--label','tpe.run='+RUN,'--label','tpe.session='+self.sid,
            '--label','tpe.owner=theophyseval','--label','tpe.task='+self.directory.parent.name,'--label','tpe.arm='+getattr(self,'arm','control'),'--cpus','2','--memory','4096m','--memory-swap','4096m',
            '--storage-opt','size=10240M','--network',self.network,'--cap-drop','NET_RAW','--security-opt','no-new-privileges',
            '--env','HTTP_PROXY='+RUNTIME['containerProxy'],'--env','HTTPS_PROXY='+RUNTIME['containerProxy'],
            '--env','http_proxy='+RUNTIME['containerProxy'],'--env','https_proxy='+RUNTIME['containerProxy'],
            '--env','NO_PROXY=localhost,127.0.0.1',image,'sleep','infinity')).strip()
        record=await self.owned()
        DB.execute('insert into containers values(?,?,?,null,?)',(self.cid,self.sid,time.time(),json.dumps(record))); DB.commit()
        (self.paths.trial_dir/'docker-inspect.json').write_text(json.dumps(record,indent=2))
        await docker('start',self.cid)
    async def exec(self, command, user='65534:65534', cwd=None, timeout_sec=120):
        await self.owned()
        args=['exec','--user',user]
        if cwd:args+=['--workdir',cwd]
        env={k:v for k,v in os.environ.items() if not k.endswith('_API_KEY')};env['DOCKER_HOST']=RUNTIME['dockerHost']
        p=await asyncio.create_subprocess_exec('/usr/local/bin/docker',*args,self.cid,'bash','-lc',command,
            cwd=PROJECT,env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try: out,err=await asyncio.wait_for(p.communicate(),timeout_sec)
        except BaseException: p.kill();await p.wait();raise
        return SimpleNamespace(stdout=out.decode(errors='replace'),stderr=err.decode(errors='replace'),return_code=p.returncode)
    async def _run_docker_compose_command(self, args, check=True):
        if args not in [['pause'],['unpause']]:raise RuntimeError('UnsupportedOwnedOperation')
        await self.owned();return await docker(args[0],self.cid)
    async def upload_dir(self, source, target):
        await self.owned();await docker('cp',str(source)+'/.',self.cid+':'+target)
    async def download_dir(self, source, target):
        await self.owned();await docker('cp',self.cid+':'+source+'/.',str(target),timeout=180)
    async def stop(self, delete=True):
        await self.owned();await docker('rm','-f',self.cid)
        DB.execute('update containers set disposed=? where cid=?',(time.time(),self.cid));DB.commit()
        network=json.loads(await docker('network','inspect',self.network))[0]
        if network['Labels'].get('tpe.run')!=RUN or network['Labels'].get('tpe.session')!=self.sid:
            raise RuntimeError('NetworkOwnershipMismatch')
        await docker('network','rm',self.network)
        DB.execute('update networks set removed=? where id=?',(time.time(),self.network));DB.commit()
