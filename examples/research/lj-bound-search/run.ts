// Uses the real ObjRun engine, with task-local HTTP tools and an external checker.
import { mkdirSync, readFileSync, writeFileSync, appendFileSync, realpathSync, existsSync, copyFileSync, renameSync, readdirSync } from 'node:fs';
import { join, resolve, relative, isAbsolute } from 'node:path';
import { createHash, randomBytes } from 'node:crypto';

const root = resolve(import.meta.dir, '../../..');
const originalRun = resolve(process.argv.slice(2).find(arg=>!arg.startsWith('--')) || readFileSync(join(root, 'data/lj-bound-search/latest-run.txt'), 'utf8').trim());
const preflight = process.argv.includes('--check');
if(existsSync(join(originalRun,'primary-success.json'))||existsSync(join(originalRun,'final/summary.json')))throw Error('Campaign already closed; final review only.');
const dir = preflight ? join(originalRun, 'preflight') : originalRun;
for (const p of ['engine', 'jobs', 'requests', 'verified']) mkdirSync(join(dir, p), { recursive: true });
const work = join(originalRun, 'work');
const reference = join(originalRun, 'reference');
const python = JSON.parse(readFileSync(join(originalRun, 'runtime-manifest.json'), 'utf8')).python;
const model = 'deepseek/deepseek-v4.1-flash';
const backend = process.env.LJ_BACKEND || 'bwrap';
const linuxEnv = '/home/imontlaji/.local/share/objrun-lj-20261031-env';
const linuxPath = (p: string) => '/mnt/'+p[0].toLowerCase()+p.slice(2).replaceAll('\\', '/');
function sandboxCommand() {
  // Each command is its own PID/network/mount namespace. Disk artifacts persist
  // in /work; the Python supervisor ends the entire namespace at the deadline.
  const supervise = 'import sys,time,subprocess; left=max(0,float(sys.argv[1])-time.time()); subprocess.run(["/bin/bash","-s"],timeout=left,check=False)';
  return ['wsl', '-d', 'Ubuntu', '--', 'bwrap', '--unshare-all', '--die-with-parent', '--new-session',
    '--ro-bind', '/usr', '/usr', '--ro-bind', '/bin', '/bin', '--ro-bind', '/lib', '/lib', '--ro-bind', '/lib64', '/lib64',
    '--clearenv', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--ro-bind', linuxEnv, linuxEnv,
    '--bind', linuxPath(work), '/work', '--ro-bind', linuxPath(reference), '/reference',
    '--setenv', 'HOME', '/work', '--setenv', 'PATH', linuxEnv+'/bin:/usr/bin:/bin',
    '--unsetenv', 'OPENROUTER_API_KEY', '--unsetenv', 'DEEPSEEK_API_KEY',
    '--chdir', '/work', linuxEnv+'/bin/python', '-u', '-c', supervise, String(hard/1000)];
}
const start = Date.now(); let clockWall=start, monotonicStart=performance.now();
const duration = preflight ? 180_000 : 18_000_000;
const priorDeadline = !preflight && existsSync(join(dir, 'deadline.json')) ? JSON.parse(readFileSync(join(dir, 'deadline.json'), 'utf8')) : null;
let hard = priorDeadline ? priorDeadline.deadline_epoch*1000 : start + duration;
const remaining = () => Math.max(0, Math.min(hard-Date.now(), hard-clockWall-(performance.now()-monotonicStart)));
const unlimited = 2_147_483_647;
const container = 'objrun-rna-' + start + (preflight ? '-check' : '');
const event = (value: any) => appendFileSync(join(dir, 'events.jsonl'), JSON.stringify({ time: new Date().toISOString(), ...value })+'\n');
const callLog = (value: any) => appendFileSync(join(dir, 'calls.jsonl'), JSON.stringify({ time: new Date().toISOString(), ...value })+'\n');
const put = (file: string, value: any) => { writeFileSync(file+'.tmp', JSON.stringify(value, null, 2)); renameSync(file+'.tmp', file); };
let deadline = priorDeadline ?? { started_utc: new Date(start).toISOString(), deadline_utc: new Date(hard).toISOString(), deadline_epoch: hard/1000, duration_seconds: duration/1000, model, only_campaign_budget: 'elapsed time' };
if (!remaining()) throw new Error('Original five-hour window is over; refusing to restart it.');
if (existsSync(join(dir, 'completion.json'))) renameSync(join(dir, 'completion.json'), join(dir, `completion-before-recovery-${start}.json`));
if (preflight || priorDeadline) put(join(dir, 'deadline.json'), deadline);
let engine: any, base = '', activeDatabase = '', phase = Math.max(0, ...readdirSync(join(dir, 'engine')).map(n=>Number(n.match(/^phase-(\d+)/)?.[1]??0))), currentTask = '', stopping = false;
let best = JSON.parse(readFileSync(join(originalRun, 'best-verified.json'), 'utf8'));
const thresholds = new Map<string, any>();
const controllers = new Set<AbortController>();
const jobs = new Map<number, any>();
let nextJob = Math.max(0, ...readdirSync(join(dir, 'jobs')).map(n => Number(n.match(/^(\d+)\.command\.txt$/)?.[1] ?? 0)));
let nextRequest = Math.max(0, ...readdirSync(join(dir, 'requests')).map(n => Number(n.match(/^(\d+)\.json$/)?.[1] ?? 0)));
let proxy: any, toolServer: any;
let hardTimer: any;
function armTimer() { clearTimeout(hardTimer); hardTimer=setTimeout(()=>{
  stopping=true;
  for(const ctl of controllers) ctl.abort();
  for(const job of jobs.values()) if(job.exitCode===null) try{job.proc.kill();}catch{}
  try{engine?.kill();}catch{}
  event({event:'hard_deadline_local_stop'});
},Math.max(1,remaining())); }
armTimer();


function startPaidClock() {
  if (preflight) throw new Error('Paid requests are prohibited in --check');
  if (existsSync(join(dir,'deadline.json'))) return;
  const first=Date.now(); clockWall=first; monotonicStart=performance.now(); hard=first+18_000_000;
  deadline={started_utc:new Date(first).toISOString(),deadline_utc:new Date(hard).toISOString(),deadline_epoch:hard/1000,duration_seconds:18000,model,only_campaign_budget:'elapsed time; begins immediately before first paid dispatch'};
  put(join(dir,'deadline.json'),deadline); armTimer();
  event({event:'first_paid_dispatch_clock',...deadline});
}

const token = randomBytes(24).toString('hex');
let graderQueue = Promise.resolve();
const frozen = JSON.parse(readFileSync(join(originalRun,'frozen-g.json'),'utf8'));
function assertFrozen() {
  for (const [name, hash] of Object.entries(frozen.files)) {
    if (createHash('sha256').update(readFileSync(join(originalRun,name))).digest('hex') !== hash)
      throw new Error('Frozen G integrity failure: '+name);
  }
}
assertFrozen();


async function command(args: string[], stdin?: string) {
  const proc = Bun.spawn(args, { cwd: root, stdin: stdin === undefined ? 'ignore' : 'pipe', stdout: 'pipe', stderr: 'pipe', windowsHide: true });
  if (stdin !== undefined) { proc.stdin.write(stdin); proc.stdin.end(); }
  const [stdout, stderr, code] = await Promise.all([new Response(proc.stdout).text(), new Response(proc.stderr).text(), proc.exited]);
  return { stdout, stderr, code };
}

async function api(method: string, path: string, body?: any) {
  const response = await fetch(base+path, { method, headers: { 'content-type': 'application/json', authorization: `Bearer ${token}` }, ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(20_000) });
  const raw = await response.text();
  let value: any; try { value = JSON.parse(raw); } catch { value = raw; }
  if (!response.ok) throw new Error(`${path}: ${response.status} ${JSON.stringify(value)}`);
  return value;
}

function runJob(cmd: string) {
  if (!remaining() || stopping) throw new Error('The campaign deadline has been reached.');
  const id = ++nextJob;
  const logPath = join(dir, 'jobs', `${id}.log`);
  const errPath = join(dir, 'jobs', `${id}.stderr.log`);
  writeFileSync(logPath, ''); writeFileSync(errPath, '');
  writeFileSync(join(dir, 'jobs', `${id}.command.txt`), cmd);
  const argv = backend === 'bwrap' ? sandboxCommand() : ['docker', 'exec', '-i', '-w', '/work', container, 'bash', '-s'];
  const proc = Bun.spawn(argv, { stdin: 'pipe', stdout: Bun.file(logPath), stderr: Bun.file(errPath), windowsHide: true });
  proc.stdin.write(cmd); proc.stdin.end();
  const job = { id, proc, logPath, errPath, started: new Date().toISOString(), exitCode: null as number|null };
  jobs.set(id, job);
  event({ event: 'job_started', id });
  proc.exited.then((code: number) => { job.exitCode = code; event({ event: 'job_finished', id, code }); });
  return job;
}

function jobStatus(id: number, tail = 100) {
  const job = jobs.get(id);
  if (!job) return { error: 'unknown job id', known: [...jobs.keys()] };
  const readTail = (p: string) => existsSync(p) ? readFileSync(p, 'utf8').split(/\r?\n/).slice(-Math.max(1, tail)).join('\n') : '';
  return { id, started: job.started, running: job.exitCode === null, exitCode: job.exitCode, stdout: readTail(job.logPath), stderr: readTail(job.errPath), remaining_seconds: Math.ceil(remaining()/1000) };
}

async function verifyArtifact(answer: string, taskId: string) {
  let descriptor: any;
  try { descriptor=JSON.parse(answer); } catch { return {value:false,note:'Expected JSON {"path":"candidate.json"}'}; }
  if(typeof descriptor?.path!=='string') return {value:false,note:'Missing path'};
  const p=descriptor.path.replace(/^\/work\//,'');
  if(isAbsolute(p)||p.split(/[\\/]/).includes('..')) return {value:false,note:'Path must remain inside /work'};
  let text:string;
  try {const actual=realpathSync(join(work,p)),rel=relative(realpathSync(work),actual);if(rel.startsWith('..')||isAbsolute(rel))throw Error('outside workspace');text=readFileSync(actual,'utf8').replace(/^\uFEFF/,'');}
  catch(e){return {value:false,note:String(e)};}
  const hash=createHash('sha256').update(text).digest('hex');
  const artifact=join(dir,'verified',hash+'.candidate.json'),reportPath=join(dir,'verified',hash+'.json');
  if(!existsSync(artifact))writeFileSync(artifact,text);
  assertFrozen();
  if(existsSync(reportPath)) return {value:false,note:JSON.stringify({...JSON.parse(readFileSync(reportPath,'utf8')),already_checked:true})};
  const certificate=join(dir,'verified',hash+'.certificate.json');
  const checked=await command([python,join(originalRun,'checker/check.py'),artifact,certificate]);
  writeFileSync(join(dir,'verified',hash+'.checker.stdout.log'),checked.stdout);
  writeFileSync(join(dir,'verified',hash+'.checker.stderr.log'),checked.stderr);
  if(checked.code!==0)return {value:false,note:'Checker incomplete; no accepted theorem.'};
  let report:any;try{report=JSON.parse(checked.stdout.trim());}catch{throw Error('Invalid checker response');}
  report={...report,artifact,raw_sha256:hash,task:taskId,checked_utc:new Date().toISOString(),certificate};
  if(report.valid && report.improved){
    const replay=await command([python,join(originalRun,'checker/replay.py'),certificate]);
    writeFileSync(join(dir,'verified',hash+'.replay.stdout.log'),replay.stdout);
    writeFileSync(join(dir,'verified',hash+'.replay.stderr.log'),replay.stderr);
    try{report.independent_replay=JSON.parse(replay.stdout.trim());}catch{report.independent_replay={independent_replay_passed:false};}
    const obj=JSON.parse(text);
    const proofRel=String(obj.proof_path??'PROOF.md');
    if(isAbsolute(proofRel)||proofRel.split(/[\\/]/).includes('..'))report.proof_saved=false;
    else{
      try{const actual=realpathSync(join(work,proofRel));const rel=relative(realpathSync(work),actual);if(rel.startsWith('..')||isAbsolute(rel))throw Error('outside');
        const proof=readFileSync(actual,'utf8');report.proof_saved=proof.length>200;
        writeFileSync(join(dir,'verified',hash+'.model-proof.md'),proof);
      }catch{report.proof_saved=false;}
    }
    if(report.independent_replay.independent_replay_passed && report.proof_saved){
      assertFrozen();best=report;put(join(dir,'best-verified.json'),best);
      put(join(dir,'primary-success.json'),{utc:new Date().toISOString(),report,authorization:'User explicitly requests immediate stop after independent main-goal verification.',analytic_basis:'Frozen host PROOF_FAMILY.md; independent exact polynomial and tail replay.'});
      event({event:'primary_success_independently_verified',bound:report.c_new_expression,sha256:hash});
      stopping=true;
      for(const ctl of controllers)ctl.abort();
      for(const job of jobs.values())if(job.exitCode===null)try{job.proc.kill();}catch{}
    }
  }
  put(reportPath,report);appendFileSync(join(dir,'verifier-events.jsonl'),JSON.stringify(report)+'\n');
  return {value:Boolean(report.valid&&report.improved&&report.independent_replay?.independent_replay_passed&&report.proof_saved),note:JSON.stringify(report)};
}

async function serializedVerify(answer: string, task: string) {
  const previous = graderQueue;
  let release: () => void = () => {};
  graderQueue = new Promise<void>(resolve => { release = resolve; });
  await previous;
  try { return await verifyArtifact(answer, task); } finally { release(); }
}

function serveJson(fn: (req: Request) => Promise<any>) {
  return async (req: Request) => {
    // Drain the full upload before streaming a response. With a large context,
    // responding early can leave Bun's request body unread and stall req.json().
    const buffered = await req.text();
    const replay = new Request(req.url, { method: req.method, headers: req.headers, body: buffered });
    const encoder = new TextEncoder();
    // Whitespace heartbeat prevents transport idle timeouts; computation still
    // has only the campaign deadline. It is valid before a JSON document.
    return new Response(new ReadableStream({ start(out) {
      let open = true;
      out.enqueue(encoder.encode(' '));
      const beat = setInterval(() => { if (open) try { out.enqueue(encoder.encode(' ')); } catch { open = false; } }, 5000);
      fn(replay).then(result => { if (open) { out.enqueue(encoder.encode(JSON.stringify(result))); out.close(); } }).catch(e => {
        event({ event: 'endpoint_error', error: String(e) });
        if (open) { out.enqueue(encoder.encode(JSON.stringify({ valid: false, outcome: 'grader_error', error: String(e) }))); out.close(); }
      }).finally(() => { open = false; clearInterval(beat); });
    }}), { headers: { 'content-type': 'application/json', 'connection': 'close' } });
  };
}

async function startProxy() {
  proxy = Bun.serve({ hostname: '127.0.0.1', port: 0, idleTimeout: 255, fetch: serveJson(async req => {
    if (!remaining() || stopping) throw new Error('campaign deadline');
    const body: any = await req.json();
    if (body.model !== model) throw new Error('Unexpected model; substitutions are prohibited.');
    delete body.max_tokens; delete body.max_completion_tokens;
    delete body.provider; delete body.seed;
    body.reasoning = { enabled: true, effort: 'high', exclude: false };
    body.reasoning_effort = 'high';
    body.stream = false;
    const wire = JSON.stringify(body);
    while (remaining() && !stopping) {
      startPaidClock();
      const id = ++nextRequest, ctl = new AbortController(); controllers.add(ctl);
      const timeout = setTimeout(() => ctl.abort(), Math.max(1, remaining()));
      writeFileSync(join(dir, 'requests', `${id}.json`), wire);
      callLog({ event: 'dispatch', id, model, max_tokens: 'omitted', request_sha256: createHash('sha256').update(wire).digest('hex') });
      try {
        const res = await fetch('https://openrouter.ai/api/v1/chat/completions', { method: 'POST', headers: { authorization: `Bearer ${process.env.OPENROUTER_API_KEY}`, 'content-type': 'application/json' }, body: wire, signal: ctl.signal });
        const raw = await res.text();
        writeFileSync(join(dir, 'requests', `${id}.response.json`), raw);
        let parsed: any; try { parsed = JSON.parse(raw); } catch { throw new Error(`Non-JSON response, HTTP ${res.status}`); }
        callLog({ event: 'response', id, http_status: res.status, generation_id: parsed.id, response_model: parsed.model, provider: parsed.provider, usage: parsed.usage, finish_reason: parsed.choices?.[0]?.finish_reason, error: parsed.error });
        if (res.ok && parsed.choices?.length) { if(parsed.model !== model) throw new Error('Provider returned unexpected model '+parsed.model); return parsed; }
        if (![408, 409, 425, 429, 500, 502, 503, 504].includes(res.status)) return parsed;
      } catch (e) {
        callLog({ event: 'fault', id, error: String(e), remote_cancellation: 'unconfirmed; no receipt cost available' });
        if (!remaining() || stopping) throw e;
      } finally { clearTimeout(timeout); controllers.delete(ctl); }
      await Bun.sleep(Math.min(10_000, remaining()));
    }
    throw new Error('campaign deadline');
  }) });
}

async function startEngine() {
  const portServer = Bun.serve({ hostname: '127.0.0.1', port: 0, fetch: () => new Response('') });
  const port = portServer.port; await portServer.stop(true);
  const engineDirectory=priorDeadline?join(dir,'engine',`recovery-${start}`):join(dir,'engine');
  mkdirSync(engineDirectory,{recursive:true});
  const config = join(engineDirectory, 'config.yaml');
  activeDatabase=join(engineDirectory,'data/h2h.sqlite');
  writeFileSync(config, `server: { host: 127.0.0.1, port: ${port}, bodyLimit: 16777216, shutdownTimeout: 2000 }\nlog: { level: warn }\ndb: { file: ./data/h2h.sqlite, sealed: ./data/sealed.sqlite, pragmas: { journal_mode: WAL, synchronous: NORMAL, foreign_keys: ON, busy_timeout: 5000 } }\napi: { prefix: /api, token: ${token}, allowQuery: true, allowWrite: true, maxRows: 100000, defaultLimit: 100 }\nllm: { maxTokens: 16384, retryTimes: 0, continueTimes: ${unlimited}, reasoningEffort: high, temperature: 0.6, seed: 42 }\ncors: { enabled: false, origin: '*' }\n`);
  engine = Bun.spawn([process.execPath, join(originalRun, 'runtime/src/main.ts')], { cwd: root, env: { ...process.env, TGENGIN_CONFIG: config }, stdin: 'ignore', stdout: Bun.file(join(dir, 'engine.stdout.log')), stderr: Bun.file(join(dir, 'engine.stderr.log')), windowsHide: true });
  base = `http://127.0.0.1:${port}/api`;
  while (remaining()) {
    if (engine.exitCode !== null) throw new Error('Engine exited during startup; inspect engine.stderr.log');
    try { await api('GET', '/health'); return; } catch {}
    await Bun.sleep(200);
  }
  throw new Error('Engine startup exceeded campaign deadline');
}

async function configure() {
  const toolBase = `http://127.0.0.1:${toolServer.port}`;
  await api('POST', '/declare', {
    handles: ['/run', '/job', '/shape', '/verify'].map(path => ({ name: toolBase+path, expectMs: duration })),
    tools: [
      { name: 'run_command', identity: toolBase+'/run', does: 'Execute a bash command in the isolated scientific container. Python numpy/scipy/mpmath/sympy and g++ are installed. /work persists; /reference is read-only. Use background=true for long searches.', params: { type: 'object', properties: { command: { type: 'string' }, background: { type: 'boolean' } }, required: ['command'], additionalProperties: false }, output: { type: 'object' }, concurrent: false, gives: 'event', when: [[{ dim: 'cycle', key: 'cycle', op: 'ne', value: 'submit' }]] },
      { name: 'job_status', identity: toolBase+'/job', does: 'Read a background job log without interrupting it. Includes elapsed deadline remaining. Do useful work between polls.', params: { type: 'object', properties: { id: { type: 'integer' }, tail_lines: { type: 'integer' } }, required: ['id'], additionalProperties: false }, output: { type: 'object' }, concurrent: false, gives: 'look', when: [[{ dim: 'cycle', key: 'cycle', op: 'ne', value: 'submit' }]] },
    ],
    places: [{ place: 'local' }],
    modes: [{ mode: 'lj-bound-search', cycles: [
      { cycle: 'ask', apiMode: 'chat', maxUnits: unlimited, from: [], next: ['act'], infer: 'fn:infer.dfs' },
      { cycle: 'act', maxUnits: unlimited, from: ['ask'], next: ['ask'], infer: 'fn:infer.dfs' },
    ] }],
    agents: [{ name: 'lj', apis: [['OPENROUTER_API_KEY', model]], unit: 'fn:unit.tools' }],
  });
  await api('POST', '/exec', { sql: "update tool set usable=0 where name not in ('run_command','job_status','submit','verify','task_tree','node_load')" });
  await api('POST', '/exec', { sql: "update api set base_url=:base,retry_on='[]' where key_env='OPENROUTER_API_KEY' and model=:model", params: { base: `http://127.0.0.1:${proxy.port}`, model } });
  // The stock tool executor has its own watchdog. Align all runtime handles
  // with the campaign clock, so a long CPU job cannot spend an unrelated cap.
  await api('POST', '/exec', { sql: 'update handle set expect_ms=:ms', params: { ms: duration } });
}

async function publish() {
  const threshold = best;
  assertFrozen();
  currentTask = 'lj-bound-search-'+String(++phase).padStart(3, '0');
  thresholds.set(currentTask, threshold);
  put(join(dir,'engine',`phase-${phase}.json`),{task:currentTask,threshold,deadline:deadline.deadline_utc});
  const goal = readFileSync(join(originalRun, 'GOAL.md'), 'utf8');
  const objective = { nodes: [
    { name: 'candidate_shape', moment: 'done', domain: 'bool', handle: `http://127.0.0.1:${toolServer.port}/shape` },
    { name: 'independent_lj_uniform_bound_check', moment: 'done', domain: 'bool', handle: `http://127.0.0.1:${toolServer.port}/verify` },
  ], edges: [{ src: 'candidate_shape', out: 0, dst: 'independent_lj_uniform_bound_check' }], sink: 'independent_lj_uniform_bound_check', checks: unlimited, reuse: 'never' };
  const description=goal+`\nCurrent independently checked best: ${JSON.stringify(best)}. About ${Math.floor(remaining()/60000)} minutes remain. First dispatch freezes the exact deadline; it can never be reset. Search for a genuinely improved all-N proof and save code, full proof and candidate.json. Submit promptly when complete; independent success ends this campaign immediately. Inspect persisted /work progress.\n`;

  await api('POST', '/tasks', { id: currentTask, run: 'lj-five-hours', mode: 'lj-bound-search', agent: 'lj', place: 'local', source: 'user', description, objective, readable: false, solveSeconds: unlimited, maxBranches: unlimited, maxDeadSiblings: unlimited });
  event({ event: 'task_started', id: currentTask, threshold, remaining_seconds: Math.floor(remaining()/1000) });
}

try {
  if (!process.env.OPENROUTER_API_KEY) throw new Error('OPENROUTER_API_KEY is missing');
  await startProxy();
  toolServer = Bun.serve({ hostname: '127.0.0.1', port: 0, idleTimeout: 255, fetch: serveJson(async req => {
    const body: any = await req.json(), path = new URL(req.url).pathname;
    if (path === '/shape') {
      try { const candidate = JSON.parse(String(body.input?.result?.body ?? '')); return { value: typeof candidate.path === 'string', note: 'Candidate must be a JSON path descriptor.' }; }
      catch { return { value: false, note: 'Candidate must be JSON {"path":"candidate.json"}.' }; }
    }
    if (path === '/verify') {
      if (body.feed?.some((f: any) => f.value !== true)) return { value: false, note: 'Fix the candidate descriptor before artifact verification.' };
      return serializedVerify(String(body.input?.result?.body ?? body.input?.task?.result ?? ''), String(body.input?.task?.id ?? ''));
    }
    const args = body.args ?? body;
    if (path === '/job') return jobStatus(Number(args.id), Number(args.tail_lines ?? 100));
    if (path === '/run') {
      const job = runJob(String(args.command ?? ''));
      if (!args.background) await job.proc.exited;
      return jobStatus(job.id);
    }
    throw new Error('Unknown endpoint');
  }) });
  const keeper = 'import sys,time; end=float(sys.argv[1]); stop=time.monotonic()+max(0,end-time.time());\nwhile time.time()<end and time.monotonic()<stop: time.sleep(min(1,max(0.01,stop-time.monotonic())))';
  if (backend === 'docker') {
    const started = await command(['docker', 'run', '-d', '--name', container, '--network', 'none', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--mount', `type=bind,source=${work},target=/work`, '--mount', `type=bind,source=${reference},target=/reference,readonly`, 'objrun-lj-bound-search:local', 'python', '-u', '-c', keeper, String(hard/1000)]);
    if (started.code !== 0) throw new Error(started.stderr);
  }
  await startEngine();
  const times = await command([python, '-c', `import psutil,json; print(json.dumps({p:psutil.Process(p).create_time() for p in [${process.pid},${engine.pid}]}))`]);
  const created = JSON.parse(times.stdout);
  put(join(dir, 'process.json'), { runner: { pid: process.pid, created: created[process.pid] }, engine: { pid: engine.pid, created: created[engine.pid] }, container: backend === 'docker' ? container : null, backend, model });
  if (!preflight) {
    const guard = Bun.spawn([python, join(originalRun, 'guard.py'), dir], { stdin: 'ignore', stdout: Bun.file(join(dir, 'guard.stdout.log')), stderr: Bun.file(join(dir, 'guard.stderr.log')), windowsHide: true });
    guard.unref();
    put(join(dir, 'guard-process.json'), { pid: guard.pid });
  }
  await configure();
  put(join(dir,'endpoints.json'),{engine:base,tool_port:toolServer.port,proxy_port:proxy.port,database:activeDatabase});
  // Test real container tools and real independent validation before any model call.
  const smoke = runJob("python - <<'PY'\nimport numpy,scipy,mpmath,sympy\nprint('LJ environment ready')\nPY\ng++ --version | head -n 1");
  await smoke.proc.exited;
  if (smoke.exitCode !== 0) throw new Error('Scientific container preflight failed');
  const audit = await verifyArtifact('{"path":"candidate.json"}', 'preflight');
  if (!JSON.parse(audit.note).valid) throw new Error('Reference code failed verification');
  if (preflight) {
    const state = await api('POST', '/query', { sql: "select name,usable from tool where name in ('run_command','job_status','verify','submit')" });
    put(join(dir, 'check-result.json'), { passed: true, model_calls: 0, audit: JSON.parse(audit.note), tools: state, container: jobStatus(smoke.id) });
    console.log(JSON.stringify({ passed: true, model_calls: 0, directory: dir }));
  } else {
    await publish();
    console.log(JSON.stringify({ started: true, directory: dir, ...deadline }));
    let lastAudit=0, lastCandidateHash='';
    while (remaining() && !stopping && engine.exitCode === null) {
      if(Date.now()-lastAudit>15000){
        lastAudit=Date.now();
        try {
          const h=createHash('sha256').update(readFileSync(join(work,'candidate.json'))).digest('hex');
          if(h!==lastCandidateHash){await serializedVerify('{"path":"candidate.json"}',currentTask);lastCandidateHash=h;}
        }catch(e){event({event:'checkpoint_audit_error',error:String(e)});}
      }
      let task: any;
      try { task = await api('GET', '/tasks/'+currentTask+'/status'); }
      catch (e) { event({ event: 'status_error', error: String(e) }); await Bun.sleep(Math.min(5000, remaining())); continue; }
      put(join(dir, 'status.json'), { updated_utc: new Date().toISOString(), remaining_seconds: Math.ceil(remaining()/1000), phase, task, verified_best: best, active_jobs: [...jobs.values()].filter(j => j.exitCode === null).map(j => j.id), model_requests: nextRequest });
      if (['done', 'failed'].includes(task.state)) {
        event({ event: 'task_closed', task: currentTask, state: task.state, best });
        if (remaining() > 0 && !stopping) await publish();
      }
      await Bun.sleep(Math.min(5000, remaining()));
    }
    if (engine.exitCode !== null && remaining() > 0 && !stopping) throw new Error('Engine unexpectedly stopped');
  }
} catch (e) {
  event({ event: 'fatal', error: String(e) });
  process.exitCode = 1;
} finally {
  stopping = true;
  clearTimeout(hardTimer);
  for (const ctl of controllers) ctl.abort();
  // PID1 also enforces the same deadline independently of this host runner.
  if (backend === 'docker') try { await command(['docker', 'stop', '--time', '0', container]); } catch {}
  for (const job of jobs.values()) if (job.exitCode === null) try { job.proc.kill(); } catch {}
  try { if (engine) { engine.kill(); await engine.exited; } } catch {}
  // Capture the last complete checkpoint even if the model did not submit it.
  event({event:'final_verification_deferred_to_finalize_script'});
  await proxy?.stop(true); await toolServer?.stop(true);
  const result = { finished_utc: new Date().toISOString(), reason: process.exitCode ? 'infrastructure_error' : preflight ? 'preflight_passed' : existsSync(join(dir,'primary-success.json')) ? 'independent_primary_success' : 'five_hour_deadline', phase, model_requests: nextRequest, best, original_deadline: deadline.deadline_utc, remote_cancellation: controllers.size ? 'In-flight HTTP requests aborted locally; remote cancellation/charges require provider receipt.' : 'No model request remained in flight.' };
  put(join(dir, 'completion.json'), result);
  console.log(JSON.stringify(result));
}
