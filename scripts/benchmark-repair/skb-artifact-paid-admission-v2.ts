/** Own SkillsBench admission; latest human instruction overrides only balance/reserve. */
import { randomBytes } from 'node:crypto';
import { existsSync,readFileSync,readdirSync,lstatSync,unlinkSync } from 'node:fs';
import { join,resolve } from 'node:path';
import { scanOtherPaidRuns,type AdmissionLease } from './paid-resource-admission-v2.ts';
import { actualJpgPriorUsd,jpgCarry,scanJpgPaidRuns,durableJpgJson } from './jpg-paid-resource-admission-v1.ts';
import { scanJpgDRegistries } from './jpg-D-paid-resource-admission-v1.ts';
import { scanChemiqFPaidRuns as scanChemiqV1 } from './chemiq-f-paid-admission-v1.ts';
import { scanChemiqV2RecoveredPaidRuns as scanChemiqV2 } from './chemiq-v2-recovered-scanner-v3.ts';
import { scanChemiqFPaidRuns as scanChemiqV3 } from './chemiq-f-paid-admission-v3.ts';
import { ACTUAL_FINANCIAL_INTERRUPTED_BOUNDARY,FINANCIAL_KNOWN_USD,verifyFinancialInterruptedBoundary } from './financial-interruption-closure-v1.ts';
import { FINANCIAL_RUN } from './financial-interruption-release.ts';
import { actualPin,demand,jsonPin,nanoCny,REAL_CLOCK,same,validatePrices,verifyPin,type Pin } from './paid-resource-proof-v2.ts';
import { verifyCashClosure } from './cny-cash-shadow-v2.ts';
import { SKB_ARTIFACT_FAMILY } from './skb-artifact-journal-contract-v2.ts';
import { SKB_ROOT,validateSkbRecipe,type SkbRecipe } from './skb-artifact-recipe-v2.ts';
import { scanTb12ClosedPaidRuns } from './skb-tb12-closed-scan-v2.ts';

export const SKB_REGISTRY='skillsbench-ten-paid-resource-run-v2';
export async function skbFinancialPreflight(currentRun:string){
  const fixed=await verifyFinancialInterruptedBoundary(ACTUAL_FINANCIAL_INTERRUPTED_BOUNDARY);
  scanOtherPaidRuns(SKB_ROOT,FINANCIAL_RUN);scanJpgPaidRuns(SKB_ROOT,currentRun);
  const jpgD=scanJpgDRegistries(SKB_ROOT,currentRun),chemiqV1=await scanChemiqV1(SKB_ROOT,currentRun),chemiqV2=await scanChemiqV2(SKB_ROOT,currentRun),chemiqV3=await scanChemiqV3(SKB_ROOT,currentRun);
  const tb12=await scanTb12ClosedPaidRuns(SKB_ROOT,currentRun);
  const supported=new Set(['paid-resource-v2-run','jpg-paid-resource-run-v1','jpg-D-paid-resource-run-v1','chemiq-f-paid-resource-run-v1','chemiq-f-paid-resource-run-v2','chemiq-f-paid-resource-run-v3','tb12-paid-resource-run-v1',SKB_REGISTRY]);
  const discoveryPins:Pin[]=[];let dirs=0;
  const visit=(dir:string)=>{demand(!lstatSync(dir).isSymbolicLink()&&++dirs<100000,'skb_discovery_identity');for(const e of readdirSync(dir,{withFileTypes:true})){
    const path=join(dir,e.name);demand(!e.isSymbolicLink(),'skb_discovery_reparse');if(e.isDirectory()){visit(path);continue;}
    if(e.isFile()&&/(?:paid.*(?:resource.*run|registry)|campaign.*registry)\.json$/.test(e.name)){const p=actualPin(path),row=jsonPin(p);demand(supported.has(row.protocol),'skb_unknown_paid_family');discoveryPins.push(p);}
  }};
  for(const name of ['docs/repair-2026-10-08','docs/repair-2026-10-09'])if(existsSync(join(SKB_ROOT,name)))visit(join(SKB_ROOT,name));
  const own=await scanSkbPaidRuns(currentRun),base=actualJpgPriorUsd(SKB_ROOT);
  const chemiqRunIds=[...chemiqV1.closedRunIds,...chemiqV2.closedRunIds,...chemiqV3.closedRunIds];demand(new Set(chemiqRunIds).size===chemiqRunIds.length,'skb_cross_version_duplicate_cost');
  demand(!existsSync(join(SKB_ROOT,'docs/repair-2026-10-08/campaigns',FINANCIAL_RUN,'api-ledger.json')),'skb_historical_double_count');
  return {fixed,base,jpgD,chemiqV1,chemiqV2,chemiqV3,tb12,own,discoveryPins,prior:base+FINANCIAL_KNOWN_USD+jpgD.closedRecordedCostUpperBoundUsd+chemiqV1.closedRecordedCostUpperBoundUsd+chemiqV2.closedRecordedCostUpperBoundUsd+chemiqV3.closedRecordedCostUpperBoundUsd+tb12.closedRecordedCostUpperBoundUsd+own.closedRecordedCostUpperBoundUsd};
}
export async function verifySkbCertificate(pin:Pin,runId:string){
  const c=jsonPin(pin);demand(c.protocol==='skillsbench-ten-close-certificate-v2'&&c.family===SKB_ARTIFACT_FAMILY&&c.runId===runId&&['score','financial-abort','local-mock'].includes(c.kind),'skb_certificate_type');
  const {auditSkbCampaign}=await import('./audit-skb-artifact-journal-v2.ts');const replay=await auditSkbCampaign(c.recipePin,c.kind);
  demand(replay.financialClosed===true&&replay.integrityValid===true&&same(jsonPin(c.auditorPin),replay),'skb_independent_certificate_graph');
  return {certificate:c,replay};
}
export async function scanSkbPaidRuns(currentRun:string){
  const home=join(SKB_ROOT,'docs/repair-2026-10-08/skb-ten-paid-discovery-v2');let total=0;const inputPins:Pin[]=[];
  if(existsSync(home))for(const name of readdirSync(home)){
    const pointer=actualPin(join(home,name,'discovery.json')),d=jsonPin(pointer);if(d.runId===currentRun)continue;
    const p=jsonPin(d.registryPin);demand(p.protocol===SKB_REGISTRY&&p.family===SKB_ARTIFACT_FAMILY&&p.released===true&&p.certificationPin&&p.releaseCommittedPin,'skb_previous_unclosed');
    const graph=await verifySkbCertificate(p.certificationPin,p.runId),ack=jsonPin(p.releaseCommittedPin),ad=jsonPin(p.admissionPin);
    demand(ack.released===true&&ack.ownerNonce===ad.owned.ownerNonce&&same(ack.authorizationPin,p.releasePin),'skb_previous_release_ack');
    total+=graph.replay.recordedUsageUpperBoundUsd;inputPins.push(pointer,d.registryPin,p.certificationPin,p.releaseCommittedPin,p.releasePin);
  }
  return {family:SKB_ARTIFACT_FAMILY,closedRecordedCostUpperBoundUsd:total,inputPins};
}
export async function acquireSkbPaidResource(r:SkbRecipe):Promise<AdmissionLease>{
  validateSkbRecipe(r,true);
  const path=join(SKB_ROOT,'.phase1-data/owned-paid-campaign.lock.json');demand(!existsSync(path),'skb_shared_paid_owner_busy');
  const carry=jpgCarry(r as never),prices=validatePrices(r.prices),b=jsonPin(r.balance);
  const available=nanoCny(b.balances.find((x:any)=>x.currency==='CNY').total_balance),envelope=nanoCny(r.requestedNewEnvelopeCny);
  demand(Date.now()-Date.parse(prices.observedAtUtc)>=0&&Date.now()-Date.parse(prices.observedAtUtc)<=86400000,'skb_price_expired');
  const preflight=await skbFinancialPreflight(r.runId);demand(preflight.prior===r.priorCampaignCostUpperBoundUsd,'skb_prior_changed');
  demand(!existsSync(join(r.output,'skb-admission.json')),'skb_admission_fresh');
  const owned=Object.freeze({pid:process.pid,startedAt:new Date().toISOString(),runId:r.runId,entry:join(import.meta.dir,'skb-artifact-journal-campaign-v2.ts'),ownerNonce:randomBytes(24).toString('hex'),family:SKB_ARTIFACT_FAMILY,purpose:'ten-paired-UF'});
  durableJpgJson(path,owned);let released=false,cashPin:Pin|undefined;const registered:Pin[]=[];
  const assertOwned=()=>demand(!released&&same(JSON.parse(readFileSync(path,'utf8')),owned),'skb_owner_changed');
  const proofPin=durableJpgJson(join(r.output,'skb-admission.json'),{protocol:'paid-resource-admission-v2',family:SKB_ARTIFACT_FAMILY,runId:r.runId,scope:'production',owned,recipe:r,sourcePins:r.sourcePins,
    originalCriticalPins:carry.critical,carry:carry.carry,carryNanoCny:'8392180000',balanceNanoCny:available.toString(),headroomNanoCny:'0',selectedNewEnvelopeNanoCny:envelope.toString(),
    balanceOverride:r.balanceOverride,balancePin:r.balance,pricePin:r.prices,priorDecomposition:preflight,createdAtUtc:new Date().toISOString(),invoice:false,foreignExchangeConversion:false});
  const registry=join(r.output,'skb-paid-resource-run.json'),pointer=join(SKB_ROOT,'docs/repair-2026-10-08/skb-ten-paid-discovery-v2',r.runId,'discovery.json');
  const saveRegistry=(value:any,replace=false)=>{const p=durableJpgJson(registry,value,replace);durableJpgJson(pointer,{protocol:'skillsbench-ten-paid-discovery-v2',family:SKB_ARTIFACT_FAMILY,runId:r.runId,registryPin:p,storageDescriptorPin:r.storageDescriptorPin},existsSync(pointer));};
  saveRegistry({protocol:SKB_REGISTRY,family:SKB_ARTIFACT_FAMILY,runId:r.runId,providerKind:'real-provider',admissionPin:proofPin,released:false,certificationPin:null});
  const validateForwardSource=()=>{assertOwned();for(const p of [...r.sourcePins,r.freezePin,r.prices])verifyPin(p,undefined,512*1024**2);const t=Date.parse(prices.observedAtUtc);demand(Date.now()>=t&&Date.now()-t<=86400000,'skb_price_expired');};
  return Object.freeze({protocol:'paid-resource-admission-v2' as const,root:SKB_ROOT,runId:r.runId,path,proofPin,owned,clock:REAL_CLOCK,scope:'production' as const,sourcePins:r.sourcePins,
    envelopeNanoCny:envelope,balanceNanoCny:available,headroomNanoCny:0n,carryNanoCny:8392180000n,carry:carry.carry,assertOwned,validateForwardSource,
    registerCash(p:Pin){assertOwned();const c=jsonPin(p);demand(!cashPin&&c.ownerNonce===owned.ownerNonce&&same(c.admissionPin,proofPin)&&c.envelopeNanoCny===envelope.toString()&&c.carryNanoCny==='8392180000','skb_cash_registration');cashPin=p;},
    registerOwnedProcess(p:Pin){assertOwned();const v=jsonPin(p);demand(v.protocol==='paid-owned-process-v2'&&v.family===SKB_ARTIFACT_FAMILY&&v.runId===r.runId&&v.ownerNonce===owned.ownerNonce&&v.pid>0&&v.pid!==process.pid&&!registered.some(q=>same(q,p)),'skb_process_registration');registered.push(p);},
    async release(proof:any){assertOwned();validateForwardSource();for(const p of carry.critical)verifyPin(p,undefined,512*1024**2);demand(cashPin,'skb_cash_missing');
      const {certificate:c,replay}=await verifySkbCertificate(proof.certification,r.runId);
      demand(same(c.sourcePin,proof.sourceClosed)&&same(c.ownedPin,proof.ownedClosed)&&same(c.cashPin,proof.cashClosed)&&same(c.rawPin,proof.rawClosed)
        &&same(jsonPin(c.ownedPin).registrationPins,registered)&&same(verifyCashClosure(c.cashPin).config.admissionPin,proofPin),'skb_release_exact_graph');
      demand(Date.now()-Date.parse(c.createdAtUtc)<=60000&&replay.financialClosed,'skb_fresh_release_certificate');
      const releasePin=durableJpgJson(join(r.output,'skb-financial-release.json'),{protocol:'skillsbench-ten-financial-release-v2',family:SKB_ARTIFACT_FAMILY,runId:r.runId,ownerNonce:owned.ownerNonce,certificationPin:proof.certification,originalUnknownSettled:false,carriedOriginalUnknownNanoCny:'8392180000',authorizedAtUtc:new Date().toISOString()});
      assertOwned();unlinkSync(path);released=true;
      const ack=durableJpgJson(join(r.output,'skb-lock-release-committed.json'),{protocol:'skillsbench-ten-lock-release-committed-v2',family:SKB_ARTIFACT_FAMILY,runId:r.runId,ownerNonce:owned.ownerNonce,authorizationPin:releasePin,released:true,committedAtUtc:new Date().toISOString()});
      saveRegistry({protocol:SKB_REGISTRY,family:SKB_ARTIFACT_FAMILY,runId:r.runId,providerKind:'real-provider',admissionPin:proofPin,released:true,certificationPin:proof.certification,releasePin,releaseCommittedPin:ack},true);
    }});
}
