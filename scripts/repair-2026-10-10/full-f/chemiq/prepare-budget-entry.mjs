import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';
const here=import.meta.dirname,root=path.resolve(here,'../../../..'),base=path.join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq');
let stage=fs.readFileSync(path.join(here,'stage-budget-handoff.mjs'),'utf8');
stage=stage.replaceAll('budget-handoff-staging','budget-handoff-entry-staging').replaceAll('budget-handoff-control-machine.mjs','budget-handoff-entry-machine.mjs').replaceAll('task39-budget-handoff-staged.json','task39-budget-handoff-entry-build.json');
const start=stage.indexOf("const candidate="),end=stage.indexOf('\nconst candidatePath=',start);assert(start>0&&end>start);
stage=stage.slice(0,start)+`const candidate='import {budgetBoundary} from '+JSON.stringify(path.join(import.meta.dirname,'budget-handoff-boundary-trace.mjs'))+';\\n'+original.replace(anchor,'const budgetSubmit = budgetBoundary(a.task, r.kind, handedIn, spoke, a.unit, a.cycle.cycle);\\n      '+anchor+'\\n      if (budgetSubmit) return toSubmit;');`+stage.slice(end);
stage=stage.replace('current.transformed],files=',"current.transformed,actualPin(path.join(import.meta.dirname,'budget-handoff-boundary-trace.mjs'))],files=");
fs.writeFileSync(path.join(here,'stage-budget-handoff-entry.mjs'),stage);
let control=fs.readFileSync(path.join(here,'task39-budget-sdk-control.mjs'),'utf8').replaceAll('budget-handoff-control-machine.mjs','budget-handoff-entry-machine.mjs').replaceAll("'-budget-'","'-budget-entry-'").replaceAll('task39-budget-sdk-','task39-budget-entry-sdk-');
control=control.replace('proof.sourcePins=[',"if(engine){const tracePath=path.join(dir,'engine','budget-handoff-boundaries.jsonl');if(fs.existsSync(tracePath)){proof.boundaryTracePin=actualPin(tracePath);proof.boundaries=fs.readFileSync(tracePath,'utf8').trim().split(/\\r?\\n/).filter(Boolean).map(JSON.parse);if(mode==='green')assert(proof.boundaries.some(b=>b.applied&&b.remainingSeconds>0&&b.remainingSeconds<=225));}}\n proof.sourcePins=[");
fs.writeFileSync(path.join(here,'task39-budget-entry-sdk-control.mjs'),control);
let runner=fs.readFileSync(path.join(here,'run-task39-supplier.ts'),'utf8').replace("from './native-machine.ts'","from './budget-handoff-entry-machine.mjs'");
runner=runner.replace('export async function run(){',`export async function run(){
  if(SUPPLIER!=='relace')throw Error('Budget variant only Relace scope');
  const review=JSON.parse(readFileSync(join(OUT,'task39-budget-entry-root-approval.json'),'utf8'));
  if(review.approved!==true||review.onlyIndex!==39||review.retainedValid!==815)throw Error('Await root concrete entry review');
  for(const pin of review.sourcePins)verifyPin(pin);
  const once=join(OUT,'task39-budget-entry-launch-issued.json');
  writeFileSync(once,JSON.stringify({atUtc:utc(),pid:process.pid,approvalPin:actualPin(join(OUT,'task39-budget-entry-root-approval.json'))}),{flag:'wx'});`);
runner=runner.replace('const runManifest={',`const privateBudget=JSON.parse(readFileSync(join(OUT,'task39-budget-handoff-entry-build.json'),'utf8'));
  sourcePins.push(...privateBudget.sourcePins,...privateBudget.files,actualPin(privateBudget.proofPath),actualPin(privateBudget.machinePath),actualPin(join(OUT,'task39-budget-handoff-entry-build.json')),...review.sourcePins);
  for(const pin of sourcePins)verifyPin(pin);
  const runManifest={schedulingVariant:{name:'native prompt boundary <=225s budget submit',traceFile:'engine/budget-handoff-boundaries.jsonl',genericContinuationHint:false,idleTimeoutModified:false,paidOutcomeProven:false},`);
runner=runner.replace("const candidate=finalCandidate(","const boundaryPath=join(directory,'budget-handoff-boundaries.jsonl');if(existsSync(boundaryPath))writeFileSync(join(out,'budget-handoff-boundaries.jsonl'),readFileSync(boundaryPath));\n    const candidate=finalCandidate(");
fs.writeFileSync(path.join(here,'run-task39-budget-relace.ts'),runner);
console.log(JSON.stringify({staged:true,paidStarted:false}));

