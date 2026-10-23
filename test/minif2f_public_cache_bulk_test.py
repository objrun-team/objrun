"""F-only synthetic bulk streams plus actual durable files; zero network/E/LLM."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.client import HTTPMessage
import importlib.util
import json
from pathlib import Path
import ssl
import unittest
import urllib.error
import uuid

PROJECT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bulk_stage_control',PROJECT/'scripts/repair-2026-10-08/minif2f_public_cache_bulk_stage.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s);k=s.k
BASE=PROJECT/'.scratch/minif2f-public-bulk-tests';BASE.mkdir(exist_ok=True)


class Response:
    def __init__(self,key,data,advertised=None,error=None):
        self.status=200;self.url=k.AZURE+key;self.headers=HTTPMessage();self.at=0
        self.data,self.error=data,error;advertised=data if advertised is None else advertised
        self.headers.add_header('Content-Length',str(len(advertised)))
        self.headers.add_header('Content-MD5',base64.b64encode(hashlib.md5(advertised,usedforsecurity=False).digest()).decode())
        self.headers.add_header('ETag','0xFIXTUREOPAQUE');self.closed=False
    def geturl(self):return self.url
    def read1(self,limit):
        if self.error and self.at>=len(self.data):raise self.error
        value=self.data[self.at:self.at+8192];self.at+=len(value);return value
    def __enter__(self):return self
    def __exit__(self,*_):self.closed=True
    def close(self):self.closed=True


class Opener:
    def __init__(self,*items):self.items=list(items);self.requests=[]
    def open(self,request,timeout):
        self.requests.append(request);item=self.items.pop(0)
        if isinstance(item,Exception):raise item
        return item


class BulkControls(unittest.TestCase):
    def setUp(self):
        self.root=BASE/str(uuid.uuid4());(self.root/'audit').mkdir(parents=True)
        (self.root/'downloads/mathlib-cache').mkdir(parents=True)
        self.receipt=self.root/'audit/cache-downloads.jsonl';self.receipt.write_bytes(b'')
        self.lease=type('FixtureLease',(),{'id':str(uuid.uuid4())})()
        self.book=k.Book(0,292278,reserve=lambda *_:{'fixtureOnly':True})
        self.journal=k.Journal(self.root);self.dispatch=s.DispatchJournal(self.root,self.lease.id,'f'*64)
        self.book.dispatch_journal=self.dispatch;self.completed={}
        self.key='aaaaaaaaaaaaaaaa.ltar';self.data=(b'fixture-public-body\x00'*2000)[:32769]
    def run_one(self,opener,key=None):
        key=key or self.key
        return k.get_one({'ltar':key,'module':'Fixture/Control.lean'},self.root,self.lease,self.book,
            self.journal,self.book.check,self.receipt,self.completed,opener,sleeper=lambda _:None)
    def evidence(self):return k.validate_evidence(self.root,[{'ltar':n}for n in self.book.get_counts],
        {'body_journal':self.journal.footer(),'prefix_operations_closed':True})
    def test_complete_get_md5_sha_and_unknown_all_history(self):
        opener=Opener(Response(self.key,self.data));r=self.run_one(opener)
        self.assertEqual(r['transport_gets'],1);self.assertEqual(r['old_v3_key_interval'],[0,3])
        self.assertEqual(r['v3_plus_bulk_key_interval'],[1,4]);self.assertIsNone(r['all_history_key_gets'])
        self.assertIsNone(r['all_history_global_gets']);self.assertEqual(r['sha256'],hashlib.sha256(self.data).hexdigest())
        k.validate_new_rows(self.root,self.completed,self.evidence())
        counts,n,_=s.inspect_dispatch(self.dispatch.path,self.lease.id,'f'*64,{self.key});self.assertEqual(n,1)
        self.assertEqual(counts,{self.key:1});self.assertNotIn('Range',opener.requests[0].headers)
        self.assertNotIn('Authorization',opener.requests[0].headers);self.assertLessEqual(len(k.encode_row(r)),2048)
    def test_short_eof_preserves_g1_and_complete_fresh_g2(self):
        opener=Opener(Response(self.key,self.data[:12000],self.data),Response(self.key,self.data))
        r=self.run_one(opener);self.assertEqual(r['transport_gets'],2);self.assertEqual(r['body_generations'],2)
        self.assertEqual(self.book.recoveries,1);self.assertEqual(self.book.prefix_bytes,292278+12000)
        e=self.evidence();prefix=next(iter(e['prefixes'].values()))
        self.assertEqual(prefix['body_error_type'],'ShortBodyEOF');self.assertEqual((self.root/prefix['path']).read_bytes(),self.data[:12000])
        self.assertEqual((self.root/'downloads/mathlib-cache'/self.key).read_bytes(),self.data)
        self.assertEqual(r['failed_prefix_bytes_reused_in_body'],0);k.validate_new_rows(self.root,self.completed,e)
    def test_timeout_then_fresh_success_has_durable_prefix(self):
        opener=Opener(Response(self.key,self.data[:9000],self.data,TimeoutError('fixture')),Response(self.key,self.data))
        r=self.run_one(opener);self.assertEqual(r['body_generations'],2);self.assertEqual(self.book.recoveries,1)
        self.assertEqual(next(iter(self.evidence()['prefixes'].values()))['body_error_type'],'TimeoutError')
    def test_second_eof_stops_with_both_generations_and_no_third(self):
        opener=Opener(Response(self.key,self.data[:1000],self.data),Response(self.key,self.data[:17000],self.data))
        with self.assertRaises(k.ShortBodyEOF):self.run_one(opener)
        self.assertEqual(len(opener.requests),2);self.assertFalse(self.completed)
        parts=self.book.settle_unclosed_parts();self.assertEqual(len(parts),1);self.assertEqual(parts[0]['bytes'],17000)
        self.assertEqual(self.evidence()['bytes'],1000)
    def test_opening_timeout_and_body_timeout_share_three_gets(self):
        opener=Opener(TimeoutError('opening'),Response(self.key,self.data[:6000],self.data,TimeoutError('body')),Response(self.key,self.data))
        r=self.run_one(opener);self.assertEqual(r['transport_gets'],3);self.assertEqual(self.book.open_calls,3)
        self.assertEqual(len(opener.requests),3)
    def test_three_opening_timeouts_consume_three_and_stop(self):
        opener=Opener(*[TimeoutError('opening')for _ in range(3)])
        with self.assertRaises(TimeoutError):self.run_one(opener)
        self.assertEqual(self.book.gets,3);self.assertEqual(self.book.open_calls,3);self.assertFalse(self.completed)
    def test_http_tls_and_wrong_headers_never_retry(self):
        for error in (ssl.SSLError('fixture'),urllib.error.HTTPError(k.AZURE+self.key,403,'fixture',None,None)):
            self.setUp();opener=Opener(error)
            with self.assertRaises(Exception):self.run_one(opener)
            self.assertEqual(len(opener.requests),1);self.assertFalse(self.completed)
        self.setUp();response=Response(self.key,self.data);del response.headers['Content-MD5'];opener=Opener(response)
        with self.assertRaisesRegex(RuntimeError,'Content-MD5'):self.run_one(opener)
        self.assertEqual(len(opener.requests),1)
    def test_complete_md5_and_prefix_drift_rejected_without_retry(self):
        opener=Opener(Response(self.key,b'X'+self.data[1:],self.data))
        with self.assertRaisesRegex(RuntimeError,'MD5'):self.run_one(opener)
        self.assertEqual(len(opener.requests),1);self.assertFalse(self.completed)
        self.setUp();opener=Opener(Response(self.key,self.data[:1000],self.data),Response(self.key,b'X'+self.data[1:],self.data))
        with self.assertRaisesRegex(RuntimeError,'prefix SHA'):self.run_one(opener)
        self.assertEqual(len(opener.requests),2);self.assertFalse(self.completed);self.evidence()
    def test_stage_four_recoveries_then_refuses_fifth_and_keeps_part(self):
        for i in range(4):
            key=f'{i:016x}.ltar';self.run_one(Opener(Response(key,self.data[:1000],self.data),Response(key,self.data)),key)
        key='5555555555555555.ltar'
        with self.assertRaisesRegex(RuntimeError,'budget4'):self.run_one(Opener(Response(key,self.data[:1000],self.data)),key)
        self.assertEqual(self.book.recoveries,4);self.assertEqual(len(self.book.settle_unclosed_parts()),1)
    def test_shared_dispatch_order_and_per_key_identity(self):
        keys={f'{i:016x}.ltar'for i in range(4)}
        def fetch(key):return self.run_one(Opener(Response(key,self.data)),key)
        with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(fetch,keys))
        counts,n,_=s.inspect_dispatch(self.dispatch.path,self.lease.id,'f'*64,keys)
        self.assertEqual(n,4);self.assertEqual(counts,{key:1 for key in keys})
        self.assertEqual(self.book.open_calls,4);self.assertEqual(len(self.completed),4)
    def test_existing_intent_and_failed_fsync_do_not_dispatch_again(self):
        with self.assertRaises(RuntimeError):s.DispatchJournal(self.root,self.lease.id,'f'*64)
        class FailedJournal:
            def append(self,_):raise OSError('fixture fsync failure')
        self.book.dispatch_journal=FailedJournal();opener=Opener(Response(self.key,self.data))
        with self.assertRaises(OSError):self.run_one(opener)
        self.assertEqual(self.book.gets,1);self.assertEqual(self.book.open_calls,0);self.assertEqual(opener.requests,[])
    def test_inflight_abort_retention_forecast_and_original_deadline(self):
        for i in range(3):self.book.begin(str(i),k.MAX_BLOB)
        with self.assertRaisesRegex(RuntimeError,'retention forecast'):self.book.begin('fourth',k.MAX_BLOB)
        self.assertEqual(len(self.book.reservations),3)
        with self.assertRaisesRegex(RuntimeError,'expired'):
            k.carry.Deadline(wall=lambda:k.carry.DEADLINE+1,monotonic=lambda:0)


if __name__=='__main__':unittest.main(verbosity=2)
