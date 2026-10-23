/** Independent close controller: raw cash replay, source pins, offline audit and
 * actual secret-value scanning. It cannot send provider requests. */
import { spawn } from "node:child_process";
import { existsSync, readdirSync, readFileSync, openSync, readSync, closeSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { gunzipSync } from "node:zlib";
import { Database } from "bun:sqlite";
import { actualPin, demand, jsonPin, verifyPin, type Pin } from "../../repair-2026-10-08/paid-resource-proof-v2.ts";
import { verifyCashClosure } from "../../repair-2026-10-08/cny-cash-shadow-v2.ts";
import { durable, TB12_FAMILY } from "./paid_admission.ts";

const ROOT=resolve(import.meta.dir,"../../..");
export async function nativePython(script:string,args:string[],output:string) {
  const python="D:/ProgramData/anaconda3/python.exe",argv=["-B","-X","utf8",script,...args];
  const startedAtUtc=new Date().toISOString(),child=spawn(python,argv,{windowsHide:true,stdio:["ignore","pipe","pipe"]});
  demand(child.pid,"tb12_auditor_actual_pid");
  const parts:Buffer[][]=[[],[]],counts=[0,0];let exitObserved=false,closeObserved=false,exitCode:number|null=null;
  const faults:string[]=[];
  for(const [index,stream]of [child.stdout,child.stderr].entries())stream?.on("data",(chunk:Buffer)=>{
    counts[index]+=chunk.length;if(counts[index]>2*1024**2){faults.push("auditor-stream-limit");child.kill("SIGKILL");}
    else parts[index].push(Buffer.from(chunk));
  });
  child.on("error",error=>faults.push(error.name));child.on("exit",code=>{exitObserved=true;exitCode=code;});
  await new Promise<void>(done=>child.on("close",()=>{closeObserved=true;done();}));
  const receipt=durable(output,{protocol:"tb12-independent-native-auditor-close-v1",pid:child.pid,argv:[python,...argv],
    startedAtUtc,closedAtUtc:new Date().toISOString(),exitObserved,closeObserved,exitCode,faults,
    stdout:Buffer.concat(parts[0]).toString("utf8"),stderr:Buffer.concat(parts[1]).toString("utf8"),
    executable:actualPin(python),source:actualPin(script),modelCalls:0});
  demand(exitObserved&&closeObserved&&!faults.length&&exitCode===0,"tb12_independent_native_auditor_failed");
  return{receipt,stdout:Buffer.concat(parts[0]).toString("utf8")};
}

export function projectSecrets() {
  const secrets=new Set<string>();
  for(const line of readFileSync(join(ROOT,".env"),"utf8").split(/\r?\n/)) {
    const found=line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if(!found||!/(KEY|TOKEN|SECRET|PASSWORD)/i.test(found[1]))continue;
    let value=found[2];if((value.startsWith('"')&&value.endsWith('"'))||(value.startsWith("'")&&value.endsWith("'")))value=value.slice(1,-1);
    if(value&&value.length>=6)secrets.add(value);
  }
  return secrets;
}
export function scanRunSecrets(home:string,secrets:Set<string>) {
  const needles=[...secrets].map(value=>Buffer.from(value));
  demand(needles.length>0&&needles.every(value=>value.length>=6),"tb12_actual_secret_values_required");
  const files:Pin[]=[],excluded:Pin[]=[],mutableScanned:Pin[]=[];
  const maximum=Math.max(...needles.map(value=>value.length));
  const check=(raw:Buffer)=>demand(needles.every(needle=>!raw.includes(needle)),"tb12_actual_secret_in_exportable_evidence");
  const walk=(folder:string)=>{
    for(const item of readdirSync(folder,{withFileTypes:true})) {
      const path=join(folder,item.name),name=relative(home,path).replaceAll("\\","/");
      demand(!item.isSymbolicLink(),"tb12_evidence_symlink");
      if(item.isDirectory()){walk(path);continue;}
      demand(item.isFile(),"tb12_nonordinary_evidence");
      if(/^workers\/\d+-[UF]\/config.yaml$/.test(name)||/\/broker\/broker-key.pem$/.test(name)) {
        excluded.push(actualPin(path));continue;
      }
      if(item.name.endsWith(".gz"))check(gunzipSync(readFileSync(path),{maxOutputLength:64*1024**2}));
      else {
        const fd=openSync(path,"r"),chunk=Buffer.alloc(1024**2);let carry=Buffer.alloc(0);
        try{let count:number;while((count=readSync(fd,chunk))>0){const block=Buffer.concat([carry,chunk.subarray(0,count)]);check(block);carry=block.subarray(Math.max(0,block.length-maximum+1));}}
        finally{closeSync(fd);}
      }
      if(/^paid-registry.sqlite(?:-wal|-shm)?$/.test(name)||name==="tb12-paid-resource-run.json")mutableScanned.push(actualPin(path));
      else files.push(actualPin(path));
    }
  };walk(home);
  return durable(join(home,"independent/secret-scan.json"),{protocol:"tb12-actual-export-secret-scan-v1",
    passed:true,actualSecretValueCount:needles.length,secretValuesExcluded:true,scannedFiles:files,excludedPrivateFiles:excluded,
    mutableReleaseRegistryScannedBeforeFinalization:mutableScanned,mutableRegistryRequiresFinalPackageScan:true,
    compressedBodiesExpanded:true,modelCalls:0,scannerSource:actualPin(import.meta.path)});
}

export async function certifyClose(options:{home:string;runId:string;ownerNonce:string;secrets:Set<string>;sourcePins:Pin[];financialOnly?:boolean}) {
  const home=resolve(options.home),inputs:Pin[]=[];
  for(const pin of options.sourcePins){verifyPin(pin);inputs.push(pin);}
  const cashClosePin=actualPin(join(home,"cash/cash-close.json"));
  const cash=verifyCashClosure(cashClosePin);
  demand(cash.config.providerKind==="real-provider"&&cash.config.runId===options.runId&&cash.config.ownerNonce===options.ownerNonce,"tb12_certificate_cash_owner");
  inputs.push(cashClosePin,cash.proof.configPin,cash.proof.cashEventsPin);
  let audited:any=null,auditPin:Pin|undefined;
  const summary=existsSync(join(home,"summary.json"))?jsonPin(actualPin(join(home,"summary.json"))):null;
  if(!options.financialOnly&&summary?.operationalComplete) {
    const target=join(home,"independent/raw-audit.json");
    const run=await nativePython(join(import.meta.dir,"audit_trial.py"),["--run-directory",home,"--output",target],join(home,"independent/auditor-native-close.json"));
    auditPin=actualPin(target);audited=jsonPin(auditPin);inputs.push(auditPin,run.receipt,...audited.inputPins);
    demand(audited.integrityValid===true&&audited.providerKind==="real-provider"&&audited.result.taskRuns===24&&audited.result.distinctTaskCount===12,"tb12_real_score_audit_required");
  }
  const database=join(home,"stand-process/stand/owned-native.sqlite");
  if(existsSync(database)) {
    const db=new Database(database,{readonly:true});
    try{demand(db.query("select count(*) as n from actor where closed=0").get().n===0,"tb12_certificate_open_actor");
      for(const row of db.query("select json from command").all() as any[]){const value=JSON.parse(row.json);demand(value.closeObserved===true&&Number.isInteger(value.exitCode),"tb12_certificate_unclosed_native");}
    }finally{db.close();}
    inputs.push(actualPin(database));
  }
  for(const folder of existsSync(join(home,"workers"))?readdirSync(join(home,"workers")):[]) {
    const path=join(home,"workers",folder,"engine-close.json");demand(existsSync(path),"tb12_certificate_engine_without_close");
    const pin=actualPin(path),value=jsonPin(pin);demand(value.exitObserved&&value.closeObserved&&!value.captureFaults.length,"tb12_certificate_engine_close");inputs.push(pin);
  }
  const stand=join(home,"stand-process/stand-close.json");
  if(existsSync(join(home,"stand-process"))) {
    demand(existsSync(stand),"tb12_certificate_stand_without_close");
    const pin=actualPin(stand),value=jsonPin(pin);demand(value.exitObserved&&value.closeObserved&&!value.faults.length,"tb12_certificate_stand_close");inputs.push(pin);
  }
  const proxy=actualPin(join(home,"provider-native-close.json"));demand(jsonPin(proxy).serverClosed===true,"tb12_certificate_proxy_close");inputs.push(proxy);
  // Private config tokens are re-read from the actual generated files too.
  for(const folder of existsSync(join(home,"workers"))?readdirSync(join(home,"workers")):[]) {
    const config=JSON.parse(readFileSync(join(home,"workers",folder,"config.yaml"),"utf8"));
    options.secrets.add(config.api.token);options.secrets.add(config.api.publisherToken);
  }
  const scanPin=scanRunSecrets(home,options.secrets);inputs.push(scanPin,...jsonPin(scanPin).scannedFiles);
  return durable(join(home,"independent/close-certificate.json"),{protocol:"tb12-independent-close-certificate-v1",family:TB12_FAMILY,
    runId:options.runId,ownerNonce:options.ownerNonce,kind:audited?"score-and-financial":"financial-only",
    modelCallsByAuditor:0,sourceVerified:true,rawFinancialVerified:true,ownedCloseVerified:true,tokenSecretScanPassed:true,
    operationalComplete:!!audited,distinctTaskCount:audited?.result.distinctTaskCount??0,realTaskRuns:audited?.result.taskRuns??0,
    cashClosePin,rawAuditPin:auditPin??null,secretScanPin:scanPin,inputPins:inputs,source:actualPin(import.meta.path),
    newEstimatedNanoCny:cash.proof.snapshot.newKnownEstimatedNanoCny,invoice:false});
}

export async function freshAbsence(home:string,runId:string,ownerNonce:string) {
  const run=await nativePython(join(import.meta.dir,"fresh_absence.py"),["--run-directory",home,"--run-id",runId,"--owner-nonce",ownerNonce],
    join(home,"independent/fresh-observer-native-close.json"));
  const lines=run.stdout.trim().split(/\r?\n/),last=JSON.parse(lines.at(-1)!);
  demand(last.allAbsent===true,"tb12_fresh_observer_not_absent");return actualPin(last.observation);
}
