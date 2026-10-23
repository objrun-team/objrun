import {existsSync,readFileSync,readdirSync} from 'node:fs';
import {join} from 'node:path';
import {ROOT,OUT,save} from './prepare.ts';
import {inspectFullFClosedCash} from '../shared/supplier-closed-run-cost.ts';
import {inspectCampaignJournal as inspectSupplierJournal} from '../shared/supplier-journal.ts';
import {inspectCampaignJournal as inspectLegacyJournal} from '../../../benchmark-repair/campaign-journal.ts';
import {inspectCampaignJournal as inspectDigitalOceanJournal} from '../shared/digitalocean-journal.ts';
import {verifyBenchmarkCashClosure} from '../../../benchmark-repair/benchmark-usd-cash.ts';
import {actualPin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
const active=existsSync(join(OUT,'active-run.json'))?JSON.parse(readFileSync(join(OUT,'active-run.json'),'utf8')):null;
if(!active){console.log(JSON.stringify({phase:'queued',completed:0,denominator:816,knownCostUsd:0}));process.exit(0);}
const root=active.output,cashConfig=JSON.parse(readFileSync(join(root,'journal/currency/cash-config.json'),'utf8')),inspection=(String(cashConfig.sourcePin?.path??'').includes('supplier-usd-cash.ts')?inspectSupplierJournal:String(cashConfig.sourcePin?.path??'').includes('digitalocean-usd-cash.ts')?inspectDigitalOceanJournal:inspectLegacyJournal)(join(root,'journal'));
const records=readdirSync(root,{withFileTypes:true}).filter(e=>e.isDirectory()&&/^task-\d+$/.test(e.name)).flatMap(e=>{const p=join(root,e.name,'result.json');return existsSync(p)?[JSON.parse(readFileSync(p,'utf8'))]:[]});
const gradeReceipts=readdirSync(root,{withFileTypes:true}).filter(e=>e.isDirectory()&&/^task-\d+$/.test(e.name)).flatMap(e=>{const p=join(root,e.name,'physical-grading');return existsSync(p)?readdirSync(p).filter(n=>n.endsWith('-receipt.json')).map(n=>JSON.parse(readFileSync(join(p,n),'utf8'))):[]});
const closed=join(root,'journal/currency/cash-close.json');
const closure=existsSync(closed)?inspectFullFClosedCash(ROOT,actualPin(closed)):null;
const realScore=(r:any)=>r.generationValid&&r.acceptance?.valid&&(r.index!==39||(r.candidateHow!=="none"&&r.acceptance?.nodes?.correct?.valid===true));
const result={observedAtUtc:new Date().toISOString(),runId:active.runId,denominator:816,records:records.length,validScored:records.filter(realScore).length,passed:records.filter(r=>realScore(r)&&r.acceptance.passed).length,journal:inspection,realGraderReceipts:gradeReceipts.length,validGraderReceipts:gradeReceipts.filter(r=>r.valid&&r.fixtureOnly===false).length,cashClosed:existsSync(closed),cashClosure:closure};
save('inspection.json',result);console.log(JSON.stringify({denominator:816,records:records.length,validScored:result.validScored,realGraderReceipts:result.realGraderReceipts,journalValid:inspection.valid,financialClosed:closure?.financiallyResolved??false}));
