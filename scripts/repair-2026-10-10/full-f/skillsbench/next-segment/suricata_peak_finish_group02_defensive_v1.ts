export function requireSuricataPeak(plan:any,resources:any){
 const memory=resources.environment.memory_mb;
 if(!Number.isFinite(memory)||memory<=0||plan.originalPeakMemoryMb!==3*memory)throw Error('suricata_three_actor_peak_plan_required');
 return 3*memory;
}
