import {processIncarnation} from './process-incarnation-v70.ts';
import {readFileSync} from 'node:fs';
export function validateOwnedForwardSnapshot(h:any,c:any,lease:any,now=Date.now()){
 const age=now-Date.parse(h.atUtc),r=h.resourceSlots?.find((r:any)=>r.kind==='heavy-container'&&r.slug==='terminal-bench'&&r.pid===process.pid);
 if(!(age>=0&&age<=30000&&h.healthy===true&&h.pid===c.pid&&h.runId===c.runId&&h.targetMax===16&&h.adoption?.protocol==='novaeve-truthful-broker-price-renewal-v1'&&h.adoption.singleResourcePool===true&&h.adoption.exactOwnedLeaseLaneBinding===true&&r&&!r.adoptedOrphanHold&&!r.inheritedResourceHold&&r.token===lease.token&&r.ownerIncarnation===lease.ownerIncarnation&&r.ownerIncarnation===processIncarnation(process.pid)&&r.slots===1&&r.memoryMb>=lease.memoryMb&&r.plannedGrowthBytes>=lease.plannedGrowthBytes))throw Error('ocaml_actual_owned_resource_forward_closed');
}
export function createOwnedForwardGuard(connection:any,lease:any){return ()=>validateOwnedForwardSnapshot(JSON.parse(readFileSync(connection.healthPath,'utf8')),connection,lease);}
