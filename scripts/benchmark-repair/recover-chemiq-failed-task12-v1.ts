/** Recover an invalid interrupted task's candidate/trace from a new copy; never grade it or alter originals. */
import { closeSync, copyFileSync, existsSync, fsyncSync, mkdirSync, openSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { finalCandidate } from '../../app/src/objective/candidate.ts';
import { actualPin, demand, hash, jsonPin, same, verifyPin } from './paid-resource-proof-v2.ts';
import { CHEMIQ_F_ROOT as ROOT, loadChemiqFPlan } from './chemiq-f-journal-contract-v2.ts';
import { durableChemiqJson } from './chemiq-f-paid-admission-v2.ts';
const runId='repair-2026-10-09T09-40-03-707Z',plan=loadChemiqFPlan(runId,'pilot16'),task=plan.tasks[12];
const output=join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-campaigns-v2',runId),target=join(output,'failed-task12-recovered-v1');
demand(!existsSync(target),'chemiq_recovery_never_overwrites');
const source=join(ROOT,'.phase1-data/chemiq-f-journal-v2',runId,'task-12/data/h2h.sqlite');
const originalPins=['','-wal','-shm'].filter(s=>existsSync(source+s)).map(s=>actualPin(source+s));
const existing=jsonPin(actualPin(join(output,'failed-owned-sqlite-copy-observation.json')));
demand(same(originalPins,existing.sourcePins.map(({path,bytes,sha256}:any)=>({path,bytes,sha256}))),'chemiq_recovery_exact_stopped_originals');
mkdirSync(target);const copy=join(target,'copied-database');mkdirSync(copy);
for(const pin of originalPins){const suffix=pin.path.slice(source.length);copyFileSync(pin.path,join(copy,'h2h.sqlite'+suffix));verifyPin(pin);}
const copyBefore=originalPins.map(p=>actualPin(join(copy,'h2h.sqlite'+p.path.slice(source.length))));
const {Database}=require('bun:sqlite'),db=new Database(join(copy,'h2h.sqlite'),{readonly:true});
const tracePath=join(target,'trace-12-recovered.jsonl'),fd=openSync(tracePath,'wx',0o600);let traceRows=0,explicitVerifyCalls=0;let candidate:any,terminal:any;
try{
  const all=(sql:string,params:any[]=[])=>db.query(sql).all(...params);
  const rows=all('select state,result,created_at,solve_seconds from task where id=?',[task.taskId]);
  demand(rows.length===1&&rows[0].solve_seconds===900&&rows[0].state==='claimed'&&rows[0].result===null,'chemiq_recovery_invalid_original_task');terminal=rows[0];
  candidate=finalCandidate({all,run(){throw Error('readonly');},exec(){throw Error('readonly');},close(){}} as never,task.taskId);
  for(const row of db.query('select instance,unit,seq,role,kind,body,at,thought,prompt_tokens,completion_tokens,reasoning_tokens,cached_tokens from agent_bot_msg where instance like ? order by unit,seq').iterate(task.taskId+'#%')){
    writeFileSync(fd,JSON.stringify(row)+'\n');traceRows++;
    if(row.kind==='call')try{explicitVerifyCalls+=JSON.parse(row.body).calls?.filter((c:any)=>c.name==='verify').length??0;}catch{}
  }fsyncSync(fd);
}finally{closeSync(fd);db.close();}
for(const p of originalPins)verifyPin(p);
const proof=durableChemiqJson(join(target,'recovered-invalid-task12.json'),{protocol:'chemiq-failed-task-supplementary-recovery-v1',runId,taskIndex:12,officialId:task.officialId,taskId:task.taskId,
  originalTaskRecordAbsent:true,originalState:terminal.state,originalRuntimeVerdict:terminal.result,generationValid:false,scoreCertificateValid:false,graded:false,modelCalls:0,graderCalls:0,
  answer:candidate?.body??'',candidateHow:candidate?.how??'none',candidateSha256:hash(candidate?.body??''),candidateDeadlinePolicy:'frozen-finalCandidate-at<=created+solve_seconds',actualCreatedAt:terminal.created_at,solveSeconds:900,
  tracePin:actualPin(tracePath),traceRows,explicitVerifyCalls,originalDatabasePins:originalPins,copiedDatabasePinsBeforeSqlite:copyBefore,copiedDatabasePinAfterSqlite:actualPin(join(copy,'h2h.sqlite')),
  originalDatabasesNeverOpenedBySqlite:true,originalChanged:false,financialRecoveryNotAValidScore:true,sourcePin:actualPin(import.meta.path)});
console.log(JSON.stringify({proofPin:proof,traceRows,scoreCertificateValid:false,modelCalls:0,graderCalls:0}));
