import { Database } from 'bun:sqlite';
import { existsSync,readFileSync,readdirSync,writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { OUT,save } from './prepare.ts';
import { finalCandidate } from '../../../../app/src/objective/candidate.ts';
import { classifyGeneration,gradeFixedCandidate } from '../../../repair-2026-10-08/campaign-contract.ts';
import { inspectCampaignJournal } from '../../../repair-2026-10-08/campaign-journal.ts';
import { actualPin } from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import { verifyBenchmarkCashClosure } from '../../../repair-2026-10-08/benchmark-usd-cash.ts';
import { digest } from '../../../repair-2026-10-08/scientific-journal-plan.ts';
const json=(p:string)=>JSON.parse(readFileSync(p,'utf8')),s=json(join(OUT,'status.json')),runOut=s.runOut;
if(!s.financeClosed||!inspectCampaignJournal(join(runOut,'journal')).accountingClosed||!verifyBenchmarkCashClosure(actualPin(join(runOut,'currency/cash-close.json'))).proof.releasePermitted)throw Error('Current run must be closed');
const objective={nodes:[{name:'parsed',domain:'bool',moment:'done',handle:'http://127.0.0.1:17906/parsed'},{name:'correct',domain:'bool',moment:'done',handle:'http://127.0.0.1:17906/correct'}],edges:[{src:'parsed',out:0,dst:'correct'}],sink:'correct',checks:5,reuse:'text'};
const findings=[];
for(const file of readdirSync(runOut).filter(n=>/^task-\d+\.json$/.test(n))){const p=join(runOut,file),record=json(p);if(record.acceptance?.valid||record.terminalProtocolFailure)continue;
  const dbPath=join(runOut,`worker-${record.worker}`,`task-${record.index}`,'data/h2h.sqlite');if(!existsSync(dbPath))continue;
  const db=new Database(dbPath,{readonly:true});let candidate:any,terminal:any,trace:any[];
  try{terminal=db.query('select state,result from task where id=?').get(record.taskId);trace=db.query('select instance,unit,seq,role,kind,body,at,thought,prompt_tokens,completion_tokens,reasoning_tokens,cached_tokens from agent_bot_msg where instance like ? order by unit,seq').all(record.taskId+'#%');candidate=finalCandidate({all:(sql:string,params:any[]=[])=>{const stmt=db.prepare(sql);try{return stmt.all(...params);}finally{stmt.finalize();}},run(){throw Error('readonly');},exec(){throw Error('readonly');},close(){}} as any,record.taskId);}finally{db.close();}
  const verdict=terminal.result?JSON.parse(terminal.result):undefined;if(!['done','failed'].includes(terminal.state)||!verdict||['finalization_pending','finalization_error'].includes(verdict.outcome)){findings.push({index:record.index,recovered:false,terminal});continue;}
  const generation=classifyGeneration({runtimeVerdict:verdict,state:terminal.state,calls:record.apiCalls,trace:trace!,candidate:candidate?.body});
  const acceptance=await gradeFixedCandidate({objective,task:{id:record.taskId},candidate:candidate?.body,generation,expectedCandidateSha256:digest(candidate?.body??'')});
  findings.push({index:record.index,recovered:acceptance.valid,acceptance});
  if(acceptance.valid)writeFileSync(join(OUT,'results',file),JSON.stringify({...record,state:terminal.state,runtimeVerdict:verdict,generationClassification:generation,answer:candidate?.body??'',candidateHow:candidate?.how??'none',candidateSha256:digest(candidate?.body??''),trace,acceptance,
    recoveredFromClosedEngine:{originalFailurePin:actualPin(p),atUtc:new Date().toISOString(),modelCalls:0,deadlineEnforcedByProductionFinalCandidate:true}},null,2)+'\n');
}
save('closed-engine-recovery.json',{runOut,findings,modelCalls:0,originalRunArtifactsUnchanged:true});console.log(JSON.stringify({recovered:findings.filter(f=>f.recovered).map(f=>f.index),unrecovered:findings.filter(f=>!f.recovered).map(f=>f.index),modelCalls:0}));
