/** Root-only preparation: no model calls, no process termination. */
import {readFileSync,writeFileSync,mkdirSync,copyFileSync,existsSync} from 'node:fs';
import {join,resolve,basename} from 'node:path';
import {actualPin,verifyPin} from '../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {atomicStateJson as atomicJson} from './shared/atomic-state.ts';
import {verifyClosedBrokerHistory} from './audit-closed-broker.ts';
const root=resolve(import.meta.dir,'../../..'),base=join(root,'docs/repair-2026-10-10/full-f-rerun');
const read=(p:string)=>JSON.parse(readFileSync(p,'utf8'));
const controlPath=join(base,'control.json'),control=read(controlPath),old=control.broker;
function check(ok:unknown,message:string):asserts ok{if(!ok)throw Error(message);}
check(old.pid===142416&&old.sourcePins[0].path.endsWith('digitalocean-broker-cb-score-completion.ts'),'unexpected_old_broker');
for(const pin of old.sourcePins)verifyPin(pin);
const ready=read(join(base,'chemiq/task39-stream-entry-ready.json'));
check(ready.ready&&ready.paidStarted===false,'CQ39_entry_not_ready');verifyPin(ready.entryPin);verifyPin(ready.scopeTemplatePin);
const health=async()=>await(await fetch(old.endpoint+'/health')).json() as any;
function closed(h:any){check(h.pid===old.pid&&h.runId===old.runId&&h.healthy&&h.activeRequests===0&&h.queuedRequests===0&&!h.canonicalOwner&&h.lanes.every((l:any)=>l.closed)&&!(h.resourceSlots??Object.values(h.resources)).length,'old_broker_not_natively_quiescent');check(!existsSync(join(root,'.phase1-data/owned-paid-campaign.lock.json')),'canonical_owner_still_present');}
closed(await health());
const paused=await fetch(old.endpoint+'/admin/pause',{method:'POST',headers:{authorization:'Bearer '+old.accessToken},body:'{}'});check(paused.ok,'old_dispatch_pause_failed');
const h=await health();closed(h);
const directory=join(base,'chemiq-stream-switch',old.runId);mkdirSync(directory,{recursive:true});
const save=(name:string,value:any)=>{const p=join(directory,name);writeFileSync(p,JSON.stringify(value,null,2)+'\n',{flag:'wx'});return actualPin(p);};
const closedHealthPin=save('closed-health.json',h);
const pins=old.sourcePins.map((original:any,index:number)=>{const path=join(directory,'sources',index+'-'+basename(original.path));mkdirSync(join(directory,'sources'),{recursive:true});copyFileSync(original.path,path);const archived=actualPin(path);check(archived.sha256===original.sha256&&archived.bytes===original.bytes,'source_archive_mismatch');return{original,archived};});
const sourceArchivePin=save('source-archive.json',{atUtc:new Date().toISOString(),pins});
const entry={runId:old.runId,pid:old.pid,healthPath:old.healthPath,closedHealthPin,sourceArchivePin,releasePins:h.roundReceipts,closedAtUtc:new Date().toISOString(),reason:'normal native closure before sole ChemIQ39 stream migration'};
const audit=verifyClosedBrokerHistory(entry);save('native-history-audit.json',audit);
const fresh=read(controlPath);check(fresh.broker.pid===old.pid&&fresh.broker.runId===old.runId,'broker_changed_during_prepare');
atomicJson(controlPath,{...fresh,paidReady:false,brokerHistory:[...(fresh.brokerHistory??[]),entry],dockerRecovery:{...fresh.dockerRecovery,phase:'blocked_host_e_disk_full',graderHealthy:false,secondFailureEvidence:'docker-recovery-2026-10-10/second-space-failure.json'},chemiqStreamSwitch:{phase:'old_native_closed_verified_pending_exact_retirement',candidateEntry:'scripts/repair-2026-10-10/full-f/shared/digitalocean-broker-cq-stream.ts',oldPid:old.pid,oldBornUtc:'2026-10-10T20:04:21.3233060Z',historyEntry:entry,actualModelCalls:0,storageHold:true},updatedAtUtc:new Date().toISOString()});
console.log(JSON.stringify({prepared:true,oldPid:old.pid,nativeVerified:true,knownUsd:audit.effectiveBilledUsd,unknown:audit.remainingUnknownCostCount,lanes:h.lanes.length,modelCalls:0,paidReady:false,directory}));
