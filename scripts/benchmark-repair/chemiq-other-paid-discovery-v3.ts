/** Fail closed when another newly delegated paid family is not covered by reviewed accounting. */
import { existsSync, lstatSync, readdirSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { actualPin, demand, jsonPin, type Pin } from './paid-resource-proof-v2.ts';
const KNOWN_PROTOCOLS=new Set(['paid-resource-v2-run','jpg-paid-resource-run-v1','jpg-D-paid-resource-run-v1','chemiq-f-paid-resource-run-v1','chemiq-f-paid-resource-run-v2','chemiq-f-paid-resource-run-v3','tb12-paid-resource-run-v1']);
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
      if(row.protocol==='tb12-paid-resource-run-v1'){
        demand(typeof row.runId==='string'&&/^repair-[0-9TZ-]+$/.test(row.runId)&&row.family==='terminal-bench-twelve-journal-v1','chemiq_tb12_discovery_namespace');
        demand(resolve(path)===join(root,'docs/repair-2026-10-09/tb12-runs-v1',row.runId,'tb12-paid-resource-run.json'),'chemiq_tb12_discovery_namespace');
      }
      registries.push({path,protocol:row.protocol,runId:row.runId,released:row.released??null});
    }
  }
  for(const name of ['docs/repair-2026-10-08','docs/repair-2026-10-09']) {const path=join(root,name);if(existsSync(path))visit(path);}
  const statusHome=join(root,'docs/repair-2026-10-08/parallel-bench-handoff-2026-10-09');
  const otherBenches=[['terminal-bench-status.json','newProjectLlmRequests'],['skillsbench-status.json','realModelCalls']];
  const statuses=otherBenches.map(([name,key])=>{
    const pin=actualPin(join(statusHome,name)),row=jsonPin(pin),calls=row[key];inputPins.push(pin);
    demand(Number.isSafeInteger(calls)&&calls>=0,'chemiq_other_bench_paid_status_unknown');
    let coveredRegistryPin:Pin|undefined;
    if(calls>0&&name==='terminal-bench-status.json'){
      const home=join(root,'docs/repair-2026-10-09/tb12-runs-v1');
      demand(typeof row.liveRealRun==='string','chemiq_tb12_positive_status_missing_run');
      const live=resolve(row.liveRealRun),runId=basename(live),registryPath=join(live,'tb12-paid-resource-run.json');
      demand(dirname(live)===home&&/^repair-[0-9TZ-]+$/.test(runId),'chemiq_tb12_positive_status_run_scope');
      const found=inputPins.find(p=>resolve(p.path)===registryPath);demand(found,'chemiq_tb12_positive_status_unregistered_run');
      const registration=jsonPin(found);
      demand(registration.protocol==='tb12-paid-resource-run-v1'&&registration.family==='terminal-bench-twelve-journal-v1'&&registration.runId===runId,'chemiq_tb12_positive_status_family');
      coveredRegistryPin=found;
    }
    demand(calls===0||coveredRegistryPin,'chemiq_other_new_paid_family_requires_reviewed_scanner');
    return {path:pin.path,modelCalls:calls,statusUpdatedAtUtc:row.updatedAtUtc??null,coveredRegistryPin:coveredRegistryPin??null};
  });
  registries.sort((a,b)=>a.path.localeCompare(b.path));
  return {protocol:'chemiq-other-paid-discovery-v2',observedAtUtc:new Date().toISOString(),modelCalls:0,registries,statuses,inputPins,directories,
    unknownFamiliesIgnored:false,tb12ClosedRunsRequireFinancialReplay:true,newSKBAllowedOnlyUntilActualPaidEvidence:false,
    limitation:'Existing science/JPG/ChemIQ and TB12 registries are separately audited. Active/unclosed TB12 rejects financial preflight; a new SKB family still requires a reviewed scanner.'};
}
