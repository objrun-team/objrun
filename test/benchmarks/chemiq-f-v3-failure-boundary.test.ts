import { expect, test } from 'bun:test';
import { closeSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createCampaignJournal, inspectCampaignJournal } from '../../scripts/benchmark-repair/campaign-journal.ts';
import { createCnyCashShadow, verifyCashClosure } from '../../scripts/benchmark-repair/cny-cash-shadow-v2.ts';
import { actualPin, hash } from '../../scripts/benchmark-repair/paid-resource-proof-v2.ts';
import { createChemiqModelWitness } from '../../scripts/benchmark-repair/chemiq-f-model-witness-v3.ts';
import { ChemiqRouteSeal } from '../../scripts/benchmark-repair/chemiq-f-journal-contract-v3.ts';

const root=process.cwd(), area=join(root,'.scratch','chemiq-v3','failure-regression-'+crypto.randomUUID());
mkdirSync(area,{recursive:true});
const raw=JSON.stringify({model:'deepseek-flash',temperature:0,seed:42,reasoning_effort:'none',max_tokens:8192,messages:[{role:'user',content:'Local failure boundary fixture'}]});
function fixture(name:string,beforeAdmission:()=>void,hooks?:any){
  const directory=join(area,name);mkdirSync(directory);
  const runId='repair-'+new Date().toISOString().replace(/[:.]/g,'-');
  const journal=createCampaignJournal({directory:join(directory,'journal'),campaign:runId,capUsd:100,priorCampaignCostUpperBoundUsd:0},hooks);
  const pricePath=join(directory,'fixture-prices.json');writeFileSync(pricePath,JSON.stringify({protocol:'deepseek-cny-pricing-source-snapshot-v1',observedAtUtc:new Date().toISOString(),currency:'CNY',model:'deepseek-flash',modelCalls:0,officialSource:'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',peak:{uncachedInput:2,cachedInput:.04,output:8},offPeak:{uncachedInput:1,cachedInput:.02,output:4}}));
  const cash=createCnyCashShadow({directory:join(directory,'cash'),runId,providerKind:'local-mock',prices:actualPin(pricePath),journal:{directory:journal.directory,configPin:actualPin(join(journal.directory,'journal-config.json')),sourcePin:actualPin(join(root,'scripts/benchmark-repair/campaign-journal.ts'))}});
  const seal=new ChemiqRouteSeal();seal.open('fixture',Date.now());let forwarded=0;
  const proxy=createChemiqModelWitness({runId,routes:new Set(['fixture']),failureDirectory:join(directory,'failures'),journal,cash,seal,beforeAdmission,onFinancialStop(){},async transport(){forwarded++;throw Error('Fixture transport must never run');}});
  return {journal,cash,proxy,forwarded:()=>forwarded};
}
test('a guard failure before admission stops work without inventing an unacknowledged cash ticket',async()=>{
  const f=fixture('guard',()=>{throw Error('chemiq_fixture_source_guard');});
  try{
    expect((await f.proxy.handle('fixture',raw)).httpStatus).toBe(503);await f.proxy.drain();
    expect(f.forwarded()).toBe(0);expect(f.proxy.anomalies.length).toBe(1);
    expect(f.cash.snapshot().poisoned).toBe(false);
    expect(f.journal.snapshot().acceptedRequestCount).toBe(0);
    expect(f.proxy.anomalies[0].confirmedNoForward).toBe(true);
    expect(verifyCashClosure(f.cash.close()).proof.releasePermitted).toBe(true);
  }finally{f.journal.close();}
});
test('a partial journal admission remains poisoned and cannot mint financial closure',async()=>{
  let fired=false;
  const f=fixture('partial',()=>{},{before(op:any){if(!fired&&op.kind==='fsync'&&op.stage.startsWith('checkpoint:start:')){fired=true;closeSync(op.fd);}}});
  try{
    expect((await f.proxy.handle('fixture',raw)).httpStatus).toBe(503);await f.proxy.drain();
    expect(f.forwarded()).toBe(0);expect(f.cash.snapshot().poisoned).toBe(true);
    expect(inspectCampaignJournal(f.journal.directory).accountingClosed).toBe(false);
    expect(()=>verifyCashClosure(f.cash.close())).toThrow();
  }finally{f.journal.close();}
});
console.log('CHEMIQ_V3_FAILURE_REGRESSION_ROOT='+area);
