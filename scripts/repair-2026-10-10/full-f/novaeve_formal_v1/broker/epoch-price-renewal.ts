import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {actualPin,verifyPin} from 'F:/git/TgEngin-handoff-2026-10-07/TgEngin/scripts/repair-2026-10-08/paid-resource-proof-v2.ts';
import {verifyAdoptedActivation,verifyAdoptedConnection} from './adopted-consumer-price-renewal.ts';
export async function activated(path:string){
 if(actualPin(path).sha256!=='8ffa69afefa8c5dcc108aeb6550fd4bc777dc330a43a1aea4dbe0ef142f66248')throw Error('exact_adopted_v76_activation_required');
 const activation=JSON.parse(readFileSync(path,'utf8'));
 if(activation.dockerHost!=='tcp://127.0.0.1:18750'||activation.network?.gateway!=='172.30.89.1'||activation.network?.proxy!=='http://172.30.89.1:10809'||resolve(activation.controlPath)!==resolve(activation.brokerControlPath)||activation.controlPin.sha256!=='a85556689f23b8dd510da768be7004dc42fdf95f043caaa6a1d2ccfb142a17ba')throw Error('exact_private_v76_control_and_native_scope_required');
 verifyPin(activation.controlPin);const adopted=await verifyAdoptedActivation(path);return {activation,connection:adopted.connection,adopted};
}
export async function resource(connection:any,plan:any){
 await verifyAdoptedConnection(connection);verifyPin(plan.planPin);
 if(!Number.isSafeInteger(plan.originalPeakMemoryMb)||plan.originalPeakMemoryMb<4096||!Number.isSafeInteger(plan.originalPlannedGrowthBytes)||plan.originalPlannedGrowthBytes<=0)throw Error('original_ocaml_resource_contract_required');
 const body={slug:'terminal-bench',kind:'heavy-container',pid:process.pid,slots:1,memoryMb:plan.originalPeakMemoryMb,plannedGrowthBytes:plan.originalPlannedGrowthBytes};
 const rpc=async(path:string,b:any)=>{const r=await fetch(connection.endpoint+path,{method:'POST',headers:{authorization:'Bearer '+connection.accessToken,'content-type':'application/json'},body:JSON.stringify(b),signal:AbortSignal.timeout(30000)});const v:any=await r.json();if(!r.ok)throw Error(v.error??v.reason??'resource_denied');return v;};
 const claim=await rpc('/resource/acquire',body);if(typeof claim.token!=='string'||!claim.ownerIncarnation||claim.adoptedOrphanHold||claim.inheritedResourceHold)throw Error('new_incarnated_owned_resource_required');let closed=false;
 process.env.NOVAEVE_RESOURCE_LEASE_PID=String(process.pid);process.env.NOVAEVE_RESOURCE_TOKEN=claim.token;process.env.NOVAEVE_RESOURCE_MEMORY_MB=String(body.memoryMb);process.env.NOVAEVE_RESOURCE_GROWTH_BYTES=String(body.plannedGrowthBytes);
 return {token:claim.token,ownerIncarnation:claim.ownerIncarnation,memoryMb:body.memoryMb,plannedGrowthBytes:body.plannedGrowthBytes,async release(){if(closed)throw Error('resource_already_released');await rpc('/resource/release',{...body,token:claim.token});closed=true;delete process.env.NOVAEVE_RESOURCE_TOKEN;}};
}
