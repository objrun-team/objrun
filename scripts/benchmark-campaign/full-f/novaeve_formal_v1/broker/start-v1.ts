import {existsSync,readFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {startFullFBroker} from './broker-v1.ts';
import {atomicStateJson} from '../../shared/atomic-state.ts';
import {verifyRemoteDisk} from './remote-disk-gate-v1.ts';
const root=resolve(import.meta.dir,'../../../../..');
const base=join(root,'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/broker');
const mode=process.argv[2];
if(!['--check','--serve'].includes(mode??''))throw Error('use --check or --serve');
const runId='repair-'+new Date().toISOString().replace(/[:.]/g,'-');
const diskPath=join(base,'remote-disk.json');
if(mode==='--serve'&&!existsSync(diskPath))throw Error('fresh remote-disk.json required');
if(mode==='--serve')verifyRemoteDisk(diskPath);
const broker=await startFullFBroker({root,output:join(base,runId),runId,port:mode==='--check'?0:17889,recordAndContinue:true,maxInFlight:16,targetMax:16,perBenchMax:16,heavyCapacity:16,heavyMemoryMb:262144,perBenchHeavySlots:16,localMock:mode==='--check',remoteDiskObservationPath:mode==='--serve'?diskPath:undefined});
if(mode==='--check'){
 const r=await fetch(broker.connection.endpoint+'/admin/concurrency',{method:'POST',body:'{}'});
 if(r.status!==401)throw Error('authentication check failed');
 const s=broker.snapshot(); if(s.maxInFlight!==16||s.lanes.length!==0||s.activeRequests!==0)throw Error('zero-call check failed');
 await broker.stop(); console.log(JSON.stringify({protocol:'novaeve-broker-check-v1',modelCalls:0,authenticated:true,total:16,portClosed:true}));
}else{
 // Private handoff only. The root operator publishes control after validating old paid owners.
 atomicStateJson(join(base,'connection.private.json'),broker.connection);
 console.log(JSON.stringify({protocol:'novaeve-broker-start-v1',pid:process.pid,endpoint:broker.connection.endpoint,runId,modelCalls:0,controlPublished:false}));
}
