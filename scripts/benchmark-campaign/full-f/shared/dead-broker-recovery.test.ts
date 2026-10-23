import {test,expect} from 'bun:test';
import {readFileSync,mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {tmpdir} from 'node:os';
import {actualPin,jsonPin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import {verifyDeadBrokerRecovery} from './dead-broker-recovery.ts';
const root=resolve(import.meta.dir,'../../../..'),control=JSON.parse(readFileSync(join(root,'docs/repair-2026-10-10/full-f-rerun/control.json'),'utf8'));
const originalPin=control.brokerHistory.find((x:any)=>x.recoveryPin).recoveryPin;
test('independent crashed-owner replay retains all five lanes and fourteen uncertain fees',()=>{
 const r=verifyDeadBrokerRecovery(originalPin);expect(r.verifiedLanes).toBe(5);expect(r.remainingUnknownCostCount).toBe(14);expect(r.actualResponseCostsMatch).toBe(true);
});
test('replay rejects missing lane, invented zero unknown, and missing process time evidence',()=>{
 const dir=mkdtempSync(join(tmpdir(),'bench-recovery-'));
 try {for(const [i,change] of [(r:any)=>r.lanes.pop(),(r:any)=>r.unknownCount=0,(r:any)=>delete r.crashObservedAtUtc].entries()) {
  const r=jsonPin(originalPin);change(r);const p=join(dir,i+'.json');writeFileSync(p,JSON.stringify(r));expect(()=>verifyDeadBrokerRecovery(actualPin(p))).toThrow();
 }}finally{rmSync(dir,{recursive:true});}
});
