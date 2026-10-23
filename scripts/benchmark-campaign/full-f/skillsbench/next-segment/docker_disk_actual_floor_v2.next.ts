/** Next-segment only: no Docker command or resource acquisition in this guard. */
import {readFileSync,mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {evaluateDockerDisk,observeDockerDisk,GiB} from '../../shared/actual-physical-disk-floor.next.ts';
import {actualPin} from '../../../../benchmark-repair/paid-resource-proof-v2.ts';
import {atomicStateJson} from '../../shared/atomic-state.ts';
export function checkSkillsBenchDockerDisk(root:string,taskId:string,phase:string){
 const home=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench');
 const descriptorPath=join(home,'task-descriptors',taskId+'.json');
 const descriptor=JSON.parse(readFileSync(descriptorPath,'utf8'));
 const storageMb=descriptor.originalResources.environment.storage_mb;
 if(!Number.isFinite(storageMb)||storageMb<=0)throw Error('original_task_storage_required');
 // Original growth is recorded; only actual E/F five-GiB floors gate admission.
 const plannedGrowthBytes=storageMb*1024**2;
 const observation=observeDockerDisk('E:/Docker/wsl/disk/docker_data.vhdx');
 const decision=evaluateDockerDisk(observation,{nowMs:Date.now(),expectedDrive:'E:',plannedGrowthBytes:0,minimumFreeBytes:5*GiB,maximumAgeMs:30000});
 const workspaceObservation=observeDockerDisk('F:/');
 const workspaceDecision=evaluateDockerDisk(workspaceObservation,{nowMs:Date.now(),expectedDrive:'F:',plannedGrowthBytes:0,minimumFreeBytes:5*GiB,maximumAgeMs:30000});
 const folder=join(home,'physical-disk-admission',crypto.randomUUID());mkdirSync(folder,{recursive:true});
 const proof={protocol:'skillsbench-next-physical-disk-admission-v1',atUtc:new Date().toISOString(),taskId,phase,observation,decision,workspaceObservation,workspaceDecision,plannedGrowthBytes,growthBasis:'original storage_mb retained as observation, not admission threshold',descriptorPin:actualPin(descriptorPath),guardSourcePin:actualPin(import.meta.path),sharedGuardSourcePin:actualPin(join(root,'scripts/benchmark-campaign/full-f/shared/actual-physical-disk-floor.next.ts')),dockerOperations:false,resourceClaimed:false,modelCalls:0,denominator:87};
 atomicStateJson(join(folder,'result.json'),proof);
 if(!workspaceDecision.admissible)throw Error('physical_docker_disk_queued:F:'+workspaceDecision.reason);
 if(!decision.admissible)throw Error('physical_docker_disk_queued:'+decision.reason);
 return proof;
}
