/** Non-paid resource client. Uses the published broker and its original RPC. */
import { existsSync,readFileSync,writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { demand } from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import { acquireFullFResource,type FullFConnection } from '../shared/shared-admission.ts';

export function acquirePreparationResource(root:string){
  const control=JSON.parse(readFileSync(join(root,'docs/repair-2026-10-10/full-f-rerun/control.json'),'utf8'));
  const connection=control.broker as FullFConnection;
  demand(connection&&Array.isArray(connection.sourcePins)&&connection.sourcePins.length>0,'published_resource_broker_required');
  const holdPath=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench/coordination-hold.json');
  if(existsSync(holdPath)){
    const hold=JSON.parse(readFileSync(holdPath,'utf8'));
    if(!hold.releasedAtUtc){
      demand(control.paidReady===true&&(connection.pid!==hold.brokerPid||connection.runId!==hold.brokerRunId),'coordinator_broker_transition_hold');
      writeFileSync(holdPath,JSON.stringify({...hold,releasedAtUtc:new Date().toISOString(),replacementBrokerPid:connection.pid,replacementBrokerRunId:connection.runId},null,2)+'\n');
    }
  }
  const health=JSON.parse(readFileSync(connection.healthPath,'utf8'));
  demand(health.pid===connection.pid&&health.runId===connection.runId&&Date.now()-Date.parse(health.atUtc)<30000,'published_resource_broker_identity_or_freshness');
  // Published paid source pins can become stale while the coordinator repairs
  // stopped forwarding. Resource RPCs retain the adapter's original live
  // broker identity/auth checks; paid admission still verifies all source pins.
  // The server independently authorizes /resource/acquire and checks its sole
  // slot, including when paid forwarding is stopped. This calls no admission,
  // owner, cash or transport API and changes no shared configuration.
  return acquireFullFResource(root,'skillsbench','heavy-container',connection);
}
