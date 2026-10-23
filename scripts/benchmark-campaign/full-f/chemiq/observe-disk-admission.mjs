import fs from 'node:fs';import path from 'node:path';
import {observeDockerDisk,evaluateDockerDisk,GiB} from '../shared/docker-physical-disk-admission-staged.ts';
import {actualPin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
const root=path.resolve(import.meta.dir,'../../../..'),out=path.join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq');
const dockerDataPath='E:/Docker/wsl/disk/docker_data.vhdx',observation=observeDockerDisk(dockerDataPath),policy={nowMs:Date.now(),expectedDrive:'E:',minimumFreeBytes:8*GiB,plannedGrowthBytes:0,maximumAgeMs:30000},result=evaluateDockerDisk(observation,policy);
const proof={atUtc:new Date().toISOString(),dockerDataPath,observation,policy,result,storageAndGraderHoldStillRequired:true,paidStarted:false,modelCalls:0,dockerActions:0,plannedGrowthBasis:'Existing original grader; no new Docker builds/pulls/containers.8GiB growth reserve stays mandatory',guardPin:actualPin(path.join(root,'scripts/benchmark-campaign/full-f/shared/docker-physical-disk-admission-staged.ts')),entryPin:actualPin(path.join(import.meta.dir,'run-task39-stream.ts'))};
fs.writeFileSync(path.join(out,'physical-disk-admission-ready.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify({admissible:result.admissible,reason:result.reason,drive:observation?.drive,freeBytes:observation?.freeBytes,paidStarted:false}));
