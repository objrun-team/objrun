import { Database } from 'bun:sqlite';
import { readFileSync,writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { OUT,save } from './prepare.ts';
import { inspectCampaignJournal } from '../../../benchmark-repair/campaign-journal.ts';
import { verifyBenchmarkCashClosure } from '../../../benchmark-repair/benchmark-usd-cash.ts';
import { actualPin } from '../../../benchmark-repair/paid-resource-proof-v2.ts';
const json=(p:string)=>JSON.parse(readFileSync(p,'utf8'));
const state=json(join(OUT,'status.json')),runOut=state.runOut;
if(!state.financeClosed)throw Error('Drain and close current run before diagnosis classification');
const inspection=inspectCampaignJournal(join(runOut,'journal'));
const financial=verifyBenchmarkCashClosure(actualPin(join(runOut,'currency/cash-close.json')));
if(!inspection.valid||!inspection.accountingClosed||!financial.proof.releasePermitted)throw Error('Not safely financially closed');
const findings=[];
for(const index of [3,4]){
  const recordPath=join(runOut,`task-${index}.json`),record=json(recordPath);
  const db=new Database(join(runOut,`worker-${record.worker}/data/h2h.sqlite`),{readonly:true});
  const fault=db.query(`select m.unit,m.at,json_extract(m.body,'$.stuck') as fault from agent_bot_msg m join task_repair u on u.instance=m.instance and u.unit=m.unit where u.task=? and u.cycle='submit' and m.role='system' and json_valid(m.body) and json_extract(m.body,'$.stuck')='The required submit tool was not called exactly once' order by m.at desc limit 1`).get(record.taskId) as any;
  const task=db.query('select state,result,solve_seconds from task where id=?').get(record.taskId) as any;db.close();
  const last=record.apiCalls.at(-1),body=JSON.parse(gunzipSync(readFileSync(last.responseFile)).toString());
  const reproduced=Boolean(fault)&&task.result.includes('finalization_pending')&&body.choices[0].finish_reason==='stop'&&!body.choices[0].message.tool_calls?.length;
  findings.push({index,officialId:record.officialId,reproduced,fault,task,requestId:last.requestId,usageCost:body.usage.cost,originalFailurePin:actualPin(recordPath)});
  if(process.argv.includes('--classify')){if(!reproduced)throw Error('No durable protocol failure evidence');
    writeFileSync(join(OUT,'results',`task-${index}.json`),JSON.stringify({...record,terminalProtocolFailure:true,state:'submission_protocol_failure',
      acceptance:{valid:false,passed:false,outcome:'submission_protocol_failure'},classificationEvidence:{originalFailurePin:actualPin(recordPath),fault,finalGenerationId:last.requestId,
      rule:'Explicit final submit-station RequiredToolCallMissing, fully accounted successful provider response without tool_calls; preserved terminal protocol failure, not scored completion'}},null,2)+'\n');}
}
save('stall-diagnosis.json',{findings,cause:'RequiredToolCallMissing leaves submit unit unfinished; production finalizer waits up to 16min, beyond runner hard limit750s',
  cashClosed:true,billedUsd:financial.proof.snapshot.billedUsd,modelCalls:inspection.snapshot?.acceptedRequestCount,sharedSourceChangesRequired:false});
console.log(JSON.stringify({reproduced:findings.every(f=>f.reproduced),indices:findings.map(f=>f.index),classified:process.argv.includes('--classify')}));
if(!process.argv.includes('--classify')&&findings.every(f=>f.reproduced))process.exitCode=1;
