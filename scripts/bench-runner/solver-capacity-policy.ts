import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
/** Explicit CPU and memory reservation; unknown inherited CPU is never zero. */
export const CAPACITY48 = Object.freeze({maximumSolvers:48, physicalCpu:192, memoryMb:262144});
function need(ok:unknown,why:string):asserts ok {if(!ok)throw Error(why)}
export function inheritedCpuCharge(r:any){
 if(Number.isSafeInteger(r.cpu)&&r.cpu>0&&r.cpu<=CAPACITY48.physicalCpu)return {cpu:r.cpu,basis:'explicit-reservation'};
 if(r.cpu===null&&Number.isSafeInteger(r.cpuReservationUpperBound)&&r.cpuReservationUpperBound>0&&r.cpuReservationUpperBound<=CAPACITY48.physicalCpu&&r.cpuUpperBoundProofPin){
 const p=r.cpuUpperBoundProofPin,b=readFileSync(p.path);need(b.length===p.bytes&&createHash('sha256').update(b).digest('hex')===p.sha256,'legacy_cpu_proof_changed');const q=JSON.parse(b.toString());
 need(q.protocol==='bench-reviewed-inherited-cpu-upper-bound-v1'&&q.pid===r.pid&&q.ownerIncarnation===r.ownerIncarnation&&q.cpuReservationUpperBound===r.cpuReservationUpperBound&&q.originalResourcePinsVerified===true,'legacy_cpu_upper_bound_binding');
 return {cpu:r.cpuReservationUpperBound,basis:'reviewed-upper-bound'};
 }
 return {cpu:CAPACITY48.physicalCpu,basis:'unknown-conservative-physical-cap'};
}
export function capacityUsage(rows:any[]){return rows.reduce((a,r)=>{need(Number.isSafeInteger(r.memoryMb)&&r.memoryMb>0,'inherited_memory_unknown');const c=inheritedCpuCharge(r);return {cpu:a.cpu+c.cpu,memoryMb:a.memoryMb+r.memoryMb,unknownCpuRows:a.unknownCpuRows+(c.basis==='unknown-conservative-physical-cap'?1:0)}},{cpu:0,memoryMb:0,unknownCpuRows:0});}
export function checkCapacityReservation(rows:any[],request:any,held:any){
 need(Number.isSafeInteger(request.cpu)&&request.cpu>0&&request.cpu<=CAPACITY48.physicalCpu,'explicit_cpu_reservation_required');
 if(held){need(held.cpu===request.cpu,'resource_reclaim_cpu_changed');return;}
 const u=capacityUsage(rows);
 need(u.cpu+request.cpu<=CAPACITY48.physicalCpu,'physical_cpu_capacity');
 need(u.memoryMb+request.memoryMb<=CAPACITY48.memoryMb,'aggregate_memory_capacity');
}
