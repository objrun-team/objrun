import {readFileSync,existsSync,renameSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {actualPin,hash} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import {inspectFullFClosedCash} from '../shared/digitalocean-closed-run-cost.ts';
const root=resolve(import.meta.dir,'../../../..'),out=join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq'),source=join(import.meta.dir,'run.ts'),pending=source+'.pending';
if(!existsSync(pending))process.exit(0);
const active=JSON.parse(readFileSync(join(out,'active-run.json'),'utf8'));
try{process.kill(active.pid,0);throw Error('Refuse source replacement while runner alive');}catch(error){if(error.code!=='ESRCH')throw error;}
const state=JSON.parse(readFileSync(join(active.output,'journal/api-state.json'),'utf8'));
if(state.acceptedRequestCount!==state.finishedRequestCount||state.reservedUpperBoundUsd!==0)throw Error('Journal not drained');
const lane=JSON.parse(readFileSync(join(active.output,'lane-close.json'),'utf8'));if(!lane.closed)throw Error('Lane not closed');
const cash=inspectFullFClosedCash(root,actualPin(join(active.output,'journal/currency/cash-close.json')));
const prepared=JSON.parse(readFileSync(join(out,'pending-recovery-scheduler.json'),'utf8'));
if(hash(readFileSync(source))!==prepared.originalSha256||hash(readFileSync(pending))!==prepared.sha256)throw Error('Prepared source changed');
new Bun.Transpiler({loader:'ts'}).transformSync(readFileSync(pending,'utf8'));
for(const file of prepared.additionalFiles??[]){if(hash(readFileSync(join(root,file.path)))!==file.originalSha256||hash(readFileSync(join(root,file.pending)))!==file.sha256)throw Error('Additional prepared source changed');new Bun.Transpiler({loader:'ts'}).transformSync(readFileSync(join(root,file.pending),'utf8'));}
for(const file of prepared.additionalFiles??[])renameSync(join(root,file.pending),join(root,file.path));
renameSync(pending,source);
writeFileSync(join(out,'recovery-scheduler-installed.json'),JSON.stringify({protocol:'chemiq-safe-boundary-source-install-v1',atUtc:new Date().toISOString(),previousRunId:active.runId,previousPid:active.pid,journalDrained:true,laneClosed:true,cashAccountingClosed:cash.accountingClosed,unknownCostsRetained:cash.unknownCostCount,sourceSha256:actualPin(source).sha256,prepared,modelCalls:0},null,2)+'\n');
console.log('Recovery order installed at drained closed boundary');
