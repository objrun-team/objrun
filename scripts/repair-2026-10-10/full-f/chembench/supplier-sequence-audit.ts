import {readFileSync,readdirSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {inspectAnyJournal,inspectAnyClosedCash} from './supplier-accounting.ts';
import {actualPin,verifyPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
const root=resolve(import.meta.dir,'../../../..');
const out=join(root,'docs/repair-2026-10-10/full-f-rerun/chembench');
const read=(p:string)=>JSON.parse(readFileSync(p,'utf8').replace(/^\uFEFF/,''));
export function decision(record:any){
  if(record?.index!==277)throw Error('Missing authentic task277 record');
  if(record.acceptance?.valid===true||record.terminalProtocolFailure===true||record.terminalTimeoutFailure===true)return 'terminal';
  if(record.state==='infrastructure_failure'&&record.acceptance?.outcome==='infrastructure_failure')return 'next_supplier';
  throw Error('Nonterminal state is not a classified infrastructure failure');
}
export function baseline(){
  const paths=readdirSync(join(out,'results')).filter(n=>/^task-\d+\.json$/.test(n));
  const records=paths.map(n=>({path:join(out,'results',n),record:read(join(out,'results',n))}));
  const terminal=records.filter(({record:r})=>r.index!==277&&(r.acceptance?.valid===true||r.terminalProtocolFailure===true||r.terminalTimeoutFailure===true));
  if(terminal.length!==499||new Set(terminal.map(t=>t.record.index)).size!==499)throw Error('Expected unique499 retained terminal records');
  const manifest=read(join(out,'manifest.json'));
  if(manifest.plannedTaskRuns!==500||manifest.taskSchedule.length!==500||new Set(manifest.taskSchedule.map((t:any)=>t.index)).size!==500)throw Error('Frozen500 manifest mismatch');
  return {manifestPin:actualPin(join(out,'manifest.json')),terminalPins:terminal.map(t=>actualPin(t.path))};
}
export function auditRun(runOut:string,slug:string,baselinePath?:string){
  if(resolve(runOut).startsWith(resolve(out,'runs')+'\\')===false)throw Error('Run outside own runs directory');
  const pins=read(join(runOut,'source-pins.json'));for(const pin of pins)verifyPin(pin);
  if(baselinePath){const saved=read(baselinePath);verifyPin(saved.manifestPin);for(const pin of saved.terminalPins)verifyPin(pin);if(saved.terminalPins.length!==499)throw Error('Retention baseline incomplete');}
  if(pins.some((p:any)=>/-authorization\.json$/i.test(p.path)))throw Error('Mutable authorization in source pins');
  const journal=inspectAnyJournal(join(runOut,'journal'));
  if(!journal.valid||Object.keys(journal.snapshot?.pending??{}).length||journal.snapshot?.acceptedRequestCount!==journal.snapshot?.finishedRequestCount)throw Error('Native journal not drained/valid');
  const cash=inspectAnyClosedCash(root,actualPin(join(runOut,'currency/cash-close.json')));
  if(!cash.accountingClosed||cash.proof.snapshot.pendingCount!==0)throw Error('Native cash not closed');
  const lane=read(join(runOut,'lane-close.json'));if(lane.closed!==true)throw Error('Lane not natively closed');
  const manifest=read(join(runOut,'manifest.json'));
  // The top manifest is the frozen cohort; the per-run plan is checked through dispatch and native record.
  if(manifest.providerSlug&&manifest.providerSlug!==slug)throw Error('Wrong supplier manifest');
  if(manifest.plannedTaskRuns!==500||manifest.taskSchedule?.length!==500||new Set(manifest.taskSchedule.map((t:any)=>t.index)).size!==500)throw Error('Per-run full500 manifest mismatch');
  const dispatch=read(join(runOut,'recovery-dispatches.json'));
  if(dispatch.length!==1||dispatch[0].index!==277)throw Error('Unexpected dispatch outside single277');
  const record=read(join(runOut,'task-277.json'));
  const config=read(join(runOut,'journal/journal-config.json'));
  if(config.providerSlug!==slug)throw Error('Journal supplier mismatch');
  if(record.runId!==config.campaign||manifest.campaign!==config.campaign)throw Error('Task/journal/manifest run identity mismatch');
  const engines=readdirSync(runOut).filter(n=>/^engine-\d+-\d+\.json$/.test(n)).map(n=>read(join(runOut,n)));
  return {runOut,slug,decision:decision(record),journalValid:true,pending:0,cashClosed:true,laneClosed:true,
    accepted:journal.snapshot.acceptedRequestCount,finished:journal.snapshot.finishedRequestCount,
    knownUsd:cash.billedUsd,unknownCostCount:cash.unknownCostCount,unknownReservationUsd:cash.unknownReservationUsd,engines};
}
if(import.meta.main){console.log(JSON.stringify(process.argv[2]==='--baseline'?baseline():auditRun(process.argv[2],process.argv[3],process.argv[4])));}
