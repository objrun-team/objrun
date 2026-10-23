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
      limitations:['初版，不代表全部认证完成','复用已通过的完整collection、六工具和现有冷对照；剩余完整认证、lab小数控制和独立打包待补','仅固定10题U/F各一次，不启动87题'],
      apiUsageLimitRemoved:true,balanceIsPrecondition:false};
    durableJpgJson(join(home,'results.json'),value,true);
    const csv=(v:any)=>'"'+String(v??'').replaceAll('"','""')+'"';const keys=Object.keys(rows[0]);
    writeFileSync(join(home,'results.csv'),'\ufeff'+[keys.map(csv).join(','),...rows.map((x:any)=>keys.map(k=>csv(x[k])).join(','))].join('\r\n')+'\r\n');
    const cell=(x:any)=>x.graded?`${x.officialReward??'无有效奖励'}（${x.strictAllPassed?'全通过':x.fullCollectionValid?'原测试拒绝':'测试结果不完整'}）`:x.status;
    const table=r.taskDescriptorPins.map((_:any,i:number)=>`| ${rows[i*2].taskId} | ${cell(rows[i*2])} | ${cell(rows[i*2+1])} |`).join('\n');
    writeFileSync(join(home,'results.md'),`# SkillsBench 初版结果\n\n已运行 ${value.realTaskRuns}/20，已评分 ${value.gradedTaskRuns}/20。固定10题 U/F 各一次，两个任务并发。模型 deepseek-flash，原任务时间预算保持不变。API 用量、余额、运营预留和旧费用上限不作为启动限制。\n\n| 题目 | U | F |\n|---|---|---|\n${table}\n\n机器可读：[results.json](results.json)，表格：[results.csv](results.csv)。各行保存原始生成、provider用量和私有评分记录路径。\n\n初版不代表全部认证完成。现有成功验证直接复用；剩余完整认证、lab 小数控制和独立打包待补。不启动87题。\n`);
  };
  save();return {update(index:number,patch:any){Object.assign(rows[index],patch);save();},save,rows};
}
