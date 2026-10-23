import {test,expect} from 'bun:test';
import {readFileSync,readdirSync} from 'node:fs';
import {join} from 'node:path';
import {requestTimeoutMs,canaryReady,failureFor,retainedTaskAttempts} from './interface-policy.ts';
const out=join(import.meta.dir,'../../../docs/newbench-20261014/classeval');
const read=(p:string)=>JSON.parse(readFileSync(p,'utf8').replace(/^\uFEFF/,''));
test('replay HTTP 200 upstream timeouts; no retry dispatch after the 600-second solve budget',()=>{
 const root=join(out,'calls/objrun/ClassEval_0/task-attempt-0');
 const digest=readdirSync(root)[0];
 let now=0,dispatches=0;
 for(let attempt=0;attempt<3;attempt++){
  let timeout:number;try{timeout=requestTimeoutMs(600000,now);}catch{break;}
  const receipt=read(join(root,digest,'attempt-'+attempt,'receipt.json'));
  const response=read(join(root,digest,'attempt-'+attempt,'response.json'));
  expect(failureFor(response,receipt.httpStatus)).toMatch(/timed out/);
  expect(timeout).toBeLessThanOrEqual(600000-now);
  dispatches++;now+=Math.min(timeout,receipt.seconds*1000)+1000*(attempt+1);
 }
 expect(dispatches).toBeLessThanOrEqual(2);
});
test('a valid baseline canary permits baseline continuation while ObjRun has an interface exception',()=>{
 const records=[read(join(out,'results/baseline/ClassEval_0.json')),read(join(out,'recovery/20261014-interface-boundary-153351/ClassEval_0.json'))];
 expect(canaryReady('baseline',records)).toBe(true);
 expect(canaryReady('objrun',records)).toBe(false);
});
test('an exhausted recovery remains exhausted after persisting and reloading its result',()=>{
 const prior={taskAttempts:2,grade:{valid:false}};
 const retained=JSON.parse(JSON.stringify({...prior,taskAttempts:retainedTaskAttempts(prior)}));
 expect(retainedTaskAttempts(retained)).toBe(2);
});
test('no monetary limit controls a retry timeout',()=>{
 expect(requestTimeoutMs(undefined,0)).toBe(600000);
});
