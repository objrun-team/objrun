/** Authorized fixed twelve-task trial, or its actual zero-forward lock control. */
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { actualPin, demand, jsonPin, type Pin } from "../../repair-2026-10-08/paid-resource-proof-v2.ts";
import { acquireTb12Admission, durable, TB12_FAMILY } from "./paid_admission.ts";
import { executePaired } from "./paired_trial.ts";
import { executedSources, snapshotSources } from "./freeze_sources.ts";
import { certifyClose, freshAbsence, projectSecrets } from "./close_certificate.ts";
import { providerGateway } from "./provider_gateway.ts";

const ROOT=resolve(import.meta.dir,"../../.."),PREP=join(ROOT,"docs/repair-2026-10-09/tb12-preparation-v1");
function latestCash():Pin {
  return actualPin(readdirSync(join(PREP,"cash-observations")).map(folder=>join(PREP,"cash-observations",folder,"balance.json"))
    .filter(existsSync).sort((a,b)=>statSync(a).mtimeMs-statSync(b).mtimeMs).at(-1)!);
}
const mode=process.argv[2],ready=actualPin(resolve(process.argv[3]??""));
demand(["control","run"].includes(mode),"tb12_entry_mode");
const sourcePins=executedSources();
const readiness=jsonPin(ready);
// A newly frozen source set must have precisely the same content as readiness.
demand(JSON.stringify(sourcePins)===JSON.stringify(readiness.sourcePins),"tb12_entry_not_frozen_in_readiness");
const runId="repair-"+new Date().toISOString().replace(/[:.]/g,"-");
const output=join(ROOT,"docs/repair-2026-10-09/tb12-runs-v1",runId);mkdirSync(output,{recursive:true});
const prices=actualPin(join(PREP,"price-observations/20261009T0959/prices.json"));
const entry=actualPin(import.meta.path),secrets=projectSecrets();
const directive=actualPin(join(PREP,"user-resource-directive.json"));
let providerKey:string|undefined;
if(mode==="run") {
  const runs=join(ROOT,"docs/repair-2026-10-09/tb12-runs-v1");
  const controlFolders=existsSync(runs)?readdirSync(runs).filter(folder=>existsSync(join(runs,folder,"zero-forward-control.json"))&&existsSync(join(runs,folder,"entry-closed.json"))).sort():[];
  const control=join(runs,controlFolders.at(-1)??"missing");
  demand(existsSync(join(control,"entry-closed.json")),"tb12_actual_financial_lifecycle_control_required");
  const start=jsonPin(actualPin(join(control,"entry-start.json"))),closed=jsonPin(actualPin(join(control,"entry-closed.json")));
  demand(start.mode==="control"&&closed.mode==="control"&&closed.canonicalOwnerReleased===true&&JSON.stringify(start.sourcePins)===JSON.stringify(sourcePins),"tb12_financial_control_not_current");
  demand(jsonPin(actualPin(join(control,"zero-forward-control.json"))).modelCalls===0&&jsonPin(closed.certificatePin).rawFinancialVerified===true,"tb12_financial_control_raw_binding");
  const found=readFileSync(join(ROOT,".env"),"utf8").match(/^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=\s*(.*?)\s*$/m);
  demand(found,"tb12_project_credential_missing");providerKey=found[1].replace(/^(['"])(.*)\1$/,"$2");
  demand(providerKey.length>6,"tb12_project_credential_invalid");secrets.add(providerKey);
}
snapshotSources(output,sourcePins);
const lease=await acquireTb12Admission({runId,output,balance:latestCash(),prices,
  crossFamily:actualPin(join(PREP,"cross-family-preflight-20261009-current.json")),sourcePins,entry,
  requestedEnvelopeCny:"9",headroomCny:"0",headroomDirective:directive,readiness:ready});
durable(join(output,"entry-start.json"),{protocol:"tb12-owned-paid-entry-v1",family:TB12_FAMILY,runId,mode,
  ownerNonce:lease.owned.ownerNonce,admissionPin:lease.proofPin,sourcePins,
  realForwardAuthorized:mode==="run",newEnvelopeCny:"9",originalUnknownCarryCny:"8.39218"});
console.log(JSON.stringify({output,mode,canonicalOwnerAcquired:true,realModelCalls:0}));
let completed=false;
try {
  if(mode==="control") {
    const gateway=providerGateway({runId,output,prices,kind:"real-provider",admission:lease,
      providerKey:"tb12-zero-forward-placeholder-credential",sourceGuard:()=>lease.validateForwardSource()});
    secrets.add(gateway.token);
    // No route is registered; there is no possible provider request here.
    await gateway.stop();const financial=gateway.close();
    durable(join(output,"zero-forward-control.json"),{protocol:"tb12-canonical-zero-forward-control-v1",
      modelCalls:0,providerRequests:0,financialClose:financial,admissionPin:lease.proofPin});
  } else {
    const result=await executePaired({kind:"real-provider",runId,output,prices,sourcePins,admission:lease,providerKey,secrets});
    completed=result.complete;
  }
  const certificate=await certifyClose({home:output,runId,ownerNonce:lease.owned.ownerNonce,secrets,sourcePins,
    financialOnly:mode==="control"||!completed});
  const absence=await freshAbsence(output,runId,lease.owned.ownerNonce);
  await lease.release({tb12CertificatePin:certificate,freshOwnedObservationPin:absence});
  durable(join(output,"entry-closed.json"),{protocol:"tb12-owned-paid-entry-closed-v1",family:TB12_FAMILY,runId,mode,
    realOperationalComplete:completed,certificatePin:certificate,canonicalOwnerReleased:true,
    originalUnknownCarrySettled:false});
  console.log(JSON.stringify({output,mode,realOperationalComplete:completed,canonicalOwnerReleased:true}));
  if(mode==="run"&&!completed)process.exitCode=2;
} catch(error) {
  durable(join(output,"entry-close-failure.json"),{protocol:"tb12-owned-paid-entry-fault-v1",runId,mode,
    canonicalOwnerReleased:false,error:error instanceof Error?{name:error.name,message:error.message,stack:error.stack}:String(error),
    noUnconditionalRelease:true});
  console.log(JSON.stringify({output,mode,canonicalOwnerReleased:false,closureFault:true}));process.exitCode=2;
}
