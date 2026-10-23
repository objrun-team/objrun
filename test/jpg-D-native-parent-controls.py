"""F-only bounded native child controls. No API, Docker, D/C/E output or lock."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'scripts/benchmark-repair'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
parent=load('jpg_D_control_parent',SCRIPTS/'jpg-D-grade-parent-v1.py')
storage=load('jpg_D_control_storage',SCRIPTS/'jpg_d_storage_profile.py')
stand=load('jpg_D_control_stand',SCRIPTS/'jpg-D-stand-v1.py')
OUTPUT=ROOT/'.scratch/jpg-D-native-parent-controls'/uuid.uuid4().hex
OUTPUT.mkdir(parents=True,exist_ok=False)

class Controls(unittest.TestCase):
    def exercise(self,name,code,deadline=2,intent_writer=parent.save):
        folder=OUTPUT/name
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','TEMP':str(OUTPUT),'TMP':str(OUTPUT),'TMPDIR':str(OUTPUT)}
        return parent.supervise_owned_child([sys.executable,'-B','-X','utf8','-c',code],env,folder,{'phase':'control','fixtureOnly':True},storage.native_actor_absent,lambda:True,deadline=deadline,intent_writer=intent_writer)
    def test_actual_child_close_and_fsync(self):
        v=self.exercise('positive',"print('owned harmless child')")
        self.assertEqual(v['exitCode'],0);self.assertIsNone(v['failureType']);self.assertTrue(v['directChildExited']);self.assertTrue(v['directChildClosed']);self.assertTrue(v['nativeProcessHandleClosed'])
        self.assertTrue(v['actualPidAbsence']['actualNativeOpenProcessAbsent']);self.assertIsNotNone(v['intentPin']);self.assertEqual(v['modelCalls'],0);self.assertFalse(v['scoreCertificate'])
        self.assertEqual(Path(v['stdoutPin']['path']).read_bytes(),b'owned harmless child\r\n')
        self.assertEqual(v['stdoutPin']['sha256'],hashlib.sha256(Path(v['stdoutPin']['path']).read_bytes()).hexdigest())
    def test_real_timeout_kills_only_this_owned_child(self):
        peer=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(20)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            v=self.exercise('timeout','import time;time.sleep(20)',deadline=.2)
            self.assertIn('operational_timeout',v['failureType']);self.assertNotEqual(v['exitCode'],0);self.assertTrue(v['directChildClosed']);self.assertTrue(v['actualPidAbsence']['actualNativeOpenProcessAbsent']);self.assertLess(v['durationMs'],3000);self.assertIsNone(peer.poll());self.assertFalse(v['scoreCertificate'])
        finally:
            if peer.poll()is None:peer.kill()
            peer.wait(timeout=3);peer._handle.Close()
        until=time.monotonic()+2
        while True:
            try:closed_peer=storage.native_actor_absent(peer.pid);break
            except storage.StorageFault as error:
                if error.kind!='actor_not_absent'or time.monotonic()>=until:raise
                time.sleep(.025)
        self.assertTrue(closed_peer['actualNativeOpenProcessAbsent'])
    def test_intent_write_fault_retains_child_close_and_stdio(self):
        def bad_write(path,value):raise OSError('controlled intent write failure')
        v=self.exercise('intent-failure','import time;time.sleep(20)',intent_writer=bad_write)
        self.assertIn('controlled intent write failure',v['failureType']);self.assertIsNone(v['intentPin']);self.assertTrue(v['directChildClosed']);self.assertTrue(v['actualPidAbsence']['actualNativeOpenProcessAbsent']);self.assertTrue(Path(v['stdoutPin']['path']).is_file());self.assertFalse(v['scoreCertificate'])
    def test_exact_candidate_missing_diagnostic(self):
        target='objrun-jpg-'+'a'*12+'-candidate-'+'b'*8
        def result(rc=1,out=b'[]\n',err=None):return subprocess.CompletedProcess([],rc,out,err or('error: no such object: '+target+'\n').encode())
        self.assertTrue(stand.candidate_missing(result(),target));self.assertTrue(stand.candidate_missing(result(err=('Error response from daemon: No such container: '+target+'\n').encode()),target))
        self.assertFalse(stand.candidate_missing(result(err=('error: no such object: '+target+'-neighbor\n').encode()),target));self.assertFalse(stand.candidate_missing(result(rc=2),target));self.assertFalse(stand.candidate_missing(result(out=b'[{}]'),target));self.assertFalse(stand.candidate_missing(result(err=('error: no such object: '+target+'\npermission denied\n').encode()),target))

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Controls);run=unittest.TextTestRunner(verbosity=2).run(suite)
    sources=[parent.pin(p)for p in(SCRIPTS/'jpg-D-grade-parent-v1.py',SCRIPTS/'jpg-D-stand-v1.py',SCRIPTS/'jpg_d_storage_profile.py',Path(__file__))]
    parent.save(OUTPUT/'result.json',{'protocol':'jpg-D-owned-native-parent-controls-v1','sourcePins':sources,'tests':run.testsRun,'failures':len(run.failures),'errors':len(run.errors),'fixtureOnly':True,'realProviderRequests':0,'DockerOperations':0,'DWrites':0,'paidReady':False,'actualNamespaceValidated':False,'output':str(OUTPUT)})
    print(str(OUTPUT/'result.json'));sys.exit(not run.wasSuccessful())
