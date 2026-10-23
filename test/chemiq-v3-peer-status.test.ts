import { expect, test } from 'bun:test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { discoverChemiqOtherPaidEvidence } from '../scripts/repair-2026-10-08/chemiq-other-paid-discovery-v3.ts';
const area=join(process.cwd(),'.scratch','chemiq-v3','peer-status-'+crypto.randomUUID());mkdirSync(area,{recursive:true});
function fixture(name:string,options:{live?:'missing'|'outside'|'registered';family?:string;skbCalls?:number;tbCalls?:number;outsideRegistry?:boolean}={}){
  const root=join(area,name),status=join(root,'docs/repair-2026-10-08/parallel-bench-handoff-2026-10-09'),home=join(root,'docs/repair-2026-10-09/tb12-runs-v1');mkdirSync(status,{recursive:true});mkdirSync(home,{recursive:true});
  const write=(path:string,value:any)=>{mkdirSync(join(path,'..'),{recursive:true});writeFileSync(path,JSON.stringify(value));};
  const old='repair-2026-10-09T00-00-00Z',current='repair-2026-10-09T01-00-00Z';
  write(join(home,old,'tb12-paid-resource-run.json'),{protocol:'tb12-paid-resource-run-v1',family:'terminal-bench-twelve-journal-v1',runId:old,released:true});
  const live=options.live==='outside'?join(root,'other-family',current):join(home,current);
  if(options.live==='registered')write(join(live,'tb12-paid-resource-run.json'),{protocol:'tb12-paid-resource-run-v1',family:options.family??'terminal-bench-twelve-journal-v1',runId:current,released:false});
  if(options.outsideRegistry)write(join(root,'docs/repair-2026-10-08/uncovered-tb-home',old,'tb12-paid-resource-run.json'),{protocol:'tb12-paid-resource-run-v1',family:'terminal-bench-twelve-journal-v1',runId:old,released:false});
  write(join(status,'terminal-bench-status.json'),{newProjectLlmRequests:options.tbCalls??3,liveRealRun:live});write(join(status,'skillsbench-status.json'),{realModelCalls:options.skbCalls??0});return root;
}
test('an old zero-forward registry cannot hide positive unregistered or different-family activity',()=>{
  expect(()=>discoverChemiqOtherPaidEvidence(fixture('missing'))).toThrow('chemiq_tb12_positive_status_unregistered_run');
  expect(()=>discoverChemiqOtherPaidEvidence(fixture('outside',{live:'outside'}))).toThrow('chemiq_tb12_positive_status_run_scope');
  expect(()=>discoverChemiqOtherPaidEvidence(fixture('family',{live:'registered',family:'uncovered-family'}))).toThrow('chemiq_tb12_discovery_namespace');
});
test('the exact registered TB12 status produces a pinned binding for the closed-only financial scanner',()=>{
  const r=discoverChemiqOtherPaidEvidence(fixture('covered',{live:'registered'}));expect(r.statuses[0].coveredRegistryPin).toBeDefined();expect(r.statuses[0].modelCalls).toBe(3);
  expect(r.registries.find(x=>x.path===r.statuses[0].coveredRegistryPin!.path)?.released).toBe(false);
});
test('registered TB12 evidence does not waive an uncovered paid SkillsBench counter',()=>{
  expect(()=>discoverChemiqOtherPaidEvidence(fixture('skb',{live:'registered',skbCalls:1}))).toThrow('chemiq_other_new_paid_family_requires_reviewed_scanner');
});
test('all TB12 registries must be inside the audited namespace even for zero or otherwise valid latest counters',()=>{
  expect(()=>discoverChemiqOtherPaidEvidence(fixture('outside-zero',{live:'registered',tbCalls:0,outsideRegistry:true}))).toThrow('chemiq_tb12_discovery_namespace');
  expect(()=>discoverChemiqOtherPaidEvidence(fixture('outside-old',{live:'registered',outsideRegistry:true}))).toThrow('chemiq_tb12_discovery_namespace');
});
console.log('CHEMIQ_V3_PEER_STATUS_FIXTURE_ROOT='+area);
