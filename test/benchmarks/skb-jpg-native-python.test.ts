import {expect,test} from 'bun:test';
import {mkdtempSync,mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {launchNativeJpgService,loadNativePython,assertHealthIdentity} from '../../scripts/benchmark-repair/skb-jpg-native-python.ts';

const scratch=resolve(import.meta.dir,'../../.scratch/jpg-native-lifecycle-v2');mkdirSync(scratch,{recursive:true});
const makeHome=()=>mkdtempSync(join(scratch,'fixture-'));
const port=async()=>{const s=Bun.serve({hostname:'127.0.0.1',port:0,fetch:()=>new Response('')});const value=s.port;await s.stop(true);return value;};
const environment=()=>({...process.env,TGENGIN_GRADER_TOKEN:'local-lifecycle-fixture'});
const stand=resolve(import.meta.dir,'../../scripts/benchmark-repair/skb-jpg-stand.py');

test('native mock PID, owner receipt and health interpreter align and actually close',async()=>{
 const home=makeHome(),p=await port(),service=launchNativeJpgService({script:stand,argv:['--mode','mock','--port',String(p),'--home',home],home,port:p,env:environment()});service.child.stdout?.resume();service.child.stderr?.resume();
 try{const health=await service.waitReady();expect(health.processIdentity.pid).toBe(service.child.pid);expect(service.identity?.pid).toBe(service.child.pid);expect(health.processIdentity.executableSha256).toBe(loadNativePython().sha256);}
 finally{const closed=await service.stop();expect(closed).toMatchObject({identityVerified:true,directChildExited:true,directChildClosed:true,portClosed:true,closed:true,serviceClosed:true});expect(closed.durationMs).toBeLessThan(4500);}
},12000);

test('fixture assertion failure still closes the real native service',async()=>{
 const home=makeHome(),p=await port(),service=launchNativeJpgService({script:stand,argv:['--mode','mock','--port',String(p),'--home',home],home,port:p,env:environment()});service.child.stdout?.resume();service.child.stderr?.resume();
 let failed=false;
 try{await service.waitReady();throw new Error('intentional fixture assertion failure');}catch(error){failed=(error as Error).message.includes('intentional');}
 finally{expect((await service.stop()).closed).toBe(true);}
 expect(failed).toBe(true);
},12000);

test('native health PID, interpreter and nonce mismatch are all rejected',async()=>{
 const home=makeHome(),p=await port(),service=launchNativeJpgService({script:stand,argv:['--mode','mock','--port',String(p),'--home',home],home,port:p,env:environment()});service.child.stdout?.resume();service.child.stderr?.resume();
 try{const health=await service.waitReady(),identity=service.identity!;
  for(const patch of [{pid:identity.pid+1},{parentPid:identity.parentPid+1},{protocol:'old-lifecycle'},{nonce:'0'.repeat(64)},{executableSha256:'0'.repeat(64)}])expect(()=>assertHealthIdentity({...health,processIdentity:{...health.processIdentity,...patch}},identity,service.native)).toThrow('identity mismatch');
 }finally{expect((await service.stop()).closed).toBe(true);}
},12000);

test('startup failure keeps its own identity and proves its actual port closed',async()=>{
 const home=makeHome(),script=join(home,'fail.py');writeFileSync(script,"raise RuntimeError('intentional startup failure')\n");const p=await port(),service=launchNativeJpgService({script,argv:[],home,port:p,env:environment(),startupMs:1500});service.child.stdout?.resume();service.child.stderr?.resume();
 try{await expect(service.waitReady()).rejects.toThrow('exited before readiness');}
 finally{expect(await service.stop()).toMatchObject({identityVerified:true,healthIdentityVerified:false,directChildExited:true,portClosed:true,closed:true});}
},6000);

test('health timeout closes only the owned identified native process within its bound',async()=>{
 const home=makeHome(),script=join(home,'idle.py');writeFileSync(script,'import time\ntime.sleep(60)\n');const p=await port(),service=launchNativeJpgService({script,argv:[],home,port:p,env:environment(),startupMs:450,graceMs:300,forceMs:300});service.child.stdout?.resume();service.child.stderr?.resume();
 try{await expect(service.waitReady()).rejects.toThrow('readiness timeout');}
 finally{expect(await service.stop()).toMatchObject({identityVerified:true,healthIdentityVerified:false,portClosed:true,closed:true});}
},5000);

test('a still-open foreign listener cannot be certified closed merely because Python exited',async()=>{
 const home=makeHome(),script=join(home,'exit.py');writeFileSync(script,'pass\n');const foreign=Bun.serve({hostname:'127.0.0.1',port:0,fetch:()=>Response.json({foreign:true})});
 const service=launchNativeJpgService({script,argv:[],home,port:foreign.port,env:environment(),startupMs:700});service.child.stdout?.resume();service.child.stderr?.resume();
 try{await expect(service.waitReady()).rejects.toThrow();const receipt=await service.stop();expect(receipt.directChildExited).toBe(true);expect(receipt.portClosed).toBe(false);expect(receipt.closed).toBe(false);expect(receipt.faults).toContain('owned_port_not_closed');expect((await fetch('http://127.0.0.1:'+foreign.port)).ok).toBe(true);}
 finally{await service.stop();await foreign.stop(true);}
},6000);

test('bare command and changed native executable profiles are rejected before spawn',()=>{
 const native=JSON.parse(readFileSync(resolve(import.meta.dir,'../../scripts/benchmark-repair/skb-jpg-native-python.json'),'utf8')),home=makeHome();
 for(const [name,patch]of [['cmd',{executable:'python.cmd'}],['digest',{sha256:'0'.repeat(64)}]] as const){const path=join(home,name+'.json');writeFileSync(path,JSON.stringify({...native,...patch}));expect(()=>loadNativePython(path)).toThrow();}
});

test('a rejected kill request is recorded and actual escalation is bounded',async()=>{
 const home=makeHome(),p=await port(),service=launchNativeJpgService({script:stand,argv:['--mode','mock','--port',String(p),'--home',home],home,port:p,env:environment(),graceMs:100,forceMs:500});service.child.stdout?.resume();service.child.stderr?.resume();
 const original=service.child.kill.bind(service.child);
 try{await service.waitReady();service.child.kill=((signal?:NodeJS.Signals|number)=>signal==='SIGTERM'?false:original(signal)) as typeof service.child.kill;
  const receipt=await service.stop();expect(receipt.terminationAttempts).toMatchObject([{signal:'SIGTERM',accepted:false},{signal:'SIGKILL',accepted:true}]);expect(receipt.directChildExited&&receipt.directChildClosed&&receipt.portClosed).toBe(true);expect(receipt.closed).toBe(false);expect(receipt.faults).toContain('SIGTERM_not_accepted');expect(receipt.durationMs).toBeLessThan(1300);
 }finally{service.child.kill=original;await service.stop();}
},6000);
