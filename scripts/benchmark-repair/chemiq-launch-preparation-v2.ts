/** Metadata-only launcher preparation from an actual prior observation; acquisition re-audits it. */
import { join, resolve } from 'node:path';
import { actualPin, cny, demand, jsonPin, nanoCny } from './paid-resource-proof-v2.ts';
import { CHEMIQ_F_ROOT as ROOT } from './chemiq-f-journal-contract-v2.ts';
import { prepareChemiqF } from './chemiq-f-journal-campaign-v2.ts';
import { chemiqCashEnvelope, durableChemiqJson } from './chemiq-f-paid-admission-v2.ts';
import { discoverChemiqOtherPaidEvidence } from './chemiq-other-paid-discovery-v2.ts';
const [gatePath,balancePath,pricePath,modelPath,priorPath]=process.argv.slice(2);
demand(gatePath&&balancePath&&pricePath&&modelPath&&priorPath,'chemiq_explicit_launch_materials');
const runtimeGate=actualPin(resolve(gatePath)),gate=jsonPin(runtimeGate),balance=actualPin(resolve(balancePath)),prices=actualPin(resolve(pricePath)),
  modelAvailability=actualPin(resolve(modelPath)),priorPin=actualPin(resolve(priorPath)),observed=jsonPin(priorPin),bal=jsonPin(balance);
demand(observed.protocol==='chemiq-resource-financial-preflight-v2'&&observed.modelCalls===0&&Number.isFinite(observed.financial.prior),'chemiq_preparation_actual_prior_observation');
const template=jsonPin(actualPin(join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-implementation-v1/resource-seed-template.json')));
const rows=bal.balances.filter((r:any)=>r.currency==='CNY');demand(rows.length===1,'chemiq_launch_balance_currency');
const requested=cny(nanoCny(rows[0].total_balance)-8392180000n);chemiqCashEnvelope(bal,requested,'0');
const discovery=discoverChemiqOtherPaidEvidence(ROOT),directive=actualPin(join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-implementation-v2/user-resource-directive.json'));
const prepared=prepareChemiqF('pilot16',gate.runId,{workers:4,headroomCny:'0',balance,prices,modelAvailability,runtimeGate,requestedNewEnvelopeCny:requested,
  capUsd:observed.financial.prior+20,priorCampaignCostUpperBoundUsd:observed.financial.prior,financialBoundary:template.financialBoundary,jpgDScanner:template.jpgDScanner,userResourceDirective:directive});
const explanation=durableChemiqJson(join(resolve(prepared.recipePin.path,'..'),'resource-preparation-basis.json'),{
  protocol:'chemiq-pilot-launch-resource-preparation-v2',modelCalls:0,paidLockTaken:false,priorObservationPin:priorPin,
  acquisitionMustRepeatFullFinancialPreflight:true,priorNotAnInvoice:true,foreignExchangeConversion:false,otherFamilyDiscovery:discovery,
  envelopeCny:requested,operatorHeadroomCny:'0',originalUnknownCny:'8.39218',sourcePin:actualPin(import.meta.path)});
console.log(JSON.stringify({...prepared,resourcePreparationBasisPin:explanation,requestedNewEnvelopeCny:requested,paidLockTaken:false}));
