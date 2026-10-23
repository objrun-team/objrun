import {readFileSync,readdirSync,existsSync,unlinkSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
import {Database} from 'bun:sqlite';
import {actualPin,jsonPin,hash,demand} from './paid-resource-proof-v2.ts';
import {durableJpgJson} from './jpg-paid-resource-admission-v1.ts';
import {inspectCampaignJournal} from './campaign-journal.ts';
import {skbStoppedSnapshot} from './skb-artifact-runtime-v2.ts';
const file=resolve(process.argv[2]!),r=jsonPin(actualPin(file)),base=jsonPin(r.storageDescriptorPin);
const inspection=inspectCampaignJournal(base.directories.journal);demand(inspection.valid&&inspection.accountingClosed,'recovery_journal_pending');
const raw=readFileSync(join(base.directories.journal,'api-events.jsonl')).subarray(0,inspection.prefix!.bytes),calls:any[]=[];let offset=0;
for(const line of raw.toString().split(/(?<=\n)/).filter(Boolean)){const e=JSON.parse(line),bytes=Buffer.byteLength(line);if(e.kind==='finish')calls.push({...e.record,requestSeq:e.requestSeq,journalRef:{callId:e.requestSeq,finishOffset:offset,finishEnd:offset+bytes,finishLineSha256:hash(line)}});offset+=bytes;}
const registrations=readdirSync(r.output).filter(x=>x.startsWith('process-')).map(x=>jsonPin(actualPin(join(r.output,x))));
const lockPath=resolve(import.meta.dir,'../../.phase1-data/owned-paid-campaign.lock.json'),lock=JSON.parse(readFileSync(lockPath,'utf8'));
demand(lock.runId===r.runId,'recovery_lock_identity');
const pids=[lock.pid,...registrations.map(x=>x.pid)];
const check=spawnSync('powershell.exe',['-NoProfile','-Command',`$p=@(${pids.join(',')}); @(Get-CimInstance Win32_Process | Where-Object {$_.ProcessId -in $p} | Select-Object ProcessId,CreationDate) | ConvertTo-Json -Compress`],{encoding:'utf8',windowsHide:true});
demand(check.status===0&&!check.stdout.trim(),'recovery_original_actor_remaining');
const recoveries=[];
for(const index of [13,15]){
 const row=r.taskSchedule[index],lp=r.slotStorageDescriptorPins[index===13?1:0],layout=jsonPin(lp),nonce=index===13?'fe59a6c122c44caebacba876f4597b01':'1eb9751f8f9c4c7a8ee5733f558860f2';
 const recoveryPin=actualPin(join(layout.directories.stand,'solver-'+nonce,'orphan-recovery.json')),recovery=jsonPin(recoveryPin);demand(jsonPin(recovery.closurePin).ownedClosed,'recovery_solver_open');
 const dbPath=join(layout.directories.sqlite,'worker-'+index,'data/h2h.sqlite'),snap=skbStoppedSnapshot(dbPath,row.id),db=new Database(dbPath,{readonly:true});const task=db.query('select * from task where id=?').get(row.id) as any;db.close();
 const rec={protocol:'skillsbench-ten-task-generation-v2',family:r.family,runId:r.runId,...row,taskDescriptorPin:r.taskDescriptorPins[Math.floor(index/2)],storageDescriptorPin:lp,actualCreatedAt:task.created_at,deadlineUnixMs:task.created_at+row.taskSeconds*1000,state:'interrupted',observedDatabaseState:task.state,runtimeVerdict:task.result?JSON.parse(task.result):null,generationValid:null,generationClassification:{valid:false,kind:'infrastructure_error',why:'host process interrupted; actual stopped artifact recovered'},fault:{stage:'generation_'+index,type:'HostProcessInterrupted',causeEvidence:'Windows System Event 2004 record 4027344; direct termination cause unproven'},candidate:snap.candidate?.body??'',candidateSha256:hash(snap.candidate?.body??''),trace:snap.trace,units:snap.units,apiCalls:calls.filter(c=>c.route===row.route),artifactCapture:{capturePin:recovery.capturePin,recoveredFromOwnedClosurePin:recovery.closurePin},solverClosurePin:recovery.closurePin,orphanRecoveryPin:recoveryPin,databasePins:[dbPath,dbPath+'-wal'].filter(existsSync).map(actualPin)};
 demand(rec.apiCalls.some(c=>c.providerAttempted&&c.httpStatus===200&&c.completionValid&&c.usage),'recovery_real_model_absent');
 recoveries.push(durableJpgJson(join(r.output,'generation-'+index+'.json'),rec));
}
const proof=durableJpgJson(join(r.output,'interrupted-owned-release-v5.json'),{protocol:'skillsbench-interrupted-owned-release-v5',runId:r.runId,owned:lock,actorPids:pids,actorAbsenceObservedAtUtc:new Date().toISOString(),recoveries,journalPrefix:inspection.prefix,pendingRequests:0,actualOwnedSolverClosed:true,originalProcessInterrupted:true,formalScoreCertified:false,financialCertificate:false,modelCalls:0});
demand(JSON.stringify(JSON.parse(readFileSync(lockPath,'utf8')))===JSON.stringify(lock),'recovery_lock_changed');unlinkSync(lockPath);
console.log(JSON.stringify({recoveryPins:recoveries,releasePin:proof,realCases:16,modelCalls:0}));
