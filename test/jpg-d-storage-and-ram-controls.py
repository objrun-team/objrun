"""Small F-only controls. No Docker client, D write, provider or actual grader.

Synthetic inspect/probe rows exercise schema only. Real controls are limited to
owned F Win32 handles, subprocess captures and fsync; never physical RAM proof.
"""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import threading
import unittest
from unittest.mock import patch
import uuid

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'scripts/benchmark-repair'))
import jpg_d_storage_profile as s
import jpg_private_ram_profile as r
import jpg_private_ram_executor as e

BASE=REPO/'.scratch/jpg-D-storage-controls'
FIXTURE_ONLY=True
BEFORE={n:hashlib.sha256((REPO/'scripts/benchmark-repair'/n).read_bytes()).hexdigest() for n in
        ('skb-jpg-journal-campaign.ts','audit-jpg-journal-campaign.py','jpg-paid-resource-admission-v1.ts','jpg-journal-contract.ts')}


def root():
    p=BASE/uuid.uuid4().hex;p.mkdir(parents=True)
    for n in ('leases','raw','receipts'): (p/n).mkdir()
    return p


def inspection(p,seeder=False):
    role='objrun-jpg-ram-seeder-' if seeder else 'objrun-jpg-private-'
    mounts={'/objrun':''} if seeder else r.MOUNTS
    return {'Id':'a'*64,'Name':'/'+role+p['nonce'],'Image':r.IMAGE,'State':{'Running':True},'SizeRw':0,
      'Config':{'Image':r.IMAGE,'Labels':{r.LABEL:p['nonce']},'Env':([] if seeder else [k+'='+v for k,v in r.ENV.items()]),
                'WorkingDir':'/' if seeder else '/app/workspace','Entrypoint':['/bin/bash'],'User':'0:0',
                'Cmd':p['seederCreate'][-2:] if seeder else ['-c','exec /bin/sleep infinity']},
      'HostConfig':{'ReadonlyRootfs':True,'NetworkMode':'none','Binds':None,'Privileged':False,'PidMode':'','IpcMode':'private',
                    'Memory':r.SEEDER_MEMORY if seeder else r.MEMORY,'MemorySwap':r.SEEDER_MEMORY if seeder else r.MEMORY,
                    'NanoCpus':1000000000 if seeder else 4000000000,'ShmSize':r.SHM,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges'],
                    'LogConfig':{'Type':'none'},'Mounts':[{'Type':'volume','Source':p['volumeName'],'Target':t,'ReadOnly':False,
                                                          'VolumeOptions':{'NoCopy':True,'Subpath':sub}} for t,sub in mounts.items()]},
      'Mounts':[{'Type':'volume','Name':p['volumeName'],'Destination':t,'Driver':'local','RW':True} for t in mounts]}


def probe(p):
    return {'protocol':r.PROTOCOL+'-native-mount-probe','nonce':p['nonce'],'imageId':r.IMAGE,'rootFilesystemReadOnly':True,
        'trustedBasePythonPath':'/usr/bin/python3.12','python':'3.12.3','basePythonSha256':'c'*64,'basePythonImageSource':r.IMAGE,
        'seederAliveDuringProbe':True,'paths':[{'path':k,'filesystem':'tmpfs','fsid':'101','device':'202','blockSize':4096,'totalBlocks':r.RAM//4096,'volumeName':p['volumeName']} for k in r.MOUNTS],
        'rootReadonlyWriteRejected':True,'capacityBoundaryReachedAndRejected':True,'capacityProbeExecuted':True,'capacityBytesWritten':r.RAM-4096,
        'graderSizeRwBefore':0,'graderSizeRwAfter':0,'fixtureOnly':True}


class Controls(unittest.TestCase):
    def setUp(self):self.d=s.descriptor('1'*32);self.p=r.plan('1'*32)
    def test_01_exact_descriptor_and_env(self):
        self.assertEqual(s.validate_descriptor(self.d),self.d)
        self.assertEqual(self.d['solverUpperMaximumBytes'],256*1024**2)
        self.assertEqual(self.d['privateSharedRamMaximumBytes'],512*1024**2)
        changed=copy.deepcopy(self.d);changed['paidReady']=True
        with self.assertRaises(s.StorageFault):s.validate_descriptor(changed)
        inherited={'TOKEN':'synthetic-not-a-real-key','TEMP':'C:/wrong'}
        env=s.native_environment(self.d,inherited);self.assertEqual(inherited['TEMP'],'C:/wrong');self.assertTrue(env['TEMP'].startswith('D:/'))
    def test_02_stage_paths(self):
        for name in ('../x','/x','C:/x','x\\y','x:y','CON','a/NUL.txt','a/../b','a//b','x.','x ','x\x00y'):
            with self.subTest(name=name),self.assertRaises(s.StorageFault):s.path_for(self.d,'provider',name)
        self.assertEqual(s.path_for(self.d,'provider','r/body.gz'),self.d['directories']['raw']+'/r/body.gz')
    def test_03_real_solver_floor_no_vhd_credit(self):
        needs=s.resource_requirements(self.d,True)
        self.assertEqual(needs['F'],1368391680);self.assertEqual(needs['solverRemainingFReservationBytes'],256*1024**2)
        self.assertEqual(needs['headroomCreditForVhdInternalSlack'],0)
        observed={'C':1156145152,'D':8689201152,'F':1100357632}
        self.assertFalse(s.assess_resources(self.d,observed,True)['admitted'])
        self.assertTrue(s.assess_resources(self.d,observed,False)['admitted'])
        self.assertFalse(s.assess_resources(self.d,{**observed,'D':6*1024**3-1},False,initial=True)['admitted'])
        with self.assertRaises(s.StorageFault):s.resource_requirements(self.d,True,256*1024**2+1)
    def test_04_ram_plan_exact_single_cap_and_copy(self):
        r.validate_plan(self.p)
        self.assertEqual(len(self.p['mountSubpaths']),6)
        self.assertEqual(self.p['privateMemoryBytes'],4*1024**3)
        self.assertEqual(self.p['officialVerifierSeconds'],600)
        changed=copy.deepcopy(self.p);changed['privateMemoryBytes']=512*1024**2
        with self.assertRaises(r.RamFault):r.validate_plan(changed)
        self.p['privateEnvironment']['HOME']='changed'
        self.assertEqual(r.plan('1'*32)['privateEnvironment']['HOME'],'/root')
    def test_05_inspect_exact_namespace_and_negative_binds(self):
        for seeder in (False,True):r.validate_container(inspection(self.p,seeder),self.p,seeder)
        for key,value in [('Binds',['F:/private:/verifier']),('Memory',1),('ReadonlyRootfs',False),('NetworkMode','host')]:
            bad=inspection(self.p);bad['HostConfig'][key]=value
            with self.subTest(key=key),self.assertRaises(r.RamFault):r.validate_container(bad,self.p)
        bad=inspection(self.p);bad['HostConfig']['Mounts'][0]['VolumeOptions']['Subpath']='other'
        with self.assertRaises(r.RamFault):r.validate_container(bad,self.p)
        bad=inspection(self.p,True);bad['Config']['Env']=['DEEPSEEK_API_KEY=synthetic']
        with self.assertRaises(r.RamFault):r.validate_container(bad,self.p,True)
    def test_06_probe_is_schema_not_physical_cert(self):
        good=probe(self.p);r.validate_mount_probe(good,self.p)
        bad=copy.deepcopy(good);bad['paths'][1]['fsid']='999'
        with self.assertRaises(r.RamFault):r.validate_mount_probe(bad,self.p)
        bad=copy.deepcopy(good);bad['paths'][1]['totalBlocks']-=1
        with self.assertRaises(r.RamFault):r.validate_mount_probe(bad,self.p)
        current=copy.deepcopy(good);current['capacityBoundaryReachedAndRejected']=False;current['capacityProbeExecuted']=False
        r.validate_mount_probe(current,self.p,require_capacity=False)
        with self.assertRaises(r.RamFault):r.validate_mount_probe(current,self.p)
        self.assertFalse(self.p['actualReady'])
    def test_07_native_share_deny_and_no_stale_takeover(self):
        p=root()
        with s.NativeStorageLease(p,p.name,fixture_only=True) as lease:
            with self.assertRaises((s.StorageFault,PermissionError,OSError)):
                with (p/'leases/storage.lock').open('rb'):pass
            with self.assertRaises(s.StorageFault):s.NativeStorageLease(p,p.name,fixture_only=True).__enter__()
            errors=[]
            def read():
                try:
                    for _ in range(20):lease.assert_owned()
                except Exception as error:errors.append(type(error).__name__)
            threads=[threading.Thread(target=read) for _ in range(4)]
            for t in threads:t.start()
            for t in threads:t.join()
            self.assertEqual(errors,[])
        self.assertFalse(json.loads((p/'leases/storage.lock').read_bytes())['held'])
        with self.assertRaises(s.StorageFault):s.NativeStorageLease(p,p.name,fixture_only=True).__enter__()
    def test_08_owned_handle_instance_delete_after_fsync(self):
        p=root();lease=s.JpgInstanceLease(self.d,'2'*32,p/'receipts',fixture_root=p).acquire()
        with self.assertRaises(s.StorageFault):s.JpgInstanceLease(self.d,'3'*32,p/'receipts',fixture_root=p).acquire()
        result=lease.release();closed=json.loads(Path(result['path']).read_bytes())
        self.assertTrue(closed['nativeDeleteByOwnedHandleReturned']);self.assertFalse(lease.path.exists())
        self.assertFalse(closed['actorAbsenceCertified']);self.assertTrue(closed['fixtureOnly'])
        self.assertFalse(json.loads(Path(closed['finalLeaseBytesPin']['path']).read_bytes())['held'])
    def test_09_native_bounded_fsynced_writes_and_unknown_reject(self):
        p=root()
        with s.NativeStorageLease(p,p.name,fixture_only=True) as lease:
            with self.assertRaises(s.StorageFault):s.OwnedWriteBudget(p,65536,0,'D:/',lease,fixture_only=True)
            w=s.OwnedWriteBudget(p,65536,0,p.anchor,lease,fixture_only=True)
            body=b'bounded-bytes'*64;q=w.write_fresh('raw/gz',body)
            self.assertEqual(q['sha256'],hashlib.sha256(body).hexdigest());self.assertTrue(q['fsyncReturned'])
            with self.assertRaises(s.StorageFault):w.write_fresh('raw/gz',body)
            with self.assertRaises(s.StorageFault):w.write_fresh('raw/big',b'x'*65536)
            self.assertEqual(w.audit()['files'],1)
            (p/'raw/unknown').write_bytes(b'unknown')
            with self.assertRaises(s.StorageFault):w.audit()
    def test_10_fsync_failure_keeps_prefix_and_poison(self):
        p=root()
        with s.NativeStorageLease(p,p.name,fixture_only=True) as lease:
            w=s.OwnedWriteBudget(p,65536,0,p.anchor,lease,fixture_only=True)
            with patch.object(s.os,'fsync',side_effect=OSError('synthetic fsync error')):
                with self.assertRaises(OSError):w.write_fresh('raw/partial',b'known-prefix')
            self.assertEqual((p/'raw/partial').read_bytes(),b'known-prefix');self.assertTrue(w.poisoned)
            with self.assertRaises(s.StorageFault):w.write_fresh('raw/retry',b'x')
    def test_11_real_child_bounded_capture_closure(self):
        p=root();rows,out,err=e.bounded_child([sys.executable,'-B','-c','import sys;sys.stdout.buffer.write(b"ok");sys.stderr.buffer.write(b"err")'],os.environ.copy(),p,1,lambda _:None,5)
        self.assertEqual(out,b'ok');self.assertEqual(err,b'err');self.assertTrue(rows['directChildWaitReturned']);self.assertTrue(rows['pipeReadersClosed'])
        self.assertEqual(rows['stdoutPin']['sha256'],hashlib.sha256(b'ok').hexdigest())
    def test_12_real_timeout_and_oversize_retained(self):
        for serial,code,timeout,cap in ((1,'import time;time.sleep(2)',0.05,1024),(2,'import sys;sys.stdout.buffer.write(b"x"*1000)',5,16)):
            p=root()
            with self.assertRaises(e.GradeFault):e.bounded_child([sys.executable,'-B','-c',code],os.environ.copy(),p,serial,lambda _:None,timeout,cap)
            value=json.loads((p/('command-%03d.json'%serial)).read_bytes())
            self.assertTrue(value['directChildWaitReturned']);self.assertTrue(value['pipeReadersClosed']);self.assertTrue(value['faults'])
            self.assertLessEqual(value['stdoutPin']['bytes'],cap)
    def test_13_only_exact_regular_tar(self):
        def tar(names):
            buffer=io.BytesIO()
            with tarfile.open(fileobj=buffer,mode='w') as t:
                for name in names:
                    m=tarfile.TarInfo(name);m.size=3;t.addfile(m,io.BytesIO(b'raw'))
            return buffer.getvalue()
        self.assertEqual(e.exact_tar_file(tar(['reward.txt']),'reward.txt',1024),b'raw')
        for names in (['../reward.txt'],['reward.txt','reward.txt']):
            with self.assertRaises(e.GradeFault):e.exact_tar_file(tar(names),'reward.txt',1024)
    def test_14_forged_flags_missing_capture_and_actor_live(self):
        with self.assertRaises(e.GradeFault):e.capture_input({'state':'absent'},self.d)
        with self.assertRaises(e.GradeFault):e.verify_namespace_proof({'namespaceValidated':True,'validated':False},e.source_pins(),{},self.p)
        with self.assertRaises(s.StorageFault):s.native_actor_absent(os.getpid())
    def test_15_original_four_and_default_inert(self):
        after={n:hashlib.sha256((REPO/'scripts/benchmark-repair'/n).read_bytes()).hexdigest() for n in BEFORE}
        self.assertEqual(after,BEFORE)
        p=root();rows,out,_=e.bounded_child([sys.executable,'-B',str(Path(e.__file__))],os.environ.copy(),p,1,lambda _:None,5)
        prepared=json.loads(out);self.assertTrue(prepared['preparedOnly']);self.assertEqual(prepared['DockerMutations'],0);self.assertFalse(prepared['actualReady'])
    def test_16_owner_chain_tail_source_and_wrong_cid(self):
        sources=e.source_pins();nonce='2'*32;pid=12345;lease=self.d['directories']['leases']+'/instance.lock'
        values=[{'kind':'instance_lease_acquired','leasePath':lease,'nonce':nonce,'sourcePins':sources,'ramPlanSourceSha256':self.p['sourceSha256']},
                {'kind':'volume_create_intent','name':self.p['volumeName']},
                {'kind':'container_create_intent','name':'objrun-jpg-private-'+self.p['nonce'],'role':'grader','imageId':r.IMAGE},
                {'kind':'container_identity','name':'objrun-jpg-private-'+self.p['nonce'],'role':'grader','expectedImageId':r.IMAGE,'containerId':'a'*64,'state':'created'}]
        def encode(rows):
            previous='0'*64;result=b''
            for i,row in enumerate(rows):
                body=s.canonical({'protocol':e.PROTOCOL+'-owner-event','seq':i,'previousSha256':previous,'pid':pid,'operationNonce':nonce,**row})
                result+=body;previous=hashlib.sha256(body).hexdigest()
            return result
        body=encode(values);parsed,pending,known=e.parse_owner_rows(body,pid,nonce,sources,self.p,lease)
        self.assertEqual(known['grader']['containerId'],'a'*64);self.assertEqual(len(pending),2)
        for changed in (body[:-1],body+b'{',body.replace(b'"pid":12345',b'"pid":99999',1)):
            with self.assertRaises((e.GradeFault,json.JSONDecodeError)):e.parse_owner_rows(changed,pid,nonce,sources,self.p,lease)
        bad=copy.deepcopy(values);bad[0]['sourcePins']=[]
        with self.assertRaises(e.GradeFault):e.parse_owner_rows(encode(bad),pid,nonce,sources,self.p,lease)
        bad=copy.deepcopy(values);bad[-1]['containerId']='not-a-cid'
        with self.assertRaises(e.GradeFault):e.parse_owner_rows(encode(bad),pid,nonce,sources,self.p,lease)
    def test_17_cleanup_exact_id_substitution_rejected_no_mutation(self):
        o=object.__new__(e.RamOperation);o.plan=self.p;o.value=self.d;o.pending=[('container','objrun-jpg-private-'+self.p['nonce'])]
        o.identities={'grader':{'name':'objrun-jpg-private-'+self.p['nonce'],'containerId':'a'*64,'expectedImageId':r.IMAGE,'role':'grader','state':'created'}}
        o.room=lambda *_args,**_kw:None;o.event=lambda *_args,**_kw:None;o.closed=False;mutations=[]
        fake=inspection(self.p);fake['Id']='b'*64
        def command(*args,**kw):
            if args[0]=='rm':mutations.append(args)
            return {'exitCode':0},json.dumps([fake]).encode(),b''
        o.command=command
        with self.assertRaises(e.GradeFault):o.cleanup()
        self.assertEqual(mutations,[]);self.assertFalse(o.closed)
        # Parent timeout recovery refuses a still-live PID before any D/Docker action.
        with self.assertRaises(s.StorageFault):e.recover_owned_after_child_exit('D:/not-used',os.getpid(),{})
    def test_18_unreported_tmpfs_extra_caps_false_no_new_privileges(self):
        for key,value in [('Tmpfs',{'/usr':'rw'}),('CapAdd',['SYS_ADMIN']),('Devices',[{'PathOnHost':'/dev/sda'}]),
                          ('DeviceRequests',[{'Driver':'nvidia'}]),('UsernsMode','host'),('SecurityOpt',['no-new-privileges:false']),
                          ('SecurityOpt',['no-new-privileges','seccomp=unconfined'])]:
            bad=inspection(self.p);bad['HostConfig'][key]=value
            with self.subTest(key=key),self.assertRaises(r.RamFault):r.validate_container(bad,self.p)


if __name__=='__main__':unittest.main(verbosity=2)
