import {usesStageOperation,claimStageOperationLocks} from './stage-custody.ts';
import { readFileSync, writeFileSync, mkdirSync, openSync, closeSync,existsSync,readdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve, join, dirname } from 'node:path';
import { spawn } from 'node:child_process';
import { dlopen, FFIType, ptr, toArrayBuffer } from 'bun:ffi';
import { Database } from 'bun:sqlite';
import type { AttemptContext, Pin, StageSpec, TaskManifest, StageResult } from './types.ts';
import { pin as streamingPin,verifyPin as streamingVerifyPin } from './manifest.ts';

export function filePin(path: string): Pin {
  return streamingPin(path);
}
export function checkPin(pin: Pin): void {
  streamingVerifyPin(pin);
}
export function readPinned(pin: Pin): any { checkPin(pin); return JSON.parse(readFileSync(pin.path, 'utf8').replace(/^\uFEFF/, '')); }
export function wxJson(path: string, value: unknown): void {
  mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, JSON.stringify(value, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
}
export function claimTaskAttemptLocks(m:TaskManifest,c:AttemptContext,argv:string[]):Pin {
  const policy=m.adapterConfig.taskLocks as any;
  if(!policy?.lockRoot||!Array.isArray(policy.historicalLockPins)||!Array.isArray(policy.historicalClosureProofPins))throw Error('reviewed_global_lock_policy_required');
  if(!c.bindings?.ENTRY_ENVELOPE)throw Error('signed_context_required_before_lock');
  const signed=JSON.parse(readFileSync(c.bindings.ENTRY_ENVELOPE,'utf8'));
  if(JSON.stringify(signed.entry?.argv)!==JSON.stringify(argv))throw Error('actual_command_differs_from_root_signed_argv');
  for(const p of [...policy.historicalLockPins,...policy.historicalClosureProofPins])checkPin(p);
  const hash=createHash('sha256').update(m.bench+':'+m.taskId).digest('hex'),root=resolve(policy.lockRoot);
  mkdirSync(root,{recursive:true});
  const canonical=join(root,hash+'.json'),attempt=join(root,hash+'.'+c.attemptId+'.json');
  if(Buffer.byteLength(hash+'.'+c.attemptId+'.json')>240)throw Error('short_attempt_lock_required');
  const reviewed=new Map(policy.historicalLockPins.map((p:Pin)=>[resolve(p.path),p]));
  for(const name of readdirSync(root).filter(n=>n===hash+'.json'||n.startsWith(hash+'.')&&n.endsWith('.json'))) {
    const path=join(root,name),p=reviewed.get(path) as Pin|undefined;
    if(!p)throw Error('unreviewed_existing_task_lock_custody_unknown');checkPin(p);
  }
  if(existsSync(canonical)) {
    if(policy.historicalClosureProofPins.length===0||!c.originalRecoveryProofPin)throw Error('existing_canonical_requires_closed_original_recovery');
    checkPin(c.originalRecoveryProofPin);
  } else if(policy.legacyOriginalIdentityNull!==true||policy.historicalLockPins.length!==0)throw Error('new_canonical_requires_honest_legacy_null_identity');
  const receipt={protocol:'bench-permanent-task-attempt-lock-v1',taskId:m.taskId,bench:m.bench,attemptId:c.attemptId,
    manifestPin:c.manifestPin,signedEntryPin:filePin(c.bindings.ENTRY_ENVELOPE),argv,sourcePins:m.provenance.sourcePins,
    historicalNonce:policy.legacyOriginalIdentityNull?null:policy.historicalNonce,historicalLockPins:policy.historicalLockPins,
    historicalClosureProofPins:policy.historicalClosureProofPins,originalRecoveryProofPin:c.originalRecoveryProofPin??null};
  wxJson(attempt,receipt);
  if(!existsSync(canonical))wxJson(canonical,{...receipt,protocol:'bench-first-truthful-canonical-lock-v1',firstAttemptLockPin:filePin(attempt)});
  const path=join(c.runDir,'locks-receipt.json');wxJson(path,{canonicalPin:filePin(canonical),attemptLockPin:filePin(attempt),historicalLocksPreserved:true});return filePin(path);
}
export function expand(value: string, context: AttemptContext): string {
  const fields: Record<string, string> = { attemptId: context.attemptId, taskId: context.taskId, bench: context.bench,
    stage: context.stage, runDir: context.runDir, manifestPath: context.manifestPath,
    'manifestPin.path': context.manifestPin.path, admissionControlPath: context.admissionControlPath };
  return value.replace(/\{\{([^{}]+)\}\}/g, (_, name) => {
    if (name.startsWith('bindings.')) {
      const key=name.slice('bindings.'.length), bindings=(context as AttemptContext & {bindings?:Record<string,string>}).bindings;
      if (!/^[A-Z][A-Z0-9_]*$/.test(key) || !bindings || !Object.hasOwn(bindings,key)) throw Error('unverified_or_unknown_binding:'+key);
      return bindings[key];
    }
    if (!(name in fields)) throw Error('unknown_template:' + name); return fields[name];
  });
}
export function assertContext(manifest: TaskManifest, context: AttemptContext): void {
  if (context.taskId !== manifest.taskId || context.bench !== manifest.bench) throw Error('context_identity_mismatch');
  checkPin(context.manifestPin);
  const frozen=JSON.parse(readFileSync(context.manifestPin.path,'utf8').replace(/^\uFEFF/,''));
  if (JSON.stringify(frozen)!==JSON.stringify(manifest)) throw Error('context_manifest_object_changed');
  for (const pin of [...manifest.provenance.sourcePins, ...manifest.provenance.contractPins, manifest.provenance.inventoryPin]) checkPin(pin);
  if (manifest.provenance.authorizationPin) checkPin(manifest.provenance.authorizationPin);
  if (!manifest.history.stateKnown) throw Error('unknown_history_quarantined');
}
export interface CommandReceipt { exitCode: number | null; signal: string | null; timedOut: boolean;
  processPin: Pin; stdoutPin: Pin; stderrPin: Pin; closeObserved: boolean }
export function processIdentity(pid: number): { incarnation: string; creation: string; kind: string } {
  if (process.platform === 'win32') {
    const api = dlopen('kernel32.dll', {
      OpenProcess:{args:[FFIType.u32,FFIType.i32,FFIType.u32],returns:FFIType.u64},
      GetProcessTimes:{args:[FFIType.u64,FFIType.ptr,FFIType.ptr,FFIType.ptr,FFIType.ptr],returns:FFIType.i32},
      CloseHandle:{args:[FFIType.u64],returns:FFIType.i32},
    });
    const handle = api.symbols.OpenProcess(0x1000,0,pid);
    try {
      if (!handle) throw Error('process_incarnation_unavailable');
      const buffers = [0,1,2,3].map(()=>new Uint8Array(8));
      if (!api.symbols.GetProcessTimes(handle,...buffers.map(ptr) as [number,number,number,number])) throw Error('process_creation_unavailable');
      const creation = new DataView(buffers[0].buffer).getBigUint64(0,true).toString();
      return { incarnation:creation, creation, kind:'windows-filetime' };
    } finally { if (handle) api.symbols.CloseHandle(handle); api.close(); }
  }
  if (process.platform === 'linux') {
    const stat = readFileSync('/proc/'+pid+'/stat','utf8');
    const start = stat.slice(stat.lastIndexOf(')')+2).split(' ')[19];
    const boot = readFileSync('/proc/sys/kernel/random/boot_id','utf8').trim();
    return {incarnation:boot+':'+start,creation:start,kind:'linux-boot-id-start-ticks'};
  }
  throw Error('unsupported_exact_process_identity');
}
export function actualProcess(pid:number):{pid:number;parentPid:number;argv:string[];incarnation:string} {
  if(!Number.isSafeInteger(pid)||pid<1)throw Error('exact_pid_required');
  const identity=processIdentity(pid);
  if(process.platform==='linux') {
    const stat=readFileSync('/proc/'+pid+'/stat','utf8'),parentPid=Number(stat.slice(stat.lastIndexOf(')')+2).split(' ')[1]);
    const argv=readFileSync('/proc/'+pid+'/cmdline','utf8').split('\0').filter(Boolean);
    if(processIdentity(pid).incarnation!==identity.incarnation)throw Error('process_reused_during_query');
    return {pid,parentPid,argv,incarnation:identity.incarnation};
  }
  if(process.platform!=='win32'||process.arch!=='x64')throw Error('exact_process_argv_platform');
  const kernel=dlopen('kernel32.dll',{
    OpenProcess:{args:[FFIType.u32,FFIType.i32,FFIType.u32],returns:FFIType.u64},CloseHandle:{args:[FFIType.u64],returns:FFIType.i32},
    LocalFree:{args:[FFIType.u64],returns:FFIType.u64},lstrlenW:{args:[FFIType.u64],returns:FFIType.i32},
  });
  const nt=dlopen('ntdll.dll',{NtQueryInformationProcess:{args:[FFIType.u64,FFIType.u32,FFIType.ptr,FFIType.u32,FFIType.ptr],returns:FFIType.i32}});
  const shell=dlopen('shell32.dll',{CommandLineToArgvW:{args:[FFIType.ptr,FFIType.ptr],returns:FFIType.u64}});
  const handle=kernel.symbols.OpenProcess(0x1000,0,pid);let argvPointer:any;
  try {
    if(!handle)throw Error('process_query_handle');
    const basic=new Uint8Array(48),length=new Uint32Array(1);
    if(nt.symbols.NtQueryInformationProcess(handle,0,ptr(basic),48,ptr(length))<0)throw Error('process_parent_query');
    const parentPid=Number(new DataView(basic.buffer).getBigUint64(40,true));
    nt.symbols.NtQueryInformationProcess(handle,60,0,0,ptr(length));
    if(length[0]<16||length[0]>1024*1024)throw Error('bounded_process_command_line');
    const data=new Uint8Array(length[0]);const dataPointer=ptr(data);
    if(nt.symbols.NtQueryInformationProcess(handle,60,dataPointer,data.length,ptr(length))<0)throw Error('process_command_line_query');
    const view=new DataView(data.buffer,data.byteOffset,data.byteLength),bytes=view.getUint16(0,true),offset=Number(view.getBigUint64(8,true))-Number(dataPointer);
    if(offset<0||offset+bytes>data.length)throw Error('command_line_buffer_bounds');
    const wide=new Uint8Array(bytes+2);wide.set(data.subarray(offset,offset+bytes));const argc=new Int32Array(1);
    argvPointer=shell.symbols.CommandLineToArgvW(ptr(wide),ptr(argc));
    if(!argvPointer||argc[0]<1||argc[0]>16384)throw Error('command_line_argv');
    const pointers=new DataView(toArrayBuffer(Number(argvPointer),0,argc[0]*8)),argv:string[]=[];
    for(let i=0;i<argc[0];i++) {const p=pointers.getBigUint64(i*8,true),n=kernel.symbols.lstrlenW(p);if(n<0||n>32768)throw Error('command_line_arg_bound');argv.push(Buffer.from(toArrayBuffer(Number(p),0,n*2)).toString('utf16le'));}
    if(processIdentity(pid).incarnation!==identity.incarnation)throw Error('process_reused_during_query');
    return {pid,parentPid,argv,incarnation:identity.incarnation};
  } finally {if(argvPointer)kernel.symbols.LocalFree(argvPointer);if(handle)kernel.symbols.CloseHandle(handle);shell.close();nt.close();kernel.close();}
}
/** Evidence joins a root-owned launch receipt to OS incarnation, actual DB and live lane; spawn alone is insufficient. */
export async function inspectActualSolver(evidencePin: Pin): Promise<NonNullable<StageResult['actualSolver']>> {
  const e = readPinned(evidencePin);
  if (e.protocol !== 'bench-actual-solver-evidence-v1') throw Error('solver_evidence_protocol');
  const worker = readPinned(e.workerProcessPin), engine = readPinned(e.engineProcessPin);
  const actual=[worker,engine].map(p=>actualProcess(p.pid));
  for (const [i,p] of [worker,engine].entries()) {
    if (!Number.isSafeInteger(p.pid) || !p.incarnation || actual[i].incarnation !== p.incarnation) throw Error('solver_process_incarnation');
    checkPin(p.sourcePin);
    if(JSON.stringify(actual[i].argv)!==JSON.stringify(p.argv))throw Error('solver_actual_os_argv_mismatch');
    if (!Array.isArray(p.argv) || !p.argv.some((x:unknown)=>typeof x==='string' && resolve(x)===resolve(p.sourcePin.path))) throw Error('solver_source_argv');
  }
  let parent=actual[1].parentPid,joined=false;
  for(let depth=0;depth<16&&parent>0;depth++) {if(parent===worker.pid){joined=true;break;}parent=actualProcess(parent).parentPid;}
  if(!joined)throw Error('engine_not_in_worker_actual_parent_chain');
  const db = new Database(e.databasePath,{readonly:true});
  let task:any,active:any;
  try { task=db.query("select id,run,state from task where id=? and source='user'").get(e.mainTaskId);active=db.query('select count(*) as n from agent_bot_ctx where task=? and unit=1 and done=0').get(e.mainTaskId); }
  finally { db.close(); }
  if (!task || task.run!==e.mainRun || !['claimed','running','doing'].includes(task.state)||active?.n<1) throw Error('main_not_actively_solving');
  const healthResponse = await fetch(e.engineHealthUrl,{signal:AbortSignal.timeout(3000)});
  if (!healthResponse.ok) throw Error('engine_health_unavailable'); const health:any=await healthResponse.json();
  if (resolve(health.db)!==resolve(e.databasePath)) throw Error('engine_db_health_mismatch');
  const laneResponse=await fetch(e.brokerHealthUrl,{signal:AbortSignal.timeout(3000)});
  if (!laneResponse.ok) throw Error('broker_health_unavailable');const broker:any=await laneResponse.json();
  if (!broker.healthy || !broker.lanes?.some((l:any)=>l.runId===e.runId && !l.closed && l.output===e.output)) throw Error('live_lane_not_bound');
  return {workerPid:worker.pid,enginePid:engine.pid,runId:e.runId,mainTaskId:e.mainTaskId,
    workerIncarnation:worker.incarnation,mainActive:true,dbHealthBound:true,liveLaneBound:true};
}

/** A timeout quarantines custody; it never kills a driver, provider request or native actor. */
export async function executeCommand(manifest: TaskManifest, spec: StageSpec, context: AttemptContext): Promise<CommandReceipt> {
  assertContext(manifest, context);
  if(spec.effect==='model'&&context.stage!=='solve')throw Error('model_command_only_solve');
  if (!Array.isArray(spec.command) || !spec.command.length || spec.command.some(x => typeof x !== 'string' || x.includes('\0'))) throw Error('command_array_required');
  if (!(spec.timeoutSeconds > 0) || !Number.isFinite(spec.timeoutSeconds)) throw Error('bounded_stage_required');
  const argv = spec.command.map(x => expand(x, context));
  // The executable itself and any script arguments must be in the reviewed source set.
  const sources = manifest.provenance.sourcePins;
  const executable = resolve(argv[0]);
  if (!sources.some(p => resolve(p.path) === executable)) throw Error('executable_source_pin_required');
  mkdirSync(context.runDir, { recursive: true });
  if(usesStageOperation(context,spec))claimStageOperationLocks(manifest,spec,context,argv);else if(spec.effect!=='read-only')claimTaskAttemptLocks(manifest,context,argv);
  const intent = join(context.runDir, 'command-intent.json'), processPath = join(context.runDir, 'process.json');
  wxJson(intent, { protocol: 'bench-command-intent-v1', attemptId: context.attemptId, taskId: context.taskId,
    bench: context.bench, stage: context.stage, argv, cwd: manifest.root, manifestPin: context.manifestPin,
    sourcePins: sources, resourceMode: spec.resourceMode ?? 'none', atUtc: new Date().toISOString() });
  const stdout = join(context.runDir, 'stdout.log'), stderr = join(context.runDir, 'stderr.log');
  const out = openSync(stdout, 'wx', 0o600), err = openSync(stderr, 'wx', 0o600);
  let child: ReturnType<typeof spawn>;
  try { child = spawn(argv[0], argv.slice(1), { cwd: manifest.root, shell: false, windowsHide: true,
    stdio: ['ignore', out, err], env: { ...process.env, BENCH_ATTEMPT_ID: context.attemptId,
      BENCH_MANIFEST_PATH: context.manifestPath, BENCH_STAGE: context.stage, BENCH_RUN_DIR: context.runDir, BENCH_MODELS_FORBIDDEN: usesStageOperation(context,spec)?'1':process.env.BENCH_MODELS_FORBIDDEN } }); }
  finally { closeSync(out); closeSync(err); }
  let identity: ReturnType<typeof processIdentity> | undefined;
  try { if (child.pid) identity = processIdentity(child.pid); } catch { /* Keep unresolved custody, never invent creation. */ }
  wxJson(processPath, { protocol: 'bench-process-custody-v1', pid: child.pid ?? null, parentPid: process.pid,
    argv, creationObservedAtUtc: new Date().toISOString(), creation:identity?.creation ?? null, incarnation:identity?.incarnation ?? null,
    incarnationKind:identity?.kind ?? null, incarnationStatus:identity?'exact-os-observed':'requires-driver-or-os-reconciliation', sourcePin: sources.find(p => resolve(p.path) === executable),
    manifestPin: context.manifestPin, intentPin: filePin(intent), attemptId: context.attemptId, stage: context.stage });
  return await new Promise((ok, bad) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return; settled = true;
      wxJson(join(context.runDir, 'timeout.json'), { pid: child.pid, timeoutSeconds: spec.timeoutSeconds,
        closeObserved: false, custody: 'unknown', processNotKilled: true, atUtc: new Date().toISOString() });
      ok({ exitCode: null, signal: null, timedOut: true, closeObserved: false, processPin: filePin(processPath), stdoutPin: filePin(stdout), stderrPin: filePin(stderr) });
    }, spec.timeoutSeconds * 1000);
    child.once('error', error => {
      if (settled) return; settled = true; clearTimeout(timer);
      wxJson(join(context.runDir, 'spawn-error.json'), { error: String(error), pid: child.pid ?? null, custody: 'unknown' }); bad(error);
    });
    child.once('close', (code, signal) => {
      wxJson(join(context.runDir, 'exit.json'), { pid: child.pid, code, signal, closeObserved: true, atUtc: new Date().toISOString() });
      if (settled) return; settled = true; clearTimeout(timer);
      ok({ exitCode: code, signal, timedOut: false, closeObserved: true, processPin: filePin(processPath), stdoutPin: filePin(stdout), stderrPin: filePin(stderr) });
    });
  });
}
