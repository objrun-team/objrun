/** Optional task-owned proxy binding for neutral probes only. */
import {verifyProviderProbeScope as baseScope,verifyProviderProbeForward as baseForward,markProviderProbeDispatch as baseMark} from './provider-probe-continuation-policy-v1.ts';
import{readFileSync}from'node:fs';import{resolve}from'node:path';import{createHash,verify}from'node:crypto';import{dlopen,FFIType,ptr}from'bun:ffi';
function need(v:unknown,w:string):asserts v{if(!v)throw Error(w)}
const sha=(b:Buffer)=>createHash('sha256').update(b).digest('hex');
function pin(p:any){need(p&&typeof p.path==='string'&&Number.isSafeInteger(p.bytes),'probe_transport_pin');const b=readFileSync(p.path);need(b.length===p.bytes&&sha(b)===p.sha256,'probe_transport_pin_changed');return b}
const api=dlopen('C:/Windows/System32/kernel32.dll',{OpenProcess:{args:[FFIType.u32,FFIType.i32,FFIType.u32],returns:FFIType.u64},GetProcessTimes:{args:[FFIType.u64,FFIType.ptr,FFIType.ptr,FFIType.ptr,FFIType.ptr],returns:FFIType.i32},GetExitCodeProcess:{args:[FFIType.u64,FFIType.ptr],returns:FFIType.i32},CloseHandle:{args:[FFIType.u64],returns:FFIType.i32}});
function live(pid:number,incarnation:string){need(process.platform==='win32'&&process.arch==='x64'&&Number.isSafeInteger(pid)&&pid>0,'probe_transport_host_identity');const h=api.symbols.OpenProcess(0x1000,0,pid);need(h,'probe_transport_owner_absent');try{const code=new Uint8Array(4),values=[0,1,2,3].map(()=>new Uint8Array(8));need(api.symbols.GetExitCodeProcess(h,ptr(code))&&new DataView(code.buffer).getUint32(0,true)===259,'probe_transport_owner_exited');need(api.symbols.GetProcessTimes(h,...values.map(ptr)as[number,number,number,number])&&new DataView(values[0].buffer).getBigUint64(0,true).toString()===incarnation,'probe_transport_incarnation_changed')}finally{api.symbols.CloseHandle(h)}}
export function verifyProviderProbeScope(scopePin:any,lane:any){const p=baseScope(scopePin,lane);if(!p.transportProfilePin)return p;
 const e=JSON.parse(pin(p.transportProfilePin).toString()),g=e.proof,key=pin(e.authorityPublicPin);
 need(e.protocol==='bench-signed-task-scoped-openrouter-transport-profile-v1'&&e.authorityPublicPin.sha256==='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98'&&verify(null,Buffer.from(JSON.stringify(g)),key,Buffer.from(e.signature,'base64')),'probe_transport_profile_signature');
 need(g.protocol==='bench-task-scoped-openrouter-transport-profile-v1'&&g.acceptedReadOnlyComponent===true&&g.realModelTransportAccepted===false&&g.endpoint==='http://127.0.0.1:18092'&&g.globalProxyUnmodified===true&&JSON.stringify(g.allowedHosts)===JSON.stringify(['openrouter.ai']),'probe_transport_exact_profile');
 pin(g.enginePin);pin(g.configurationPin);pin(g.readOnlyActualProofPin);const start=JSON.parse(pin(p.proxyStartReceiptPin).toString());
 need(start.pid===p.transportProxyPid&&start.incarnation===p.transportProxyIncarnation&&start.error===null&&resolve(start.actualExecutable)===resolve(g.enginePin.path)&&JSON.stringify(start.argv)===JSON.stringify([g.enginePin.path,'-d',g.configurationDirectory,'-f',g.configurationPin.path]),'probe_transport_actual_spawn_join');
 live(p.transportProxyPid,p.transportProxyIncarnation);return{...p,transportProxyURL:g.endpoint};
}
export function verifyProviderProbeForward(lane:any,raw:string){const p=verifyProviderProbeScope(lane.providerProbeScopePin,lane);baseForward(lane,raw);return p}
export function markProviderProbeDispatch(lane:any,raw:string){verifyProviderProbeScope(lane.providerProbeScopePin,lane);return baseMark(lane,raw)}
