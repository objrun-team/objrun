import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { OUT, ROOT, makePlan, save } from './prepare.ts';
import { inspectAnyClosedCash as inspectFullFClosedCash } from './accounting.ts';
import { inspectAnyJournal as inspectCampaignJournal } from './accounting.ts';
import { actualPin } from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import { verifyBenchmarkCashClosure } from '../../../benchmark-repair/benchmark-usd-cash.ts';
import { digest } from '../../../benchmark-repair/scientific-journal-plan.ts';
const json=(p:string)=>JSON.parse(readFileSync(p,'utf8'));
const manifest=json(join(OUT,'manifest.json')),plan=makePlan(manifest.campaign);
const resultsDir=join(OUT,'results');
const records=existsSync(resultsDir)?readdirSync(resultsDir).filter(n=>/^task-\d+\.json$/.test(n)).map(n=>json(join(resultsDir,n))):[];
const idValid=records.every(r=>plan.tasks[r.index]?.officialId===r.officialId&&plan.tasks[r.index]?.promptSha256===r.promptSha256&&r.arm==='F'&&(!r.candidateSha256||digest(r.answer??'')===r.candidateSha256))&&new Set(records.map(r=>r.index)).size===records.length;
const runs=existsSync(join(OUT,'runs'))?readdirSync(join(OUT,'runs')).map(n=>join(OUT,'runs',n)):[];
const finances=runs.filter(p=>existsSync(join(p,'journal/journal-config.json'))).map(p=>{const journal=inspectCampaignJournal(join(p,'journal'));const pin=actualPin(join(p,'currency/cash-close.json'));const cash=inspectFullFClosedCash(ROOT,pin);return {run:p,journalValid:journal.valid,accountingClosed:cash.accountingClosed,cashReleasePermitted:cash.financiallyResolved,billedUsd:cash.billedUsd,unknownReservationUsd:cash.unknownReservationUsd,unknownCostCount:cash.unknownCostCount,originalReleasePermitted:cash.originalReleasePermitted,calls:journal.snapshot?.acceptedRequestCount,knownCostMatches:cash.financiallyResolved};});
const financeClosed=finances.every(f=>f.journalValid&&f.accountingClosed&&f.cashReleasePermitted&&f.knownCostMatches);
const graded=records.filter(r=>r.acceptance?.valid===true).length,passed=records.filter(r=>r.acceptance?.passed===true).length;
const result={protocol:'chembench-full-f-audit-v1',denominator:500,recorded:records.length,graded,passed,score:passed/500,
  fullIdIntegrity:idValid,financeClosed,finances,actualCostUsd:finances.reduce((n,f)=>n+f.billedUsd,0),modelCalls:finances.reduce((n,f)=>n+(f.calls??0),0),
  terminalProtocolFailures:records.filter(r=>r.terminalProtocolFailure).length,terminalTimeoutFailures:records.filter(r=>r.terminalTimeoutFailure).length,
  unknownReservationUsd:finances.reduce((n,f)=>n+f.unknownReservationUsd,0),unknownCostCount:finances.reduce((n,f)=>n+f.unknownCostCount,0),
  complete:records.length===500&&graded===500&&idValid&&financeClosed,failures:records.filter(r=>!r.acceptance?.valid).map(r=>({index:r.index,officialId:r.officialId,outcome:r.acceptance?.outcome})),
  missing:plan.tasks.filter(t=>!records.some(r=>r.index===t.index)).map(t=>t.officialId),updatedAt:new Date().toISOString()};
save('audit.json',result);
writeFileSync(join(OUT,'report.md'),`# ChemBench full F\n\nStage: ${result.complete?'complete':'incomplete'}. Official denominator: 500; recorded ${records.length}; graded ${graded}; passed ${passed}; all-denominator score ${passed}/500 (${(passed/5).toFixed(2)}%).\n\nUSD cost: $${result.actualCostUsd.toFixed(9)}; model calls ${result.modelCalls}; financial closure ${financeClosed}. No U calls. Public U references and protocol differences: public-u.json.\n\nOfficial grader commit ${plan.datasets.chembench.source.commit}; dataset ${plan.datasets.chembench.source.datasetRevision}. This is the entire existing 500-task pinned cohort, not the upstream 2785-task corpus. Failures and missing tasks remain in the denominator. See audit.json and per-run journal/cash for receipts.\n`);
console.log(JSON.stringify({...result,finances:undefined,missing:undefined,failures:undefined}));
