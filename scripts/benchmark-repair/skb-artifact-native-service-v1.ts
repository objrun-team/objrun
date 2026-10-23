/** Explicit D service seam. It never changes the frozen F/C native launcher. */
import { randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import { closeSync, existsSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { actualPin, demand, hash, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { assertHealthIdentity, loadNativePython, localhostPortClosed, type ClosureReceipt, type ServiceIdentity } from './skb-jpg-native-python.ts';
import { SKB_ARTIFACT_D_PARENT, skbArtifactNativeEnvironment, loadSkbStorageDescriptor, type SkbStorageDescriptor } from './skb-artifact-storage.ts';

const ROOT=resolve(import.meta.dir,'../..');
export const SKB_NATIVE_PROTOCOL='skb-artifact-native-service-lifecycle-v1';
const canonical=(path:string)=>realpathSync(path).replaceAll('\\','/').toLowerCase();

export function assertSkbArtifactServiceHome(d:SkbStorageDescriptor,home:string){
  demand(resolve(home)===resolve(d.directories.stand!)&&resolve(d.storePhysical)===resolve(SKB_ARTIFACT_D_PARENT,d.ownerNonce),'skb_service_exact_home');
  return resolve(home);
}
function ordinary(path:string){
  let current=resolve(path);
  while(true){const s=lstatSync(current);demand(s.isDirectory()&&!s.isSymbolicLink()&&canonical(current)===current.replaceAll('\\','/').toLowerCase(),'skb_service_reparse');const parent=dirname(current);if(parent===current)break;current=parent;}
}
function durable(path:string,value:unknown){
  const raw=Buffer.from(JSON.stringify(value,null,2)+'\n'),fd=openSync(path,'wx',0o600);
  try{writeFileSync(fd,raw);fsyncSync(fd);}finally{closeSync(fd);}
  demand(readFileSync(path).equals(raw),'skb_service_receipt_readback');return actualPin(path);
}

/** No implicit launch on import. Only this exact direct child is signalled. */
export function launchSkbArtifactNativeService(input:{script:Pin;argv:string[];descriptorPin:Pin;storageSourcePin:Pin;port:number;env:NodeJS.ProcessEnv;startupMs?:number;graceMs?:number;forceMs?:number}){
  const d=loadSkbStorageDescriptor(input.descriptorPin,input.storageSourcePin),native=loadNativePython(),home=assertSkbArtifactServiceHome(d,d.directories.stand!);
  verifyPin(input.script);demand(resolve(input.script.path)===join(import.meta.dir,'skb-artifact-stand-v1.py'),'skb_service_executed_script');
  demand(Number.isInteger(input.port)&&input.port>0&&input.port<65536,'skb_service_port');
  ordinary(d.storePhysical);if(!existsSync(home))mkdirSync(home,{recursive:false});ordinary(home);
  const receiptPath=join(home,'native-process-owner.json'),closurePath=join(home,'native-process-closure.json');
  demand(!existsSync(receiptPath)&&!existsSync(closurePath),'skb_service_fresh_home');
  const nonce=randomBytes(32).toString('hex'),startedAt=new Date().toISOString(),startedNs=process.hrtime.bigint();
  const child=spawn(native.executable,['-B','-X','utf8',join(import.meta.dir,'skb-jpg-native-bootstrap.py'),'--receipt',receiptPath,'--nonce',nonce,'--home',home,'--script',input.script.path,'--',...input.argv],{windowsHide:true,env:{...skbArtifactNativeEnvironment(d,input.env),OBJRUN_JPG_LIFECYCLE_NONCE:nonce},stdio:['ignore','pipe','pipe']});
  let exit:{code:number|null;signal:string|null}|undefined,childClosed=false,spawnError=false,identity:ServiceIdentity|undefined,healthIdentityVerified=false;
  child.once('exit',(code,signal)=>{exit={code,signal};});child.once('close',()=>{childClosed=true;});child.once('error',()=>{spawnError=true;});
  function source(){verifyPin(input.script);verifyPin(input.descriptorPin);verifyPin(input.storageSourcePin);verifyPin(actualNativePin);}
  const actualNativePin=actualPin(native.executable);
  function owner(){
    if(identity)return identity;if(!existsSync(receiptPath))return;
    ordinary(home);const s=lstatSync(receiptPath);demand(s.isFile()&&!s.isSymbolicLink()&&s.size<=8192,'skb_owner_receipt_regular');
    const v=JSON.parse(readFileSync(receiptPath,'utf8')) as ServiceIdentity;
    demand(v.protocol==='jpg-native-python-service-lifecycle-v2'&&v.pid===child.pid&&v.parentPid===process.pid&&v.nonce===nonce&&v.sameProcessExecution===true&&canonical(v.executable)===canonical(native.executable)&&v.executableSha256===native.sha256&&resolve(v.home)===home,'skb_service_actual_owner');
    identity=v;return v;
  }
  async function waitReady(){
    const end=process.hrtime.bigint()+BigInt(input.startupMs??10000)*1000000n;
    while(process.hrtime.bigint()<end){
      source();const v=owner();demand(!spawnError&&!exit&&!childClosed,'skb_service_exited_before_ready');
      if(v){let health:any;try{const response=await fetch('http://127.0.0.1:'+input.port+'/health',{headers:{'X-ObjRun-Grader-Token':input.env.TGENGIN_GRADER_TOKEN??''},signal:AbortSignal.timeout(300)});if(response.ok)health=await response.json();}catch{}
        if(health){assertHealthIdentity(health,v,native);demand(health.storageProtocol===d.protocol&&health.storageOwnerNonce===d.ownerNonce&&same(health.storageDescriptorPin,input.descriptorPin),'skb_service_health_storage');durable(join(home,'native-process-health.json'),health);healthIdentityVerified=true;return health;}}
      await Bun.sleep(25);
    }throw new Error('skb_native_readiness_timeout');
  }
  let stopping:Promise<ClosureReceipt&{storageDescriptorPin:Pin;sourcePin:Pin;storageProtocol:string;descriptorOwnerNonce:string}>|undefined;
  function stop(){
    if(stopping)return stopping;
    stopping=(async()=>{
      const began=process.hrtime.bigint(),faults:string[]=[],terminationAttempts:ClosureReceipt['terminationAttempts']=[];
      try{owner();source();}catch{faults.push('owner_or_source_identity_invalid');}
      const wait=async(ms:number)=>{const end=process.hrtime.bigint()+BigInt(ms)*1000000n;while(!childClosed&&process.hrtime.bigint()<end)await Bun.sleep(10);};
      const kill=(signal:'SIGTERM'|'SIGKILL')=>{let accepted=false;try{accepted=child.kill(signal);}catch{}terminationAttempts.push({signal,accepted,at:new Date().toISOString()});if(!accepted&&!childClosed)faults.push(signal+'_not_accepted');};
      if(!childClosed){kill('SIGTERM');await wait(input.graceMs??1500);}if(!childClosed){kill('SIGKILL');await wait(input.forceMs??1500);}
      const until=process.hrtime.bigint()+600000000n;let portClosed=false;do{portClosed=await localhostPortClosed(input.port,100);if(portClosed)break;await Bun.sleep(25);}while(process.hrtime.bigint()<until);
      if(!exit)faults.push('direct_child_exit_not_observed');if(!childClosed)faults.push('direct_child_close_not_observed');if(!portClosed)faults.push('owned_port_not_closed');if(spawnError)faults.push('spawn_failed');if(!identity)faults.push('service_identity_not_observed');
      const closed=!!identity&&!!exit&&childClosed&&portClosed&&faults.length===0;
      const result:ClosureReceipt&{storageDescriptorPin:Pin;sourcePin:Pin;storageProtocol:string;descriptorOwnerNonce:string}={protocol:'jpg-native-python-service-lifecycle-v2',childPid:child.pid,identityVerified:!!identity,healthIdentityVerified,identity,nativeExecutableSha256:native.sha256,nativeProfileSha256:native.profileSha256,startedAt,finishedAt:new Date().toISOString(),durationMs:Number((process.hrtime.bigint()-began)/1000000n),terminationAttempts,exit,directChildExited:!!exit,directChildClosed:childClosed,portClosed,closed,serviceClosed:closed,faults,storageDescriptorPin:input.descriptorPin,sourcePin:actualPin(import.meta.path),storageProtocol:d.protocol,descriptorOwnerNonce:d.ownerNonce,scope:'Exact direct native ten-task service PID/listener only; container and background process closure require independent owned receipts.'};
      ordinary(home);durable(closurePath,result);return result;
    })();return stopping;
  }
  return{child,native,receiptPath,closurePath,waitReady,stop,get identity(){return identity;},startedAtMonotonicNs:startedNs.toString(),serviceProtocol:SKB_NATIVE_PROTOCOL};
}
