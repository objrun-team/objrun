import {expect,test} from 'bun:test';
import {join} from 'node:path';
import {mkdtempSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {auditJpgEvidence} from '../scripts/repair-2026-10-08/skb-jpg-audit.ts';

test('actual host capture bounds a stalled Docker daemon before its first TAR byte',async()=>{
 const code=String.raw`
import importlib.util,json,os,subprocess,tempfile,time
from pathlib import Path
path=Path('scripts/repair-2026-10-08/skb-jpg-stand.py')
spec=importlib.util.spec_from_file_location('jpg_bridge_probe',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.CAPTURE_SECONDS=0.2
original=subprocess.Popen
def launch(argv,*args,**kwargs):
    if argv[:2]==['docker','cp']:
        return original(['python','-u','-c','import time;time.sleep(2)'],*args,**kwargs)
    return original(argv,*args,**kwargs)
module.subprocess.Popen=launch
with tempfile.TemporaryDirectory(prefix='tgengin-jpg-host-capture-')as home:
    bridge=module.Bridge.__new__(module.Bridge)
    bridge.lock=module.threading.RLock();bridge.args=type('Args',(),{'mode':'live'})()
    bridge.name='objrun-jpg-fixture-candidate';bridge.container_id='a'*64
    bridge.place='skb:fixture/U/jpg-ocr-stat';bridge.home=Path(home)
    bridge.captures=[];bridge.sealed=False;bridge.stop_for_capture=lambda:None
    started=time.monotonic()
    try:bridge.capture(final=True);raise AssertionError('stalled capture unexpectedly certified')
    except RuntimeError as error:
        assert 'deadline' in str(error).lower(),str(error)
    elapsed=time.monotonic()-started
    assert elapsed<1.2,elapsed
    assert not bridge.captures
    print(json.dumps({'bounded':True,'elapsedSeconds':elapsed,'captureReceipts':len(bridge.captures)}))
`;
 const home=mkdtempSync(join(tmpdir(),'tgengin-jpg-host-probe-')),file=join(home,'probe.py');writeFileSync(file,code);
 try{const child=Bun.spawn(['python','-X','utf8',file],{cwd:join(import.meta.dir,'..'),stdout:'pipe',stderr:'pipe'});
 const [stdout,stderr]=await Promise.all([new Response(child.stdout).text(),new Response(child.stderr).text()]);
 expect({code:await child.exited,stderr}).toEqual({code:0,stderr:''});expect(JSON.parse(stdout).bounded).toBe(true);
 }finally{rmSync(home,{recursive:true,force:true});}
},10000);

test('actual evidence audit consumes one framed credential message while the host stdin remains open',async()=>{
 const home=mkdtempSync(join(tmpdir(),'tgengin-jpg-audit-frame-'));
 const child=Bun.spawn(['python','-X','utf8',join(import.meta.dir,'../scripts/repair-2026-10-08/skb-jpg-host-ops.py'),'--audit','--output',home,'--store',home],{stdin:'pipe',stdout:'pipe',stderr:'pipe'});
 try{
  child.stdin.write(JSON.stringify(Array.from({length:6},(_,index)=>'test-framed-credential-'+index))+'\n');
  const code=await Promise.race([child.exited,Bun.sleep(1500).then(()=>null)]);
  expect(code).toBe(0);
  const report=JSON.parse(await new Response(child.stdout).text());expect(report.passed).toBe(true);expect(report.secretValuesChecked).toBe(6);
 }finally{child.stdin.end();if(child.exitCode===null){child.kill();await child.exited;}rmSync(home,{recursive:true,force:true});}
},5000);

test('the actual campaign audit caller explicitly closes its asynchronous input pipe',async()=>{
 const home=mkdtempSync(join(tmpdir(),'tgengin-jpg-audit-caller-'));
 try{const result=await auditJpgEvidence({script:join(import.meta.dir,'../scripts/repair-2026-10-08/skb-jpg-host-ops.py'),output:home,store:home,privateConfigs:[],secrets:Array.from({length:6},(_,index)=>'fixture-only-'+index),timeoutMs:3000});
 expect(result.closed).toBe(true);expect(JSON.parse(readFileSync(join(home,'evidence-secret-audit.json'),'utf8')).passed).toBe(true);
 }finally{rmSync(home,{recursive:true,force:true});}
},5000);

test('actual capture accepts a bounded PAX header for the sole regular workbook',async()=>{
 const code=String.raw`
import importlib.util,io,json,subprocess,tarfile,tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('jpg_bridge_pax',Path('scripts/repair-2026-10-08/skb-jpg-stand.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
original=subprocess.Popen
with tempfile.TemporaryDirectory(prefix='tgengin-jpg-pax-probe-')as home:
    home=Path(home);raw=io.BytesIO();payload=b'local-wrong-workbook'
    with tarfile.open(fileobj=raw,mode='w',format=tarfile.PAX_FORMAT)as archive:
        item=tarfile.TarInfo('stat_ocr.xlsx');item.size=len(payload);item.mtime=1.5;archive.addfile(item,io.BytesIO(payload))
    assert raw.getvalue()[156:157]==b'x'
    archive_path=home/'capture.tar';archive_path.write_bytes(raw.getvalue())
    emit=home/'emit.py';emit.write_text('import sys;from pathlib import Path;sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())')
    def launch(argv,*args,**kwargs):
        if argv[:2]==['docker','cp']:return original(['python','-X','utf8',str(emit),str(archive_path)],*args,**kwargs)
        return original(argv,*args,**kwargs)
    module.subprocess.Popen=launch
    bridge=module.Bridge.__new__(module.Bridge);bridge.lock=module.threading.RLock();bridge.args=type('Args',(),{'mode':'live'})()
    bridge.name='objrun-jpg-fixture-candidate';bridge.container_id='a'*64;bridge.place='skb:fixture/U/jpg-ocr-stat';bridge.home=home
    bridge.captures=[];bridge.sealed=False;bridge.stop_for_capture=lambda:None
    receipt=bridge.capture(final=True);assert receipt['state']=='regular',receipt
    assert Path(receipt['hostArtifactPath']).read_bytes()==payload
    assert receipt['daemonEvidence']['memberKind']=='regular'and receipt['daemonEvidence']['rawTarCaptureComplete']
    print(json.dumps({'regularPaxCaptured':True,'bytes':receipt['artifactBytes']}))
`;
 const home=mkdtempSync(join(tmpdir(),'tgengin-jpg-host-probe-')),file=join(home,'probe.py');writeFileSync(file,code);
 try{const child=Bun.spawn(['python','-X','utf8',file],{cwd:join(import.meta.dir,'..'),stdout:'pipe',stderr:'pipe'});
 const [stdout,stderr]=await Promise.all([new Response(child.stdout).text(),new Response(child.stderr).text()]);
 expect({code:await child.exited,stderr}).toEqual({code:0,stderr:''});expect(JSON.parse(stdout).regularPaxCaptured).toBe(true);
 }finally{rmSync(home,{recursive:true,force:true});}
},10000);

test('actual private CLI timeout reconciles only exact owned IDs, and rejects pending or foreign identities',async()=>{
 const code=String.raw`
import importlib.util,json,os,subprocess,tempfile,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('jpg_host_probe',Path('scripts/repair-2026-10-08/skb-jpg-host-ops.py'))
host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
with tempfile.TemporaryDirectory(prefix='tgengin-jpg-lease-probe-')as home:
    home=Path(home);host.LEASE_PATH=home/'owned-instance.lock'
    image='sha256:'+'f'*64;cid='a'*64;prefix='objrun-jpg-123456abcdef';name=prefix+'-grader-012345ab'
    folder=home/'grade-fixture';folder.mkdir()
    source=home/'slow-cli.py'
    source.write_text('''import json,os,sys,time
from pathlib import Path
folder=Path(sys.argv[1]);lease=Path(sys.argv[2]);nonce='b'*32
lease.write_text(json.dumps({'pid':os.getpid(),'nonce':nonce}))
owner={'schemaVersion':1,'taskId':'jpg-ocr-stat','protocol':'skb-jpg-output-v1-preseed','processId':os.getpid(),'ownerLabelKey':'objrun.jpg-owner','ownerLabelValue':'objrun-jpg-123456abcdef','lease':{'path':str(lease),'nonce':nonce,'released':False},'containers':[{'name':'objrun-jpg-123456abcdef-grader-012345ab','expectedImageId':'sha256:'+'f'*64,'role':'grader','containerId':'a'*64,'state':'created'}]}
(folder/'operation-owner.json').write_text(json.dumps(owner))
time.sleep(2)
''')
    original=host.recover_owned_grader;removed=[];exists=True
    def docker(argv,**kw):
        global exists
        if argv==['inspect',name]and exists:
            return subprocess.CompletedProcess(argv,0,json.dumps([{'Id':cid,'Name':'/'+name,'Image':image,'Config':{'Labels':{'objrun.jpg-owner':prefix}}}]).encode(),b'')
        if argv==['rm','-f',cid]:
            exists=False;removed.append(cid);return subprocess.CompletedProcess(argv,0,cid.encode(),b'')
        return subprocess.CompletedProcess(argv,1,b'',('Error: No such object: '+argv[-1]).encode())
    host.recover_owned_grader=lambda folder,pid,image:original(folder,pid,image,docker)
    try:host.run_private_grader(['python','-X','utf8',str(source),str(folder),str(host.LEASE_PATH)],folder,image,0.3);raise AssertionError('timeout unexpectedly succeeded')
    except RuntimeError as error:assert 'deadline'in str(error),str(error)
    receipt=json.loads((folder/'host-recovery.json').read_text());assert receipt['processExited']and receipt['reconciled']and receipt['leaseReleased']
    assert removed==[cid]and not host.LEASE_PATH.exists()
    owner=json.loads((folder/'operation-owner.json').read_text());pid=owner['processId']
    for mode in ['foreign_image','pending_absent','active_process','changed_lease']:
        owner['processId']=os.getpid()if mode=='active_process'else pid
        owner['containers'][0].update(containerId=None if mode=='pending_absent'else cid,state='creation_pending'if mode=='pending_absent'else'created')
        (folder/'operation-owner.json').write_text(json.dumps(owner));host.LEASE_PATH.write_text(json.dumps({'pid':pid,'nonce':'c'*32 if mode=='changed_lease'else'b'*32}))
        calls=[]
        def rejected_docker(argv,**kw):
            calls.append(argv)
            if mode=='foreign_image':return subprocess.CompletedProcess(argv,0,json.dumps([{'Id':cid,'Name':'/'+name,'Image':'sha256:'+'0'*64,'Config':{'Labels':{'objrun.jpg-owner':prefix}}}]).encode(),b'')
            return subprocess.CompletedProcess(argv,1,b'',('Error: No such object: '+argv[-1]).encode())
        try:original(folder,owner['processId'],image,rejected_docker);raise AssertionError(mode+' unexpectedly certified')
        except RuntimeError:pass
        assert host.LEASE_PATH.exists(),mode
        assert not any(call[0]=='rm'for call in calls),mode
    print(json.dumps({'exactOwnedIdRemoved':True,'leaseReleasedAfterExit':True,'foreignPendingActiveChangedRejected':4}))
`;
 const home=mkdtempSync(join(tmpdir(),'tgengin-jpg-host-probe-')),file=join(home,'probe.py');writeFileSync(file,code);
 try{const child=Bun.spawn(['python','-X','utf8',file],{cwd:join(import.meta.dir,'..'),stdout:'pipe',stderr:'pipe'});
 const [stdout,stderr]=await Promise.all([new Response(child.stdout).text(),new Response(child.stderr).text()]);
 expect({code:await child.exited,stderr}).toEqual({code:0,stderr:''});expect(JSON.parse(stdout)).toMatchObject({exactOwnedIdRemoved:true,foreignPendingActiveChangedRejected:4});
 }finally{rmSync(home,{recursive:true,force:true});}
},10000);
