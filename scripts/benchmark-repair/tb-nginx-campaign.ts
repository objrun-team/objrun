import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import { spawn, execFileSync, type ChildProcess } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, statfsSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { gzipSync } from 'node:zlib';
import { Database } from 'bun:sqlite';
import type { Machine } from '../../test/_lib.ts';
import { tbEngine } from './tb-engine.ts';
import { graderFetch } from '../../app/src/engine/registry.ts';
import { finalCandidate } from '../../app/src/objective/candidate.ts';
import { campaignComplete, checkedOutputTokens, completionFault, gradeFixedCandidate, reconcileReceiptCost as actualCost, validTokenUsage, type ApiReceipt, type GenerationClassification } from './campaign-contract.ts';
import { IMAGE_ID, TASK_ID, SIX_TOOLS, OFFICIAL_HASHES, requireSafeHealth, requireNginxPreflight, nginxObjective, nginxGeneration, mockCall } from './tb-nginx-contract.ts';
import { acquirePaidCampaignLock } from './paid-campaign-lock.ts';
import { tbToolGateway } from './tb-tool-gateway.ts';

const root = resolve(import.meta.dir, '../..');
const mode = process.argv[2] ?? 'prepare';
if (!['prepare', 'mock', 'run'].includes(mode)) throw new Error('usage: bun tb-nginx-campaign.ts prepare|mock|run');
const paid = mode === 'run';
if (paid && !process.env.OBJRUN_TB_PREFLIGHT_JSON) throw new Error('Paid TB is blocked until OBJRUN_TB_PREFLIGHT_JSON points at current valid empty/oracle controls');
const sha = (value: string | Buffer) => createHash('sha256').update(value).digest('hex');
const save = (path: string, value: unknown) => { mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, JSON.stringify(value, null, 2) + '\n'); };
const feeRoot = join(root, 'docs/repair-2026-10-08/campaigns');
if (paid) for (const name of readdirSync(feeRoot)) {
  const path = join(feeRoot, name, 'summary.json');
  if (!existsSync(path)) continue;
  const summary = JSON.parse(readFileSync(path, 'utf8'));
  if (summary.completed !== true && !summary.fatal) throw new Error('Another unfinished fee campaign exists; TB run is blocked: ' + name);
}
const campaign = 'tb-nginx-' + new Date().toISOString().replace(/[:.]/g, '-');
const paidLock = paid ? acquirePaidCampaignLock({ root, runId: campaign, entry: basename(import.meta.path) }) : undefined;
process.once('exit', () => { try { paidLock?.release(); } catch {} });
const output = join(root, paid ? 'docs/repair-2026-10-08/campaigns' : 'docs/repair-2026-10-08/tb-preparation', campaign);
const store = join(root, '.phase1-data/repair', campaign);
mkdirSync(output, { recursive: true }); mkdirSync(store, { recursive: true });
const cap = Number(process.env.OBJRUN_REPAIR_BUDGET_USD ?? 15);
const maxTokens = 8192;
const key = paid ? process.env.DEEPSEEK_API_KEY : randomBytes(24).toString('hex');
if (!key) throw new Error('Load the project API credential only for explicit run mode');
const reconcileReceiptCost: typeof actualCost = (receipt, reserve, options = {}) => actualCost(receipt, paid ? reserve : 0, paid ? options : { ...options, knownUncharged: true, rates: { input: 0, cachedInput: 0, output: 0 } as never });
const mockSteps = new Map<string, number>();
let hostAuthProbeCommand = '';
const providerFetch = async (_url: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1], route = '') => {
  if (mode !== 'mock') { if (!paid) throw new Error('Preparation cannot request an LLM'); return await fetch(_url, init); }
  const body = JSON.parse(String(init?.body));
  const arm = route.includes('/F/') ? 'F' : 'U';
  const index = mockSteps.get(arm) ?? 0; mockSteps.set(arm, index + 1);
  const call = mockCall(index, arm);
  if (index === 0 && call.name === 'bash' && hostAuthProbeCommand) call.args = { ...call.args, command: String(call.args.command) + '\n' + hostAuthProbeCommand };
  const forced = body.tool_choice?.function?.name;
  if (forced === 'submit') { call.name = 'submit'; call.args = { answer: 'smoke-final' }; }
  const names = (body.tools ?? []).map((tool: {function?:{name?:string}}) => tool.function?.name);
  if (!names.includes(call.name)) throw new Error('Mock action unavailable: ' + call.name);
  return Response.json({ id: 'local-mock-' + arm + '-' + index, model: 'local-mock-deepseek-flash', choices: [{ index: 0, finish_reason: 'tool_calls', message: { role: 'assistant', content: null, tool_calls: [{ id: 'mock-' + arm + '-' + index, type: 'function', function: { name: call.name, arguments: JSON.stringify(call.args) } }] } }], usage: { prompt_tokens: 1, completion_tokens: 1 } });
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

const corpus = resolve(process.env.TGENGIN_TB_CORPUS ?? join(root, '.phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks'));
const bench = join(root, 'examples/benchmark/terminal-bench');
const runtime = JSON.parse(readFileSync(join(bench, '.runtime/manifest.json'), 'utf8'));
const official = Object.entries(OFFICIAL_HASHES).map(([path, expected]) => {
  const file = join(corpus, TASK_ID, path); if (sha(readFileSync(file)) !== expected) throw new Error('Official nginx source changed: ' + path);
  return { path: file, name: 'official/' + path, sha256: expected };
});
const assets = Object.entries(runtime.assets).map(([name, expected]) => {
  const path = join(bench, '.runtime', name); if (sha(readFileSync(path)) !== expected) throw new Error('Runtime asset changed: ' + name);
  return { path, name: 'runtime/' + name, sha256: expected };
});
for (const [path, expected] of Object.entries(runtime.frozenSources)) if (sha(readFileSync(join(root, path))) !== expected) throw new Error('Runtime core source changed: ' + path);
const graderHashes = Object.fromEntries(['stand.py','isolated_verifier.py','nginx_client.py'].map(name=>['examples/benchmark/terminal-bench/'+name,sha(readFileSync(join(bench,name)))]).concat([['examples/benchmark/_lib/grader_status.py',sha(readFileSync(join(root,'examples/benchmark/_lib/grader_status.py')))]]));
const preflightPath = process.env.OBJRUN_TB_PREFLIGHT_JSON ? resolve(process.env.OBJRUN_TB_PREFLIGHT_JSON) : undefined;
const preflight = preflightPath ? JSON.parse(readFileSync(preflightPath,'utf8')) : undefined;
if(paid || process.env.TGENGIN_TB_VERIFIER_DEPS || preflight) requireNginxPreflight(preflight,graderHashes,sha(readFileSync(join(bench,'.runtime/manifest.json'))));
const dependencyArtifacts = preflight ? (preflight.dependencyArtifacts ?? []).map((file:{path:string;name:string;sha256:string}) => {if(/secret|token|broker|\.env|\.pem|\.key/i.test(file.name))throw new Error('Private secrets cannot be archived');if(sha(readFileSync(file.path))!==file.sha256)throw new Error('Dependency artifact changed');return file;}) : [];
const image = JSON.parse(execFileSync('docker', ['image', 'inspect', IMAGE_ID], { windowsHide: true, encoding: 'utf8' }))[0];
if (image.Id !== IMAGE_ID) throw new Error('The audited immutable nginx image must already be cached');
const dockerVersion = execFileSync('docker', ['version', '--format', '{{json .}}'], { windowsHide: true, encoding: 'utf8' });
const sourcePath = join(output, 'source.json');
execFileSync(process.execPath, [join(root, 'scripts/phase1/source-snapshot.ts'), sourcePath], { cwd: root, windowsHide: true });
const source = JSON.parse(readFileSync(sourcePath, 'utf8'));
source.repairFiles = [basename(import.meta.path), 'tb-engine.ts', 'tb-tool-gateway.ts', 'tb-nginx-contract.ts', 'campaign-contract.ts', 'paid-campaign-lock.ts', 'freeze-tb-source.py'].map(name => ({ path: 'scripts/benchmark-repair/' + name, sha256: sha(readFileSync(join(import.meta.dir, name))) }));
source.artifacts = [...official, ...assets, ...dependencyArtifacts, ...(preflight?[{path:preflightPath,name:'preflight/proof.json',sha256:sha(readFileSync(preflightPath!))}]:[]), { path: join(bench, '.runtime/manifest.json'), name: 'runtime/manifest.json', sha256: sha(readFileSync(join(bench, '.runtime/manifest.json'))) }];
source.executionDigest = sha(JSON.stringify({ sourceDigest: source.sourceDigest, repairFiles: source.repairFiles, artifacts: source.artifacts }));
save(sourcePath, source);
const used = new Set(['test/_lib.ts', ...['stand.py','isolated_verifier.py','nginx_client.py','prepare_runtime.py','prepare_verifier_dependencies.py','objective.ts'].map(name => 'examples/benchmark/terminal-bench/' + name), 'examples/benchmark/_lib/grader_status.py']);
function validateSource() {
  for (const file of [...source.files.filter((file: {path:string}) => file.path.startsWith('app/src/') || used.has(file.path)), ...source.repairFiles]) if (sha(readFileSync(join(root, file.path))) !== file.sha256) throw new Error('Executed source changed: ' + file.path);
  for (const artifact of source.artifacts) if (sha(readFileSync(artifact.path)) !== artifact.sha256) throw new Error('Frozen artifact changed: ' + artifact.name);
}
const port = await (async () => { const server = Bun.serve({ hostname: '127.0.0.1', port: 0, fetch: () => new Response('') }); const port = server.port; await server.stop(true); return port; })();
const stand = 'http://127.0.0.1:' + port;
const token = randomBytes(32).toString('hex');
process.env.TGENGIN_GRADER_TOKEN = token;
const gateway = tbToolGateway({stand,token,store:join(store,'tool-receipts'),ledger:receipts=>save(join(output,'tool-ledger.json'),{campaign,receipts})});
process.env.TGENGIN_GRADER_ORIGINS = stand + ',' + gateway.origin;
process.env.OBJRUN_TB_MOCK_KEY = key;
const standProcess: ChildProcess = spawn('python', ['-X','utf8',join(bench,'stand.py'),'--port',String(port),'--level','2','--graders','1'], { windowsHide: true, env: { ...process.env, TGENGIN_TB_BACKEND: 'docker', TGENGIN_TB_CORPUS: corpus, TGENGIN_TB_HOME: join(store,'stand'), TGENGIN_UNSAFE_DIAGNOSTIC: '0' }, stdio: ['ignore','pipe','pipe'] });
let standLog = '';
standProcess.stdout?.on('data', chunk => { standLog += chunk.toString(); }); standProcess.stderr?.on('data', chunk => { standLog += chunk.toString(); });
const records: Record<string, unknown>[] = [];
let engine: Machine | undefined, livePlace: string | undefined, completed = false;
async function stopStand() {
  if (standProcess.exitCode === null) await new Promise<void>(resolve => { const timer = setTimeout(() => standProcess.kill('SIGKILL'), 3000); standProcess.once('exit', () => { clearTimeout(timer); resolve(); }); standProcess.kill(); });
}
try {
  let health: Record<string, unknown> | undefined;
  for (let i=0;i<100;i++) { try { const response=await fetch(stand+'/health'); if(response.ok){health=await response.json();break;} } catch {} if(standProcess.exitCode !== null) throw new Error('TB stand failed to start'); await Bun.sleep(100); }
  if (!health) throw new Error('TB stand readiness timed out'); requireSafeHealth(health);
  if(preflight && health.protocol !== preflight.protocol) throw new Error('Actual TB dependency protocol differs from preflight');
  const response = await graderFetch(stand+'/problems?n=1&seed=0',{}); if(!response.ok) throw new Error('Protected problem request failed');
  const items = await response.json() as {id:string;instruction:string;seconds:number;workdir:string}[];
  if(items.length!==1 || items[0]!.id!==TASK_ID) throw new Error('Only the audited nginx task is allowed');
  const item=items[0]!, seconds=item.seconds;
  const prompt = item.instruction + '\n\nEvery bash/read/write/edit/glob/grep call runs inside your task container. Hand in the live service with submit; the answer is only an attempt label. Official tests stay outside your container. Use verify only when offered.';
  const manifest = { schemaVersion: 2, campaign, createdAt:new Date().toISOString(), profile: paid?'pilot':'zero-cost-validation', benchmarks:['terminal-bench'], arms:['U','F'], independentRReplicas:5, model:'deepseek-flash', provider:paid?'https://api.deepseek.com':'local-mock', temperature:0,seed:42,reasoningEffort:'none',maxTokensPerRequest:maxTokens,checksPerAttempt:4,maxBranchesF:1,maxBranchesUR:1,maxDeadSiblingsF:1,concurrency:1,capUsd:cap,priorCampaignCostUpperBoundUsd:priorCampaignCost,sourceExecutionDigest:source.executionDigest,taskSeconds:seconds,tools:[...SIX_TOOLS,'submit'],feedbackTool:'F only: verify',reuse:'never',llmRequests:paid?undefined:0,datasets:{'terminal-bench':{source:JSON.parse(readFileSync(join(root,'.phase1-data/terminal-bench/source.json'),'utf8')),selectedTaskIds:[TASK_ID],sourceTaskCount:89,supportedTaskCount:1,unsupportedTaskCount:88,health,publicTaskDigest:sha(JSON.stringify(items))}},isolation:{protocol:health.protocol,candidateImage:{id:image.Id,repoDigests:image.RepoDigests,os:image.Os,architecture:image.Architecture},runtime,docker:JSON.parse(dockerVersion),standPid:standProcess.pid},protocolLimits:['Only nginx-request-logging; the other 88 tasks remain unsupported','Cold independent candidate per arm; one live candidate at a time','No text reuse for mutable live state','Post-delivery host engine stopped before final grading; late mutation cannot pass','Mock validation is not an LLM benchmark score'] };
  save(join(output,'manifest.json'),manifest); save(join(output,'terminal-bench-public-tasks.json'),[{officialId:TASK_ID,promptSha256:sha(prompt),row:item}]);
  execFileSync('python',['-X','utf8',join(import.meta.dir,'freeze-tb-source.py'),campaign,output,store],{cwd:root,windowsHide:true});
  if(mode==='prepare'){ validateSource();save(join(output,'preparation.json'),{ready:true,llmRequests:0,imagePulls:0,health});console.log(JSON.stringify({output,prepared:true,llmRequests:0})); }
  else {
    for(const arm of ['U','F']){
      validateSource(); const index=records.length, id=campaign+'-arm-'+arm+'/'+TASK_ID, place='tb:'+id; livePlace=place;
      const route=campaign+'/terminal-bench/'+arm+'/0/'+TASK_ID;
      mkdirSync(join(store,'worker-'+arm),{recursive:true});
      engine=await tbEngine({maxTokens,retryTimes:0,continueTimes:0,reasoningEffort:'none',temperature:0,seed:42},join(store,'worker-'+arm));
      const apiEnv=paid?'DEEPSEEK_API_KEY':'OBJRUN_TB_MOCK_KEY';
      await engine.api('POST','/exec',{sql:"insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select :key,'deepseek-flash',handle,modes,:base,'[]' from api where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'",params:{key:apiEnv,base:'http://127.0.0.1:'+proxy.port+'/'+route+'/v1'}});
      const databasePath=join(store,'worker-'+arm,'data/h2h.sqlite');
      gateway.register(place,()=>{const db=new Database(databasePath,{readonly:true});try{const task=db.query('select state,created_at,solve_seconds from task where id=?').get(id) as {state:string;created_at:number;solve_seconds:number}|null;if(!task)return undefined;if(Date.now()>=task.created_at+task.solve_seconds*1000)return 'task_deadline';if(['done','failed'].includes(task.state))return 'task_terminal';const handed=db.query("select 1 from agent_bot_msg where instance like ? and kind='tool' and json_valid(body) and json_extract(body,'$.name')='submit' limit 1").get(id+'#%');return handed?'task_delivered':undefined;}finally{db.close();}});
      await engine.api('POST','/declare',{handles:[{name:gateway.origin+'/place',expectMs:930000},...['ran','passed'].map(node=>({name:stand+'/'+node,expectMs:930000}))],places:[{place,identity:gateway.origin+'/place',forward:true,tools:SIX_TOOLS.map(tool=>({tool,policy:'always'}))}],modes:[{mode:'repair_tb',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:32,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:32,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[[apiEnv,'deepseek-flash']],unit:'fn:unit.tools'}]});
      await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('bash','read','write','edit','glob','grep','submit','verify')"});
      const cold = await graderFetch(stand+'/place',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({place,op:'ping'})}); if(!cold.ok || !(await cold.json() as {alive?:boolean}).alive) throw new Error('Cold candidate failed to start');
      const publicUrls=[stand+'/place',gateway.origin+'/place',engine.base+'/exec'].map(url=>url.replace('127.0.0.1','host.docker.internal'));
      hostAuthProbeCommand=publicUrls.flatMap(url=>['none','forged'].map(kind=>`code=$(curl --max-time 10 -s -o /dev/null -w '%{http_code}' -X POST -H 'content-type: application/json' ${kind==='forged'?"-H 'X-ObjRun-Grader-Token: invalid-probe' -H 'Authorization: Bearer invalid-probe'":""} -d '{}' '${url}'); [ "$code" = 401 ] || { printf 'host-auth-failed:%s\\n' "$code"; exit 1; }; printf 'host-auth:${kind}:401\\n'`)).join('\n');
      const started=Date.now();
      await engine.api('POST','/tasks',{id,run:campaign,mode:'repair_tb',agent:'bot',place,source:'user',domain:'software',workdir:item.workdir,description:prompt,...(arm==='F'?{objective:nginxObjective(stand),readable:false}:{}),solveSeconds:seconds,maxBranches:1,maxDeadSiblings:1,noSearch:['terminal-bench solution',TASK_ID+' solution']});
      let task:Record<string,unknown>|undefined;
      while(Date.now()-started < (seconds+950)*1000){ const state=await engine.api<Record<string,unknown>>('GET','/tasks/'+encodeURIComponent(id));const verdict=state.result?JSON.parse(String(state.result)):null; if(['done','failed'].includes(String(state.state)) && !['finalization_pending','finalization_error'].includes(verdict?.outcome)){task=state;gateway.seal(place,'task_terminal');closedRoutes.add(route);if(!(pending.get(route)??0))break;} await Bun.sleep(250); }
      if(!task) throw new Error('TB task did not finish or close its receipts');
      const quiescence=await gateway.drain(place);
      save(join(output,'quiescence-'+index+'.json'),quiescence);
      for(let i=0;i<100;i++){const status=await engine.api<{rows:{done:number}[]}>('POST','/query',{sql:'select done from agent_bot_ctx where instance like :prefix',params:{prefix:id+'#%'}});if(status.rows.every(row=>Number(row.done)===1))break;await Bun.sleep(50);}
      const trace=await engine.api<{rows:Record<string,unknown>[]}>('POST','/query',{sql:"select * from agent_bot_msg where instance like :prefix order by unit,seq",params:{prefix:id+'#%'}});
      const units=await engine.api<{rows:Record<string,unknown>[]}>('POST','/query',{sql:"select * from agent_bot_ctx where instance like :prefix order by unit",params:{prefix:id+'#%'}});
      if(mode==='mock'){const probe=trace.rows.filter(row=>row.kind==='tool').map(row=>{try{return JSON.parse(String(row.body));}catch{return null;}}).find(row=>row?.name==='bash');const stdout=String(probe?.value?.stdout??'');const valid=probe?.value?.code===0 && stdout.split('host-auth:none:401').length===4 && stdout.split('host-auth:forged:401').length===4;save(join(output,'host-auth-probe-'+index+'.json'),{valid,unauthenticated401:3,forged401:3,candidateOrigin:true,stdout});if(!valid)throw new Error('Candidate-origin host authentication controls failed');}
      await engine.stop(); const enginePid=engine.pid; engine=undefined;
      const db=new Database(join(store,'worker-'+arm,'data/h2h.sqlite'),{readonly:true});let candidate:{body:string;how:string}|undefined;
      try { candidate=finalCandidate({all:(sql,params)=>db.query(sql).all(...((params??[]) as never[])) as Record<string,unknown>[],run(){throw new Error('readonly');},exec(){throw new Error('readonly');},close(){}},id); } finally { db.close(); }
      const deadline=Number(task.created_at)+Number(task.solve_seconds)*1000, runtimeVerdict=task.result?JSON.parse(String(task.result)):{valid:true,outcome:'unaided_generated'};
      const generation=nginxGeneration({runtimeVerdict,state:String(task.state),calls:calls.filter(call=>call.route===route),trace:trace.rows,candidate:candidate?.body,deadline});
      if(generation.valid && quiescence.receipts.some(receipt=>receipt.forwarded && ['bash','write','edit'].includes(receipt.tool) && Number(receipt.finishedAt)>deadline)){generation.kind='experimental_failure';generation.outcome='budget_exhausted';generation.why='an admitted live-state mutation finished after the task deadline';}
      if(units.rows.some(unit=>Number(unit.done)!==1)) {generation.valid=false;generation.kind='infrastructure_error';generation.outcome='unfinished_tool_unit';generation.why='engine stopped with an unfinished execution unit';}
      const record={index,benchmark:'terminal-bench',arm,replica:0,officialId:TASK_ID,taskId:id,place,state:task.state,runtimeVerdict,generationValid:generation.valid,generationClassification:generation,startedAt:new Date(started).toISOString(),seconds:(Date.now()-started)/1000,actualCreatedAt:task.created_at,deadline:new Date(deadline).toISOString(),answer:candidate?.body??'',candidateHow:candidate?.how??'none',candidateSha256:sha(candidate?.body??''),promptSha256:sha(prompt),traceSha256:sha(JSON.stringify(trace.rows)),apiCalls:calls.filter(call=>call.route===route),toolQuiescence:quiescence,worker:arm,workerPid:enginePid,engineStoppedBeforeAcceptance:true,acceptance:{valid:false,outcome:'pending_after_all_generation'} as Record<string,unknown>};
      save(join(output,'task-'+index+'.json'),{...record,trace:trace.rows,units:units.rows});
      validateSource();
      record.acceptance=generation.valid && generation.kind==='experimental_failure'?{valid:true,passed:false,outcome:generation.outcome,why:generation.why,candidateSha256:record.candidateSha256,nodes:{}}:await gradeFixedCandidate({objective:nginxObjective(stand),task,candidate:candidate?.body,expectedCandidateSha256:record.candidateSha256,generation,timeoutMs:930000});
      validateSource(); records.push(record); save(join(output,'task-'+index+'.json'),{...record,trace:trace.rows,units:units.rows});
      const stopped=await graderFetch(stand+'/stop',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({place})});if(!stopped.ok) throw new Error('Owned TB candidate did not stop');livePlace=undefined;
      save(join(output,'summary.json'),{campaign,completed:false,plannedTaskRuns:2,recordedTaskRuns:records.length,generatedAt:new Date().toISOString(),recordedUsageUpperBoundUsd:spent,fatal,records});
      console.log(JSON.stringify({arm,acceptance:record.acceptance,llmRequests:paid?calls.length:0,mockRequests:paid?0:calls.length}));
      if(!generation.valid || record.acceptance.valid!==true) {fatal??='invalid_tb_record';break;}
    }
    validateSource(); completed=!fatal && campaignComplete(2,records as never);
    save(join(output,'summary.json'),{campaign,completed,plannedTaskRuns:2,recordedTaskRuns:records.length,generatedAt:new Date().toISOString(),recordedUsageUpperBoundUsd:spent,fatal,records}); ledger();
    console.log(JSON.stringify({output,completed,llmRequests:paid?calls.length:0,mockRequests:paid?0:calls.length,recordedUsageUpperBoundUsd:spent}));
    process.exitCode=completed?0:1;
  }
} catch(error){fatal??=error instanceof Error?error.message:'TBRunnerError';save(join(output,'summary.json'),{campaign,completed:false,plannedTaskRuns:2,recordedTaskRuns:records.length,generatedAt:new Date().toISOString(),recordedUsageUpperBoundUsd:spent,fatal,records});ledger();throw error;}
finally {
  if(engine) await engine.stop();
  if(livePlace) try{await graderFetch(stand+'/stop',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({place:livePlace})});}catch{}
  await stopStand();writeFileSync(join(store,'stand.log'),standLog);await gateway.stop();await proxy.stop(true);
  paidLock?.release();
}
