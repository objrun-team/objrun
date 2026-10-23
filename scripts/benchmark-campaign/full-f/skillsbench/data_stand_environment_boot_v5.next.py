"""Protected single-solver ordinary-output stand for the full F scheduler.

Only source-bound tasks with actual original collection/oracle controls are
admitted. Code-execution task policies require a different isolated adapter.
This stand never mounts a host directory in the model's container.
"""
import argparse
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import threading
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare import ROOT,HOME,public,save
from build_environment import DOCKER,ENV
from ordinary_artifacts import Policy,parse_daemon_tar,evaluation_key
from bounded_child import run as bounded_run
from snapshot_function_adapter import evaluate_snapshot
from stream_code_digest import capture as capture_code_digest
from task_skills import deploy as deploy_skills
from docker_mutation_ack import require as require_docker_mutation_ack

sys.path.insert(0,str(ROOT/'scripts/benchmark-repair'))
from skb_artifact_solver_plan_v2 import runtime_manifest,ONE_TOOL_WRAPPER

class Stand:
    def __init__(self,config):
        self.config=config;self.home=Path(config['output'])/'stand';self.home.mkdir(parents=True)
        self.token=os.environ['TGENGIN_GRADER_TOKEN'];assert len(self.token)>=32
        self.lock=threading.RLock();self.current=None;self.latest=None;self.serial=0;self.database=None;self.database_task=None;self.timer=None
        self.assets=runtime_manifest()
    def command(self,args,timeout=30,stdin=None,stdout_limit=16*1024**2):
        self.serial+=1;prefix=self.home/('command-%06d'%self.serial);started=int(time.time()*1000)
        outcome=bounded_run([DOCKER,*args],ENV,prefix.with_suffix('.stdout'),prefix.with_suffix('.stderr'),timeout,stdin,stdout_limit=stdout_limit)
        pin=save(prefix.with_suffix('.json'),{'argv':[DOCKER,*args],**outcome,'parentPid':os.getpid(),'startedAtUnixMs':started,
            'endedAtUnixMs':int(time.time()*1000),'stdoutPin':public.pin(prefix.with_suffix('.stdout')),
            'stderrPin':public.pin(prefix.with_suffix('.stderr')),'modelCalls':0})
        if outcome['exitCode'] or outcome['faults']:raise RuntimeError('Owned Docker operation failed: '+pin['path'])
        output=prefix.with_suffix('.stdout').read_bytes()
        require_docker_mutation_ack(args,output)
        return output
    def identify(self,place):
        assert isinstance(place,str)
        mapped=[row['taskId'] for row in self.config['schedule'] if row.get('id') and 'skb:'+row['id']==place]
        if mapped:
            assert len(mapped)==1 and mapped[0] in self.config['taskReadiness'];return mapped[0]
        prefix='skb:'+self.config['runId']+'/skillsbench/F/0/'
        assert place.startswith(prefix)
        tid=place[len(prefix):];assert tid in self.config['taskReadiness'] and any(r['taskId']==tid and not r.get('id','').startswith('skb-') for r in self.config['schedule'])
        return tid
    def native_source_digest(self,cid,path,maximum_bytes,timeout):
        self.serial+=1;prefix=self.home/('command-%06d'%self.serial);argv=[DOCKER,'cp','-L',cid+':'+path,'-']
        record=capture_code_digest(argv,ENV,prefix.with_suffix('.stderr'),timeout,maximum_bytes)
        diagnostic=prefix.with_suffix('.stderr').read_text(errors='replace').strip()
        absent=record['exitCode']!=0 and not record['faults'] and diagnostic=='Error response from daemon: Could not find the file '+path+' in container '+cid
        record.update(argv=argv,parentPid=os.getpid(),stderrPin=public.pin(prefix.with_suffix('.stderr')),modelCalls=0,sourceAbsent=absent)
        pin=save(prefix.with_suffix('.json'),record)
        if absent:return {'sourceAbsent':True,'sourceSha256':hashlib.sha256(b'').hexdigest(),'sourceBytes':0,'receiptPin':pin}
        if record['exitCode'] or record['faults'] or not record['sourceDigest']:raise RuntimeError('Owned streamed source capture failed: '+pin['path'])
        return {**record['sourceDigest'],'sourceAbsent':False,'receiptPin':pin}
    def create(self,body):
        tid=self.identify(body['place'])
        if self.current:
            assert self.current['place']==body['place'];return
        proof=self.config['taskReadiness'][tid]
        for key in ('builtImagesPin','controlPin'):
            assert public.pin(Path(proof[key]['path']))==proof[key]
        built=json.loads(Path(proof['builtImagesPin']['path']).read_bytes());control=json.loads(Path(proof['controlPin']['path']).read_bytes())
        if proof.get('adapter')=='acc-independent-v1':
            assert tid=='adaptive-cruise-control'
            from prepare import VENDOR
            assert public.tree(VENDOR/'tasks'/tid/'environment')==built['officialEnvironmentTree']
            assert control['controlsPassed'] and control['ownedContainersRemaining']==0 and [x['reward'] for x in control['cases']]==[0,1,0]
            prepared=json.loads(Path(proof['preparedImageResultPin']['path']).read_bytes())
            assert prepared['actualCollection']['taskId']==tid
            assert prepared['builtImagesPin']==proof['builtImagesPin'] and control['preparedImageResultPin']==proof['preparedImageResultPin']
            for pin in proof['packageSourcePins']+[proof['runtimeCorePin'],proof['snapshotAdapterPin'],proof['bundlePin'],proof['preparedImageResultPin'],proof['runtimeAcceptancePin']]:assert public.pin(Path(pin['path']))==pin
            accepted=json.loads(Path(proof['runtimeAcceptancePin']['path']).read_bytes())
            assert accepted['verified'] and accepted['ownedContainersRemaining']==0 and accepted['modelCalls']==0 and accepted['candidateSnapshotUsedForTrustedGrader'] is False
            assert [x['reward'] for x in accepted['steps']]==[0,1,0]
            assert prepared['actualCollection']['complete'] and len(prepared['actualCollection']['nodeIds'])==12
            image=json.loads(self.command(['image','inspect',proof['privateImageId']]))[0]
            assert image['Id']==proof['privateImageId'] and image['Id']!=built['candidateImageId']
        else:
            assert built['taskId']==control['taskId']==tid and control['controlsPassed'] and control['ownedContainersRemaining']==0
            assert control['builtImagesPin']==proof['builtImagesPin']
        if proof.get('adapter')=='wyckoff-function-native-v1':
            assert tid=='crystallographic-wyckoff-position-analysis' and built['protocol']=='skillsbench-full-f-isolated-code-images-v1'
            assert control['protocol']=='skillsbench-full-f-isolated-code-controls-v1'
            for pin in built['sourcePins']+control['sourcePins']:assert public.pin(Path(pin['path']))==pin
        elif proof.get('adapter')!='acc-independent-v1':
            runner=Path(built['privateRunnerSourcePin']['path'])
            assert (runner.parent==ROOT/'scripts/benchmark-campaign/full-f/skillsbench' and runner.name in ('private_eval.py','private_eval_v2.py','private_eval_multi.py','private_eval_score.py')) or (tid=='manufacturing-codebook-normalization' and runner==ROOT/'scripts/benchmark-campaign/full-f/skillsbench/next-segment/private_eval_codebook_wide_v1.next.py' and built['dataArtifactPolicy']['maximumBytes']==64*1024**2)
            assert public.pin(runner)==built['privateRunnerSourcePin']
        row=next(r for r in self.config['schedule'] if r['taskId']==tid);e=row['originalResources']['environment'];nonce=uuid.uuid4().hex
        network={'public':'bridge','no-network':'none'}[e['network_mode']]
        boot_started=time.monotonic()
        boot_seconds=e['build_timeout_sec'];assert boot_seconds>0
        def boot_command(args,timeout=None,stdin=None,stdout_limit=16*1024**2):
            remaining=boot_seconds-(time.monotonic()-boot_started)
            if remaining<=0:raise TimeoutError('original_environment_boot_budget_expired')
            return self.command(args,min(remaining,timeout if timeout is not None else remaining),stdin,stdout_limit)
        cid=boot_command(['create','--pull','never','--label','objrun.skb.role=full-f-solver','--label','objrun.skb.nonce='+nonce,
            '--network',network,'--cap-drop','ALL','--security-opt','no-new-privileges','--memory',str(e['memory_mb']*1024**2),
            '--memory-swap',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus']),'--workdir',row['workdir'],
            '--entrypoint','/bin/bash',built['candidateImageId'],'-c','exec sleep infinity']).decode().strip()
        self.current={'place':body['place'],'taskId':tid,'cid':cid,'nonce':nonce,'built':built,'control':control,'row':row,'mutation':0,
            'deadline':int(body.get('deadlineUnixMs',time.time()*1000+row['taskSeconds']*1000)),'running':False}
        try:
            boot_command(['start',cid]);self.current['running']=True
            self.current['skillsDeploymentPin']=deploy_skills(boot_command,cid,tid,self.home)
            boot_command(['exec',cid,'mkdir','-p','/rt-lib'])
            for asset in self.assets['assets']:
                pin=asset['sourcePin'];assert public.pin(Path(pin['path']))==pin
                boot_command(['cp',pin['path'],cid+':'+asset['containerPath']])
            boot_command(['exec',cid,'chmod','+x','/rt-node'])
            self.arm_deadline()
        except BaseException:self.stop();raise
    def call(self,body):
        with self.lock:
            self.create(body);c=self.current
            self.refresh_deadline()
            if body.get('op')=='ping':return {'alive':True,'ownedContainerID':c['cid'],'skillsDeploymentPin':c['skillsDeploymentPin'],'environmentAudit':{'forbiddenHostKeysPresent':False,'standTokenPresent':False}}
            assert body['tool'] in self.assets['toolNames'] and time.time()*1000<c['deadline']
            c['mutation']+=1;self.latest=None
            remaining=max(1,int(c['deadline']-time.time()*1000));raw=json.dumps({'tool':body['tool'],'args':body.get('args',{})}).encode()
            assert len(raw)<=4*1024**2
            request=self.home/('request-'+uuid.uuid4().hex+'.json');request.write_bytes(raw);target='/tmp/objrun-tool-'+uuid.uuid4().hex+'.json'
            self.command(['cp',str(request),c['cid']+':'+target])
            result=self.command(['exec','-e','LD_LIBRARY_PATH=/rt-lib',c['cid'],'/rt-node','-e',ONE_TOOL_WRAPPER,target,hashlib.sha256(raw).hexdigest(),str(remaining)],remaining/1000+30)
            assert len(result)<=8*1024**2
            return json.loads(result)
    def grade(self,body,kind):
        with self.lock:
            assert self.current and body['place']==self.current['place'];c=self.current
            answer=str(body.get('said',''));key=(c['place'],c['mutation'],answer)
            if kind=='passed' and self.latest and self.latest[0]==key:return self.latest[1]
            if c['running']:self.command(['stop','-t','1',c['cid']]);c['running']=False
            if self.config['taskReadiness'][c['taskId']].get('adapter')=='acc-independent-v1':
                return self.grade_acc(c,key,answer)
            if self.config['taskReadiness'][c['taskId']].get('adapter')=='wyckoff-function-native-v1':
                return self.grade_native(c,key,answer)
            try:
                artifacts=[];missing=[]
                policies=c['built'].get('outputPolicies',[{'path':c['built']['dataArtifactPolicy']['output'],'kind':'file','maximumFiles':1,'maximumBytes':8*1024**2}])
                for output in policies:
                    path=output['path']
                    try:
                        raw=self.command(['cp',c['cid']+':'+path,'-'],stdout_limit=output['maximumBytes']+(output['maximumFiles']+8)*2048)
                        envelope=parse_daemon_tar(raw,Policy(c['taskId'],path,path,output['kind'],output['maximumBytes'],output['maximumFiles'],True,'csv' if c['built']['dataArtifactPolicy'].get('format')=='CSV' and output['kind']=='file' else None))
                        artifacts += [{'path':f['destination'],'base64':base64.b64encode(f['body']).decode(),'sha256':f['sha256']} for f in envelope['files']]
                    except RuntimeError:
                        # Only an exact daemon absent-file diagnostic is a missing
                        # answer. Other failures, including stream limits, remain
                        # recorded capture faults and cannot turn into a pass.
                        diagnostic=(self.home/('command-%06d.stderr'%self.serial)).read_text(errors='replace').strip()
                        expected='Error response from daemon: Could not find the file '+path+' in container '+c['cid']
                        if diagnostic!=expected:raise
                        missing.append(path)
                built=c['built'];e=c['row']['originalResources']['environment'];gid=None
                try:
                    gid=self.command(['create','-i','--pull','never','--read-only','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
                        '--label','objrun.skb.role=full-f-private-grade','--memory',str(e['memory_mb']*1024**2),'--memory-swap',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus']),
                        '--tmpfs','/logs/verifier:rw,nosuid,nodev,noexec,size=64m','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=64m',
                        *[arg for parent in built.get('artifactTmpfsParents',[built['artifactTmpfsParent']]) for arg in ['--tmpfs',parent+':rw,nosuid,nodev,noexec,size='+str(built['artifactTmpfsBytes'])]],
                        '--workdir',built['workingDirectory'],built['privateImageId']]).decode().strip()
                    result=json.loads(self.command(['start','-a','-i',gid],c['row']['verifierSeconds'],json.dumps({'artifacts':artifacts}).encode()))
                    expected=json.loads(Path(c['control']['collectionPin']['path']).read_bytes())['nodeIds']
                    assert result['complete'] and result['nodeIds']==expected and result['candidateExecutablesUsed'] is False
                    pin=save(self.home/('grade-'+uuid.uuid4().hex+'.json'),{'result':result,'builtImagesPin':self.config['taskReadiness'][c['taskId']]['builtImagesPin'],
                        'controlPin':self.config['taskReadiness'][c['taskId']]['controlPin'],'solverNonce':c['nonce'],'mutation':c['mutation'],
                        'candidateAnswerSha256':hashlib.sha256(answer.encode()).hexdigest(),'graderContainerId':gid,
                        'missingArtifactPaths':missing,'artifactManifest':[{'path':f['path'],'sha256':f['sha256']} for f in artifacts]},True)
                    value={'gradeOwnerPin':pin,'valid':True,'note':json.dumps({'reward':result['reward'],'tests':len(result['nodeIds']),
                        'passed':result['passedTests'],'failed':result['failedTests'],'completeCollection':True}),
                        'passed':result['reward']==1,'verified':True}
                    self.latest=(key,value);return value
                finally:
                    if gid:self.command(['rm','-f',gid])
            finally:
                if time.time()*1000<c['deadline'] and not self.refresh_deadline():self.command(['start',c['cid']]);c['running']=True
    def grade_native(self,c,key,answer):
        try:
            def missing_source(error,cid,path):
                prefix=self.home/('command-%06d'%self.serial)
                if str(error)!='Owned Docker operation failed: '+str(prefix.with_suffix('.json')):return False
                record=json.loads(prefix.with_suffix('.json').read_bytes())
                diagnostic=prefix.with_suffix('.stderr').read_text(errors='replace').strip()
                return not record['faults'] and record['exitCode']!=0 and diagnostic=='Error response from daemon: Could not find the file '+path+' in container '+cid
            evaluation=evaluate_snapshot(self.command,c['cid'],c['nonce'],c['built'],missing_source,self.native_source_digest);result=evaluation['result']
            collection=json.loads(Path(c['control']['collectionPin']['path']).read_bytes())
            assert result['nodeIds']==collection['nodeIds']==[] and result['nativeCaseCount']==collection['nativeCaseCount']==11
            assert result['candidateExecutablesUsed'] is False and result['candidateSnapshotUsed'] is False
            proof=self.config['taskReadiness'][c['taskId']]
            pin=save(self.home/('grade-'+uuid.uuid4().hex+'.json'),{**evaluation,'builtImagesPin':proof['builtImagesPin'],'controlPin':proof['controlPin'],
                'solverNonce':c['nonce'],'mutation':c['mutation'],'candidateAnswerSha256':hashlib.sha256(answer.encode()).hexdigest()},True)
            value={'gradeOwnerPin':pin,'valid':True,'verified':True,'passed':result['reward']==1,
                'note':json.dumps({'reward':result['reward'],'pytestTests':0,'nativeCases':11,'completeOriginalScript':True})}
            self.latest=(key,value);return value
        finally:
            if time.time()*1000<c['deadline'] and not self.refresh_deadline():self.command(['start',c['cid']]);c['running']=True
    def grade_acc(self,c,key,answer):
        try:
            import importlib.util
            proof=self.config['taskReadiness'][c['taskId']];p=proof['snapshotAdapterPin']
            assert public.pin(Path(p['path']))==p
            spec=importlib.util.spec_from_file_location('objrun_acc_snapshot_'+uuid.uuid4().hex,p['path'])
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            evaluation=module.evaluate_snapshot(self.command,c['cid'],c['nonce'],proof,self.config['resourceOwnerPid'],self.home)
            result=evaluation['result'];prepared=json.loads(Path(proof['preparedImageResultPin']['path']).read_bytes())
            assert result['nodeIds']==prepared['actualCollection']['nodeIds'] and result['complete']
            assert result['candidateSnapshotUsed'] is False and result['candidateExecutablesUsed'] is False and evaluation['ownedContainersRemaining']==0
            pin=save(self.home/('grade-'+uuid.uuid4().hex+'.json'),{**evaluation,'builtImagesPin':proof['builtImagesPin'],'controlPin':proof['controlPin'],
                'solverNonce':c['nonce'],'mutation':c['mutation'],'candidateAnswerSha256':hashlib.sha256(answer.encode()).hexdigest(),'skillsDeploymentPin':c['skillsDeploymentPin']},True)
            value={'gradeOwnerPin':pin,'valid':True,'verified':True,'passed':result['reward']==1,
                'note':json.dumps({'reward':result['reward'],'tests':len(result['nodeIds']),'passed':result['passedTests'],'failed':result['failedTests'],'completeCollection':True})}
            self.latest=(key,value);return value
        finally:
            if time.time()*1000<c['deadline'] and not self.refresh_deadline():self.command(['start',c['cid']]);c['running']=True
    def retain_interruption(self):
        with self.lock:
            assert self.current
            c=self.current;tag='objrun-skb-interrupted:'+self.config['runId'].lower()
            image=self.command(['commit','--pause=true',c['cid'],tag],timeout=60).decode().strip()
            return {'imageId':image,'tag':tag,'ownedContainerId':c['cid'],'untrustedExecutionOnly':True,'usedForTrustedGrader':False}
    def register(self,body):
        self.identify(body['place']);path=Path(body['databasePath']).resolve();root=Path(self.config['output']).resolve()
        assert root in path.parents and path.name=='h2h.sqlite' and body['taskId']==body['place'][4:]
        assert path.is_file() and not path.is_symlink()
        self.database=path;self.database_task=body['taskId'];return {'ok':True}
    def refresh_deadline(self):
        if not self.database:return False
        with sqlite3.connect('file:'+self.database.as_posix()+'?mode=ro',uri=True) as database:
            row=database.execute('select created_at,solve_seconds,state from task where id=?',(self.database_task,)).fetchone()
        if row and self.current:
            deadline=row[0]+row[1]*1000
            if deadline!=self.current['deadline']:self.current['deadline']=deadline;self.arm_deadline()
        return bool(row and row[2] in ('done','failed'))
    def arm_deadline(self):
        if self.timer:self.timer.cancel()
        if not self.current:return
        cid=self.current['cid'];deadline=self.current['deadline'];nonce=self.current['nonce']
        def expire():
            # Do not wait behind a model's long-running tool lock at the hard
            # deadline. Kill only this immutable owned candidate container.
            completed=subprocess.run([DOCKER,'kill',cid],env=ENV,capture_output=True,timeout=30)
            save(self.home/('deadline-'+nonce+'.json'),{'cid':cid,'deadlineUnixMs':deadline,'stoppedAtUnixMs':int(time.time()*1000),
                'exitCode':completed.returncode,'stdout':completed.stdout.decode(errors='replace'),'stderr':completed.stderr.decode(errors='replace'),'modelCalls':0})
            if self.current and self.current['cid']==cid:self.current['running']=False
        self.timer=threading.Timer(max(0,(deadline-time.time()*1000)/1000),expire);self.timer.daemon=True;self.timer.start()
    def stop(self):
        with self.lock:
            if self.timer:self.timer.cancel();self.timer=None
            if self.current:self.command(['rm','-f',self.current['cid']]);self.current=None
            self.latest=None;self.database=None;self.database_task=None;return {'ok':True,'ownedContainersRemaining':0}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);parser.add_argument('--port',type=int,required=True);a=parser.parse_args()
    stand=Stand(json.loads(a.config.read_bytes()))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,value,status=200):
            raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path=='/health':self.send({'readyTaskIds':list(stand.config['taskReadiness']),'denominator':87,'pid':os.getpid(),'protocol':'skillsbench-full-f-data-stand-v1'})
            else:self.send({'error':'Unknown'},404)
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('X-ObjRun-Grader-Token',''),stand.token):self.send({'error':'Unauthorized'},401);return
            try:
                count=int(self.headers.get('Content-Length','0'));assert 0<=count<=4*1024**2;body=json.loads(self.rfile.read(count))
                if self.path=='/place':self.send(stand.call(body));return
                if self.path=='/register':self.send(stand.register(body));return
                if self.path=='/retain-interruption':self.send(stand.retain_interruption());return
                if self.path=='/stop':self.send(stand.stop());return
                if self.path=='/shutdown':self.send(stand.stop());threading.Thread(target=server.shutdown,daemon=True).start();return
                tid,kind=self.path.strip('/').split('/');assert kind in ('verified','passed')
                body=body.get('input',body);task=body.get('task',{});body['place']=body.get('place',task.get('place'));body['said']=body.get('said',(body.get('result') or {}).get('body',task.get('result','')))
                assert stand.identify(body['place'])==tid
                result=stand.grade(body,kind);self.send({**result,'value':result[kind]})
            except Exception as error:self.send({'valid':False,'outcome':'grader_error','errorType':type(error).__name__},503)
    server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
    try:server.serve_forever()
    finally:stand.stop();server.server_close()

if __name__=='__main__':main()
