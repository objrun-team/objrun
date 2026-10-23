/** ChemIQ-only resource preparation, never a completion request or paid lock. */
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { actualPin, cny, demand, hash, jsonPin, nanoCny, type Pin } from './paid-resource-proof-v2.ts';
import { CHEMIQ_F_ROOT as ROOT, type ChemiqFRecipe } from './chemiq-f-journal-contract-v3.ts';
import { chemiqFinancialPreflight, durableChemiqJson, chemiqCashEnvelope } from './chemiq-f-paid-admission-v3.ts';
import { prepareChemiqF } from './chemiq-f-journal-campaign-v3.ts';
const HOME=join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-implementation-v3'),DOC=join(ROOT,'docs/repair-2026-10-08');
const utc=()=>new Date().toISOString();
export async function chemiqSeedPreflight(runId='repair-'+utc().replace(/[:.]/g,'-')) {
  const template=jsonPin(actualPin(join(DOC,'chemiq-f-journal-implementation-v1/resource-seed-template.json')));
  const scope={runId,financialBoundary:template.financialBoundary,jpgDScanner:template.jpgDScanner} as ChemiqFRecipe;
  const financial=await chemiqFinancialPreflight(scope);
  const pin=durableChemiqJson(join(HOME,'observations','financial-preflight-'+utc().replace(/[:.]/g,'-')+'.json'),{
    protocol:'chemiq-resource-financial-preflight-v3',family:'chemiq-f-journal-v3',runId,observedAtUtc:utc(),financial,modelCalls:0,paidLockTaken:false,
    originalUnknownNanoCny:'8392180000',operatorHeadroomWaivedForPilot:true,
    scopeLimit:'Known legacy science/JPG/ChemIQ registry accounting only; old TB nginx USD0.019480980 excluded. New TB/SKB real families must supply reviewed scanner bindings before being treated as universal accounting.',
    sourcePin:actualPin(import.meta.path)});
  return {runId,preflightPin:pin,priorCampaignCostUpperBoundUsd:financial.prior,modelCalls:0,paidLockTaken:false};
}
export async function prepareChemiqPaidSeed(gatePath:string,balancePath:string,pricePath:string) {
  const gatePin=actualPin(resolve(gatePath)),gate=jsonPin(gatePin),runId=gate.runId;
  demand(gate.validated===true&&gate.actualHttpRequests===96,'chemiq_seed_cold96_not_complete');
  const prior=await chemiqSeedPreflight(runId),template=jsonPin(actualPin(join(DOC,'chemiq-f-journal-implementation-v1/resource-seed-template.json')));
  const balance=actualPin(resolve(balancePath)),prices=actualPin(resolve(pricePath)),bal=jsonPin(balance),rows=bal.balances.filter((r:any)=>r.currency==='CNY');
  demand(rows.length===1,'chemiq_seed_balance_currency');
  const envelope=nanoCny(rows[0].total_balance)-8392180000n;demand(envelope>0n,'chemiq_seed_actual_cash_absent');
  const seed:Partial<ChemiqFRecipe>={workers:4,headroomCny:'0',balance,prices,runtimeGate:gatePin,requestedNewEnvelopeCny:cny(envelope),
    capUsd:prior.priorCampaignCostUpperBoundUsd+20,priorCampaignCostUpperBoundUsd:prior.priorCampaignCostUpperBoundUsd,
    financialBoundary:template.financialBoundary,jpgDScanner:template.jpgDScanner,
    userResourceDirective:actualPin(join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-implementation-v2/user-resource-directive.json'))};
  chemiqCashEnvelope(bal,seed.requestedNewEnvelopeCny!,'0');
  const seedPin=durableChemiqJson(join(HOME,'observations','paid-seed-'+utc().replace(/[:.]/g,'-')+'.json'),{
    ...seed,preflightPin:prior.preflightPin,modelCalls:0,paidLockTaken:false,rechargePrerequisite:false,
    USDGuardBasis:'An operator reporting guard of 20 new USD units over this exact known prior; not an invoice or CNY exchange-rate conversion.'});
  const prepared=await prepareChemiqF('pilot16',runId,seed);
  return {...prepared,seedPin,headroomCny:'0',requestedNewEnvelopeCny:seed.requestedNewEnvelopeCny,paidLockTaken:false};
}
if(import.meta.main) {
  const [mode='preflight',gate,balance,prices]=process.argv.slice(2);
  if(mode==='preflight')console.log(JSON.stringify(await chemiqSeedPreflight()));
  else if(mode==='prepare') {demand(gate&&balance&&prices,'chemiq_seed_explicit_resources');console.log(JSON.stringify(await prepareChemiqPaidSeed(gate,balance,prices)));}
  else throw Error('Use preflight, or prepare <actual-gate.json> <fresh-balance.json> <fresh-official-price.json>');
}
