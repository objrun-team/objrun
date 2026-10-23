import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {verifyNativeResourceMapping,reserveNewAdoptedLane,claimUniqueAdoption} from './adopted-parent-v46.ts';
const root=resolve(import.meta.dir,'../../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013');
const proof=JSON.parse(readFileSync(join(home,'coordinator/broker-adoption-v46/rehydrate-proof.json'),'utf8'));
const mapping=verifyNativeResourceMapping(proof);let rejected=0;
const state={originalCapUsd:proof.originalCapUsd,inheritedRetainedUsd:proof.minimumRetainedAllocationUsd,additionalRetainedUsd:0,inheritedRunIds:['old'],newLanes:{}};
for(const f of [()=>reserveNewAdoptedLane(state,'old',1),()=>reserveNewAdoptedLane(state,'new',proof.remainingOriginalParentUsd+1),()=>verifyNativeResourceMapping({...proof,resourceHoldRows:proof.resourceHoldRows.slice(1)})]){try{f();throw Error('negative_control_accepted')}catch(e){if(String(e).includes('negative_control_accepted'))throw e;rejected++;}}
const fixture=join(home,'coordinator/broker-adoption-v46/unique-owner-negative-'+Date.now());mkdirSync(fixture,{recursive:true});const owner={runId:'local-mock-no-provider',ownerNonce:'fixture-only'};claimUniqueAdoption(fixture,owner,join(fixture,'one'),{path:'fixture',sha256:'fixture',bytes:0});try{claimUniqueAdoption(fixture,owner,join(fixture,'two'),{});throw Error('second_owner_accepted')}catch(e){if(String(e).includes('second_owner_accepted'))throw e;rejected++;}
const result={protocol:'novaeve-adoption-readonly-check-v46',actualNativeMappingPassed:true,resourceHoldPids:mapping.map((r:any)=>r.originalResourcePid),negativeControlsPassed:rejected,secondDirectorySameOwnerRefused:true,realOriginalOwnerLockModified:false,productionOwnerClaimed:false,modelCalls:0,productionStartQualified:false,pendingQualification:'actual-localMock-HTTP-journal-cash-and-production-preflight'};
writeFileSync(join(home,'coordinator/broker-adoption-v46/readonly-validation.json'),JSON.stringify(result,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(result));
