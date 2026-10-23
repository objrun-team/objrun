"""Authenticated10-task six-tool/capture/private-grade bridge with one solver."""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
from skb_artifact_solver_v2 import Solver
from skb_artifact_ram_executor_v2 import grade_captured,fresh
from skb_artifact_grade_audit_v2 import validate_grade_report

PROTOCOL='skillsbench-ten-data-artifact-stand-v2'


class Bridge:
    def __init__(self,recipe_pin):
        self.recipe_pin=recipe_pin;self.recipe=task.read_json(recipe_pin)
        task.demand(self.recipe['family']=='skillsbench-artifact-journal-v1' and self.recipe['selectedDistinctTasks']==10,'stand_family','Exact independent10-task recipe required')
        self.lp=self.recipe['storageDescriptorPin'];self.layout=task.read_json(self.lp);storage.validate_descriptor(self.layout)
        descriptors=self.recipe['taskDescriptorPins'];task.demand(len(descriptors)==10,'stand_tasks','Actual10 ready task descriptors required')
        self.descriptors={}
        for tid,dp in zip(task.TASK_IDS,descriptors):
            d=task.read_json(dp);task.demand(d['taskId']==tid,'stand_tasks','Fixed source task order differs')
            # The fast first delivery reuses the actually completed collection.
            # It leaves repeated historical/native certification for later.
            if self.recipe.get('draftFastFirst'):
                task.validate_descriptor(d);c=task.read_json(d['expectedCollectionPin'])
                task.demand(c['actualRawGraphValidated'] is True and c['taskId']==tid and c['nodeIds'],'stand_collection','Existing actual complete collection required')
            else:task.validate_descriptor(d,True)
            self.descriptors[tid]=dp
        self.token=os.environ.get('TGENGIN_GRADER_TOKEN','');task.demand(len(self.token)>=32,'stand_token','Private host token required')
        self.lock=threading.RLock();self.solver=None;self.place=None;self.db=None;self.task_id=None;self.registered_place=None;self.sealed=False;self.latest=None;self.counter=0;self.captures=[];self.grade_pins=[];self.closures=[]
        self.home=Path(self.layout['directories']['stand']);storage.ordinary(self.home,Path(self.layout['storePhysical']))

    def identify(self,place):
        prefix='skb:'+self.recipe['runId']+'/skillsbench/'
        task.demand(isinstance(place,str) and place.startswith(prefix),'stand_place','Foreign run/place rejected')
        parts=place[len(prefix):].split('/')
        task.demand(len(parts)==3 and parts[0] in ('U','F') and parts[1]=='0' and parts[2] in self.descriptors,'stand_place','Exact paired selected task/arm required')
        return parts[2]

    def create(self,place):
        tid=self.identify(place)
        if self.solver:task.demand(place==self.place,'stand_one_solver','Only one owned live task solver');return
        self.place=place;self.sealed=False;self.latest=None;self.captures=[]
        task.demand(self.registered_place in (None,place),'stand_registration','Foreign registered task/place rejected')
        self.solver=Solver(self.descriptors[tid],self.lp);self.solver.create(True)

    def call(self,body):
        with self.lock:
            self.create(body['place'])
            if self.db:
                with closing(sqlite3.connect('file:'+self.db.as_posix()+'?mode=ro',uri=True)) as db:
                    row=db.execute('select created_at,solve_seconds from task where id=?',(self.task_id,)).fetchone()
                if row:self.solver.bind_engine_deadline(*row)
            if body.get('op')=='ping':return {'alive':self.solver.running and not self.sealed,'ownedContainerID':self.solver.cid,
                'environmentAudit':{'forbiddenHostKeysPresent':False,'standTokenPresent':False},'modelCalls':0,'mock':False}
            task.demand(not self.sealed,'stand_sealed','No tools after delivery')
            self.latest=None;self.counter+=1;return self.solver.call(body['tool'],body.get('args') or {})

    def register(self,body):
        with self.lock:
            self.identify(body['place']);path=Path(body['databasePath']).resolve();root=Path(self.layout['directories']['sqlite']).resolve()
            task.demand(root in path.parents and path.name=='h2h.sqlite' and body['taskId']==body['place'][4:]
                        and self.place in (None,body['place']),'stand_database','Exact owned engine database/task/place required')
            storage.ordinary(path.parent,Path(self.layout['storePhysical']))
            task.demand(path.is_file() and not path.is_symlink() and path.stat().st_nlink==1,'stand_database','Ordinary owned SQLite file required')
            self.db=path;self.task_id=body['taskId'];self.registered_place=body['place'];return {'ok':True}

    def final(self):
        if not self.db:return False
        with closing(sqlite3.connect('file:'+self.db.as_posix()+'?mode=ro',uri=True)) as db:
            row=db.execute('select state from task where id=?',(self.task_id,)).fetchone()
        # DFS may submit a failed node and then keep working in another node.
        # Only the engine's terminal task state closes all future mutations.
        return bool(row and row[0] in ('done','failed'))

    def cache_key(self,body):
        task.demand(self.solver and body['place']==self.place,'stand_grade','Foreign grade/cache request rejected')
        epoch=self.captures[-1]['capturePin']['sha256'] if self.captures else None
        return (self.place,self.solver.dp['sha256'],self.solver.nonce,self.counter,epoch,str(body.get('said','')))

    def objective(self,body,kind):
        with self.lock:
            key=self.cache_key(body)
            if kind=='verified' or self.latest is None or self.latest[0]!=key:return self.judge(body)
            return self.latest[1:]

    def capture(self,place,final=False):
        with self.lock:
            task.demand(self.solver and place==self.place,'stand_capture','Foreign capture rejected')
            if final and self.sealed and self.captures:return self.captures[-1]
            if final:self.sealed=True
            cp=self.solver.capture(final)
            record={'capturePin':cp,'captureReceiptPath':cp['path'],'ownedContainerID':self.solver.cid,'stoppedAt':self.solver.stopped_at,
                'taskDescriptorPin':self.solver.dp,'state':task.read_json(cp)['state'],'final':final}
            self.captures.append(record);return record

    def judge(self,body):
        with self.lock:
            task.demand(self.solver and body['place']==self.place,'stand_grade','Foreign grade rejected')
            final=self.final();record=self.capture(self.place,final)
            try:
                op=grade_captured(self.solver.dp,self.lp,record['capturePin']);self.grade_pins.append(op)
                replay=validate_grade_report(self.solver.dp,op,False);result=replay['result'];evaluation=result['evaluation']
                self.latest=(self.cache_key(body),evaluation,op)
                return evaluation,op
            finally:
                if not final and not self.sealed and not self.solver.running:self.solver.resume()

    def remove(self,place=None):
        with self.lock:
            if not self.solver:return {'ok':True,'ownedContainersRemaining':0}
            task.demand(place is None or place==self.place,'stand_stop','Foreign solver stop rejected')
            pin=self.solver.close();self.closures.append(pin);task.demand(self.solver.closed,'stand_close','Actual owned solver remains')
            self.solver=None;self.place=None;self.latest=None;self.db=None;self.task_id=None;self.registered_place=None
            return {'ok':True,'closurePin':pin,'ownedContainersRemaining':0}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,required=True);p.add_argument('--recipe',type=Path,required=True);a=p.parse_args()
    recipe_pin=task.pin(a.recipe.resolve());bridge=Bridge(recipe_pin)
    identity={'pid':os.getpid(),'parentPid':os.getppid(),'executable':str(Path(sys.executable).resolve()),'executableSha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        'nonce':os.environ.get('OBJRUN_JPG_LIFECYCLE_NONCE',''),'pythonVersion':sys.version,'protocol':'jpg-native-python-service-lifecycle-v2'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,value,status=200):
            raw=json.dumps(value).encode();self.send_response(status);self.send_header('content-type','application/json');self.send_header('content-length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path=='/health':self.send({'backend':'live','protocol':PROTOCOL,'denominator':87,'implementedTaskIds':list(task.TASK_IDS),
                'readyTaskIds':list(task.TASK_IDS),'unsupportedTaskCount':77,'authenticated':True,'supportedTools':sorted(__import__('skb_artifact_solver_plan_v2').TOOLS),
                'maxLiveCandidates':1,'rpcForwardCount':bridge.counter,'processIdentity':identity,'storageProtocol':bridge.layout['protocol'],
                'storageOwnerNonce':bridge.layout['ownerNonce'],'storageDescriptorPin':bridge.lp,'modelCalls':0});return
            self.send({'error':'Unknown bridge route'},404)
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('X-ObjRun-Grader-Token',''),bridge.token):self.send({'error':'Unauthorized bridge'},401);return
            try:
                n=int(self.headers.get('content-length','0'));task.demand(0<=n<=4*1024**2,'stand_body','Bounded request required')
                body=json.loads(self.rfile.read(n) or b'{}')
                if self.path=='/register':self.send(bridge.register(body));return
                if self.path=='/place':self.send(bridge.call(body));return
                if self.path=='/capture':self.send(bridge.capture(body['place'],body.get('final') is True));return
                if self.path=='/stop':self.send(bridge.remove(body['place']));return
                if self.path=='/shutdown':
                    closed=bridge.remove();self.send(closed);threading.Thread(target=server.shutdown,daemon=True).start();return
                if self.path=='/grade-captured':
                    cp=body['capturePin'];dp=body['taskDescriptorPin'];task.demand(any(x['capturePin']==cp and x['taskDescriptorPin']==dp for x in bridge.captures),'stand_capture','Only actual owned captured artifact/descriptor may be graded')
                    op=grade_captured(dp,bridge.lp,cp);bridge.grade_pins.append(op);self.send({'gradeOwnerPin':op});return
                parts=self.path.strip('/').split('/')
                if len(parts)==2 and parts[0] in task.TASK_IDS and parts[1] in ('verified','passed'):
                    body=body.get('input',body);t=body.get('task') or {};body['place']=body.get('place',t.get('place'));body['said']=body.get('said',(body.get('result') or {}).get('body',t.get('result','')))
                    task.demand(bridge.identify(body['place'])==parts[0],'stand_objective','Foreign task objective rejected')
                    evaluation,op=bridge.objective(body,parts[1])
                    self.send({'value':bool(evaluation['valid']) if parts[1]=='verified' else bool(evaluation['allTestsPassed']),
                        'valid':True,'note':json.dumps({'tests':evaluation['collectedTests'],'passed':evaluation['passedTests'],'failed':evaluation['failedTests'],
                        'officialReward':evaluation['officialReward'],'completeCollection':evaluation['collectionValidated']}),'gradeOwnerPin':op});return
                self.send({'error':'Unknown protected route'},404)
            except Exception:self.send({'valid':False,'outcome':'grader_error','error':'Owned capture/runtime/grader graph did not certify'},503)
    server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
    try:server.serve_forever()
    finally:
        close_fault=None
        try:bridge.remove()
        except BaseException as e:close_fault={'type':type(e).__name__,'kind':getattr(e,'kind',None)}
        finally:
            server.server_close()
            fresh(bridge.home/'bridge-owned-close.json',task.canonical({'protocol':PROTOCOL+'-owned-close','actorPid':os.getpid(),'recipePin':recipe_pin,
                'solverClosures':bridge.closures,'gradeOwnerPins':bridge.grade_pins,'ownedSolversClosed':close_fault is None and bridge.solver is None,
                'closeFault':close_fault,'modelCalls':0,'parentActorClosureRequired':True}),Path(bridge.layout['storePhysical']))


if __name__=='__main__':main()
