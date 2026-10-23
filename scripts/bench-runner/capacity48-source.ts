/** Isolated exact-anchor projection; original sources remain immutable. */
import {join} from 'node:path';
import {unlimitedFinancialSource} from './financial-policy-source-benchmark.ts';
function one(s:string,a:string,b:string){if(s.split(a).length!==2)throw Error('capacity48_exact_anchor:'+a);return s.replace(a,b)}
export function capacity48Source(path:string,raw:string){
 let s=unlimitedFinancialSource(path,raw);const name=path.replaceAll('\\','/').split('/').pop();
 if(name==='broker-adoption-v76.ts'){
 s='import {CAPACITY48,capacityUsage,checkCapacityReservation} from '+JSON.stringify(join(import.meta.dir,'solver-capacity-policy.ts'))+';\n'+s;
 s=one(s,"check(!dispatchPaused,'resource_admission_paused');const held=resources.get(key);","check(!dispatchPaused,'resource_admission_paused');const held=resources.get(key);");
 s=one(s,"const sameKind=[...resources.values()].filter(r=>r.kind===d.kind);","checkCapacityReservation([...resources.values()],d,held);const sameKind=[...resources.values()].filter(r=>r.kind===d.kind);");
 s=one(s,"kind:d.kind,slug:d.slug,pid:d.pid,slots,memoryMb,plannedGrowthBytes,token:","kind:d.kind,slug:d.slug,pid:d.pid,slots,memoryMb,cpu:d.cpu,plannedGrowthBytes,token:");
 s=one(s,"heavyMemoryMb:options.heavyMemoryMb??262144,","heavyMemoryMb:options.heavyMemoryMb??262144,physicalCpuCapacity:CAPACITY48.physicalCpu,cpuReservationUsage:capacityUsage([...resources.values()]),");
 s=one(s,"protocol:'novaeve-adopted-resource-pool-v76',capacity:16,","protocol:'novaeve-adopted-resource-pool-v76',capacity:options.heavyCapacity??16,");
 }
 if(name==='start-unlimited-broker.ts'){
 s=one(s,"from'./financial-policy-loader.ts'","from'./capacity48-loader.ts'");
 s=one(s,'maxInFlight:16,targetMax:16,perBenchMax:16,heavyCapacity:16,perBenchHeavySlots:16','maxInFlight:48,targetMax:48,perBenchMax:48,heavyCapacity:48,perBenchHeavySlots:48,heavyMemoryMb:262144');
 s=one(s,'currentParentAdmissionPin:a.lease.proofPin,adoption:a.metadata()', 'capacityPolicyPin:p.capacityPolicyPin,currentParentAdmissionPin:a.lease.proofPin,adoption:a.metadata()');
 s=one(s,'sameOriginalPool16:true','sameOriginalPool16:false,sameOriginalPoolExpandedTo48:true');
 }
 if(name==='skillsbench-single-task-session.ts'){
 s=one(s,'h.targetMax===16&&','h.targetMax===48&&h.physicalCpuCapacity===192&&');
 s=one(s,'r.slots===1&&r.memoryMb>=','r.slots===1&&r.cpu===Number(process.env.NOVAEVE_RESOURCE_CPU)&&r.cpu>0&&r.memoryMb>=');
 }
 if(name==='unlimited-adopted-consumer.ts'){
 s=one(s,'h.targetMax===16&&h.maxInFlight>=1&&h.maxInFlight<=16','h.targetMax===48&&h.maxInFlight>=1&&h.maxInFlight<=48&&h.physicalCpuCapacity===192&&h.heavyMemoryMb===262144');
 s=one(s,"used+h.availableResourceSlots['heavy-container']===16","used+h.availableResourceSlots['heavy-container']===48");
 }
 if(name==='unlimited-owned-forward-guard.ts'){
 s=one(s,'h.targetMax===16&&','h.targetMax===48&&h.physicalCpuCapacity===192&&');
 s=one(s,'r.slots===1&&r.memoryMb>=lease.memoryMb','r.slots===1&&r.cpu===lease.cpu&&Number.isSafeInteger(r.cpu)&&r.cpu>0&&r.memoryMb>=lease.memoryMb');
 }
 if(name==='unlimited-adopted-parent.ts'){
 s="import {verifyRuntimeCapacityPolicy} from "+JSON.stringify(join(import.meta.dir,'runtime-capacity-policy.ts'))+";\nimport {projectLegacyResourceCpu} from "+JSON.stringify(join(import.meta.dir,'legacy-resource-cpu.ts'))+";\nimport {capacityUsage} from "+JSON.stringify(join(import.meta.dir,'solver-capacity-policy.ts'))+";\n"+s;
 s=one(s,'const p=envelope.plan;','const p=envelope.plan;verifyRuntimeCapacityPolicy(p.capacityPolicyPin);');
 s=one(s,'p.previousExecutorPid===22388','p.previousExecutorPid===30344');
 s=one(s,'p.sharedPool===16',"p.sharedPool===48&&p.capacityAuthorityPin?.sha256==='430a105d94afce428ddd4fa9e5d31b67589e91a22b84aecc665ebe3ef686d48e'");
 s=one(s,'[p.sourceLoaderPin,p.oldHealthPin','[p.capacityAuthorityPin,p.capacityPolicyPin,p.inheritedCpuEvidencePin,p.sourceLoaderPin,p.oldHealthPin');
 s=one(s,'h.pid===22388','h.pid===30344');
 s=one(s,'old=jsonPin(plan.oldAllocationPin),pool=',"rawOld=jsonPin(plan.oldAllocationPin),old={...rawOld,originalCapUsd:rawOld.originalDeclaredCapUsd,additionalRetainedUsd:Object.values(rawOld.newLanes??{}).reduce((n:number,r:any)=>n+(r.retainedUsd??0),0),historyUnknownUpperUsd:rawOld.originalHistoryUnknownUpperUsd},pool=");
 s=s.replaceAll('previousExecutorPid:22388','previousExecutorPid:30344');
 s=one(s,'const directory=plan.directory;', 'const projectedRows=projectLegacyResourceCpu(pool.rows,plan.inheritedCpuEvidencePin),usage=capacityUsage(projectedRows);demand(usage.cpu<=192&&usage.memoryMb<=262144,\"inherited_cpu_or_memory_capacity_not_proven\");const directory=plan.directory;');
 s=one(s,'return{lease,guard,ownerGuardPin,initialResources:pool.rows,','return{lease,guard,ownerGuardPin,initialResources:projectedRows,');
 s=one(s,"financialAuthorityPin:plan.financialAuthorityPin,currentParentAdmissionPin:lease.proofPin","financialAuthorityPin:plan.financialAuthorityPin,capacityPolicyPin:plan.capacityPolicyPin,currentParentAdmissionPin:lease.proofPin");
 }
 if(name==='owned-operation-resource.ts'){
 s=one(s,"memoryMb:r.memoryMb,plannedGrowthBytes:r.growthBytes","memoryMb:r.memoryMb,cpu:r.cpu,plannedGrowthBytes:r.growthBytes");
 s=one(s,"claim.memoryMb===r.memoryMb&&","claim.memoryMb===r.memoryMb&&claim.cpu===r.cpu&&");
 s=one(s,"NOVAEVE_RESOURCE_MEMORY_MB:String(r.memoryMb)","NOVAEVE_RESOURCE_MEMORY_MB:String(r.memoryMb),NOVAEVE_RESOURCE_CPU:String(r.cpu)");
 }
 if(['signed-owned-operation.ts','signed-owned-asset.ts','terminal-driver.ts'].includes(name!)){
 const a=JSON.stringify(join(import.meta.dir,'financial-policy-loader-benchmark.ts'));
 s=one(s,a,JSON.stringify(join(import.meta.dir,'capacity48-loader.ts')));
 }
 if(name==='unlimited-python-bridge-readonly-retry.ts'){
 s=one(s,"from'./financial-policy-loader.ts'","from'./capacity48-loader.ts'");
 s=one(s,'slots:r.slots,memoryMb:r.memoryMb,','slots:r.slots,memoryMb:r.memoryMb,cpu:r.cpu,');
 }
 return s;
}


