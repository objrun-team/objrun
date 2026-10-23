import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { OUT, ROOT, save, makePlan } from './prepare.ts';
const json=(p:string)=>JSON.parse(readFileSync(p,'utf8'));
const manifest=json(join(OUT,'manifest.json')),plan=makePlan(manifest.campaign);
if(manifest.taskScheduleSha256!==plan.taskScheduleSha256||manifest.plannedTaskRuns!==500)throw Error('Frozen denominator/schedule changed');
const live=await (await fetch('http://127.0.0.1:17906/problems?n=500&seed=0',{signal:AbortSignal.timeout(120000)})).json() as any[];
const {digest,scientificPrompt}=await import('../../../benchmark-repair/scientific-journal-plan.ts');
if(live.length!==500||live.some(r=>!plan.catalogs.chembench.some(t=>t.officialId===r.id&&t.promptSha256===digest(scientificPrompt('chembench',r)))))throw Error('Live catalog mismatch');
const control=json(join(ROOT,'docs/repair-2026-10-10/full-f-rerun/control.json'));
const status=json(join(OUT,'status.json'));
const report={all500IdsAndPromptsVerified:true,officialControlsAll500Passed:json(join(OUT,'official-controls.json')).allPassed===true,
  officialGraderHealth:await(await fetch('http://127.0.0.1:17906/health')).json(),paidReady:control.paidReady,
  runnerReceipt:existsSync(join(OUT,'runner-process.json'))?json(join(OUT,'runner-process.json')):null,status,modelCallsByCheck:0,updatedAt:new Date().toISOString()};
save('local-validation.json',report);console.log(JSON.stringify({planned:500,liveCatalogValid:true,officialControlsPassed:report.officialControlsAll500Passed,paidReady:report.paidReady,stage:status.stage}));
