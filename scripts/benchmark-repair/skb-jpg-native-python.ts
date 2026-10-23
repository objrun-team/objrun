import {createHash,randomBytes} from 'node:crypto';
import {spawn,type ChildProcess,type SpawnOptions} from 'node:child_process';
import {existsSync,lstatSync,mkdirSync,readFileSync,realpathSync,writeFileSync} from 'node:fs';
import {isAbsolute,join,relative,resolve} from 'node:path';
import {createConnection} from 'node:net';

export const LIFECYCLE_PROTOCOL='jpg-native-python-service-lifecycle-v2';
const root=resolve(import.meta.dir,'../..');
const cEvidenceRoot='C:/Users/y1252/.codex/visualizations/2026/10/08/01a119ed-fdf7-7c32-b323-de9bab1290b6';
export const NATIVE_PROFILE_PATH=join(import.meta.dir,'skb-jpg-native-python.json');
const sha=(value:Buffer)=>createHash('sha256').update(value).digest('hex');
const canonical=(path:string)=>realpathSync(path).replaceAll('\\','/').toLowerCase();
const inside=(parent:string,path:string)=>{const rel=relative(resolve(parent),resolve(path));return rel===''||(!rel.startsWith('..')&&!isAbsolute(rel));};
const save=(path:string,value:unknown)=>writeFileSync(path,JSON.stringify(value,null,2)+'\n');

export type NativePythonProfile={protocol:string;executable:string;bytes:number;sha256:string;preservedBytes:string;profileSha256:string};
export function loadNativePython(profilePath=NATIVE_PROFILE_PATH):NativePythonProfile{
 const raw=readFileSync(profilePath),value=JSON.parse(raw.toString('utf8'));
 if(value.protocol!=='jpg-native-python-executable-v2'||!isAbsolute(value.executable)||!value.executable.toLowerCase().endsWith('/python.exe')||lstatSync(value.executable).isSymbolicLink())throw new Error('Only the frozen absolute native Python executable is permitted');
 const bytes=readFileSync(value.executable);
 if(bytes.subarray(0,2).toString()!=='MZ'||bytes.length!==value.bytes||sha(bytes)!==value.sha256)throw new Error('Frozen native Python executable bytes changed');
 const preserved=resolve(root,value.preservedBytes);
 if(!inside(root,preserved)||sha(readFileSync(preserved))!==value.sha256)throw new Error('Preserved native Python executable bytes changed');
 return {...value,executable:realpathSync(value.executable),profileSha256:sha(raw)};
}

/** Short host-only audit/freeze helpers also bypass PATH/cmd/shim resolution. */
export function spawnNativePython(arguments_:string[],options:SpawnOptions={}):ChildProcess{
 const native=loadNativePython();
 return spawn(native.executable,['-B','-X','utf8',...arguments_],{...options,windowsHide:true});
}

export type ServiceIdentity={protocol:string;pid:number;parentPid:number;executable:string;executableSha256:string;home:string;nonce:string;startedAtUnixMs:number;pythonVersion:string;sameProcessExecution:boolean};
export type ClosureReceipt={protocol:string;childPid:number|undefined;identityVerified:boolean;healthIdentityVerified:boolean;identity?:ServiceIdentity;nativeExecutableSha256:string;nativeProfileSha256:string;startedAt:string;finishedAt:string;durationMs:number;terminationAttempts:{signal:string;accepted:boolean;at:string}[];exit?:{code:number|null;signal:string|null};directChildExited:boolean;directChildClosed:boolean;portClosed:boolean;closed:boolean;serviceClosed:boolean;faults:string[];scope:string};

export async function localhostPortClosed(port:number,timeoutMs=300):Promise<boolean>{
 return await new Promise(resolve_=>{
  const socket=createConnection({host:'127.0.0.1',port});let settled=false;
  const done=(value:boolean)=>{if(settled)return;settled=true;socket.destroy();resolve_(value);};
  socket.once('connect',()=>done(false));
  socket.once('error',(error:NodeJS.ErrnoException)=>done(error.code==='ECONNREFUSED'));
  socket.setTimeout(timeoutMs,()=>done(false));
 });
}

export function assertHealthIdentity(health:any,identity:ServiceIdentity,native:NativePythonProfile){
 const value=health?.processIdentity;
 if(!value||value.protocol!==LIFECYCLE_PROTOCOL||value.pid!==identity.pid||value.parentPid!==identity.parentPid||value.nonce!==identity.nonce||value.executableSha256!==native.sha256||canonical(value.executable)!==canonical(native.executable))throw new Error('JPG actual service health PID/interpreter identity mismatch');
}

/**
 * The bootstrap executes the stand in the same native process. Its xb/fsynced
 * receipt must match child.pid before health is trusted. This certifies this
 * service and its port only, never an arbitrary descendant process tree.
 */
export function launchNativeJpgService(input:{script:string;argv:string[];home:string;port:number;env?:NodeJS.ProcessEnv;startupMs?:number;graceMs?:number;forceMs?:number}){
 const native=loadNativePython(),home=resolve(input.home),script=resolve(input.script);
 if(!inside(root,script)||!existsSync(script))throw new Error('Owned frozen service script is required');
 if(!inside(root,home)&&!inside(cEvidenceRoot,home))throw new Error('Native service home must remain inside an authorized workspace');
 if(!Number.isInteger(input.port)||input.port<1||input.port>65535)throw new Error('Invalid owned service port');
 mkdirSync(home,{recursive:true});
 const receiptPath=join(home,'native-process-owner.json'),closurePath=join(home,'native-process-closure.json');
 if(existsSync(receiptPath)||existsSync(closurePath))throw new Error('Fresh native lifecycle home required');
 const nonce=randomBytes(32).toString('hex');
 const child=spawn(native.executable,['-B','-X','utf8',join(import.meta.dir,'skb-jpg-native-bootstrap.py'),'--receipt',receiptPath,'--nonce',nonce,'--home',home,'--script',script,'--',...input.argv],{windowsHide:true,env:{...(input.env??process.env),OBJRUN_JPG_LIFECYCLE_NONCE:nonce},stdio:['ignore','pipe','pipe']});
 const startedAt=new Date().toISOString();
 let exit:{code:number|null;signal:string|null}|undefined,childClosed=false,spawnError=false,identity:ServiceIdentity|undefined,healthIdentityVerified=false;
 child.once('exit',(code,signal)=>{exit={code,signal};});child.once('close',()=>{childClosed=true;});child.once('error',()=>{spawnError=true;});
 function owner(){
  if(identity)return identity;
  if(!existsSync(receiptPath))return undefined;
  const raw=readFileSync(receiptPath);if(raw.length>8192)throw new Error('Owned lifecycle receipt size mismatch');
  const value=JSON.parse(raw.toString('utf8')) as ServiceIdentity;
  if(value.protocol!==LIFECYCLE_PROTOCOL||value.pid!==child.pid||value.parentPid!==process.pid||value.nonce!==nonce||value.sameProcessExecution!==true||canonical(value.executable)!==canonical(native.executable)||value.executableSha256!==native.sha256||resolve(value.home)!==home)throw new Error('JPG native owner PID/interpreter identity mismatch');
  identity=value;return value;
 }
 async function waitReady(){
  const until=Date.now()+(input.startupMs??10000);
  while(Date.now()<until){
   const actual=owner();
   if(spawnError||exit||childClosed)throw new Error('Native JPG service exited before readiness');
   if(actual){
    let health:any;
    try{const response=await fetch('http://127.0.0.1:'+input.port+'/health',{signal:AbortSignal.timeout(300)});if(response.ok)health=await response.json();}catch{}
    if(health){assertHealthIdentity(health,actual,native);save(join(home,'native-process-health.json'),health);healthIdentityVerified=true;return health;}
   }
   await Bun.sleep(25);
  }
  throw new Error('Native JPG service health readiness timeout');
 }
 let stopping:Promise<ClosureReceipt>|undefined;
 function stop():Promise<ClosureReceipt>{
  if(stopping)return stopping;
  stopping=(async()=>{
   const began=Date.now(),faults:string[]=[],terminationAttempts:ClosureReceipt['terminationAttempts']=[];
   try{owner();}catch{faults.push('owner_identity_invalid');}
   const wait=async(ms:number)=>{const until=Date.now()+ms;while(!childClosed&&Date.now()<until)await Bun.sleep(10);};
   const kill=(signal:'SIGTERM'|'SIGKILL')=>{let accepted=false;try{accepted=child.kill(signal);}catch{}terminationAttempts.push({signal,accepted,at:new Date().toISOString()});if(!accepted&&!childClosed)faults.push(signal+'_not_accepted');};
   if(!childClosed){kill('SIGTERM');await wait(input.graceMs??1500);}
   if(!childClosed){kill('SIGKILL');await wait(input.forceMs??1500);}
   // A successful kill request alone is not an exit or listener-close proof.
   const portUntil=Date.now()+600;let portClosed=false;
   do{portClosed=await localhostPortClosed(input.port,100);if(portClosed)break;await Bun.sleep(25);}while(Date.now()<portUntil);
   if(!exit)faults.push('direct_child_exit_not_observed');if(!childClosed)faults.push('direct_child_close_not_observed');if(!portClosed)faults.push('owned_port_not_closed');if(spawnError)faults.push('spawn_failed');if(!identity)faults.push('service_identity_not_observed');
   const closed=!!identity&&!!exit&&childClosed&&portClosed&&faults.length===0;
   const result:ClosureReceipt={protocol:LIFECYCLE_PROTOCOL,childPid:child.pid,identityVerified:!!identity,healthIdentityVerified,identity,nativeExecutableSha256:native.sha256,nativeProfileSha256:native.profileSha256,startedAt,finishedAt:new Date().toISOString(),durationMs:Date.now()-began,terminationAttempts,exit,directChildExited:!!exit,directChildClosed:childClosed,portClosed,closed,serviceClosed:closed, faults,scope:'Exact same-process native Python service PID and listener; arbitrary grandchildren or background container processes are not certified.'};
   save(closurePath,result);return result;
  })();return stopping;
 }
 return {child,native,receiptPath,closurePath,waitReady,stop,get identity(){return identity;}};
}
