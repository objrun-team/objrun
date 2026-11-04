"""Exercise the real HTTP handlers without downloading or starting task images.

Only the grading backend and Linux caller-namespace probe are substituted. These
tests prove transport/fault semantics, not official task grading or isolation.
"""
import ast
import contextlib
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import subprocess
import threading
import time
import unittest
from unittest.mock import Mock
import urllib.error
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'examples/benchmark/_lib'))
from grader_status import require_result, fault_payload, can_cache_result

BENCHES={'deepswe':('applies','resolved'),'terminal-bench':('ran','passed'),'skillsbench':('verified','passed')}

def definitions(slug, names, namespace):
    path=ROOT/f'examples/benchmark/{slug}/stand.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    selected=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in names]
    if len(selected)!=len(names):raise AssertionError('Expected the actual adapter definitions')
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),namespace)
    return namespace

class ContainerGraderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servers={}
        for slug in BENCHES:
            env={'json':json,'hmac':hmac,'GRADER_TOKEN':'host-only-test-token','ALLOW_UNSAFE_DIAGNOSTIC':False,'BaseHTTPRequestHandler':BaseHTTPRequestHandler,'BOOK':{'case':{}},'task_id_of':lambda tid:tid.split('/')[-1],'container_of':lambda place:place,'ref_of':lambda value:value,'judge':Mock(return_value={'reward':0,'ran':True}),'judged':lambda *_:None,'note_of':lambda *_:'','from_container':lambda *_:(False,''),'AUTOCOMMITTED':{},'require_result':require_result,'fault_payload':fault_payload}
            definitions(slug,{'Handler','task_of'},env)
            server=ThreadingHTTPServer(('127.0.0.1',0),env['Handler'])
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True);thread.start()
            cls.servers[slug]=(env,server,thread)
    @classmethod
    def tearDownClass(cls):
        for _,server,thread in cls.servers.values():server.shutdown();server.server_close();thread.join(timeout=2)
    def setUp(self):
        for env,_,_ in self.servers.values():
            env['judge'].reset_mock();env['judge'].side_effect=None;env['judge'].return_value={'reward':0,'ran':True}
    def request(self,slug,route,tid='case'):
        port=self.servers[slug][1].server_address[1]
        body={'input':{'task':{'id':tid,'place':slug+':'+tid},'result':{'body':'deadbeef'}},'place':slug+':'+tid,'feed':[{'value':True}]}
        req=urllib.request.Request(f'http://127.0.0.1:{port}/{route}',json.dumps(body).encode(),{'content-type':'application/json','X-ObjRun-Grader-Token':'host-only-test-token'})
        try:
            with urllib.request.urlopen(req,timeout=3) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def test_verifier_crash_is_invalid_for_online_and_offline_grading(self):
        for slug,nodes in BENCHES.items():
            self.servers[slug][0]['judge'].return_value={'reward':0,'crashed':True,'why':'hidden-reference-answer=123456'}
            for route in (*nodes,'grade'):
                with self.subTest(slug=slug,route=route):
                    status,body=self.request(slug,route);self.assertEqual(status,503);self.assertFalse(body['valid']);self.assertEqual(body['outcome'],'grader_error');self.assertNotIn('123456',json.dumps(body));self.assertNotIn('value',body)
    def test_valid_rejections_and_passes_keep_boolean_semantics(self):
        for slug,(first,last) in BENCHES.items():
            for reward in [0,1]:
                self.servers[slug][0]['judge'].return_value={'reward':reward,'ran':True}
                with self.subTest(slug=slug,reward=reward):
                    status,body=self.request(slug,first);self.assertEqual(status,200);self.assertIs(body['value'],True)
                    status,body=self.request(slug,last);self.assertEqual(status,200);self.assertIs(body['value'],bool(reward))
    def test_backend_exceptions_are_invalid_and_sanitized(self):
        for slug,nodes in BENCHES.items():
            self.servers[slug][0]['judge'].side_effect=RuntimeError('hidden-reference-answer=123456')
            for route in (*nodes,'grade'):
                with self.subTest(slug=slug,route=route):
                    status,body=self.request(slug,route);self.assertEqual(status,503);self.assertEqual(body['errorType'],'RuntimeError');self.assertNotIn('123456',json.dumps(body))
    def test_unknown_task_is_not_a_model_rejection(self):
        for slug,nodes in BENCHES.items():
            for route in (*nodes,'grade'):
                with self.subTest(slug=slug,route=route):
                    status,_=self.request(slug,route,'unknown');self.assertEqual(status,422)
            self.servers[slug][0]['judge'].assert_not_called()
    def test_missing_or_nonfinite_rewards_are_invalid(self):
        for slug,nodes in BENCHES.items():
            for result in [{},{'reward':float('nan')},{'reward':float('inf')},{'reward':2},{'reward':'1'}]:
                self.servers[slug][0]['judge'].return_value=result
                for route in (*nodes,'grade'):
                    with self.subTest(slug=slug,route=route,result=result):self.assertEqual(self.request(slug,route)[0],503)
    def test_deepswe_does_not_cache_a_verifier_outage(self):
        backend=Mock(side_effect=[{'reward':0,'crashed':True},{'reward':1}])
        env={'hashlib':hashlib,'threading':threading,'time':time,'CACHE':{},'CACHE_LOCK':threading.Lock(),'INFLIGHT':{},'VERIFY_SECONDS':1,'GATE':threading.Semaphore(1),'patch_of':lambda *_a,**_k:'immutable patch','run_verifier':backend,'require_result':require_result,'can_cache_result':can_cache_result}
        definitions('deepswe',{'judge'},env)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(env['judge']('place','case','ref')['crashed'])
            self.assertEqual(env['judge']('place','case','ref')['reward'],1)
        self.assertEqual(backend.call_count,2)

    def test_skillsbench_does_not_reuse_a_mutable_state_fingerprint(self):
        backend=Mock(side_effect=[{'reward':1},{'reward':0}])
        env={'threading':threading,'time':time,'uuid':uuid,'CACHE_LOCK':threading.Lock(),'INFLIGHT':{},'GATE':threading.Semaphore(1),'container_up':lambda _:'container','state_key':lambda _:'identical-path-fingerprint','BOOK':{'case':{'verify_seconds':1}},'BACKEND':'docker','sh':lambda *args:subprocess.CompletedProcess(args,0,'',''),'run_verifier':backend}
        # Exercise old snapshot diagnostics; this is not formal scorer trust.
        env['ALLOW_UNSAFE_DIAGNOSTIC']=True
        definitions('skillsbench',{'judge','require_isolation'},env)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(env['judge']('place','case')['reward'],1)
            self.assertEqual(env['judge']('place','case')['reward'],0)
        self.assertEqual(backend.call_count,2)

if __name__=='__main__':unittest.main()
