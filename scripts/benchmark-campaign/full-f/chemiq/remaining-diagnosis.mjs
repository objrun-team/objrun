import fs from 'node:fs';import path from 'node:path';import {Database} from 'bun:sqlite';
import {finalCandidate} from '../../../../app/src/objective/candidate.ts';
import {actualPin,hash} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
const root=path.resolve(import.meta.dir,'../../../..'),base=path.join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8')),manifest=read(path.join(base,'manifest.json')),histories=new Map(),valid=new Set(),terminal=new Set();
for(const name of fs.readdirSync(path.join(base,'runs')).sort()){
 const dir=path.join(base,'runs',name);for(const task of fs.readdirSync(dir).filter(n=>/^task-\d+$/.test(n))){const file=path.join(dir,task,'result.json');if(!fs.existsSync(file))continue;const r=read(file),index=r.index;const h=histories.get(index)??[];h.push({r,file});histories.set(index,h);if(r.generationValid&&r.acceptance?.valid)valid.add(index);if(['done','failed'].includes(r.state)&&(/RequiredToolCallMissing/.test(String(r.runtimeVerdict?.why??''))||r.runtimeVerdict?.outcome==='required_tool_call_missing'))terminal.add(index);}
}
const recoveredReady=path.join(base,'delivery-recovery-ready.json');if(fs.existsSync(recoveredReady)){const ready=read(recoveredReady),report=read(ready.reportPin.path);for(const r of report.records)if(r.generationValid&&r.acceptance?.valid)valid.add(r.index);}
const tasks=[];
for(const t of manifest.taskSchedule.filter(t=>!valid.has(t.index)&&!terminal.has(t.index))){
 const history=histories.get(t.index)??[],attempts=history.map(({r,file})=>({runId:r.runId,state:r.state,outcome:r.runtimeVerdict?.outcome,why:r.runtimeVerdict?.why,error:r.error,generation:r.generationClassification,acceptance:r.acceptance?.outcome,candidateHow:r.candidateHow,answerSha256:r.candidateSha256,calls:(r.calls??[]).map(c=>({fault:c.fault,httpStatus:c.httpStatus,startedAt:c.startedAt,finishedAt:c.finishedAt})),resultPin:actualPin(file)}));
 const candidates=[];for(const {r,file} of history.slice(-4)){
  const database=path.join(path.dirname(file),'engine/data/h2h.sqlite');if(!fs.existsSync(database))continue;const db=new Database(database,{readonly:true});try{const task=db.query('select id,state,result,created_at,solve_seconds from task limit1'.replace('limit1','limit 1')).get();if(!task)continue;const all=(sql,args=[])=>db.query(sql).all(...args);const candidate=finalCandidate({all,run(){throw Error('readonly');},exec(){throw Error('readonly');},close(){}},task.id);candidates.push({runId:r.runId,taskId:task.id,state:task.state,createdAt:task.created_at,deadlineAt:task.created_at+task.solve_seconds*1000,candidateHow:candidate?.how??'none',candidateSha256:candidate?hash(candidate.body):null,candidateBytes:candidate?Buffer.byteLength(candidate.body):0,databasePin:actualPin(database),scoreCertified:false});}catch(e){candidates.push({runId:r.runId,error:String(e)});}finally{db.close();}
 }
 tasks.push({index:t.index,officialId:t.officialId,attemptCount:history.length,attempts,candidates});
}
const faults={};for(const task of tasks)for(const a of task.attempts){const key=a.outcome??a.error??a.state??'unknown';faults[key]=(faults[key]??0)+1;}
const result={atUtc:new Date().toISOString(),denominator:816,valid:valid.size,terminalProtocol:terminal.size,remaining:tasks.length,faults,tasks,readonly:true,modelCalls:0,graderCalls:0,action:'Diagnosis only. No old failures rewritten or candidate certified. Keep current healthy frozen segment; original deadline submit evidence may support independent recovery after complete generation/trace/grader verification.'};
fs.writeFileSync(path.join(base,'remaining-diagnosis.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({valid:valid.size,terminalProtocol:terminal.size,remaining:tasks.length,faults,deadlineSubmittedCandidates:tasks.filter(t=>t.candidates.some(c=>c.candidateHow==='submitted')).map(t=>t.index)}));
