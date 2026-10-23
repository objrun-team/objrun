import {readFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {atomicStateJson} from '../../shared/atomic-state.ts';
import {verifyRemoteDisk} from './remote-disk-gate-v1.ts';
const root=resolve(import.meta.dir,'../../../../..');
const base=join(root,'docs/repair-2026-10-10/full-f-rerun');
if(process.argv[2]!=='--publish')throw Error('root operator must explicitly use --publish');
const path=join(base,'control.json'); const c=JSON.parse(readFileSync(path,'utf8'));
const next=JSON.parse(readFileSync(join(base,'novaeve-formal-20261013/broker/connection.private.json'),'utf8'));
if(c.broker&&c.broker.runId!==next.runId){
 let old:any;try{old=await (await fetch(c.broker.endpoint+'/health',{signal:AbortSignal.timeout(3000)})).json();}catch{throw Error('old_broker_unreachable_requires_owner_audit');}
 if(!old.dispatchPaused)throw Error('old_broker_must_be_paused_before_handoff');
 if(old.activeRequests||old.queuedRequests||old.lanes.some((x:any)=>!x.closed)||old.canonicalOwner||old.resourceSlots?.length)throw Error('old_broker_owns_unfinished_paid_work');
}
const health:any=await (await fetch(next.endpoint+'/health',{signal:AbortSignal.timeout(3000)})).json();
if(health.runId!==next.runId||!health.healthy||health.maxInFlight!==16||health.targetMax!==16)throw Error('new_broker_not_ready');
if(health.localMock||health.activeRequests||health.queuedRequests||health.canonicalOwner||health.lanes.length||health.resourceSlots?.length||health.providerSlug!=='digitalocean'||health.transportPolicy?.timeoutMs!==600000)throw Error('new_broker_not_clean_real_provider');
verifyRemoteDisk(join(base,'novaeve-formal-20261013/broker/remote-disk.json'));
atomicStateJson(join(base,'novaeve-formal-20261013/broker/control-before.private.json'),c);
atomicStateJson(path,{...c,broker:next,paidReady:true,updatedAtUtc:new Date().toISOString(),novaeve:{protocol:'novaeve-local-worker-remote-docker-v1',totalConcurrency:16},concurrency:{...c.concurrency,initialGlobal:16,targetGlobal:16,perBenchRequests:16,heavySlots:16,perBenchHeavySlots:16}});
console.log(JSON.stringify({published:true,runId:next.runId,total:16,secretsPrinted:false}));
