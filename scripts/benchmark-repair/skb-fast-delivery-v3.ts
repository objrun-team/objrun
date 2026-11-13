/** Continuously publish actual pilot state; never label pending grades passed. */
import { writeFileSync } from 'node:fs';
import { join,resolve } from 'node:path';
import { durableJpgJson } from './jpg-paid-resource-admission-v1.ts';

export function createFastDelivery(r:any){
  const home=resolve(import.meta.dir,'../../docs/repair-2026-10-08/skillsbench-ten-takeover-v1/first-delivery-v3');
  const rows=r.taskSchedule.map((x:any)=>({index:x.index,taskId:x.officialId,arm:x.arm,status:'未运行',officialReward:null,strictAllPassed:null,
    fullCollectionValid:null,graded:false,providerRequests:0,promptTokens:0,completionTokens:0,rawGenerationPath:null,rawGradePath:null,fault:null}));
  const save=()=>{
    const value={protocol:'skillsbench-first-delivery-v3',updatedAtUtc:new Date().toISOString(),runId:r.runId,runDirectory:r.output,plannedDistinctTasks:10,
      plannedRealTaskRuns:20,realTaskRuns:rows.filter((x:any)=>x.providerRequests>0&&x.status!=='运行中').length,gradedTaskRuns:rows.filter((x:any)=>x.graded).length,
      concurrency:2,formalScoreCertified:false,rows,collectionIndexPin:r.collectionIndexPin,
      limitations:['Initial version; full certification is not complete','Reuse validated complete collection, six tools, and existing cold controls; remaining full certification, lab fractional controls, and independent packaging are outstanding','Only 10 fixed tasks, one U/F run each; do not start 87 tasks'],
      apiUsageLimitRemoved:true,balanceIsPrecondition:false};
    durableJpgJson(join(home,'results.json'),value,true);
    const csv=(v:any)=>'"'+String(v??'').replaceAll('"','""')+'"';const keys=Object.keys(rows[0]);
    writeFileSync(join(home,'results.csv'),'\ufeff'+[keys.map(csv).join(','),...rows.map((x:any)=>keys.map(k=>csv(x[k])).join(','))].join('\r\n')+'\r\n');
    const cell=(x:any)=>x.graded?`${x.officialReward??'no valid reward'} (${x.strictAllPassed?'all passed':x.fullCollectionValid?'rejected by original tests':'incomplete test results'})`:x.status;
    const table=r.taskDescriptorPins.map((_:any,i:number)=>`| ${rows[i*2].taskId} | ${cell(rows[i*2])} | ${cell(rows[i*2+1])} |`).join('\n');
    writeFileSync(join(home,'results.md'),`# Initial SkillsBench results\n\nRun ${value.realTaskRuns}/20, graded ${value.gradedTaskRuns}/20. Ten fixed tasks, one U and one F run each, two tasks concurrent. Model deepseek-flash; original task time budgets are unchanged. API usage, balance, operating reserves, and old cost caps are not startup constraints.\n\n| Task | U | F |\n|---|---|---|\n${table}\n\nMachine-readable: [results.json](results.json), table: [results.csv](results.csv). Each row saves paths to original generation, provider usage, and private grading records.\n\nThis initial version does not establish complete certification. Existing successful validations are reused directly; remaining full certification, lab fractional controls, and independent packaging are outstanding. Do not start 87 tasks.\n`);
  };
  save();return {update(index:number,patch:any){Object.assign(rows[index],patch);save();},save,rows};
}
