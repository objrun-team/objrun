"""Real scientific HTTP handlers, mocked score backend; no data downloads."""
import ast
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
import threading
import unittest
from unittest.mock import Mock
import urllib.error
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'examples/benchmark/_lib'))
from grader_status import require_valid_verdict,fault_payload

class ScientificHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servers={}
        for slug in ['scicode','llm-srbench']:
            env={'ast':ast,'hashlib':hashlib,'json':json,'re':re,'BaseHTTPRequestHandler':BaseHTTPRequestHandler,
                 'PROBLEMS':{'5':{'required_dependencies':'','sub_steps':[{}]}},'PILOT_IDS':['5'],
                 'PREFIXES':{'case':{'problem':'5','step':0,'previous':[]}},
                 'BOOK':{'case':{'rawId':'5'}},'CACHE':{},'score':Mock(),
                 'require_valid_verdict':require_valid_verdict,'fault_payload':fault_payload}
            path=ROOT/f'examples/benchmark/{slug}/stand.py'
            tree=ast.parse(path.read_text(encoding='utf-8'))
            definitions=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))]
            exec(compile(ast.Module(body=definitions,type_ignores=[]),str(path),'exec'),env)
            server=ThreadingHTTPServer(('127.0.0.1',0),env['Handler'])
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True)
            thread.start();cls.servers[slug]=(env,server,thread)
    @classmethod
    def tearDownClass(cls):
        for _,server,thread in cls.servers.values():
            server.shutdown();server.server_close();thread.join(timeout=2)
    def setUp(self):
        for env,_,_ in self.servers.values():
            env['CACHE'].clear();env['score'].reset_mock();env['score'].side_effect=None
            env['score'].return_value={'valid':True,'passed':False}
    def request(self,slug,route,tid='case',code='def predict(X): return X[:,0]'):
        port=self.servers[slug][1].server_address[1]
        body={'input':{'task':{'id':tid},'result':{'body':code}},'problem':'5','codes':[code]}
        req=urllib.request.Request(f'http://127.0.0.1:{port}/{route}',json.dumps(body).encode(),{'content-type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=3) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:return error.code,json.load(error)
    def routes(self):
        return [('scicode','passed'),('scicode','accept'),('llm-srbench','correct'),('llm-srbench','accept')]
    def test_outage_recovers_on_same_candidate(self):
        for slug,route in self.routes():
            env=self.servers[slug][0];env['CACHE'].clear();env['score'].reset_mock()
            env['score'].side_effect=[{'valid':False,'passed':False,'errorType':'hidden-reference=123456'},
                                      {'valid':True,'passed':True}]
            with self.subTest(slug=slug,route=route):
                status,body=self.request(slug,route);self.assertEqual(status,503)
                self.assertIs(body['valid'],False);self.assertEqual(body['outcome'],'grader_error')
                self.assertNotIn('123456',json.dumps(body))
                status,body=self.request(slug,route);self.assertEqual(status,200)
                self.assertIs(body['passed'] if route=='accept' else body['value'],True)
                self.assertEqual(env['score'].call_count,2)
            env['score'].side_effect=None
    def test_malformed_verdict_is_invalid_and_uncached(self):
        for slug,route in self.routes():
            env=self.servers[slug][0]
            for malformed in [None,{},True,{'valid':True,'passed':'true'},{'valid':'true','passed':False}]:
                env['CACHE'].clear();env['score'].reset_mock()
                env['score'].side_effect=[malformed,{'valid':True,'passed':False}]
                with self.subTest(slug=slug,route=route,malformed=malformed):
                    self.assertEqual(self.request(slug,route)[0],503)
                    status,body=self.request(slug,route);self.assertEqual(status,200)
                    self.assertIs(body['passed'] if route=='accept' else body['value'],False)
                    self.assertEqual(env['score'].call_count,2)
                env['score'].side_effect=None
    def test_exceptions_are_sanitized_grader_faults(self):
        for slug,route in self.routes():
            env=self.servers[slug][0];env['CACHE'].clear()
            env['score'].side_effect=RuntimeError('hidden-reference=123456')
            with self.subTest(slug=slug,route=route):
                status,body=self.request(slug,route);self.assertEqual(status,503)
                self.assertIs(body['valid'],False);self.assertEqual(body['outcome'],'grader_error')
                self.assertEqual(body['errorType'],'RuntimeError');self.assertNotIn('123456',json.dumps(body))
            env['score'].side_effect=None
    def test_valid_rejections_can_be_cached(self):
        for slug,route in [('scicode','passed'),('llm-srbench','correct'),('llm-srbench','accept')]:
            env=self.servers[slug][0];env['CACHE'].clear();env['score'].reset_mock()
            for _ in range(2):
                status,body=self.request(slug,route);self.assertEqual(status,200)
                self.assertIs(body['passed'] if route=='accept' else body['value'],False)
            self.assertEqual(env['score'].call_count,1)
    def test_training_and_final_scores_are_separate(self):
        env=self.servers['llm-srbench'][0]
        env['score'].side_effect=[{'valid':True,'passed':False},{'valid':True,'passed':True}]
        self.assertIs(self.request('llm-srbench','correct')[1]['value'],False)
        self.assertIs(self.request('llm-srbench','accept')[1]['passed'],True)
        self.assertIs(self.request('llm-srbench','correct')[1]['value'],False)
        self.assertEqual(env['score'].call_count,2)
    def test_final_acceptance_records_code_identity(self):
        code='def predict(X): return X[:,0]'
        status,body=self.request('scicode','accept',code=code)
        self.assertEqual(status,200)
        self.assertEqual(body['candidateCodeSha256'],[hashlib.sha256(code.encode()).hexdigest()])
        self.assertEqual(body['cumulativeCodeSha256'],hashlib.sha256(('\n\n'+code).encode()).hexdigest())
    def test_unknown_task_does_not_call_backend(self):
        for slug,route in [('scicode','passed'),('llm-srbench','correct')]:
            env=self.servers[slug][0]
            self.assertEqual(self.request(slug,route,tid='unknown')[0],422)
            env['score'].assert_not_called()

if __name__=='__main__':unittest.main()
