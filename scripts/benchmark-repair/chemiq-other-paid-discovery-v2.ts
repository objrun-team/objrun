/** Fail closed when another newly delegated paid family is not covered by reviewed accounting. */
import { existsSync, lstatSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { actualPin, demand, jsonPin, type Pin } from './paid-resource-proof-v2.ts';
const KNOWN_PROTOCOLS=new Set(['paid-resource-v2-run','jpg-paid-resource-run-v1','jpg-D-paid-resource-run-v1','chemiq-f-paid-resource-run-v1','chemiq-f-paid-resource-run-v2']);
export function discoverChemiqOtherPaidEvidence(root:string) {
  const inputPins:Pin[]=[],registries:any[]=[];let directories=0;
  function visit(directory:string) {
    demand(!lstatSync(directory).isSymbolicLink(),'chemiq_paid_discovery_reparse');
    demand(++directories<100000,'chemiq_paid_discovery_directory_bound');
    for(const e of readdirSync(directory,{withFileTypes:true})) {
      const path=join(directory,e.name);
      if(e.isSymbolicLink()) demand(false,'chemiq_paid_discovery_reparse');
      if(e.isDirectory()) {visit(path);continue;}
      if(!e.isFile()||!/(?:paid.*(?:resource.*run|registry)|campaign.*registry)\.json$/.test(e.name))continue;
      const pin=actualPin(path),row=jsonPin(pin);inputPins.push(pin);
      demand(KNOWN_PROTOCOLS.has(row.protocol),'chemiq_unrecognized_paid_registry_requires_reviewed_scanner');
      registries.push({path,protocol:row.protocol,runId:row.runId,released:row.released??null});
    }
  }
  for(const name of ['docs/repair-2026-10-08','docs/repair-2026-10-09']) {const path=join(root,name);if(existsSync(path))visit(path);}
  const statusHome=join(root,'docs/repair-2026-10-08/parallel-bench-handoff-2026-10-09');
  const otherBenches=[['terminal-bench-status.json','newProjectLlmRequests'],['skillsbench-status.json','realModelCalls']];
  const statuses=otherBenches.map(([name,key])=>{
    const pin=actualPin(join(statusHome,name)),row=jsonPin(pin),calls=row[key];inputPins.push(pin);
    demand(Number.isSafeInteger(calls)&&calls>=0,'chemiq_other_bench_paid_status_unknown');
    demand(calls===0,'chemiq_other_new_paid_family_requires_reviewed_scanner');
    return {path:pin.path,modelCalls:calls,statusUpdatedAtUtc:row.updatedAtUtc??null};
  });
  return {protocol:'chemiq-other-paid-discovery-v2',observedAtUtc:new Date().toISOString(),modelCalls:0,registries,statuses,inputPins,directories,
    unknownFamiliesIgnored:false,newTBAndSKBAllowedOnlyUntilActualPaidEvidence:false,
    limitation:'Existing science/JPG/ChemIQ registries are separately audited. A new TB/SKB paid registry or positive model counter is rejected pending a reviewed family scanner.'};
}
