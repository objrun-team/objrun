import {mkdirSync,writeFileSync,readFileSync,existsSync,readdirSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {loadChemiqFPlan,CHEMIQ_F_SETTINGS} from '../../../repair-2026-10-08/chemiq-f-journal-contract-v3.ts';
import {actualPin,hash} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
export const ROOT=resolve(import.meta.dir,'../../../..');
export const OUT=join(ROOT,'docs/repair-2026-10-10/full-f-rerun/chemiq');
export function save(name:string,value:any){mkdirSync(OUT,{recursive:true});writeFileSync(join(OUT,name),JSON.stringify(value,null,2)+'\n');}
export function prepare(){
  const prior=existsSync(join(OUT,'manifest.json'))?JSON.parse(readFileSync(join(OUT,'manifest.json'),'utf8')):null;
  const runId=prior?.runId??'repair-'+new Date().toISOString().replace(/[:.]/g,'-');
  const plan=loadChemiqFPlan(runId,'full816');
  const manifest={protocol:'chemiq-full-f-manifest-v1',runId,createdAtUtc:prior?.createdAtUtc??new Date().toISOString(),denominator:816,plannedTaskRuns:816,arms:['F'],settings:CHEMIQ_F_SETTINGS,
    taskSchedule:plan.taskSchedule,taskScheduleSha256:plan.taskScheduleSha256,datasetPin:plan.datasetPin,scopePin:plan.scopePin,readinessPin:plan.readinessPin,
    datasetRepository:'https://github.com/oxpig/ChemIQ',datasetCommit:'63826f64990802e87f1b11b9192606a20838d522',
    grader:{origin:'http://127.0.0.1:17918',level:0,opsin:'local-2.8',opsinVersion:'2.8.0',restFallback:false,lengthPolicy:'raw-input-length',protocolRelation:'explicit local variant of official verifier; not equivalent to paper REST / official-parsed'},
    concurrency:{tasks:2,perBenchRequests:2,globalRequests:4},allowedTools:['submit','verify','task_tree','node_load'],requestedCycleMaxUnits:12,freshMachinePerTask:true,
    authorization:{userConfirmed:true,source:'2026-10-10 full F rerun delegation',URequestsAuthorized:false},
    limits:['Failed, timed out, ungraded and infrastructure tasks remain in denominator.','Counting carbon/ring and shortest path have finite answer spaces; report category-specific results.','Five checks are explicit verify budget, not all physical grading calls.']};
  if(prior&&hash(JSON.stringify(prior))!==hash(JSON.stringify(manifest)))throw Error('Frozen manifest changed');
  if(!prior)save('manifest.json',manifest);
  save('public-tasks.json',plan.tasks.map(({officialId,promptSha256,row})=>({officialId,promptSha256,row})));
  const walk=(p:string):string[]=>readdirSync(p,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(join(p,e.name)):[join(p,e.name)]);
  const sources=[...walk(join(ROOT,'app/src')).filter(p=>/\.(ts|html)$/.test(p)),join(ROOT,'test/_lib.ts'),join(ROOT,'examples/benchmark/chemiq/stand.py'),...readdirSync(join(ROOT,'scripts/repair-2026-10-08')).filter(n=>/^(chemiq-|campaign-|benchmark-|scientific-journal-plan)/.test(n)&&n.endsWith('.ts')).map(n=>join(ROOT,'scripts/repair-2026-10-08',n)),...walk(import.meta.dir).filter(p=>p.endsWith('.ts'))];
  save('preparation.json',{protocol:'chemiq-full-f-preparation-v1',observedAtUtc:new Date().toISOString(),manifestPin:actualPin(join(OUT,'manifest.json')),datasetSha256:plan.datasetPin.sha256,publicQuestions:plan.tasks.length,categories:Object.fromEntries([...new Set(plan.tasks.map(t=>t.category))].map(c=>[c,plan.tasks.filter(t=>t.category===c).length])),sourcePins:sources.sort().map(actualPin),modelCalls:0,paidOwnerAcquired:false});
  return plan;
}
if(import.meta.main){const p=prepare();console.log(JSON.stringify({runId:p.runId,planned:p.tasks.length,output:OUT,modelCalls:0}));}
