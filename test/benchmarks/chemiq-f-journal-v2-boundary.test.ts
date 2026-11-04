import { expect, test } from 'bun:test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { CHEMIQ_F_ROOT, loadChemiqFPlan } from '../../scripts/benchmark-repair/chemiq-f-journal-contract-v2.ts';
import { assertChemiqPrivateBridgeObservation } from '../../scripts/benchmark-repair/chemiq-private-boundary-v2.ts';
import { chemiqCashEnvelope } from '../../scripts/benchmark-repair/chemiq-f-paid-admission-v2.ts';
const root=CHEMIQ_F_ROOT;
const original=JSON.parse(readFileSync(join(root,'.local-evidence/repository/test/fixtures/repair/chemiq-f-journal-implementation-v2/observations/private-inspect-2026-10-09T08-28-01-515672+00-00.json'),'utf8'));
test('only the actual original bridge service with its exact protected configuration is accepted',()=>{
  expect(()=>assertChemiqPrivateBridgeObservation(original,root)).not.toThrow();
  const faults=[
    (r:any)=>r.inspect.Id='a'.repeat(64),
    (r:any)=>r.inspect.Image='sha256:'+'b'.repeat(64),
    (r:any)=>r.inspect.HostConfig.NetworkMode='host',
    (r:any)=>r.inspect.HostConfig.ReadonlyRootfs=false,
    (r:any)=>r.inspect.HostConfig.Privileged=true,
    (r:any)=>r.inspect.HostConfig.PidMode='host',
    (r:any)=>r.inspect.HostConfig.CapAdd=['SYS_ADMIN'],
    (r:any)=>r.inspect.HostConfig.SecurityOpt=[],
    (r:any)=>r.inspect.HostConfig.PortBindings['17918/tcp'][0].HostIp='0.0.0.0',
    (r:any)=>r.inspect.NetworkSettings.Ports['17919/tcp']=[{HostIp:'127.0.0.1',HostPort:'17919'}],
    (r:any)=>r.inspect.Mounts[1].RW=true,
    (r:any)=>r.inspect.Mounts.push({Type:'bind',Source:root,Destination:'/candidate',RW:false}),
  ];
  for(const fault of faults){const changed=structuredClone(original);fault(changed);expect(()=>assertChemiqPrivateBridgeObservation(changed,root)).toThrow();}
});
test('the user waiver removes the artificial 30 CNY margin while carrying the original unknown liability',()=>{
  const balance={protocol:'deepseek-resource-readonly-v1',provider:'https://api.deepseek.com',endpoint:'/user/balance',method:'GET',httpStatus:200,isAvailable:true,modelCalls:0,credentialPrinted:false,observedAtUtc:new Date().toISOString(),balances:[{currency:'CNY',total_balance:'50.95',granted_balance:'0.00',topped_up_balance:'50.95'}]};
  expect(chemiqCashEnvelope(balance,'42.55782','0').carry).toBe(8392180000n);
  expect(()=>chemiqCashEnvelope(balance,'42.557821','0')).toThrow('chemiq_cash_envelope');
  expect(()=>chemiqCashEnvelope(balance,'42.55782','30')).toThrow('chemiq_cash_envelope');
});
test('v2 preserves the frozen pilot16 indices, F900 settings and original 816 denominator',()=>{
  const plan=loadChemiqFPlan('repair-2026-10-09T08-40-00Z','pilot16');
  expect(plan.tasks.map(t=>t.officialIndex)).toEqual([0,50,100,148,149,256,343,348,435,440,470,640,660,680,725,770]);
  expect(plan.fullDenominator).toBe(816);expect(plan.tasks.every(t=>t.arm==='F'&&t.seconds===900)).toBe(true);
});
