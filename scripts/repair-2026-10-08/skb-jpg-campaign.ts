import {createHash,randomBytes,timingSafeEqual} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {existsSync,mkdirSync,readFileSync,readdirSync,statfsSync,writeFileSync} from 'node:fs';
import {basename,dirname,join,resolve,relative} from 'node:path';
import {gzipSync} from 'node:zlib';
import {Database} from 'bun:sqlite';
import {tbEngine} from './tb-engine.ts';
import {tbToolGateway} from './tb-tool-gateway.ts';
import {graderFetch} from '../../app/src/engine/registry.ts';
import {finalCandidate} from '../../app/src/objective/candidate.ts';
import {campaignComplete,checkedOutputTokens,completionFault,reconcileReceiptCost as actualCost,validTokenUsage,type ApiReceipt} from './campaign-contract.ts';
import {TASK_ID,PROTOCOL,ARTIFACT,SECONDS,VERIFY_SECONDS,CHECKS,OFFICIAL_HASHES,requirePaidJpgGate,jpgObjective,jpgGeneration,artifactVerdict,mockCall} from './skb-jpg-contract.ts';
import {SIX_TOOLS} from './tb-nginx-contract.ts';
import {acquirePaidCampaignLock} from './paid-campaign-lock.ts';
import {auditJpgEvidence} from './skb-jpg-audit.ts';
import {loadNativePython,launchNativeJpgService,NATIVE_PROFILE_PATH,LIFECYCLE_PROTOCOL} from './skb-jpg-native-python.ts';

const root=resolve(import.meta.dir,'../..'),mode=process.argv[2]??'prepare',paid=mode==='run',live=paid||mode==='docker-mock';
if(!['prepare','mock','docker-mock','run'].includes(mode))throw new Error('Use prepare|mock|docker-mock|run');
const sha=(value:string|Buffer)=>createHash('sha256').update(value).digest('hex');
const save=(path:string,value:unknown)=>{mkdirSync(dirname(path),{recursive:true});writeFileSync(path,JSON.stringify(value,null,2)+'\n');};
const grader=join(import.meta.dir,'software-jpg-private-grader.py');
const paths={controls:process.env.OBJRUN_SKB_JPG_CONTROLS_JSON,image:process.env.OBJRUN_SKB_JPG_IMAGE_JSON,build:process.env.OBJRUN_SKB_JPG_BUILD_JSON,profile:process.env.OBJRUN_SKB_JPG_DEPENDENCY_JSON};
let gate:any,gateError:string|undefined;
try{if(Object.values(paths).some(value=>!value))throw new Error('Actual JPG image/build/dependency/three-control gate is not yet available');gate=Object.fromEntries(Object.entries(paths).map(([name,path])=>[name,JSON.parse(readFileSync(path!,'utf8'))]));requirePaidJpgGate({...gate,graderSha:sha(readFileSync(grader))});}catch(error){gateError=error instanceof Error?error.message:'JPG gate unavailable';}
if(live&&gateError)throw new Error('Paid JPG is fail-closed: '+gateError);
const nativePython=loadNativePython();
const campaign='skb-jpg-'+new Date().toISOString().replace(/[:.]/g,'-');
const paidLock=paid?acquirePaidCampaignLock({root,runId:campaign,entry:basename(import.meta.path)}):undefined;
const cEvidenceRoot='C:/Users/y1252/.codex/visualizations/2026/10/08/01a119ed-fdf7-7c32-b323-de9bab1290b6';
const storeRoot=resolve(process.env.OBJRUN_SKB_STORE_ROOT??join(cEvidenceRoot,'experiment-stores'));
const inside=(parent:string,path:string)=>{const rel=relative(resolve(parent),resolve(path));return rel===''||(!rel.startsWith('..')&&!/^[A-Za-z]:/.test(rel));};
if(!inside(root,storeRoot)&&!inside(cEvidenceRoot,storeRoot))throw new Error('JPG store must remain inside an authorized workspace root');
const output=join(root,paid?'docs/repair-2026-10-08/campaigns':'docs/repair-2026-10-08/software-preparation',campaign),store=join(storeRoot,campaign);
mkdirSync(output,{recursive:true});mkdirSync(store,{recursive:true});
const cap=Number(process.env.OBJRUN_REPAIR_BUDGET_USD??15),maxTokens=8192;
const key=paid?process.env.DEEPSEEK_API_KEY:randomBytes(24).toString('hex');if(!key)throw new Error('Project model credential missing');
const reconcileReceiptCost:typeof actualCost=(receipt,reserve,options={})=>actualCost(receipt,paid?reserve:0,paid?options:{...options,knownUncharged:true,rates:{input:0,cachedInput:0,output:0}as never});
const mockSteps=new Map<string,number>();
const providerFetch=async(url:Parameters<typeof fetch>[0],init?:Parameters<typeof fetch>[1],route='')=>{
 if(paid)return await fetch(url,init);if(!['mock','docker-mock'].includes(mode))throw new Error('Preparation cannot call an LLM');
 const body=JSON.parse(String(init?.body)),arm=route.includes('/F/')?'F':'U',index=mockSteps.get(arm)??0;mockSteps.set(arm,index+1);const call=mockCall(index,arm,live);
 if(body.tool_choice?.function?.name==='submit'){call.name='submit';call.args={answer:'mock-workbook'};}
 if(!(body.tools??[]).some((item:any)=>item.function?.name===call.name))throw new Error('Mock tool unavailable');
 return Response.json({id:'local-skb-mock-'+arm+'-'+index,model:'local-mock',choices:[{finish_reason:'tool_calls',message:{role:'assistant',content:null,tool_calls:[{id:'local-'+arm+'-'+index,type:'function',function:{name:call.name,arguments:JSON.stringify(call.args)}}]}}],usage:{prompt_tokens:1,completion_tokens:1}});
};
type CaptureError = { stage: string; at: string; requestSha256?: string };
type CallReceipt = ApiReceipt & { route: string; startedAt: string; requestSha256: string; requestedModel: string; servedModel?: string; requestId?: string; usage?: Record<string, unknown>; requestFile?: string; responseFile?: string; responseSha256?: string; wireParameters?: Record<string, unknown>; providerAttempted: boolean; captureErrors?: CaptureError[]; providerFault?: string };
const calls: CallReceipt[] = [];
const captureErrors: CaptureError[] = [];
let spent = 0, reserved = 0, fatal: string | undefined;
const pending = new Map<string, number>();
const closedRoutes = new Set<string>(), blockedAfterDelivery: {route:string;at:string}[] = [];
function ledger() { save(join(output, "api-ledger.json"), { campaign, capUsd: cap, priorCampaignCostUpperBoundUsd: priorCampaignCost, recordedUsageUpperBoundUsd: spent, reservedUpperBoundUsd: reserved, fatal, pending: Object.fromEntries(pending), blockedAfterDelivery, captureErrors, calls }); }
const authorization = `Bearer ${key}`;
if (!Number.isFinite(cap) || cap <= 0) throw new Error("A positive finite campaign budget is required");
let priorCampaignCost = 0;
const campaignRoot = dirname(output);
for (const name of readdirSync(campaignRoot)) {
  if (name === campaign) continue;
  const previous = join(campaignRoot, name, "api-ledger.json");
  if (!existsSync(previous)) continue;
  const data = JSON.parse(readFileSync(previous, "utf8"));
  const prior = data.recordedUsageUpperBoundUsd, outstanding = data.reservedUpperBoundUsd;
  if (typeof prior !== "number" || typeof outstanding !== "number" || !Number.isFinite(prior) || !Number.isFinite(outstanding) || prior < 0 || outstanding < -1e-9) throw new Error(`Invalid prior cost ledger: ${name}`);
  // Preserve old raw ledgers; numerical cancellation can leave a negative fraction of a nanodollar.
  priorCampaignCost += prior + Math.max(0, outstanding);
}
const proxy = Bun.serve({ hostname: "127.0.0.1", port: 0, maxRequestBodySize: 4 * 1024 * 1024,
  async fetch(request) {
    const supplied = request.headers.get("authorization") ?? "";
    const a = Buffer.from(supplied), b = Buffer.from(authorization);
    if (a.length !== b.length || !timingSafeEqual(a, b)) return Response.json({ error: { message: "Unauthorized local API proxy" } }, { status: 401 });
    const captureFailure = (stage: string, record?: CallReceipt) => {
      const error: CaptureError = { stage, at: new Date().toISOString(), ...(record ? { requestSha256: record.requestSha256 } : {}) };
      captureErrors.push(error);
      fatal ??= "local_evidence_error";
      if (record) {
        if (record.fault && record.fault !== "capture_error") record.providerFault ??= record.fault;
        record.fault = "capture_error";
        (record.captureErrors ??= []).push(error);
      }
    };
    const persistLedger = (stage: string, record?: CallReceipt) => {
      try { ledger(); return true; }
      catch { captureFailure(stage, record); return false; }
    };
    const url = new URL(request.url);
    if (request.method !== "POST" || !url.pathname.endsWith("/chat/completions")) return Response.json({ error: { message: "Unsupported local API route" } }, { status: 404 });
    const route = url.pathname.slice(1, -"/v1/chat/completions".length);
    if (closedRoutes.has(route)) { blockedAfterDelivery.push({route,at:new Date().toISOString()}); persistLedger('post_delivery_block'); return Response.json({error:{message:'Task delivery closed the model route'}},{status:409}); }
    const raw = await request.text();
    let body: Record<string, unknown>;
    try { body = JSON.parse(raw); } catch { return Response.json({ error: { message: "Invalid API request JSON" } }, { status: 400 }); }
    if (body.model !== "deepseek-flash" || body.stream === true) return Response.json({ error: { message: "Only the frozen non-streaming model route is permitted" } }, { status: 400 });
    let outputLimit: number;
    try { outputLimit = checkedOutputTokens(body); }
    catch { fatal = "invalid_request_output_limit"; persistLedger("invalid_limit_ledger"); return Response.json({ error: { message: "Invalid frozen output token limit" } }, { status: 400 }); }
    const inputUpper = Buffer.byteLength(raw) + 2048 + (Array.isArray(body.messages) ? body.messages.length * 256 : 0);
    const reserve = (inputUpper * 0.3 + outputLimit * 1.2) / 1e6;
    let disk;
    try { disk = statfsSync(store); }
    catch { captureFailure("disk_status"); persistLedger("disk_status_ledger"); return Response.json({ error: { message: "Campaign stopped: evidence storage unavailable" } }, { status: 503 }); }
    if (disk.bavail * disk.bsize < 512 * 1024 * 1024) { fatal = "local_disk_low"; persistLedger("disk_guard_ledger"); return Response.json({ error: { message: "Campaign stopped: insufficient evidence storage space" } }, { status: 507 }); }
    if (fatal || priorCampaignCost + spent + reserved + reserve > cap) {
      fatal ??= "local_budget_exhausted"; persistLedger("stopped_ledger");
      return Response.json({ error: { message: "Campaign stopped: infrastructure or local budget limit", code: "insufficient_quota" } }, { status: 402 });
    }
    const sequence = calls.length;
    const requestFile = join(store, `provider-${sequence}-request.json.gz`);
    const record: CallReceipt = { route, startedAt: new Date().toISOString(), requestSha256: sha(raw), requestedModel: String(body.model), requestFile, providerAttempted: false,
      wireParameters: Object.fromEntries(["model", "temperature", "seed", "reasoning_effort", "thinking", "max_tokens", "max_completion_tokens", "tool_choice", "response_format", "stream"].filter(k => k in body).map(k => [k, body[k]])) };
    let allocated = false, forwarded = false;
    let stage = "request_reservation";
    let result = Response.json({ error: { message: "Campaign call did not complete" } }, { status: 503 });
    try {
      calls.push(record);
      reserved += reserve;
      pending.set(route, (pending.get(route) ?? 0) + 1);
      allocated = true;
      stage = "request_capture";
      writeFileSync(requestFile, gzipSync(raw));
      stage = "initial_ledger";
      ledger();
      stage = "provider_request";
      forwarded = true;
      record.providerAttempted = true;
      const response = await providerFetch("https://api.deepseek.com/chat/completions", { method: "POST", headers: { "content-type": "application/json", authorization }, body: raw, signal: AbortSignal.timeout(300000) }, route);
      record.httpStatus = response.status;
      stage = "provider_response";
      const text = await response.text();
      record.responseFile = join(store, `provider-${sequence}-response.json.gz`);
      stage = "response_capture";
      writeFileSync(record.responseFile, gzipSync(text));
      record.responseSha256 = sha(text);
      stage = "provider_decision";
      let data: Record<string, unknown>;
      try { data = JSON.parse(text); } catch { record.fault = "InvalidProviderJSON"; fatal = record.fault; throw new Error(record.fault); }
      record.servedModel = typeof data.model === "string" ? data.model : undefined;
      record.requestId = typeof data.id === "string" ? data.id : undefined;
      if (data.usage && typeof data.usage === "object") record.usage = data.usage as Record<string, unknown>;
      spent += reconcileReceiptCost(record, reserve, { knownUncharged: !record.usage && [401, 402, 403].includes(response.status) }).deltaUsd;
      if (response.ok) {
        if (!validTokenUsage(record.usage)) throw new Error("MissingOrInvalidProviderTokenUsage");
        record.completionFault = completionFault(data);
        record.completionValid = !record.completionFault;
        if (record.completionFault) throw new Error(record.completionFault);
      } else if (![401, 402, 403].includes(response.status)) {
        record.fault = "ProviderUnsuccessfulResponse"; fatal = record.fault;
      }
      if ([401, 402, 403].includes(response.status)) fatal = `provider_http_${response.status}`;
      result = new Response(text, { status: response.status, headers: { "content-type": "application/json" } });
    } catch (error) {
      if (["request_reservation", "request_capture", "initial_ledger", "response_capture"].includes(stage)) captureFailure(stage, record);
      else {
        record.fault = error instanceof Error ? error.name + ":" + error.message : "ProviderTransportError";
        fatal ??= "unreconciled_provider_call";
      }
      // A local failure before forwarding is provably uncharged; an attempted
      // provider call can be charged without usage, so retain its reservation.
      spent += reconcileReceiptCost(record, reserve, { knownUncharged: !forwarded }).deltaUsd;
      result = Response.json({ error: { message: "Campaign call or evidence capture failed; further calls stopped" } }, { status: 503 });
    } finally {
      if (allocated) {
        reserved = Math.max(0, reserved - reserve);
        pending.set(route, Math.max(0, (pending.get(route) ?? 1) - 1));
      }
      record.finishedAt = new Date().toISOString();
      if (!persistLedger("final_ledger", record)) result = Response.json({ error: { message: "Campaign stopped: evidence ledger could not be saved" } }, { status: 503 });
    }
    return result;
  },
});

const taskRoot=join(root,'.phase1-data/skillsbench/vendor/skillsbench/tasks',TASK_ID);
const artifacts:{path:string;name:string;sha256:string}[]=[];
artifacts.push({path:nativePython.executable,name:'host-execution/native-python.exe',sha256:nativePython.sha256},{path:NATIVE_PROFILE_PATH,name:'host-execution/native-python-profile.json',sha256:nativePython.profileSha256});
for(const [name,want]of Object.entries(OFFICIAL_HASHES)){const path=join(taskRoot,name);if(sha(readFileSync(path))!==want)throw new Error('Official JPG source changed: '+name);artifacts.push({path,name:'official/'+name,sha256:want});}
const walk=(directory:string):string[]=>readdirSync(directory,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?walk(join(directory,entry.name)):[join(directory,entry.name)]);
for(const path of walk(join(taskRoot,'environment')))artifacts.push({path,name:'public-environment/'+relative(join(taskRoot,'environment'),path).replaceAll('\\','/'),sha256:sha(readFileSync(path))});
const runtimeDir=join(root,'examples/benchmark/terminal-bench/.runtime'),runtime=JSON.parse(readFileSync(join(runtimeDir,'manifest.json'),'utf8'));
for(const [name,want]of Object.entries(runtime.assets)){const path=join(runtimeDir,name);if(sha(readFileSync(path))!==want)throw new Error('Frozen six-tool asset changed');artifacts.push({path,name:'runtime/'+name,sha256:String(want)});}
artifacts.push({path:join(runtimeDir,'manifest.json'),name:'runtime/manifest.json',sha256:sha(readFileSync(join(runtimeDir,'manifest.json')))});
for(const [path,want]of Object.entries(runtime.frozenSources))if(sha(readFileSync(join(root,path)))!==want)throw new Error('Frozen executor core source changed');
if(live){for(const [name,path]of Object.entries(paths))artifacts.push({path:path!,name:'gate/'+name+'.json',sha256:sha(readFileSync(path!))});for(const item of gate.profile.assets){const path=resolve(dirname(paths.profile!),item.path);if(!path.startsWith(resolve(dirname(paths.profile!))+'/')&&!path.startsWith(resolve(dirname(paths.profile!))+'\\'))throw new Error('Profile path escape');if(sha(readFileSync(path))!==item.sha256)throw new Error('JPG private dependency asset changed');artifacts.push({path,name:'grader-dependencies/'+item.path,sha256:item.sha256});}}
if(live){const name='software-jpg-build.py',path=join(import.meta.dir,name),actual=sha(readFileSync(path));if(gate.image.executorSourceHashes?.[name]!==actual||gate.build.executorSourceHashes?.[name]!==actual)throw new Error('Actual JPG image construction recipe source changed');artifacts.push({path,name:'image-construction/'+name,sha256:actual});}
const sourcePath=join(output,'source.json');execFileSync(process.execPath,[join(root,'scripts/phase1/source-snapshot.ts'),sourcePath],{cwd:root,windowsHide:true});
const source=JSON.parse(readFileSync(sourcePath,'utf8'));
source.repairFiles=[basename(import.meta.path),'skb-jpg-contract.ts','skb-jpg-stand.py','skb-jpg-host-ops.py','skb-jpg-audit.ts','skb-jpg-native-python.ts','skb-jpg-native-bootstrap.py','skb-jpg-native-python.json','software-jpg-private-grader.py','freeze-skb-source.py','tb-engine.ts','tb-tool-gateway.ts','tb-nginx-contract.ts','campaign-contract.ts','paid-campaign-lock.ts'].map(name=>({path:'scripts/repair-2026-10-08/'+name,sha256:sha(readFileSync(join(import.meta.dir,name)))}));
const referenceArchive=resolve(process.env.OBJRUN_SKB_ARCHIVE_BASE??join(cEvidenceRoot,'experiment-stores/skb-jpg-2026-10-08T10-44-53-897Z/frozen-source.zip'));
if(!inside(root,referenceArchive)&&!inside(cEvidenceRoot,referenceArchive))throw new Error('Dependency archive reference must remain inside an authorized workspace');
if(!existsSync(referenceArchive))throw new Error('The immutable public dependency archive must exist before JPG preparation');
source.dependencyArchiveReference={path:referenceArchive,sha256:sha(readFileSync(referenceArchive)),scope:'Only explicitly enumerated npm/Node/private-grader public dependency members are used; all older executable source and host-only task data in the base archive are unreferenced.'};
source.artifacts=artifacts;source.executionDigest=sha(JSON.stringify({sourceDigest:source.sourceDigest,repairFiles:source.repairFiles,artifacts,dependencyArchiveReference:source.dependencyArchiveReference}));save(sourcePath,source);
let dependencyMembers:{sourcePath:string;sha256:string}[]=[];
const validateSource=()=>{for(const file of [...source.files.filter((file:any)=>file.path.startsWith('app/src/')||file.path==='test/_lib.ts'),...source.repairFiles])if(sha(readFileSync(join(root,file.path)))!==file.sha256)throw new Error('Executed JPG source changed: '+file.path);for(const item of artifacts)if(sha(readFileSync(item.path))!==item.sha256)throw new Error('Frozen JPG data/profile asset changed: '+item.name);if(sha(readFileSync(referenceArchive))!==source.dependencyArchiveReference.sha256)throw new Error('Immutable dependency archive changed');};
const publicPrompt=readFileSync(join(taskRoot,'task.md'),'utf8')+'\n\nWork only inside your task container. Deliver the single regular workbook at /app/workspace/stat_ocr.xlsx using submit; the submitted text is only an attempt label. Only use verify when offered.';
let actualImage:any;
if(live){actualImage=JSON.parse(execFileSync('docker',['image','inspect',gate.image.imageId],{windowsHide:true,encoding:'utf8'}))[0];if(actualImage.Id!==gate.image.imageId||(actualImage.Config?.Labels?.['objrun.skb.task-id'])!==TASK_ID)throw new Error('Actual complete JPG image identity mismatch');}
const manifest={schemaVersion:2,campaign,createdAt:new Date().toISOString(),profile:paid?'pilot':'zero-cost-preparation',benchmarks:['skillsbench'],arms:['U','F'],independentRReplicas:5,concurrency:1,model:'deepseek-flash',temperature:0,seed:42,reasoningEffort:'none',maxTokensPerRequest:maxTokens,provider:paid?'https://api.deepseek.com':'local-mock',taskSeconds:SECONDS,verifierSeconds:VERIFY_SECONDS,checksPerAttempt:CHECKS,queryBudgetSource:'ObjRun existing CHECKS=6; the original task declares no number of G queries',tools:[...SIX_TOOLS,'submit'],feedback:'F only',reuse:'never',maxBranchesF:1,maxBranchesUR:1,maxDeadSiblingsF:1,sourceExecutionDigest:source.executionDigest,capUsd:cap,priorCampaignCostUpperBoundUsd:priorCampaignCost,storage:{output,store,storeRoot,configuredBy:process.env.OBJRUN_SKB_STORE_ROOT?'OBJRUN_SKB_STORE_ROOT':'authorized C workspace default'},datasets:{skillsbench:{source:JSON.parse(readFileSync(join(root,'.phase1-data/skillsbench/source.json'),'utf8')),selectedTaskIds:[TASK_ID],sourceTaskCount:87,supportedTaskCount:1,unsupportedTaskCount:86,readyTaskIds:[],publicTaskDigest:sha(publicPrompt)}},artifact:{path:ARTIFACT,regularOnly:true,maxBytes:8*1024**2,candidateStoppedBeforeCapture:true,privateGraderNetwork:'none',candidateInterpreterOrSnapshotUsed:false},runtime,gate:{passed:!gateError,reason:gateError,formalLlmClosedLoopValidated:false},actualImage,mockOnly:!paid,protocolLimits:['Only JPG implemented; the other86 tasks stay unsupported','prepare/mock do not certify official controls or LLM scores','Same cold original task image per U/F; no candidate executable/environment copied to grader','F may pause candidate for pure output feedback; final seal drains all admitted API tools and freezes workbook before private grading','Each tool RPC has an 890s completion guard; artifact Docker transport90s; official agent1800s/verifier600s','Private grader128MiB writable reserve and output8MiB limits are explicit operational constraints']};
Object.assign(manifest,{hostOperationalLimits:{candidateWritableMaxBytes:256*1024**2,privateGraderWritableMaxBytes:128*1024**2,artifactTransportSeconds:90,privateCliSeconds:650,minimumCFreeBytes:1536*1024**2,minimumFFreeBytes:1152*1024**2,minimumFFreeBytesBeforePaid:1536*1024**2,officialTaskStorageBytes:10*1024**3,scope:'Declared local host resource constraints; no claim that they replace the official 10GiB storage allowance'}});
Object.assign(manifest,{executionMode:mode,candidateBackend:live?'docker':'simulated',tarExtensionMetadataMaxBytes:256*1024});
Object.assign(manifest,{bridgeLifecycle:{protocol:LIFECYCLE_PROTOCOL,nativeExecutable:nativePython.executable,nativeExecutableSha256:nativePython.sha256,nativeExecutableBytes:nativePython.bytes,nativeProfileSha256:nativePython.profileSha256,healthMustMatchChildPid:true,bootstrapReceiptFsynced:true,terminationGraceMs:1500,terminationForceMs:1500,listenerCloseMs:600,scope:'Actual same-process native Python service and port only; arbitrary grandchildren are not certified'}});
save(join(output,'manifest.json'),manifest);save(join(output,'skillsbench-public-tasks.json'),[{officialId:TASK_ID,promptSha256:sha(publicPrompt),row:{id:TASK_ID,prompt:publicPrompt,seconds:SECONDS,workdir:'/app/workspace'}}]);
const disk=statfsSync(store),fDisk=statfsSync(root),cDisk=statfsSync(cEvidenceRoot);
if(fDisk.bavail*fDisk.bsize<(live?1536:1152)*1024**2||cDisk.bavail*cDisk.bsize<1536*1024**2||disk.bavail*disk.bsize<(inside(cEvidenceRoot,store)?1552:1168)*1024**2)throw new Error('JPG freeze requires preserved C/F and archive storage reserves');
execFileSync(nativePython.executable,['-B','-X','utf8',join(import.meta.dir,'freeze-skb-source.py'),output,store],{cwd:root,windowsHide:true,stdio:'ignore',timeout:120000});
const frozen=JSON.parse(readFileSync(join(output,'frozen-source.json'),'utf8'));dependencyMembers=frozen.dependencyReferences.members;
source.executionDigest=sha(JSON.stringify({preFreezeExecutionDigest:source.executionDigest,dependencyMembersDigest:frozen.dependencyReferences.membersSha256}));save(sourcePath,source);frozen.sourceExecutionDigest=source.executionDigest;save(join(output,'frozen-source.json'),frozen);manifest.sourceExecutionDigest=source.executionDigest;Object.assign(manifest,{dependencyArchiveReference:source.dependencyArchiveReference,dependencyMembersDigest:frozen.dependencyReferences.membersSha256});save(join(output,'manifest.json'),manifest);
if(mode==='prepare'){
 validateSource();save(join(output,'preparation.json'),{prepared:true,paidReady:!gateError,readyTaskIds:[],implementedTaskIds:[TASK_ID],unsupportedTaskCount:86,gateError,llmRequests:0,officialControlsExecuted:false});ledger();console.log(JSON.stringify({output,prepared:true,paidReady:!gateError,llmRequests:0,gateError}));await proxy.stop(true);paidLock?.release();
}else{
 const tempServer=Bun.serve({hostname:'127.0.0.1',port:0,fetch:()=>new Response('')}),port=tempServer.port;await tempServer.stop(true);
 const stand='http://127.0.0.1:'+port,token=randomBytes(32).toString('hex');process.env.TGENGIN_GRADER_TOKEN=token;process.env.OBJRUN_SKB_MOCK_KEY=key;
 const gateway=tbToolGateway({stand,token,store:join(store,'tool-receipts'),ledger:receipts=>save(join(output,'tool-ledger.json'),{campaign,receipts})});process.env.TGENGIN_GRADER_ORIGINS=stand+','+gateway.origin;
 const argv=['--mode',live?'live':'mock','--port',String(port),'--home',join(store,'stand')];if(live)argv.push('--image-manifest',paths.image!,'--build-proof',paths.build!,'--dependency-profile',paths.profile!);
 const bridgeProcess=launchNativeJpgService({script:join(import.meta.dir,'skb-jpg-stand.py'),argv,home:join(store,'stand'),port,env:{...process.env}}),child=bridgeProcess.child;let standLog='';child.stdout?.on('data',chunk=>{standLog+=chunk;});child.stderr?.on('data',chunk=>{standLog+=chunk;});
 const records:any[]=[],privateConfigs:string[]=[],evidenceSecrets:string[]=[token,key!];let engine:Awaited<ReturnType<typeof tbEngine>>|undefined,livePlace:string|undefined;
 const request=async(path:string,body:unknown)=>{const response=await graderFetch(stand+path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(930000)});const value=await response.json();if(!response.ok)throw new Error('JPG host capture/grader operation invalid: '+path);return value;};
 try{
  const health=await bridgeProcess.waitReady();if(!health||health.denominator!==87||health.unsupportedTaskCount!==86||health.authenticated!==true||health.backend!==(live?'live':'mock'))throw new Error('JPG bridge readiness invalid');
  save(join(output,'bridge-health.json'),health);
  for(const arm of ['U','F']){
   validateSource();const index=records.length,id=campaign+'/skillsbench/'+arm+'/0/'+TASK_ID,place='skb:'+id,route=id;livePlace=place;const directory=join(store,'worker-'+arm);mkdirSync(directory,{recursive:true});engine=await tbEngine({maxTokens,retryTimes:0,continueTimes:0,reasoningEffort:'none',temperature:0,seed:42},directory);
   const privateConfig=join(directory,'config.yaml'),config=readFileSync(privateConfig,'utf8'),credentials=/api: \{prefix: \/api, token: ("[^"]+"), publisherToken: ("[^"]+")/.exec(config);if(!credentials)throw new Error('Private engine credential evidence unavailable');privateConfigs.push(privateConfig);evidenceSecrets.push(JSON.parse(credentials[1]!),JSON.parse(credentials[2]!));
   const authProbe:any[]=[];for(const path of ['/exec','/tasks','/declare'])for(const forged of [false,true]){const response=await fetch(engine.base+path,{method:'POST',headers:{'content-type':'application/json',...(forged?{authorization:'Bearer forged','X-TGEngin-Publisher':'forged'}:{})},body:JSON.stringify(path==='/exec'?{sql:'select 1'}:{})});authProbe.push({path,forged,status:response.status});if(response.status!==401)throw new Error('Private JPG engine admission was not protected');}save(join(output,'host-auth-'+arm+'.json'),{probes:authProbe,missingAndForgedRejected:true,mockOnly:!paid});
   const apiEnv=paid?'DEEPSEEK_API_KEY':'OBJRUN_SKB_MOCK_KEY';await engine.api('POST','/exec',{sql:"insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select :key,'deepseek-flash',handle,modes,:base,'[]' from api where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'",params:{key:apiEnv,base:'http://127.0.0.1:'+proxy.port+'/'+route+'/v1'}});
   const databasePath=join(directory,'data/h2h.sqlite');gateway.register(place,()=>{const db=new Database(databasePath,{readonly:true});try{const row=db.query('select state,created_at,solve_seconds from task where id=?').get(id)as any;if(!row)return undefined;if(Date.now()>=row.created_at+row.solve_seconds*1000)return 'task_deadline';if(['done','failed'].includes(row.state))return 'task_terminal';return db.query("select 1 from agent_bot_msg where instance like ? and kind='tool' and json_valid(body) and json_extract(body,'$.name')='submit' limit 1").get(id+'#%')?'task_delivered':undefined;}finally{db.close();}});
   await engine.api('POST','/declare',{handles:[{name:gateway.origin+'/place',expectMs:930000},...['verified','passed'].map(name=>({name:stand+'/'+name,expectMs:650000}))],places:[{place,identity:gateway.origin+'/place',forward:true,tools:SIX_TOOLS.map(tool=>({tool,policy:'always'}))}],modes:[{mode:'repair_jpg',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:32,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:32,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[[apiEnv,'deepseek-flash']],unit:'fn:unit.tools'}]});await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('bash','read','write','edit','glob','grep','submit','verify')"});
   await request('/register',{place,taskId:id,databasePath});const cold=await request('/place',{place,op:'ping'});if(!cold.alive)throw new Error('Cold JPG candidate/runtime failed before generation');if(live&&(!cold.environmentAudit||cold.environmentAudit.forbiddenHostKeysPresent!==false||cold.environmentAudit.standTokenPresent!==false))throw new Error('Cold JPG environment credential gate failed');save(join(output,'cold-candidate-'+arm+'.json'),cold);
   await engine.api('POST','/tasks',{id,run:campaign,mode:'repair_jpg',agent:'bot',place,source:'user',domain:'software',workdir:'/app/workspace',description:publicPrompt,...(arm==='F'?{objective:jpgObjective(stand),readable:false}:{}),solveSeconds:SECONDS,maxBranches:1,maxDeadSiblings:1,noSearch:['jpg-ocr-stat solution']});
   let task:any;const start=Date.now();while(Date.now()-start<(SECONDS+1400)*1000){const value=await engine.api<any>('GET','/tasks/'+encodeURIComponent(id));const verdict=value.result?JSON.parse(value.result):null;if(['done','failed'].includes(value.state)&&!['finalization_pending','finalization_error'].includes(verdict?.outcome)){task=value;gateway.seal(place);closedRoutes.add(route);if(!(pending.get(route)??0))break;}await Bun.sleep(100);}if(!task)throw new Error('JPG task did not finalize');
   const quiescence=await gateway.drain(place);save(join(output,'quiescence-'+index+'.json'),quiescence);
   for(let i=0;i<100;i++){const status=await engine.api<{rows:{done:number}[]}>('POST','/query',{sql:'select done from agent_bot_ctx where instance like :prefix',params:{prefix:id+'#%'}});if(status.rows.every(row=>row.done===1))break;await Bun.sleep(50);}
   const trace=await engine.api<{rows:any[]}>('POST','/query',{sql:'select * from agent_bot_msg where instance like :prefix order by unit,seq',params:{prefix:id+'#%'}}),units=await engine.api<{rows:any[]}>('POST','/query',{sql:'select * from agent_bot_ctx where instance like :prefix order by unit',params:{prefix:id+'#%'}});const pid=engine.pid;await engine.stop();engine=undefined;
   const db=new Database(databasePath,{readonly:true});let candidate:{body:string;how:string}|undefined;try{candidate=finalCandidate({all:(sql,params)=>db.query(sql).all(...((params??[])as never[]))as any[],run(){throw new Error('readonly');},exec(){throw new Error('readonly');},close(){}},id);}finally{db.close();}
   const capture=await request('/capture',{place,final:true});save(join(output,'capture-'+index+'.json'),capture);const removed=await request('/stop',{place});if(removed.ok!==true||removed.ownedContainersRemaining!==0)throw new Error('JPG candidate removal did not certify');livePlace=undefined;
   const runtimeVerdict=task.result?JSON.parse(task.result):{valid:true,outcome:'unaided_generated'},deadline=Number(task.created_at)+SECONDS*1000;
   const generation=jpgGeneration({runtimeVerdict,state:task.state,calls:calls.filter(call=>call.route===route),trace:trace.rows,candidate:candidate?.body,deadline,receipts:quiescence.receipts,capture});if(units.rows.some(row=>row.done!==1)){generation.valid=false;generation.kind='infrastructure_error';generation.outcome='unfinished_tool_unit';}
   const record:any={index,benchmark:'skillsbench',arm,replica:0,officialId:TASK_ID,taskId:id,state:task.state,place,runtimeVerdict,generationValid:generation.valid,generationClassification:generation,actualCreatedAt:task.created_at,deadline:new Date(deadline).toISOString(),answer:candidate?.body??'',candidateHow:candidate?.how??'none',candidateSha256:sha(candidate?.body??''),artifactSha256:capture.artifactSha256??null,artifactCapture:capture,promptSha256:sha(publicPrompt),traceSha256:sha(JSON.stringify(trace.rows)),apiCalls:calls.filter(call=>call.route===route),worker:arm,workerPid:pid,engineStoppedBeforeAcceptance:true,toolQuiescence:quiescence,acceptance:{valid:false,outcome:'pending_after_all_generation'}};
   validateSource();
   if(live){let graded:any;if(generation.valid&&generation.kind==='candidate')graded=await request('/grade-captured',{place,captureReceiptPath:capture.captureReceiptPath});record.acceptance=artifactVerdict(graded,capture,record.candidateSha256,generation);}
   else record.acceptance={valid:false,passed:false,outcome:'simulated_grader_no_official_tests',mockOnly:true,officialGradingValid:false};
   validateSource();records.push(record);save(join(output,'task-'+index+'.json'),{...record,trace:trace.rows,units:units.rows});save(join(output,'summary.json'),{campaign,completed:false,mockCompleted:false,plannedTaskRuns:2,recordedTaskRuns:records.length,recordedUsageUpperBoundUsd:spent,fatal,records,mockOnly:!paid});
   if(live&&record.acceptance.valid!==true){fatal??='invalid_jpg_record';break;}
  }
  validateSource();save(join(output,'summary.json'),{campaign,completed:false,mockCompleted:false,closing:true,plannedTaskRuns:2,recordedTaskRuns:records.length,recordedUsageUpperBoundUsd:spent,fatal,records,mockOnly:!paid,formalLlmClosedLoopValidated:false,readyTaskIds:[]});ledger();
 }catch(error){fatal??=error instanceof Error?error.message:'JpgRunnerError';save(join(output,'summary.json'),{campaign,completed:false,mockCompleted:false,mockOnly:!paid,plannedTaskRuns:2,recordedTaskRuns:records.length,fatal,records});ledger();throw error;}
 finally{
  const phases:string[]=[],cleanupErrors:{stage:string;message:string}[]=[];let bridgeClosure:any;
  const mark=(phase:string)=>{phases.push(phase);save(join(output,'cleanup.json'),{phases,bridgePid:child.pid,actualBridgePid:bridgeProcess.identity?.pid,bridgeClosure,errors:cleanupErrors,closed:false});};
  const attempt=async(stage:string,action:()=>Promise<unknown>|unknown)=>{try{await action();mark(stage);}catch(error){cleanupErrors.push({stage,message:error instanceof Error?error.message:'cleanup failed'});mark(stage+'_failed');}};
  mark('begin');
  if(livePlace){gateway.seal(livePlace);closedRoutes.add(livePlace.slice(4));}
  await attempt('engine_stopped',async()=>{if(engine)await engine.stop();});
  let candidateRemoved=!livePlace;
  if(livePlace)await attempt('candidate_stopped',async()=>{await gateway.drain(livePlace!);const removed=await request('/stop',{place:livePlace});if(removed.ok!==true||removed.ownedContainersRemaining!==0)throw new Error('Candidate cleanup was not certified');candidateRemoved=true;});
  else mark('candidate_stopped');
  await attempt('bridge_stopped',async()=>{bridgeClosure=await bridgeProcess.stop();save(join(output,'bridge-process-closure.json'),bridgeClosure);if(!bridgeClosure.closed||!bridgeClosure.identityVerified||bridgeClosure.childPid!==bridgeProcess.identity?.pid)throw new Error('Actual native JPG service and listener closure did not certify');});
  if(live&&!candidateRemoved)await attempt('exact_bridge_recovery',()=>{if(!bridgeProcess.identity||!bridgeClosure?.closed)throw new Error('Actual native bridge identity/exit is required before owned recovery');execFileSync(nativePython.executable,['-B','-X','utf8',join(import.meta.dir,'skb-jpg-host-ops.py'),'--recover','--output',join(store,'stand'),'--process-id',String(bridgeProcess.identity.pid),'--image-id',gate.image.imageId],{windowsHide:true,timeout:90000,stdio:'ignore'});candidateRemoved=true;});
  await attempt('stand_log_saved',()=>writeFileSync(join(store,'stand.log'),standLog));
  await attempt('gateway_stopped',()=>gateway.stop());await attempt('proxy_stopped',()=>proxy.stop(true));
  const settleUntil=Date.now()+310000;while(Array.from(pending.values()).some(value=>value>0)&&Date.now()<settleUntil)await Bun.sleep(50);
  const receiptsClosed=reserved<=1e-9&&Array.from(pending.values()).every(value=>value===0)&&calls.every(call=>!!call.finishedAt);
  if(!receiptsClosed)fatal??='unreconciled_calls_during_shutdown';
  ledger();
  if(evidenceSecrets.length===6)await attempt('evidence_credentials_absent',()=>auditJpgEvidence({script:join(import.meta.dir,'skb-jpg-host-ops.py'),output,store,privateConfigs,secrets:evidenceSecrets}));
  else if(records.length===2)cleanupErrors.push({stage:'evidence_credentials_absent',message:'Both private engine credential sets were not captured for exact audit'});
  await attempt('source_closed',validateSource);
  await attempt('dependency_bytes_closed',()=>{for(const member of dependencyMembers)if(sha(readFileSync(member.sourcePath))!==member.sha256)throw new Error('Executed public dependency bytes changed');});
  const closed=receiptsClosed&&candidateRemoved&&cleanupErrors.length===0;
  if(!closed)fatal??='owned_cleanup_or_source_incomplete';
  const completed=paid&&!fatal&&closed&&campaignComplete(2,records),mockCompleted=!paid&&!fatal&&closed&&records.length===2&&records.every(record=>record.generationValid&&(!live||record.acceptance.valid));
  ledger();save(join(output,'cleanup.json'),{phases:[...phases,closed?'complete':'lock_preserved'],bridgePid:child.pid,actualBridgePid:bridgeProcess.identity?.pid,bridgeClosure,errors:cleanupErrors,closed,receiptsClosed,candidateRemoved});
  save(join(output,'summary.json'),{campaign,completed,mockCompleted,dockerArtifactClosedLoopValidated:mode==='docker-mock'&&mockCompleted,plannedTaskRuns:2,recordedTaskRuns:records.length,recordedUsageUpperBoundUsd:spent,fatal,records,mockOnly:!paid,formalLlmClosedLoopValidated:completed,readyTaskIds:completed?[TASK_ID]:[],receiptClosure:receiptsClosed,sourceClosure:!cleanupErrors.some(error=>error.stage==='source_closed'),cleanupClosed:closed});
  if(closed)paidLock?.release();
  console.log(JSON.stringify({output,completed,mockCompleted,realLLMRequests:paid?calls.length:0,mockRequests:paid?0:calls.length,recordedUsageUpperBoundUsd:spent,officialControlsExecuted:false,cleanupClosed:closed}));process.exitCode=completed||mockCompleted?0:1;
 }
}

// All servers/owned engines and the shared receipt queue have closed before CLI exit.
process.exit(process.exitCode??0);
