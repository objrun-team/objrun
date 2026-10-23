/** Explicit Bench/resource scope for a root-signed native operation in the original pool. */
import{demand,verifyPin}from'./manifest.ts';import{processIdentity}from'./runtime.ts';
import{verifyAdoptedConnection}from'../benchmark-campaign/full-f/novaeve_formal_v1/broker/adopted-consumer-price-renewal.ts';
export async function ownedOperationResource(connection:any,plan:any){
 verifyPin(plan.planPin);await verifyAdoptedConnection(connection);const r=plan.resource;
 demand(['terminal-bench','skillsbench'].includes(r.bench)&&r.slots===1&&Number.isSafeInteger(r.memoryMb)&&r.memoryMb>0&&Number.isSafeInteger(r.growthBytes)&&r.growthBytes>0,'explicit_original_resource_scope');
 const body={slug:r.bench,kind:'heavy-container',pid:process.pid,slots:1,memoryMb:r.memoryMb,plannedGrowthBytes:r.growthBytes};
 const rpc=async(path:string,body:any)=>{const response=await fetch(connection.endpoint+path,{method:'POST',headers:{authorization:'Bearer '+connection.accessToken,'content-type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});const value:any=await response.json();demand(response.ok,value.error??value.reason??'original_pool_resource_denied');return value};
 const claim=await rpc('/resource/acquire',body);demand(claim.pid===body.pid&&claim.ownerIncarnation===processIdentity(process.pid).incarnation&&claim.memoryMb===r.memoryMb&&claim.plannedGrowthBytes===r.growthBytes&&claim.slots===1&&!claim.adoptedOrphanHold&&!claim.inheritedResourceHold&&typeof claim.token==='string'&&claim.token.length>0,'exact_new_owned_resource_claim');
 Object.assign(process.env,{NOVAEVE_RESOURCE_PARENT_PID:String(process.pid),NOVAEVE_RESOURCE_LEASE_PID:String(process.pid),NOVAEVE_RESOURCE_MEMORY_MB:String(r.memoryMb),NOVAEVE_RESOURCE_GROWTH_BYTES:String(r.growthBytes),NOVAEVE_RESOURCE_BENCH:r.bench,NOVAEVE_RESOURCE_TOKEN:claim.token,NOVAEVE_RESOURCE_SLOTS:'1',NOVAEVE_ROOT_ONLY_DISPATCH:'1'});
 let released=false;return{...claim,async release(){demand(!released,'resource_already_released');await rpc('/resource/release',{...body,token:claim.token});released=true;delete process.env.NOVAEVE_RESOURCE_TOKEN}};
}
