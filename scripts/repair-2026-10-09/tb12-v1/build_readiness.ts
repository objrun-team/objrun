/** Freeze preparation receipts, without claiming any paid trial result. */
import { existsSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { actualPin, demand, jsonPin, type Pin } from "../../repair-2026-10-08/paid-resource-proof-v2.ts";
import { durable, TB12_FAMILY } from "./paid_admission.ts";
import { executedSources } from "./freeze_sources.ts";
const ROOT=resolve(import.meta.dir,"../../.."),PREP=join(ROOT,"docs/repair-2026-10-09/tb12-preparation-v1");
export function freezeReadiness(coldDirectory:string) {
  const coldAudit=actualPin(join(coldDirectory,"independent-audit.json")),coldSummary=actualPin(join(coldDirectory,"summary.json"));
  const audited=jsonPin(coldAudit),summary=jsonPin(coldSummary);
  demand(audited.integrityValid===true&&audited.providerKind==="local-mock"&&audited.modelCallsByAuditor===0&&summary.operationalComplete===true&&summary.modelCalls===0,"tb12_actual_cold_receipts");
  const controls=new Map<string,Pin>();
  for(const folder of readdirSync(join(PREP,"cold-snapshots"))) {
    const path=join(PREP,"cold-snapshots",folder,"control.json");
    let pin:Pin,value:any;try{pin=actualPin(path);value=jsonPin(pin);}catch{continue;}
    if(value.validated&&value.allOwnedContainersClosed&&value.modelCalls===0&&!value.fatal)
      controls.set(value.taskId+"/"+value.control,pin);
  }
  for(const kind of ["empty","positive","wrong"])demand([...controls.keys()].filter(name=>name.endsWith("/"+kind)).length===12,"tb12_all_actual_control_profiles");
  for(const kind of ["ascii-worker","malformed-worker"])demand(controls.has("openssl-selfsigned-cert/"+kind),"tb12_actual_untrusted_worker_controls");
  const runtimePaths=readdirSync(join(PREP,"runtime-probes")).map(folder=>join(PREP,"runtime-probes",folder,"probes.json"))
    .filter(existsSync).filter(path=>jsonPin(actualPin(path)).validated===true).sort((a,b)=>statSync(a).mtimeMs-statSync(b).mtimeMs);
  const runtime=actualPin(runtimePaths.at(-1)!);
  const collection=actualPin(join(PREP,"original-collections/4b15ff898ebb49eb8643f5577e0d4c4a/collection.json"));
  demand(jsonPin(runtime).validated&&jsonPin(runtime).allOwnedContainersClosed&&jsonPin(runtime).records.length===12,"tb12_actual_all_six_tools");
  demand(jsonPin(collection).allTwelveOriginalCollectionsValidated&&jsonPin(collection).totalOriginalTestsCollected===48&&jsonPin(collection).allOwnedCollectionContainersClosed,"tb12_actual_original_collection");
  const sourcePins=executedSources();
  return durable(join(PREP,"readiness-"+new Date().toISOString().replace(/[:.]/g,"-")+".json"),{
    protocol:"tb12-frozen-execution-readiness-v1",family:TB12_FAMILY,validated:true,modelCalls:0,
    distinctTaskCount:12,plannedTaskRuns:24,originalTests:48,actualColdPaidTaskRuns:0,
    coldAuditPin:coldAudit,coldSummaryPin:coldSummary,controlPins:[...controls.values()],runtimePin:runtime,collectionPin:collection,
    sourcePins,officialScope:actualPin(join(ROOT,"docs/repair-2026-10-08/tb-multitask-twelve-scope-v1/task-scope.json")),
    storageQuotaProbe:actualPin(join(PREP,"storage-probes/c61a0504a9714ac298c45f6070fdd8cf/probe.json")),
    hardStorageQuotaEnforced:false,writableLayerBoundarySamplingBytes:10240*1024**2,
    candidatePythonReplacement:false,oldSingleNginxIncluded:false,fullRunAuthorized:false,
    financialLifecycleControlRequiredBeforeRealForward:true});
}
if(import.meta.main)console.log(JSON.stringify({readiness:freezeReadiness(resolve(process.argv[2]))}));
