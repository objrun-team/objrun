"""D-only derived JPG bridge. Frozen candidate/runtime methods are inherited.

This module is inert when imported. Private grading is delegated to the new
source-pinned RAM executor; the original fd3 CLI and C lease are not replaced.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import tempfile
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[2]
BASE_SHA='505d08b6862ffeace1bc693b44ade351e19ebcdee6041c8e2509e3ac0637c189'
FIXED_CANDIDATE_BYTES=256*1024**2
TASK='jpg-ocr-stat'
PROTOCOL='skb-jpg-output-v1-preseed'

def require(value,message):
    if not value:raise RuntimeError(message)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while block:=f.read(65536):h.update(block)
    return h.hexdigest()

def load(name,path,expected=None):
    if expected is not None:require(sha(path)==expected,'frozen_bridge_base_changed')
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

# Importing definitions performs no Docker/service/file mutation.
base=load('jpg_D_frozen_stand',ROOT/'scripts/repair-2026-10-08/skb-jpg-stand.py',BASE_SHA)
storage=load('jpg_D_storage',ROOT/'scripts/repair-2026-10-08/jpg_d_storage_profile.py')

def read(path):
    def pairs(rows):
        result={}
        for k,v in rows:require(k not in result,'duplicate_json_key');result[k]=v
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=pairs)

def verify(pin):
    p=Path(pin['path']);s=p.lstat()
    require(stat.S_ISREG(s.st_mode) and not (getattr(s,'st_file_attributes',0)&0x400) and s.st_nlink==1,'bridge_pin_not_regular')
    require(s.st_size==pin['bytes'] and sha(p)==pin['sha256'],'bridge_pin_changed');return p

def save(path,value):
    path=Path(path);storage.ordinary(path.parent,Path('D:/'))
    raw=(json.dumps(value,indent=2)+'\n').encode()
    with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    require(path.read_bytes()==raw,'bridge_durable_readback')

def candidate_missing(result,target):
    """Exact known target, one observed complete error line, and no extra item."""
    if result.returncode!=1 or not isinstance(target,str)or not re.fullmatch('[a-f0-9]{64}|objrun-jpg-[a-f0-9]{12}-candidate-[a-f0-9]{8}',target):return False
    try:
        out=result.stdout.decode('utf-8')if isinstance(result.stdout,bytes)else result.stdout
        err=result.stderr.decode('utf-8')if isinstance(result.stderr,bytes)else result.stderr
        if len(out)>64 or len(err)>1024 or(out.strip()and json.loads(out)!=[]):return False
        lines=err.splitlines()
        if len(lines)!=1:return False
        return any(re.fullmatch('(?i:'+re.escape(prefix)+')'+re.escape(target),lines[0].strip())is not None for prefix in('Error: No such object: ','Error response from daemon: No such container: ','No such object: ','No such container: '))
    except (ValueError,UnicodeError,TypeError):return False

class DCandidateDocker(base.CandidateDocker):
    def __init__(self,output,descriptor,client_pin):
        super().__init__(output);self.descriptor=descriptor;self.client_pin=client_pin;self.client=str(verify(client_pin))

    def run(self,*args,timeout=60,binary=False,cap=1024*1024):
        verify(self.client_pin);previous=getattr(self,'bounded_public_copy',False);self.bounded_public_copy=bool(args and args[0]=='cp')
        try:
            self.check_resources()
            with tempfile.TemporaryFile()as stdout,tempfile.TemporaryFile()as stderr:
                child=subprocess.Popen([self.client,*args],stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
                started=time.monotonic()
                try:
                    while child.poll()is None:
                        require(time.monotonic()-started<=timeout,'owned_Docker_operational_deadline');self.check_resources()
                        require(os.fstat(stdout.fileno()).st_size<=cap and os.fstat(stderr.fileno()).st_size<=1024*1024,'owned_Docker_output_boundary');time.sleep(.15)
                    self.check_resources()
                finally:
                    if child.poll()is None:child.kill();child.wait(timeout=10)
                stdout.seek(0);stderr.seek(0);out,err=stdout.read(cap+1),stderr.read(1024*1024+1)
                require(len(out)<=cap and len(err)<=1024*1024,'owned_Docker_capture_boundary')
            return subprocess.CompletedProcess([self.client,*args],child.returncode,out if binary else out.decode('utf-8','replace'),err if binary else err.decode('utf-8','replace'))
        finally:self.bounded_public_copy=previous

    def record_ownership(self):
        # Preserve the base operation-owner schema used by candidate receipts.
        path=self.output/'operation-owner.json';part=path.with_name(path.name+'.'+uuid.uuid4().hex+'.part')
        save(part,{'schemaVersion':1,'taskId':TASK,'protocol':PROTOCOL,'processId':os.getpid(),
            'ownerLabelKey':'objrun.jpg-owner','ownerLabelValue':self.prefix,'lease':self.lease_identity,
            'containers':list(self.identities.values()),'storageProtocol':self.descriptor['protocol'],
            'storageOwnerNonce':self.descriptor['ownerNonce']})
        part.replace(path)

    def check_resources(self):
        deferred=getattr(self,'bounded_public_copy',False);writable=getattr(self,'last_writable',0)
        if self.active and not deferred:
            verify(self.client_pin);r=subprocess.run([self.client,'inspect','--size','--format','{{.SizeRw}}',self.active],capture_output=True,timeout=30)
            require(r.returncode==0,'candidate_size_query_failed');writable=int(r.stdout.strip());self.last_writable=writable
        require(0<=writable<=FIXED_CANDIDATE_BYTES,'candidate_frozen_256MiB_boundary')
        free={k:shutil.disk_usage(k+':/').free for k in ('C','D','F')}
        observation=storage.assess_resources(self.descriptor,free,bool(self.active),writable if self.active else 0)
        require(observation['admitted'],'candidate_profile_resource_guard')
        self.samples.append({'at':time.time(),'freeCBytes':free['C'],'freeDBytes':free['D'],'freeFBytes':free['F'],
            'container':self.active,'writableBytes':writable,'maximumWritableBytes':FIXED_CANDIDATE_BYTES,
            'deferredForBoundedPublicCopy':deferred,'storageResourceObservation':observation})

    def remove(self,name):
        require(name in self.owned,'foreign_candidate_remove');verify(self.client_pin)
        r=subprocess.run([self.client,'inspect',name],capture_output=True,timeout=10)
        if r.returncode:
            require(candidate_missing(r,name),'candidate_cleanup_identity_unknown')
            self.owned.remove(name)
            if self.active==name:self.active=None
            self.identities[name]['state']='absent_after_create_attempt';self.record_ownership();return
        actual=json.loads(r.stdout)[0];row=self.identities[name]
        require(actual['Name']=='/'+name and actual['Image']==row['expectedImageId']and(actual['Config'].get('Labels')or{}).get('objrun.jpg-owner')==self.prefix and(not row['containerId']or row['containerId']==actual['Id']),'candidate_cleanup_substitution')
        row['containerId']=actual['Id'];removed=subprocess.run([self.client,'rm','-f',actual['Id']],capture_output=True,timeout=30);require(removed.returncode==0,'candidate_cleanup_failed')
        absent=subprocess.run([self.client,'inspect',actual['Id']],capture_output=True,timeout=10)
        require(candidate_missing(absent,actual['Id']),'candidate_cleanup_daemon_unconfirmed')
        self.owned.remove(name)
        if self.active==name:self.active=None
        row['state']='removed';self.record_ownership()

class DRuntime(base.Runtime):
    """The same frozen Node RPC, with an explicitly pinned host Docker client."""
    def __init__(self,name,assets,client_pin):
        self.name=name;self.client_pin=client_pin;self.client=str(verify(client_pin))
        self.proc=subprocess.Popen([self.client,'exec','-i','-e','LD_LIBRARY_PATH=/rt-lib',name,'/rt-node','/rt-runtime.mjs'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1)
        self.number=0;self.rpc('initialize',{'protocolVersion':'2026-07-28'})
    def rpc(self,method,params):
        import queue
        verify(self.client_pin);self.number+=1;self.proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':self.number,'method':method,'params':params})+'\n');self.proc.stdin.flush()
        replies=queue.Queue();threading.Thread(target=lambda:replies.put(self.proc.stdout.readline()),daemon=True).start()
        try:line=replies.get(timeout=890)
        except queue.Empty:
            subprocess.run([self.client,'stop','--time','0',self.name],capture_output=True,timeout=30);raise RuntimeError('owned_RPC_completion_boundary')
        require(bool(line),'runtime_closed_before_response');result=json.loads(line);require(not result.get('error'),'runtime_RPC_error');return result.get('result',{})

class BridgeOperationLease:
    """Fresh native acquisition per resume; repeated stopped captures do not delete.

    The shared module's lease is deliberately single-use. All of its closed
    bytes remain in a distinct directory and are later consumed by the auditor.
    """
    def __init__(self,descriptor,home):
        self.descriptor,self.home=descriptor,home;self.current=None;self.poisoned=False;self.closures=[]
        self.path=Path(descriptor['directories']['leases'])/'instance.lock';self.nonce=None
    @property
    def held(self):return bool(self.current and self.current.held)
    def acquire(self):
        require(not self.poisoned and not self.held,'bridge_lease_not_fresh')
        self.nonce=uuid.uuid4().hex;folder=self.home/('candidate-instance-'+self.nonce);folder.mkdir(exist_ok=False)
        self.current=storage.JpgInstanceLease(self.descriptor,self.nonce,folder)
        try:self.current.acquire()
        except BaseException:self.poisoned=True;raise
    def release(self):
        require(not self.poisoned,'bridge_instance_failed')
        if self.held:
            try:closed=self.current.release();self.closures.append(closed);return closed
            except BaseException:self.poisoned=True;raise
        if self.closures:
            verify(self.closures[-1]);return self.closures[-1]
        require(self.current is None,'bridge_instance_lease_unknown')
    def retain_after_failure(self):
        self.poisoned=True
        if self.current:self.current.retain_after_failure()

class DBridge(base.Bridge):
    def __init__(self,args):
        self.args=args;self.recipe=read(args.recipe);self.descriptor=read(verify(self.recipe['DStorage']['descriptorPin']))
        storage.validate_descriptor(self.descriptor)
        require(self.recipe['family']=='jpg-journal-v1' and self.recipe['protocol']=='jpg-D-journal-recipe-v1','D_bridge_recipe_family')
        require(self.recipe['store']==self.descriptor['storePhysical'],'D_bridge_exact_store')
        self.token=os.environ.get('TGENGIN_GRADER_TOKEN','');require(bool(self.token),'host_authentication_required')
        self.home=Path(self.descriptor['directories']['stand']);storage.ordinary(self.home,Path('D:/'))
        self.lock=threading.RLock();self.owner='objrun-skb-jpg-'+uuid.uuid4().hex[:12]
        self.place=None;self.name=None;self.container_id=None;self.runtime=None;self.running=False;self.files={};self.counter=0;self.latest=None;self.captures=[];self.sealed=False;self.db_path=None;self.task_id=None;self.environment_audit=None
        self.assets=ROOT/'examples/benchmark/terminal-bench/.runtime';self.runtime_manifest=read(self.assets/'manifest.json')
        for name,want in self.runtime_manifest['assets'].items():require(base.private.sha(self.assets/name)==want,'six_tool_asset_changed')
        for name,want in self.runtime_manifest['frozenSources'].items():require(base.private.sha(ROOT/name)==want,'six_tool_source_changed')
        self.image=base.private.require_build(read(verify(self.recipe['gates']['image'])),read(verify(self.recipe['gates']['build'])),base.private.sources())
        base.private.require_dependencies(verify(self.recipe['gates']['profile']),self.image)
        self.docker=DCandidateDocker(self.home,self.descriptor,self.recipe['DStorage']['dockerClientPin'])
        self.lease=BridgeOperationLease(self.descriptor,self.home)
        actual=json.loads(self.docker.checked('image','inspect',self.image).stdout)[0];require(actual['Id']==self.image,'full_image_identity_changed')

    def create(self,place):
        require(not self.place or self.place==place,'only_one_owned_candidate')
        if self.name:return
        require(place.endswith('/'+TASK),'only_JPG_foundation_supported')
        self.place=place;self.sealed=False;self.files={};self.captures=[];self.latest=None;self.lease.acquire();self.docker.record_lease(self.lease)
        self.name=self.docker.create(self.image,'candidate','bridge',['-c','sleep infinity'])
        config=json.loads(self.docker.checked('inspect',self.name).stdout)[0];self.container_id=config['Id']
        environment=config['Config'].get('Env')or[];forbidden={'TGENGIN_GRADER_TOKEN','TGENGIN_PUBLISHER_TOKEN','TGENGIN_CONFIG','DEEPSEEK_API_KEY','OBJRUN_SKB_MOCK_KEY','OBJRUN_JPG_JOURNAL_PROXY_KEY'}
        require(not any(row.partition('=')[0]in forbidden or self.token in row for row in environment),'private_host_credential_in_candidate')
        self.environment_audit={'containerId':self.container_id,'forbiddenHostKeysPresent':False,'standTokenPresent':False,'imageEnvironmentSha256':hashlib.sha256(json.dumps(environment,sort_keys=True).encode()).hexdigest()}
        self.docker.checked('start',self.name);self.running=True;self.docker.checked('exec',self.name,'mkdir','-p','/rt-lib')
        for src,dst in[('node','/rt-node'),('runtime.mjs','/rt-runtime.mjs'),('libstdc++.so.6','/rt-lib/libstdc++.so.6'),('libgcc_s.so.1','/rt-lib/libgcc_s.so.1')]:self.docker.checked('cp',str(self.assets/src),self.name+':'+dst)
        self.docker.checked('exec',self.name,'chmod','+x','/rt-node');self.runtime=DRuntime(self.name,self.assets,self.recipe['DStorage']['dockerClientPin'])
    def resume(self):
        if self.sealed:return
        self.lease.acquire();self.docker.record_lease(self.lease);self.docker.active=self.name
        self.docker.checked('start',self.name);self.running=True;self.runtime=DRuntime(self.name,self.assets,self.recipe['DStorage']['dockerClientPin'])
    def capture(self,final=False):
        with self.lock:
            require(bool(self.name),'capture_has_no_owned_candidate')
            if final and self.sealed and self.captures and self.captures[-1].get('final'):
                receipt=self.captures[-1]
                if receipt['state']=='regular':require(sha(receipt['hostArtifactPath'])==receipt['artifactSha256'],'sealed_workbook_changed')
                return receipt
            if final:self.sealed=True
            self.stop_for_capture();box=Path(self.descriptor['directories']['captures'])/('capture-'+hashlib.sha256(self.place.encode()).hexdigest()[:12]+'-'+str(len(self.captures)));box.mkdir(exist_ok=False)
            receipt={'taskId':TASK,'protocol':PROTOCOL,'ownedContainerID':self.container_id,'containerStopped':True,'artifactPath':base.FIXED,'stoppedAt':int(time.time()*1000),'final':final,'mock':False,'daemonEvidence':{'containerId':self.container_id,'method':'docker-cp-tar'}}
            raw,err,code,complete=base.host.bounded_artifact_tar([self.docker.client,'cp',self.name+':'+base.FIXED,'-'],base.MAX_FILE,base.CAPTURE_SECONDS)
            if not raw:
                diagnostic=err.decode('utf-8','replace');matched=code!=0 and 'Could not find the file '+base.FIXED+' in container 'in diagnostic and(self.name in diagnostic or self.container_id in diagnostic)
                require(matched,'capture_transport_failed_without_exact_absent');receipt.update(state='absent');receipt['daemonEvidence'].update(missingFileDiagnosticMatched=True,diagnosticSha256=hashlib.sha256(diagnostic.encode()).hexdigest())
            else:
                header=base.host.first_artifact_member(raw);require(header is not None and Path(header.name).name=='stat_ocr.xlsx','capture_unexpected_daemon_member')
                kind='directory'if header.isdir()else'symlink'if header.issym()or header.islnk()else'regular'if header.isfile()else'unsupported';require(kind!='unsupported','capture_unsupported_daemon_object')
                state=kind if kind!='regular'else'too_large'if header.size>base.MAX_FILE else'regular';receipt.update(state=state);receipt['daemonEvidence'].update(memberKind=kind,memberName=header.name,size=header.size)
                if state=='regular':
                    require(code==0 and complete,'capture_regular_transfer_incomplete');data=base.private.read_output_tar(raw);path=box/'stat_ocr.xlsx'
                    with path.open('xb')as f:f.write(data);f.flush();os.fsync(f.fileno())
                    receipt.update(artifactSha256=sha(path),artifactBytes=len(data),hostArtifactPath=str(path))
                receipt['daemonEvidence'].update(rawTarSha256=hashlib.sha256(raw).hexdigest(),rawTarCapturedBytes=len(raw),rawTarCaptureComplete=complete)
            receipt_path=box/'capture-receipt.json';save(receipt_path,receipt);receipt['captureReceiptPath']=str(receipt_path);self.captures.append(receipt)
        # The frozen capture constructs these paths; no request can nominate a
        # host file for writable fsync. Preserve and recheck its exact bytes.
        paths=[Path(receipt['captureReceiptPath'])]
        if receipt['state']=='regular':paths.append(Path(receipt['hostArtifactPath']))
        for p in paths:
            boundary=Path(self.descriptor['directories']['captures']);require(p.is_relative_to(boundary) and re.fullmatch('capture-[a-f0-9]{12}-[0-9]+',p.parent.name),'D_capture_owned_path')
            storage.ordinary(p.parent,boundary);before=p.lstat();digest=sha(p)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and not getattr(before,'st_file_attributes',0)&0x400,'D_capture_regular')
            with p.open('r+b') as f:
                opened=os.fstat(f.fileno());require((opened.st_ino,opened.st_dev,opened.st_size)==(before.st_ino,before.st_dev,before.st_size),'D_capture_open_identity');os.fsync(f.fileno())
            require(p.stat().st_size==before.st_size and sha(p)==digest,'D_capture_changed_by_flush')
        return receipt

    def grade(self,receipt):
        require(receipt in self.captures,'grade_requires_this_bridge_fixed_capture')
        if self.docker.active:self.docker.active=None
        folder=Path(self.descriptor['directories']['private-logs'])/('grade-'+uuid.uuid4().hex)
        parent=ROOT/'scripts/repair-2026-10-08/jpg-D-grade-parent-v1.py';parent_pin=next((p for p in self.recipe['sourcePins']if Path(p['path'])==parent),None)
        require(parent_pin is not None,'grade_parent_missing_source');module=load('jpg_D_private_executor_parent',verify(parent_pin),parent_pin['sha256'])
        report=module.run_capture_cli(self.recipe,receipt,folder,phase='feedback')
        require(report.get('validated') is True and report.get('officialGradingValid') is True and report.get('candidateVerdict',{}).get('valid') is True,'private_RAM_grader_invalid')
        self.docker.active=self.name if self.running else None
        return report

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['live'],required=True);parser.add_argument('--port',type=int,required=True);parser.add_argument('--recipe',type=Path,required=True)
    args=parser.parse_args();bridge=DBridge(args)
    identity={'pid':os.getpid(),'parentPid':os.getppid(),'executable':str(Path(sys.executable).resolve()),'executableSha256':sha(sys.executable),
        'nonce':os.environ.get('OBJRUN_JPG_LIFECYCLE_NONCE',''),'pythonVersion':sys.version,'protocol':'jpg-native-python-service-lifecycle-v2'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,value,status=200):
            raw=json.dumps(value).encode();self.send_response(status);self.send_header('content-type','application/json');self.send_header('content-length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path=='/health':
                public={'backend':'live','protocol':PROTOCOL,'denominator':87,'implementedTaskIds':[TASK],'readyTaskIds':[],'unsupportedTaskCount':86,'authenticated':True,'supportedTools':sorted(base.TOOLS),'maxLiveCandidates':1,'officialGradingValid':False,'rpcForwardCount':bridge.counter}
                if hmac.compare_digest(self.headers.get('X-ObjRun-Grader-Token',''),bridge.token):public.update(processIdentity=identity,storageProtocol=bridge.descriptor['protocol'],storageOwnerNonce=bridge.descriptor['ownerNonce'],storageDescriptorPin=bridge.recipe['DStorage']['descriptorPin'])
                self.send(public);return
            self.send({'error':'Unknown protected route'},404)
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('X-ObjRun-Grader-Token',''),bridge.token):self.send({'error':'Unauthorized bridge'},401);return
            try:
                size=int(self.headers.get('content-length',0));require(0<=size<=4*1024*1024,'body_limit');body=json.loads(self.rfile.read(size)or b'{}')
                if self.path=='/place':self.send(bridge.call(body));return
                if self.path=='/register':
                    path=Path(body['databasePath']).absolute();storage.ordinary(path.parent,Path(bridge.descriptor['directories']['sqlite']))
                    require(path.name=='h2h.sqlite' and path.is_relative_to(Path(bridge.descriptor['directories']['sqlite'])),'foreign_database_path')
                    require(body['taskId'] in [bridge.recipe['runId']+'/skillsbench/'+arm+'/0/'+TASK for arm in ('U','F')],'foreign_registered_task')
                    bridge.db_path=path;bridge.task_id=body['taskId'];self.send({'ok':True});return
                if self.path=='/capture':require(body.get('place')==bridge.place,'foreign_capture');self.send(bridge.capture(bool(body.get('final'))));return
                if self.path=='/grade-captured':
                    require(bridge.captures and body.get('captureReceiptPath')==bridge.captures[-1]['captureReceiptPath'],'fixed_capture_required');self.send(bridge.grade(bridge.captures[-1]));return
                if self.path=='/stop':
                    require(body.get('place')==bridge.place,'foreign_stop');bridge.remove();self.send({'ok':True,'ownedContainersRemaining':len(bridge.docker.owned)});return
                if self.path in ('/verified','/passed'):
                    body=body.get('input',body);task=body.get('task')or{};body['place']=body.get('place',task.get('place'));body['said']=body.get('said',(body.get('result')or{}).get('body',task.get('result','')))
                    require(body.get('place')==bridge.place,'foreign_objective')
                    report=bridge.judge(body) if self.path=='/verified' or bridge.latest is None or bridge.latest[0]!=str(body.get('said','')) else bridge.latest[1]
                    v=report['candidateVerdict'];self.send({'value':bool(v['ran']) if self.path=='/verified' else v['reward']==1,'valid':v['valid'],'note':json.dumps({'tests':v['completedTests'],'passed':v['passedTests'],'artifactSha256':v.get('artifactSha256')})});return
                self.send({'error':'Unknown bridge route'},404)
            except Exception:self.send({'valid':False,'outcome':'grader_error','error':'owned D capture/runtime/private RAM operation did not certify'},503)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    try:server.serve_forever()
    finally:bridge.remove();server.server_close()

if __name__=='__main__':main()
