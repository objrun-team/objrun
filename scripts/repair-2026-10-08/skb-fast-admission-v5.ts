/** Lightweight own lock and usage recording for the user's fast first delivery.
 * Historical replay, balance/reserve and the previous fee cap are deferred.
 */
import { randomBytes } from 'node:crypto';
import { existsSync,readFileSync,unlinkSync } from 'node:fs';
import { join } from 'node:path';
import { actualPin,demand,jsonPin,same,REAL_CLOCK,verifyPin,type Pin } from './paid-resource-proof-v2.ts';
import { durableJpgJson,jpgCarry } from './jpg-paid-resource-admission-v1.ts';
import { type AdmissionLease } from './paid-resource-admission-v2.ts';
import { SKB_ARTIFACT_FAMILY } from './skb-artifact-journal-contract-v2.ts';

export function acquireSkbFastAdmission(r:any,root:string):AdmissionLease&{finishLightweight(v:any):void}{
  const path=join(root,'.phase1-data/owned-paid-campaign.lock.json');demand(!existsSync(path),'skb_other_paid_owner_active');
  const carry=jpgCarry(r),owned=Object.freeze({pid:process.pid,startedAt:new Date().toISOString(),runId:r.runId,entry:join(import.meta.dir,'skb-artifact-fast-resume-runtime-v5.ts'),
    ownerNonce:randomBytes(24).toString('hex'),family:SKB_ARTIFACT_FAMILY,purpose:'fixed10-UF20-resume-unstarted'});
  durableJpgJson(path,owned);let released=false;const registrations:Pin[]=[];
  const assertOwned=()=>demand(!released&&same(JSON.parse(readFileSync(path,'utf8')),owned),'skb_fast_owner_changed');
  const proofPin=durableJpgJson(join(r.output,'skb-admission.json'),{protocol:'paid-resource-admission-v2',family:SKB_ARTIFACT_FAMILY,runId:r.runId,owned,
    selectedNewEnvelopeNanoCny:'100000000000000000',carryNanoCny:'8392180000',carry:carry.carry,sourcePins:r.sourcePins,
    balanceOverride:{authorized:true,balanceIsPrecondition:false,reserveCny:'0',userInstruction:'直接试跑 忽略余额；尽快初版，并发可以开大，不需要在意API用量'},
    apiUsageLimitRemoved:true,priorFeeCapRemoved:true,internalNonbindingFiniteSentinel:true,formalFinancialCertificate:false});
  const registry=join(r.output,'skb-fast-paid-resource-run.json');
  durableJpgJson(registry,{protocol:'skillsbench-fast-paid-resource-run-v5',family:SKB_ARTIFACT_FAMILY,runId:r.runId,admissionPin:proofPin,released:false,formalFinancialCertificate:false});
  return {protocol:'paid-resource-admission-v2',root,runId:r.runId,path,proofPin,owned,clock:REAL_CLOCK,scope:'production',sourcePins:r.sourcePins,
    envelopeNanoCny:100000000000000000n,balanceNanoCny:0n,headroomNanoCny:0n,carryNanoCny:8392180000n,carry:carry.carry,assertOwned,
    validateForwardSource(){assertOwned();for(const p of r.forwardSourcePins)verifyPin(p);},
    registerCash(p:Pin){assertOwned();const c=jsonPin(p);demand(c.ownerNonce===owned.ownerNonce&&same(c.admissionPin,proofPin),'skb_fast_cash_owner');},
    registerOwnedProcess(p:Pin){assertOwned();registrations.push(p);},
    async release(){throw Error('Fast first delivery cannot issue a full financial certificate');},
    finishLightweight(v:any){assertOwned();demand(v.ownedGenerationClosed===true&&v.pendingRequests===0,'skb_fast_actual_owned_generation_not_closed');
      const close=durableJpgJson(join(r.output,'fast-owned-release.json'),{protocol:'skillsbench-fast-owned-lock-release-v5',family:SKB_ARTIFACT_FAMILY,runId:r.runId,owned,
        ...v,registrationPins:registrations,originalUnknownSettled:false,formalFinancialCertificate:false,fullEnvironmentCertificationPending:true,observedAtUtc:new Date().toISOString()});
      assertOwned();unlinkSync(path);released=true;
      durableJpgJson(registry,{protocol:'skillsbench-fast-paid-resource-run-v5',family:SKB_ARTIFACT_FAMILY,runId:r.runId,admissionPin:proofPin,released:true,releasePin:close,
        formalFinancialCertificate:false,originalUnknownSettled:false},true);
    }};
}
