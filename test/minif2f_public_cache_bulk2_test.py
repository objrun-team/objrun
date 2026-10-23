"""Necessary continuation/real Windows handle controls; F-only and no GET."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import threading
import time
import unittest
import uuid

PROJECT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
s=load('bulk2_control',PROJECT/'scripts/repair-2026-10-08/minif2f_public_cache_bulk2_stage.py');k=s.k
f=load('bulk1_fixture_definitions_only',PROJECT/'test/minif2f_public_cache_bulk_test.py')
BASE=PROJECT/'.scratch/minif2f-bulk2-tests';BASE.mkdir(exist_ok=True)
REPORT=json.loads(s.FAILURE_PATH.read_bytes())
COPIES={Path(p['source']).name:p for p in REPORT['copied_files']}
RAW=Path(COPIES['public-cache-bulk-get-intents.jsonl']['archive']).read_bytes()
MARKER=json.loads(Path(COPIES['public-cache-acquisition.lock']['archive']).read_bytes())


class YieldingIO:
    """Actual FileIO with an injected scheduling opportunity after each seek."""
    def __init__(self,stream):self.stream=stream
    def seek(self,*args):value=self.stream.seek(*args);time.sleep(.0005);return value
    def __getattr__(self,name):return getattr(self.stream,name)


class NecessaryControls(unittest.TestCase):
    def setUp(self):
        self.root=BASE/str(uuid.uuid4());(self.root/'audit').mkdir(parents=True)
        (self.root/'downloads/mathlib-cache').mkdir(parents=True)
        (self.root/k.DISPATCH_REL).write_bytes(RAW)
        self.namespace=MARKER['lease_id'];self.book=k.Book(0,422032,reserve=lambda *_:{'fixtureOnly':True})
        counts={}
        for r in (json.loads(line)for line in RAW.splitlines()):counts[r['key']]=counts.get(r['key'],0)+1
        self.book.prior_counts=dict(counts);self.book.get_counts=dict(counts);self.book.gets=96;self.book.open_calls=96
        self.book.dispatch_journal=s.ContinuedDispatchJournal(self.root,self.namespace,'f'*64,RAW)
        self.journal=k.Journal(self.root);self.receipt=self.root/'audit/cache-downloads.jsonl';self.receipt.write_bytes(b'')
        self.completed={};self.lease=type('FixtureLease',(),{'id':self.namespace})()
        self.key='ce2c570876ca1422.ltar';self.data=f.data if hasattr(f,'data')else(b'synthetic-bulk2-public-control\x00'*2000)[:40000]
    def one(self,opener,key=None):
        return k.get_one({'ltar':key or self.key,'module':'Fixture/Control.lean'},self.root,self.lease,self.book,self.journal,
            self.book.check,self.receipt,self.completed,opener,sleeper=lambda _:None)
    def external(self):
        response=f.Response(self.key,self.data)
        self.book.external_prefixes[self.key]=dict(bytes=1000,sha256=hashlib.sha256(self.data[:1000]).hexdigest(),
            content_length=len(self.data),etag=response.headers['ETag'],content_md5=response.headers['Content-MD5'])
    def test_actual_native_cursor_red_then_locked_four_thread_green(self):
        results=[]
        for locked in (False,True):
            lease=s.LockedLease(self.root/('locked.json'if locked else'unlocked.json'),self.namespace)if locked else s.c.OwnedLease(self.root/'unlocked.json')
            lease.acquire();lease.write(dict(held=True,pid=os.getpid(),fixtureOnly=True))
            lease.stream=YieldingIO(lease.stream);clock=s.ThreadSafeDeadline();book_lock=threading.RLock()
            errors=[];count=0;start=threading.Barrier(4)
            def worker(index):
                nonlocal count
                start.wait()
                for _ in range(100):
                    try:
                        if locked and index%2:
                            with book_lock:clock.check();lease.assert_owned()
                        else:clock.check();lease.assert_owned()
                        count+=1
                    except Exception as error:errors.append(type(error).__name__)
            try:
                with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(worker,range(4)))
                lease.write(dict(held=False,pid=os.getpid(),fixtureOnly=True))
            finally:lease.close()
            marker=json.loads(lease.path.read_bytes());self.assertFalse(marker['held'])
            results.append(dict(locked=locked,assertions=count,errors=errors,nativeHandleClosed=True))
        self.assertGreater(len(results[0]['errors']),0);self.assertIn('JSONDecodeError',results[0]['errors'])
        self.assertEqual(results[1]['errors'],[]);self.assertEqual(results[1]['assertions'],400)
        path=self.root/'native-cursor-red-green.json'
        with path.open('xb')as out:out.write((json.dumps(results)+'\n').encode());out.flush();os.fsync(out.fileno())
    def test_original96_intents_and_remaining_key_count_continue_without_reset(self):
        opener=f.Opener(f.Response(self.key,self.data));r=self.one(opener)
        self.assertEqual(r['transport_gets'],2);self.assertEqual(r['prior_bulk_gets'],1);self.assertEqual(self.book.gets,97)
        self.assertEqual(self.book.open_calls,97);self.assertEqual(r['execution_generation'],2)
        self.assertEqual(r['body_generation_scope'],'this_execution_only');self.assertIsNone(r['all_history_global_gets'])
        raw=(self.root/k.DISPATCH_REL).read_bytes();self.assertTrue(raw.startswith(RAW))
        last=json.loads(raw.splitlines()[-1]);self.assertEqual(last['new_global_get'],97);self.assertEqual(last['new_key_get'],2)
        keys=set(self.book.get_counts);counts,total,_=s.inspect_dispatch(self.root/k.DISPATCH_REL,self.namespace,'f'*64,keys,RAW)
        self.assertEqual(total,97);self.assertEqual(counts[self.key],2)
    def test_archived_prefix_and_headers_verified_from_entirely_fresh_body(self):
        self.external();opener=f.Opener(f.Response(self.key,self.data));r=self.one(opener)
        self.assertTrue(r['external_interrupted_prefix_verified']);self.assertEqual(r['external_interrupted_prefix_bytes'],1000)
        self.assertEqual(r['failed_prefix_bytes_reused_in_body'],0);self.assertEqual((self.root/'downloads/mathlib-cache'/self.key).read_bytes(),self.data)
        self.assertNotIn('Range',opener.requests[0].headers);self.assertLessEqual(len(k.encode_row(r)),2048)
    def test_archived_prefix_drift_and_header_drift_refuse_with_one_remaining_call(self):
        self.external();response=f.Response(self.key,b'X'+self.data[1:],self.data);opener=f.Opener(response)
        with self.assertRaisesRegex(RuntimeError,'prefix SHA'):self.one(opener)
        self.assertEqual(len(opener.requests),1);self.assertFalse(self.completed)
        self.setUp();self.external();response=f.Response(self.key,self.data);response.headers.replace_header('ETag','0xDIFFERENT')
        opener=f.Opener(response)
        with self.assertRaisesRegex(RuntimeError,'headers changed'):self.one(opener)
        self.assertEqual(len(opener.requests),1);self.assertFalse(self.completed)
    def test_old_one_plus_two_timeouts_stops_at_three_not_four(self):
        opener=f.Opener(TimeoutError('fixture'),TimeoutError('fixture'))
        with self.assertRaises(TimeoutError):self.one(opener)
        self.assertEqual(len(opener.requests),2);self.assertEqual(self.book.get_counts[self.key],3);self.assertEqual(self.book.gets,98)
        self.assertEqual(self.book.open_calls,98)
    def test_remaining_body_retry_one_and_preservation_total_fourteen(self):
        self.book.recoveries=1
        with self.assertRaisesRegex(RuntimeError,'budget1'):self.book.allow_prefix(1)
        self.assertEqual(9+k.MAX_STAGE_RECOVERIES+4,14)
        with self.assertRaises(RuntimeError):s.ContinuedDispatchJournal(self.root,self.namespace,'f'*64,RAW+b'changed')
        with self.assertRaisesRegex(RuntimeError,'expired'):s.ThreadSafeDeadline(wall=lambda:s.c.DEADLINE+1,monotonic=lambda:0)


if __name__=='__main__':unittest.main(verbosity=2)
