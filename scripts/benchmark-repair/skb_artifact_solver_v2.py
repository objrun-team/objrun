"""Owned original-resource solver, frozen six-tool RPC and source-pinned oracle."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import shutil
import time
import threading
import uuid
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_transport_v2 as transport
import skb_artifact_solver_plan_v2 as solver_plan
import skb_artifact_ram_executor_v2 as grader
import skb_artifact_capture_v2 as capture
import skb_artifact_build_storage_v1 as build_storage

PROTOCOL='skillsbench-task-owned-solver-execution-v2'


class Solver:
    def __init__(self,descriptor_pin,layout_pin):
        self.dp,self.lp=descriptor_pin,layout_pin;self.descriptor=task.read_json(descriptor_pin);task.validate_descriptor(self.descriptor)
        self.layout=task.read_json(layout_pin);storage.validate_descriptor(self.layout)
        self.nonce=uuid.uuid4().hex;self.plan=solver_plan.plan(self.descriptor,self.nonce);self.root=Path(self.layout['storePhysical'])
        self.box=Path(self.layout['directories']['stand'])/('solver-'+self.nonce);storage.ordinary(self.box.parent,self.root);self.box.mkdir()
        self.env=transport.sanitized_environment(self.layout,storage)
        self.sources=[task.pin(x.__file__) for x in (task,storage,transport,solver_plan,capture,build_storage,grader)]+[task.pin(__file__),*transport.component_pins()]
        self.snapshots=[];src=self.box/'executed-source';src.mkdir()
        for p in self.sources:self.snapshots.append({'originalPin':p,'snapshotPin':grader.fresh(src/Path(p['path']).name,Path(p['path']).read_bytes(),self.root)})
        self.plan_pin=grader.fresh(self.box/'solver-plan.json',task.canonical(self.plan),self.root)
        self.serial=0;self.records=[];self.cid=None;self.running=False;self.closed=False;self.create_attempted=False;self.writable=0;self.tool_no=0
        self.deadline=None;self.started=None;self.stopped_at=None;self.capture_pins=[];self.cold_mode=None
        self.operation_lock=threading.RLock();self.timer=None;self.expired=False;self.deadline_fault=None
        self.engine_created_at=None
        self.guard_lock=threading.RLock();self.guard_observed=None;self.guard_at=0.0;self.command_reserve=0

    def guard(self,amount=0,closing=False):
        with self.guard_lock:
            if self.guard_observed is None or time.monotonic()-self.guard_at>=0.5:
                self.guard_observed=build_storage.observe(self.layout);self.guard_at=time.monotonic()
            observed=self.guard_observed;amount=max(amount,self.command_reserve)
        task.demand(observed['allocatedEnvelopeBytes']+amount<=storage.STORE_CAP-(0 if closing else 2*1024**2),'solver_store_cap','Owned D evidence budget exceeded')
        free={k:shutil.disk_usage(k+':/').free for k in ('C','D','F')}
        task.demand(free['D']>=storage.D_MIN+amount,'solver_D_floor','Actual D reserve cannot retain next command')
        if not closing:
            state=storage.assess_resources(self.layout,free,self.cid is not None,self.writable,
                solver_writable_limit=self.descriptor['solverWritableBudgetBytes'] if self.cid else None)
            task.demand(state['admitted'],'solver_resources','Actual original task writable allowance/resources not reserved')

    def command(self,*args,timeout=30,cap=1024**2,checked=True,closing=False):
        self.serial+=1;task.demand(self.serial<=4096,'solver_commands','Bounded task command limit exceeded')
        if not closing:
            task.demand([task.pin(p['path']) for p in self.sources]==self.sources,'solver_source','Frozen solver producer source changed')
            task.verify_pin(self.dp);task.verify_pin(self.lp)
        argv=[str(transport.DOCKER),'--host',transport.DOCKER_HOST,*args]
        with self.guard_lock:
            self.guard_observed=None;self.command_reserve=cap+256*1024+1024**2
        try:row,out,err=transport.bounded_child(argv,self.env,self.box,self.serial,lambda n:self.guard(n,closing),timeout,cap)
        finally:
            with self.guard_lock:self.guard_observed=None;self.command_reserve=0
            path=self.box/('command-%03d.json'%self.serial)
            if path.exists():self.records.append({'recordPin':task.pin(path),'argv':argv,'maximumStdoutBytes':cap,'closing':closing})
        transport.validate_command_record(self.records[-1]['recordPin'],os.getpid(),self.serial,argv,self.box,cap)
        if checked:task.demand(row['exitCode']==0,'solver_docker','Actual owned solver command failed; raw preserved')
        return row,out,err

    def inspect(self,stopped=None,closing=False):
        _,raw,_=self.command('container','inspect','--size',self.cid or self.plan['name'],closing=closing)
        rows=json.loads(raw);task.demand(len(rows)==1,'solver_identity','One exact solver inspect required');actual=rows[0]
        h=actual['HostConfig'];c=actual['Config'];labels=c.get('Labels') or {}
        task.demand(actual['Name']=='/'+self.plan['name'] and actual['Image']==c['Image']==self.plan['imageId']
                    and (not self.cid or actual['Id']==self.cid) and labels.get('objrun.skb.task-id')==self.descriptor['taskId']
                    and labels.get('objrun.skb.instance-nonce')==self.nonce and labels.get('objrun.skb.role')=='solver'
                    and h['Memory']==h['MemorySwap']==self.plan['memoryBytes'] and h['NanoCpus']==self.plan['cpus']*10**9
                    and h['NetworkMode']=='bridge' and not h.get('Binds') and not h.get('Mounts') and not h['Privileged']
                    and h['CapDrop']==['ALL'] and not h.get('PidMode') and h['LogConfig']['Type']=='none','solver_identity','Exact original-resource owned solver namespace differs')
        env=c.get('Env') or []
        task.demand(not any(x.partition('=')[0] in ('TGENGIN_GRADER_TOKEN','TGENGIN_CONFIG','DEEPSEEK_API_KEY','TGENGIN_PUBLISHER_TOKEN','OBJRUN_SKB_MOCK_KEY') for x in env),'solver_credential','Private credential entered solver')
        self.writable=actual.get('SizeRw');task.demand(type(self.writable) is int and 0<=self.writable<=self.plan['solverWritableMaximumBytes'],'solver_disk','Original solver writable bound exceeded')
        if stopped is not None:task.demand(actual['State']['Running']==(not stopped) and not actual['State']['Paused'] and not actual['State']['Dead'],'solver_state','Actual solver running/frozen state differs')
        return actual

    def create(self,bootstrap=True):
        row,out,err=self.command('container','inspect',self.plan['name'],checked=False)
        task.demand(grader.missing_target(row['exitCode'],out,err,'container',self.plan['name']),'solver_fresh','Exact owned new solver name not fresh')
        self.create_attempted=True;self.command(*self.plan['createArgv']);self.cid=self.inspect()['Id'];self.command('start',self.cid);self.running=True
        self.inspect(False)
        if bootstrap:
            self.command('exec',self.cid,'mkdir','-p','/rt-lib')
            for item in self.plan['runtime']['assets']:
                task.verify_pin(item['sourcePin'],256*1024**2);self.command('cp',item['sourcePin']['path'],self.cid+':'+item['containerPath']);task.verify_pin(item['sourcePin'],256*1024**2)
            self.command('exec',self.cid,'chmod','+x','/rt-node');self.inspect(False)
        self.started=int(time.time()*1000);self.deadline=self.started+self.plan['agentSeconds']*1000
        self.owner_pin=self.save_owner('owner-created.json')
        self.timer=threading.Timer(self.plan['agentSeconds'],self.expire);self.timer.daemon=True;self.timer.start()
        return {'ownedContainerID':self.cid,'ownerPin':self.owner_pin,'startedAtUnixMs':self.started,'deadlineUnixMs':self.deadline}

    def save_owner(self,name):
        value={'protocol':'skillsbench-solver-owner-v1','role':'solver','taskId':self.descriptor['taskId'],'instanceNonce':self.nonce,
            'containerID':self.cid,'imageId':self.plan['imageId'],'taskDescriptorPin':self.dp,'storageDescriptorPin':self.lp,
            'sourceSnapshots':self.snapshots,'actorPid':os.getpid(),'parentActorClosureRequired':True,
            'startedAtUnixMs':self.started,'deadlineUnixMs':self.deadline,'stoppedAtUnixMs':self.stopped_at,'coldMode':self.cold_mode,
            'deadlineExpired':self.expired,'deadlineFault':self.deadline_fault,'engineCreatedAtUnixMs':self.engine_created_at}
        return grader.fresh(self.box/name,task.canonical(value),self.root)

    def call(self,tool,args,timeout=None):
        with self.operation_lock:
            try:return self.call_locked(tool,args,timeout)
            except BaseException:
                if self.running:self.freeze(True)
                raise
            finally:
                if self.deadline and int(time.time()*1000)>=self.deadline:self.expire()

    def call_locked(self,tool,args,timeout=None):
        task.demand(tool in solver_plan.TOOLS and isinstance(args,dict) and self.running and not self.expired and self.deadline>int(time.time()*1000),'solver_tool','Exact six tools only within original task deadline')
        self.inspect(False);self.tool_no+=1
        raw=task.canonical({'tool':tool,'args':args});task.demand(len(raw)<=4*1024**2,'solver_tool_request','Tool request exceeds4MiB')
        request=grader.fresh(self.box/('tool-%04d.json'%self.tool_no),raw,self.root);remote='/tmp/objrun-tool-'+self.nonce+'-'+str(self.tool_no)+'.json'
        self.command('cp',request['path'],self.cid+':'+remote)
        remaining=(self.deadline-int(time.time()*1000))/1000
        task.demand(remaining>0,'solver_deadline','No tool may start after preparation exhausts the original deadline')
        limit=min(remaining,timeout) if timeout else remaining
        row,out,err=self.command('exec','--env','LD_LIBRARY_PATH=/rt-lib',self.cid,'/rt-node','-e',solver_plan.ONE_TOOL_WRAPPER,
            remote,request['sha256'],str(max(1,int(limit*1000)-1000)),timeout=limit,cap=8*1024**2,checked=False)
        self.inspect(False)
        task.demand(row['exitCode'] in (0,1),'solver_tool','Actual frozen tool RPC failed unexpectedly')
        result=json.loads(out)
        if result.get('isError') and any('deadline exceeded' in x.get('text','') for x in result.get('content',[])):
            self.freeze(True);self.expired=True
        if result.get('isError'):return {'error':''.join(x.get('text','') for x in result.get('content',[])) or 'candidate tool error'}
        if 'structuredContent' in result:return result['structuredContent']
        text=''.join(x.get('text','') for x in result.get('content',[]))
        try:return json.loads(text)
        except ValueError:return text

    def freeze(self,closing=False):
        with self.operation_lock:
            if self.running:
                self.inspect(False,closing=closing);self.command('stop','--time','0',self.cid,closing=closing)
                self.running=False;self.stopped_at=int(time.time()*1000)
            actual=self.inspect(True,closing=closing);task.demand(actual['State']['Pid']==0,'solver_freeze','Actual solver process remains after freeze')
            return self.save_owner('owner-stopped-'+uuid.uuid4().hex+'.json')

    def expire(self):
        with self.operation_lock:
            if self.closed:return
            self.expired=True
            try:
                if self.running:self.freeze(True)
            except BaseException as e:self.deadline_fault={'type':type(e).__name__,'kind':getattr(e,'kind',None)}

    def bind_engine_deadline(self,created_at,seconds):
        with self.operation_lock:
            task.demand(type(created_at) is int and 0<created_at<=int(time.time()*1000) and seconds==self.plan['agentSeconds'],
                        'solver_engine_deadline','Exact original engine task creation and resource duration required')
            task.demand(self.engine_created_at in (None,created_at),'solver_engine_deadline','Engine deadline cannot be rebound')
            if self.engine_created_at is not None:return
            self.engine_created_at=created_at;self.deadline=created_at+seconds*1000
            if self.timer:self.timer.cancel()
            remaining=(self.deadline-int(time.time()*1000))/1000
            if remaining<=0:self.expire();return
            self.timer=threading.Timer(remaining,self.expire);self.timer.daemon=True;self.timer.start()
            self.save_owner('owner-engine-deadline.json')

    def capture(self,final=False):
        owner=self.freeze()
        folder=Path(self.layout['directories']['captures'])/('capture-'+uuid.uuid4().hex)
        out=capture.capture_artifacts(self.dp,owner,folder,self.layout,task.pin(transport.DOCKER),self.lp)
        self.capture_pins.append(out)
        return out

    def resume(self):
        task.demand(not self.closed and not self.expired and self.deadline>int(time.time()*1000) and self.cid and not self.running,'solver_resume','Only this actually stopped owned solver within its deadline may resume')
        self.command('start',self.cid);self.running=True;self.inspect(False)

    def cold(self,mode):
        with self.operation_lock:return self.cold_locked(mode)

    def cold_locked(self,mode):
        task.demand(mode in ('oracle','empty','wrong') and self.tool_no==0,'solver_cold','Source-pinned controls only on fresh solver')
        self.cold_mode=mode
        if mode=='oracle':
            metadata=task.metadata(self.descriptor['taskId']);self.command('exec',self.cid,'mkdir','-p','/oracle')
            for row in metadata['oracleSourceMetadata']['files']:
                source=Path(metadata['oracleSourceMetadata']['root'])/row['path'];p=task.pin(source)
                task.demand(p['sha256']==row['sha256'] and p['bytes']==row['bytes'],'solver_oracle','Exact original oracle source changed')
                target='/oracle/'+row['path'];parent=str(Path(target).parent).replace('\\','/')
                self.command('exec',self.cid,'mkdir','-p',parent);self.command('cp',str(source),self.cid+':'+target);task.verify_pin(p,64*1024**2)
            self.command('exec',self.cid,'/bin/bash','/oracle/solve.sh',timeout=self.plan['agentSeconds'],cap=16*1024**2)
        else:
            # Ensure no image-preseeded output remains. An empty regular file
            # forces original parsers to report real failures instead of skips.
            path=self.descriptor['outputArtifacts'][0]['containerPath']
            payload=b'' if mode=='empty' else (b'"unterminated\n' if self.descriptor['taskId']=='lab-unit-harmonization' else b'objrun intentional malformed control\n')
            code='import pathlib;p=pathlib.Path('+repr(path)+');p.write_bytes('+repr(payload)+')'
            py='/usr/local/bin/python3' if self.descriptor['taskId'] in ('earthquake-plate-calculation','econ-detrending-correlation','lab-unit-harmonization') else '/usr/bin/python3'
            self.command('exec',self.cid,py,'-I','-B','-c',code)
        return self.capture(True)

    def close(self):
        with self.operation_lock:return self.close_locked()

    def close_locked(self):
        if self.timer:self.timer.cancel()
        fault=None
        try:
            if self.create_attempted:
                row,out,err=self.command('container','inspect',self.cid or self.plan['name'],checked=False,closing=True)
                if row['exitCode']==0:
                    actual=self.inspect(closing=True);self.cid=actual['Id'];self.command('rm','-f',self.cid,closing=True)
                    row,out,err=self.command('container','inspect',self.cid,checked=False,closing=True)
                task.demand(grader.missing_target(row['exitCode'],out,err,'container',self.cid or self.plan['name']),'solver_close','Actual exact owned solver absence not proven')
            self.closed=True;self.running=False
        except BaseException as e:fault={'type':type(e).__name__,'kind':getattr(e,'kind',None)}
        value={'protocol':PROTOCOL,'taskId':self.descriptor['taskId'],'taskDescriptorPin':self.dp,'storageDescriptorPin':self.lp,
            'actorPid':os.getpid(),'instanceNonce':self.nonce,'containerID':self.cid,'solverPlanPin':self.plan_pin,'sourceSnapshots':self.snapshots,
            'commandRecords':self.records,'capturePins':self.capture_pins,'ownedClosed':self.closed,'fault':fault,'parentActorClosureRequired':True,
            'completedAtUtc':datetime.now(timezone.utc).isoformat(),'modelCalls':0,'paidLockReleased':False,'scoreCertificate':False}
        return grader.fresh(self.box/'solver-closed.json',task.canonical(value),self.root)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('task-descriptor','storage-descriptor'):
        p.add_argument('--'+k,type=Path,required=True);p.add_argument('--'+k+'-sha256',required=True)
    p.add_argument('--cold',choices=('oracle','empty','wrong'),required=True);a=p.parse_args();pins=[]
    for k in ('task_descriptor','storage_descriptor'):
        value=task.pin(getattr(a,k).resolve());task.demand(value['sha256']==getattr(a,k+'_sha256'),'solver_cli','Exact fixed CLI inputs required');pins.append(value)
    solver=Solver(*pins);cp=None;fault=None
    try:solver.create(False);cp=solver.cold(a.cold)
    except BaseException as e:fault={'type':type(e).__name__,'kind':getattr(e,'kind',None),'detail':str(e)[:1024]}
    finally:closed=solver.close()
    print(json.dumps({'capturePin':cp,'closurePin':closed,'fault':fault,'modelCalls':0}),flush=True)
    raise SystemExit(1 if fault or not solver.closed else 0)


if __name__=='__main__':main()
