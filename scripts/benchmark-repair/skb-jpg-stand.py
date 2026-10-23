"""Owned authenticated JPG six-tool/capture bridge; never builds/pulls an image."""
from __future__ import annotations
import argparse
import hashlib
import hmac
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import tarfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[2]
TOOLS={'bash','read','write','edit','glob','grep'}
FIXED='/app/workspace/stat_ocr.xlsx'
PROTOCOL='skb-jpg-output-v1-preseed'
TASK_ID='jpg-ocr-stat'
MAX_FILE=8*1024*1024
CAPTURE_SECONDS=90
CANDIDATE_WRITABLE=256*1024*1024
spec=importlib.util.spec_from_file_location('private_jpg',ROOT/'scripts/benchmark-repair/software-jpg-private-grader.py')
private=importlib.util.module_from_spec(spec);spec.loader.exec_module(private)
host_spec=importlib.util.spec_from_file_location('jpg_host_ops',ROOT/'scripts/benchmark-repair/skb-jpg-host-ops.py')
host=importlib.util.module_from_spec(host_spec);host_spec.loader.exec_module(host)

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')

class CandidateDocker(private.Docker):
    def run(self,*argv,**kwargs):
        previous=getattr(self,'bounded_public_copy',False)
        self.bounded_public_copy=bool(argv and argv[0]=='cp')
        try:result=super().run(*argv,**kwargs)
        finally:self.bounded_public_copy=previous
        if argv and argv[0]=='cp':self.check_resources()
        return result
    def check_resources(self):
        free_c,free_f=private.shutil.disk_usage('C:/').free,private.shutil.disk_usage('F:/').free
        writable=0
        # Docker holds its filesystem lock while extracting a cp TAR. A second
        # inspect --size may wait behind that copy. These four public bootstrap
        # assets have fixed hashes/lengths; measure after actual copy completion.
        deferred=getattr(self,'bounded_public_copy',False)
        writable=getattr(self,'last_writable',0)
        if self.active and not deferred:
            result=subprocess.run(['docker','inspect','--size','--format','{{.SizeRw}}',self.active],capture_output=True,timeout=30)
            if result.returncode:raise RuntimeError('Owned candidate writable-layer measurement failed')
            writable=int(result.stdout.strip())
            self.last_writable=writable
        self.samples.append({'at':time.time(),'freeCBytes':free_c,'freeFBytes':free_f,'container':self.active,'writableBytes':writable,'maximumWritableBytes':CANDIDATE_WRITABLE,'deferredForBoundedPublicCopy':deferred})
        if free_c<private.MIN_C_FREE or free_f<private.MIN_F_FREE or writable>CANDIDATE_WRITABLE:raise RuntimeError('Host reserve or declared candidate writable-layer boundary reached')

class Runtime:
    def __init__(self,name,assets):
        self.name=name
        self.proc=subprocess.Popen(['docker','exec','-i','-e','LD_LIBRARY_PATH=/rt-lib',name,'/rt-node','/rt-runtime.mjs'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1)
        self.number=0
        self.rpc('initialize',{'protocolVersion':'2026-07-28'})
    def rpc(self,method,params):
        self.number+=1;self.proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':self.number,'method':method,'params':params})+'\n');self.proc.stdin.flush()
        replies=queue.Queue()
        threading.Thread(target=lambda:replies.put(self.proc.stdout.readline()),daemon=True).start()
        try:line=replies.get(timeout=890)
        except queue.Empty:
            subprocess.run(['docker','stop','--time','0',self.name],capture_output=True,timeout=30)
            raise RuntimeError('Owned RPC exceeded its declared completion boundary')
        if not line:raise RuntimeError('Candidate runtime closed before an actual response')
        result=json.loads(line)
        if result.get('error'):raise RuntimeError('Candidate runtime RPC error')
        return result.get('result',{})
    def call(self,tool,args):
        result=self.rpc('tools/call',{'name':tool,'arguments':args})
        if result.get('isError'):return {'error':'candidate tool error'}
        if 'structuredContent'in result:return result['structuredContent']
        text=''.join(x.get('text','')for x in result.get('content',[]))
        try:return json.loads(text)
        except json.JSONDecodeError:return text
    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=10)

class Bridge:
    def __init__(self,args):
        self.args=args;self.token=os.environ.get('TGENGIN_GRADER_TOKEN','')
        if not self.token:raise RuntimeError('Host authentication token is required')
        self.home=args.home;self.home.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.owner='objrun-skb-jpg-'+uuid.uuid4().hex[:12]
        self.place=None;self.name=None;self.container_id=None;self.runtime=None;self.running=False;self.files={};self.counter=0;self.latest=None;self.captures=[];self.sealed=False;self.db_path=None;self.task_id=None;self.environment_audit=None
        self.assets=ROOT/'examples/benchmark/terminal-bench/.runtime'
        self.runtime_manifest=json.loads((self.assets/'manifest.json').read_text())
        for name,want in self.runtime_manifest['assets'].items():
            if private.sha(self.assets/name)!=want:raise RuntimeError('Frozen six-tool executor asset changed')
        for name,want in self.runtime_manifest['frozenSources'].items():
            if private.sha(ROOT/name)!=want:raise RuntimeError('Frozen core executor source changed')
        self.image=None;self.docker=None;self.lease=None
        if args.mode=='live':
            if not all([args.image_manifest,args.build_proof,args.dependency_profile]):raise RuntimeError('Live bridge requires actual full-image/build/dependency proof')
            self.image=private.require_build(json.loads(args.image_manifest.read_text()),json.loads(args.build_proof.read_text()),private.sources())
            private.require_dependencies(args.dependency_profile,self.image)
            self.docker=CandidateDocker(self.home)
            self.lease=private.OwnedInstanceLease()
            actual=json.loads(self.docker.checked('image','inspect',self.image).stdout)[0]
            if actual['Id']!=self.image:raise RuntimeError('Actual complete image ID changed')
    def create(self,place):
        if self.place and self.place!=place:raise RuntimeError('Only one owned candidate may exist')
        if self.name:return
        if not place.endswith('/'+TASK_ID):raise RuntimeError('Only JPG is supported')
        self.place=place;self.sealed=False;self.files={};self.captures=[];self.latest=None
        if self.args.mode=='mock':self.name=self.owner+'-mock';self.container_id=hashlib.sha256(self.name.encode()).hexdigest();self.running=True;return
        self.lease.acquire();self.docker.record_lease(self.lease)
        self.name=self.docker.create(self.image,'candidate','bridge',['-c','sleep infinity'])
        config=json.loads(self.docker.checked('inspect',self.name).stdout)[0];self.container_id=config['Id']
        environment=config['Config'].get('Env')or[]
        forbidden={'TGENGIN_GRADER_TOKEN','TGENGIN_PUBLISHER_TOKEN','TGENGIN_CONFIG','DEEPSEEK_API_KEY','OBJRUN_SKB_MOCK_KEY'}
        if any(row.partition('=')[0]in forbidden or self.token in row for row in environment):raise RuntimeError('A private host credential entered the candidate environment')
        self.environment_audit={'containerId':self.container_id,'forbiddenHostKeysPresent':False,'standTokenPresent':False,'imageEnvironmentSha256':hashlib.sha256(json.dumps(environment,sort_keys=True).encode()).hexdigest()}
        self.docker.checked('start',self.name);self.running=True
        self.docker.checked('exec',self.name,'mkdir','-p','/rt-lib')
        for src,dst in [('node','/rt-node'),('runtime.mjs','/rt-runtime.mjs'),('libstdc++.so.6','/rt-lib/libstdc++.so.6'),('libgcc_s.so.1','/rt-lib/libgcc_s.so.1')]:self.docker.checked('cp',str(self.assets/src),self.name+':'+dst)
        self.docker.checked('exec',self.name,'chmod','+x','/rt-node')
        self.runtime=Runtime(self.name,self.assets)
    def mock_call(self,tool,args):
        path=args.get('file_path',args.get('path',''))
        if tool=='bash':return {'code':0,'stdout':'local mock; no candidate image or official verifier\n','stderr':'','timedOut':False}
        if tool=='write':self.files[path]=str(args.get('content','')).encode();return {'path':path,'bytes':len(self.files[path])}
        if tool=='edit':self.files[path]=self.files.get(path,b'').replace(str(args.get('old_string','')).encode(),str(args.get('new_string','')).encode());return {'path':path,'replaced':1}
        if tool=='read':return {'path':path,'offset':1,'lines':[{'number':1,'text':self.files.get(path,b'').decode('utf-8','replace')}],'totalLines':1,'bytes':len(self.files.get(path,b''))}
        if tool=='glob':return {'files':list(self.files),'truncated':False}
        return {'matches':[],'truncated':False}
    def call(self,body):
        with self.lock:
            self.create(str(body.get('place','')))
            if self.sealed:return {'error':'candidate sealed'}
            if body.get('op')=='ping':return {'alive':self.running,'environmentAudit':self.environment_audit,'ownedContainerID':self.container_id,'mock':self.args.mode=='mock'}
            tool=body.get('tool')
            if tool not in TOOLS:raise RuntimeError('Only the six frozen tools may be called')
            if not self.running:raise RuntimeError('Candidate is stopped')
            self.counter+=1
            if self.args.mode=='mock':return self.mock_call(tool,body.get('args')or{})
            self.docker.check_resources();result=self.runtime.call(tool,body.get('args')or{});self.docker.check_resources();return result
    def stop_for_capture(self):
        if self.args.mode=='mock':self.running=False;return
        if self.running:
            # SIGKILL has no guest grace period in which a background writer can mutate the workbook.
            self.docker.checked('stop','--time','0',self.name)
            self.running=False
            if self.runtime:self.runtime.close();self.runtime=None
        inspected=json.loads(self.docker.checked('inspect',self.name).stdout)[0]
        if inspected['Id']!=self.container_id or inspected['State']['Running']:raise RuntimeError('Owned candidate freeze cannot be proved')
        self.docker.active=None
        self.lease.release();self.docker.record_lease_release()
    def capture(self,final=False):
        with self.lock:
            if not self.name:raise RuntimeError('No owned candidate to capture')
            if final and self.sealed and self.captures and self.captures[-1].get('final'):
                prior=self.captures[-1]
                if prior['state']=='regular' and private.sha(Path(prior['hostArtifactPath']))!=prior['artifactSha256']:raise RuntimeError('Sealed host workbook changed')
                return prior
            if final:self.sealed=True
            self.stop_for_capture();stopped_at=int(time.time()*1000)
            box=self.home/('capture-'+hashlib.sha256(self.place.encode()).hexdigest()[:12]+'-'+str(len(self.captures)));box.mkdir(exist_ok=False)
            receipt={'taskId':TASK_ID,'protocol':PROTOCOL,'ownedContainerID':self.container_id,'containerStopped':True,'artifactPath':FIXED,'stoppedAt':stopped_at,'final':final,'mock':self.args.mode=='mock','daemonEvidence':{'containerId':self.container_id,'method':'docker-cp-tar'}}
            if self.args.mode=='mock':
                data=self.files.get(FIXED)
                if data is None:receipt.update(state='absent');receipt['daemonEvidence'].update(missingFileDiagnosticMatched=True)
                else:
                    path=box/'stat_ocr.xlsx';path.write_bytes(data);receipt.update(state='regular',artifactSha256=private.sha(path),artifactBytes=len(data),hostArtifactPath=str(path));receipt['daemonEvidence'].update(memberKind='regular',memberName='stat_ocr.xlsx',size=len(data))
            else:
                # Docker daemon supplies TAR metadata, never candidate stat/Python/interpreter code.
                raw,err,code,complete=host.bounded_artifact_tar(['docker','cp',self.name+':'+FIXED,'-'],MAX_FILE,CAPTURE_SECONDS)
                if not raw:
                    err=err.decode('utf-8','replace')
                    matches=code!=0 and 'Could not find the file '+FIXED+' in container ' in err and (self.name in err or self.container_id in err)
                    if not matches:raise RuntimeError('Docker artifact capture failed without a trusted absent diagnostic')
                    receipt.update(state='absent');receipt['daemonEvidence'].update(missingFileDiagnosticMatched=True,diagnosticSha256=hashlib.sha256(err.encode()).hexdigest())
                else:
                    try:
                        header=host.first_artifact_member(raw)
                        if header is None:raise RuntimeError('Daemon artifact metadata was incomplete')
                        if Path(header.name).name!='stat_ocr.xlsx':raise RuntimeError('Unexpected daemon artifact member')
                        kind='directory' if header.isdir() else 'symlink' if header.issym() or header.islnk() else 'regular' if header.isfile() else 'unsupported'
                        if kind=='unsupported':raise RuntimeError('Unsupported daemon output object')
                        state=kind if kind!='regular' else 'too_large' if header.size>MAX_FILE else 'regular'
                        receipt.update(state=state);receipt['daemonEvidence'].update(memberKind=kind,memberName=header.name,size=header.size)
                        if state=='regular':
                            if code or not complete:raise RuntimeError('Docker regular-file transfer failed')
                            data=private.read_output_tar(raw);path=box/'stat_ocr.xlsx';path.write_bytes(data);receipt.update(artifactSha256=private.sha(path),artifactBytes=len(data),hostArtifactPath=str(path))
                        receipt['daemonEvidence'].update(rawTarSha256=hashlib.sha256(raw).hexdigest(),rawTarCapturedBytes=len(raw),rawTarCaptureComplete=complete)
                    except Exception:raise
            receipt_path=box/'capture-receipt.json';save(receipt_path,receipt);receipt['captureReceiptPath']=str(receipt_path);self.captures.append(receipt);return receipt
    def resume(self):
        if self.sealed:return
        if self.args.mode=='mock':self.running=True;return
        self.lease.acquire();self.docker.record_lease(self.lease);self.docker.active=self.name
        self.docker.checked('start',self.name);self.running=True;self.runtime=Runtime(self.name,self.assets)
    def grade(self,receipt):
        if self.args.mode=='mock':return {'validated':False,'mock':True,'status':'simulated_grader_no_official_tests','formalLlmClosedLoopValidated':False,'officialGradingValid':False}
        if self.docker.active:self.docker.active=None # stopped candidate is retained, only the private grader may be active
        folder=self.home/('grade-'+uuid.uuid4().hex[:8])
        argv=[sys.executable,'-B','-X','utf8',str(ROOT/'scripts/benchmark-repair/software-jpg-private-grader.py'),'--grade','--capture-receipt',receipt['captureReceiptPath'],'--image-manifest',str(self.args.image_manifest),'--build-proof',str(self.args.build_proof),'--dependency-profile',str(self.args.dependency_profile),'--output',str(folder)]
        if receipt['state']=='regular':argv+=['--candidate-output',receipt['hostArtifactPath'],'--candidate-sha256',receipt['artifactSha256']]
        elif receipt['state']=='absent':argv+=['--captured-absent']
        else:argv+=['--captured-format-failure',receipt['state']]
        result=host.run_private_grader(argv,folder,self.image,650)
        if result.returncode or not (folder/'report.json').is_file():raise RuntimeError('Private grader CLI did not close its report')
        report=json.loads((folder/'report.json').read_text())
        if report.get('validated')is not True:raise RuntimeError('Private original-image grader was invalid')
        self.docker.active=self.name if self.running else None
        return report
    def judge(self,body):
        with self.lock:
            if body.get('place')!=self.place:raise RuntimeError('Foreign candidate grade rejected')
            final=False
            if self.db_path:
                with sqlite3.connect('file:'+self.db_path.as_posix()+'?mode=ro',uri=True)as db:
                    row=db.execute('select state from task where id=?',(self.task_id,)).fetchone()
                    handed=db.execute("select 1 from agent_bot_msg where instance like ? and kind='tool' and json_valid(body) and json_extract(body,'$.name')='submit' limit 1",(self.task_id+'#%',)).fetchone()
                    final=bool(handed)or(row and row[0]in['done','failed'])
            receipt=self.capture(final)
            try:report=self.grade(receipt);self.latest=(str(body.get('said','')),report);return report
            finally:self.resume()
    def remove(self):
        with self.lock:
            if self.runtime:self.runtime.close();self.runtime=None
            if self.args.mode=='live':
                for name in list(self.docker.owned):self.docker.remove(name)
                self.lease.release();self.docker.record_lease_release()
            self.name=None;self.place=None;self.running=False

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['mock','live'],required=True);parser.add_argument('--port',type=int,required=True);parser.add_argument('--home',type=Path,required=True)
    for name in ['image-manifest','build-proof','dependency-profile']:parser.add_argument('--'+name,type=Path)
    args=parser.parse_args();bridge=Bridge(args)
    process_identity={'pid':os.getpid(),'parentPid':os.getppid(),'executable':str(Path(sys.executable).resolve()),'executableSha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),'nonce':os.environ.get('OBJRUN_JPG_LIFECYCLE_NONCE',''),'pythonVersion':sys.version,'protocol':'jpg-native-python-service-lifecycle-v2'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,value,status=200):
            raw=json.dumps(value).encode();self.send_response(status);self.send_header('content-type','application/json');self.send_header('content-length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path=='/health':self.send({'backend':args.mode,'protocol':PROTOCOL,'denominator':87,'implementedTaskIds':[TASK_ID],'readyTaskIds':[],'unsupportedTaskCount':86,'authenticated':True,'supportedTools':sorted(TOOLS),'maxLiveCandidates':1,'officialGradingValid':False,'rpcForwardCount':bridge.counter,'processIdentity':process_identity});return
            self.send({'error':'Unknown protected route'},404)
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('X-ObjRun-Grader-Token',''),bridge.token):self.send({'error':'Unauthorized bridge'},401);return
            try:
                size=int(self.headers.get('content-length',0))
                if not 0<=size<=4*1024*1024:raise RuntimeError('Body limit')
                body=json.loads(self.rfile.read(size)or b'{}')
                if self.path=='/place':self.send(bridge.call(body));return
                if self.path=='/register':
                    path=Path(body['databasePath']).resolve()
                    if not path.is_relative_to(bridge.home.parent.resolve()):raise RuntimeError('Foreign database path')
                    bridge.db_path=path;bridge.task_id=str(body['taskId']);self.send({'ok':True});return
                if self.path=='/capture':
                    if body.get('place')!=bridge.place:raise RuntimeError('Foreign candidate capture rejected')
                    self.send(bridge.capture(bool(body.get('final'))));return
                if self.path=='/grade-captured':
                    if not bridge.captures or body.get('captureReceiptPath')!=bridge.captures[-1]['captureReceiptPath']:raise RuntimeError('Fixed host capture receipt is required')
                    self.send(bridge.grade(bridge.captures[-1]));return
                if self.path=='/stop':
                    if body.get('place')!=bridge.place:raise RuntimeError('Foreign candidate stop rejected')
                    bridge.remove();self.send({'ok':True,'ownedContainersRemaining':len(bridge.docker.owned) if bridge.docker else 0});return
                if self.path in ['/verified','/passed']:
                    body=body.get('input',body)
                    task=body.get('task')or{}
                    body['place']=body.get('place',task.get('place'))
                    body['said']=body.get('said',(body.get('result')or{}).get('body',task.get('result','')))
                    if body.get('place')!=bridge.place:raise RuntimeError('Foreign objective grade rejected')
                    report=bridge.judge(body) if self.path=='/verified' or bridge.latest is None or bridge.latest[0]!=str(body.get('said','')) else bridge.latest[1]
                    if args.mode=='mock':self.send({'value':False,'valid':True,'note':'local simulation; official grader not executed','mock':True});return
                    verdict=report['candidateVerdict'];self.send({'value':bool(verdict['ran']) if self.path=='/verified' else verdict['reward']==1,'valid':verdict['valid'],'note':json.dumps({'tests':verdict['completedTests'],'passed':verdict['passedTests'],'artifactSha256':verdict.get('artifactSha256')})});return
                self.send({'error':'Unknown bridge route'},404)
            except Exception:self.send({'valid':False,'outcome':'grader_error','error':'owned capture/runtime/grader operation did not certify'},503)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    try:server.serve_forever()
    finally:bridge.remove();server.server_close()

if __name__=='__main__':main()
