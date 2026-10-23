/** Read-only recovery of exact failed cold-engine PID/ports from its own stopped database. */
import { Database } from 'bun:sqlite';
import { join, resolve } from 'node:path';
import { actualPin, demand, jsonPin } from './paid-resource-proof-v2.ts';
import { observeChemiqOwned } from './chemiq-f-owned-v2.ts';
import { durableChemiqJson } from './chemiq-f-paid-admission-v2.ts';
const output=resolve(process.argv[2]??'');
const failurePin=actualPin(join(output,'cold-engine-failure.json')),failure=jsonPin(failurePin),registration=jsonPin(failure.registrationPin);
demand(failure.protocol==='chemiq-cold-engine-failure-v2'&&failure.modelCalls===0&&failure.stopReturned===true&&registration.role==='cold-only-native-engine-no-paid-lock','chemiq_failed_cold_recovery_scope');
const path=join(output,'solver-engine/data/h2h.sqlite'),databasePin=actualPin(path),db=new Database(path,{readonly:true});
let rows:any[]=[];try{rows=db.query("select base_url from api where key_env='OBJRUN_CHEMIQ_COLD_V2_KEY' and model='deepseek-flash'").all();}finally{db.close();}
demand(rows.length===1,'chemiq_cold_recovery_endpoint_missing');const url=new URL(rows[0].base_url);
demand(url.hostname==='127.0.0.1'&&url.pathname==='/v1'&&url.protocol==='http:'&&url.port!=='','chemiq_cold_recovery_endpoint');
const observed=await observeChemiqOwned(output,[failure.registrationPin],[Number(url.port)],'recovery');
console.log(JSON.stringify({recoveryPin:durableChemiqJson(join(output,'failed-cold-recovery.json'),{protocol:'chemiq-failed-cold-owned-recovery-v2',
  family:failure.family,runId:failure.runId,observedAtUtc:new Date().toISOString(),failurePin,databasePin,registrationPin:failure.registrationPin,
  recoveredLocalProviderPort:Number(url.port),portRecoveredFromActualStoppedApiRow:true,closedObservationPin:observed,closed:true,modelCalls:0,sourcePin:actualPin(import.meta.path),
  originalFailureModified:false,privateSharedGraderRemoved:false})}));
