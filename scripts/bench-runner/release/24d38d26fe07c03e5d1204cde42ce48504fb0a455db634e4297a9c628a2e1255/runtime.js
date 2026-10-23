// @bun
// scripts/bench-runner/stage-custody.ts
import { mkdirSync, existsSync, readdirSync, readFileSync as readFileSync2, writeFileSync, openSync as openSync2, closeSync as closeSync2, unlinkSync } from "fs";
import { join, resolve as resolve2 } from "path";
import { createHash as createHash2 } from "crypto";

// scripts/bench-runner/manifest.ts
import { openSync, readSync, closeSync, lstatSync, readFileSync, realpathSync } from "fs";
import { createHash } from "crypto";
import { resolve, isAbsolute } from "path";
function demand(value, message) {
  if (!value)
    throw Error(message);
}
function pin(path) {
  const p = resolve(path), s = lstatSync(p);
  demand(s.isFile() && !s.isSymbolicLink(), "pin_regular_file_required");
  const h = createHash("sha256"), fd = openSync(p, "r"), b = Buffer.alloc(1024 * 1024);
  try {
    let n;
    while ((n = readSync(fd, b, 0, b.length, null)) > 0)
      h.update(b.subarray(0, n));
  } finally {
    closeSync(fd);
  }
  const after = lstatSync(p);
  demand(s.size === after.size && s.mtimeMs === after.mtimeMs && s.ino === after.ino, "pin_changed_during_read");
  return { path: p, bytes: s.size, sha256: h.digest("hex") };
}
function verifyPin(p) {
  demand(p && typeof p.path === "string" && isAbsolute(p.path) && Number.isSafeInteger(p.bytes) && p.bytes >= 0 && /^[a-f0-9]{64}$/.test(p.sha256), "invalid_pin");
  const a = pin(p.path);
  demand(a.bytes === p.bytes && a.sha256 === p.sha256, "pin_changed:" + p.path);
  return a;
}

// scripts/bench-runner/stage-custody.ts
var equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
var read = (p) => {
  verifyPin(p);
  return JSON.parse(readFileSync2(p.path, "utf8"));
};
var wx = (p, v) => {
  writeFileSync(p, JSON.stringify(v, null, 2) + `
`, { flag: "wx", mode: 384 });
  return pin(p);
};
function usesStageOperation(context, spec) {
  return ["prepare", "qualify"].includes(context.stage) && ["native", "oracle"].includes(spec.effect);
}
function claimStageOperationLocks(m, spec, c, argv) {
  demand(usesStageOperation(c, spec) && spec.resourceMode === "driver-owned", "native_operation_driver_owned_required");
  if (spec.effect === "oracle")
    demand(!!spec.originalSuccessKey && m.history.stateKnown, "first_oracle_requires_known_success_key");
  demand(c.bindings?.ENTRY_ENVELOPE, "signed_context_required_before_operation");
  const signed = JSON.parse(readFileSync2(c.bindings.ENTRY_ENVELOPE, "utf8"));
  demand(equal(signed.entry?.argv, argv), "actual_operation_command_not_signed");
  const policy = m.adapterConfig.stageCustody;
  demand(policy?.protocol === "bench-stage-operation-custody-v1" && policy.modelAccess === "forbidden" && policy.guardSourcePin, "native_stage_model_forbidden_contract_required");
  verifyPin(policy.guardSourcePin);
  demand(m.provenance.sourcePins.some((p) => p.path === policy.guardSourcePin.path && p.sha256 === policy.guardSourcePin.sha256), "actual_model_denial_guard_source_required");
  const contract = read(policy.driverContractPin);
  demand(m.provenance.contractPins.some((p) => p.path === policy.driverContractPin.path && p.sha256 === policy.driverContractPin.sha256) && contract.protocol === "bench-native-stage-model-denial-contract-v1" && contract.rootReviewed === true && contract.beforeJournal === true && contract.beforeForward === true && equal(contract.guardSourcePin, policy.guardSourcePin), "reviewed_native_driver_guard_contract_required");
  verifyPin(contract.driverPin);
  demand(argv.some((a) => resolve2(a) === resolve2(contract.driverPin.path)) && m.provenance.sourcePins.some((p) => p.path === contract.driverPin.path && p.sha256 === contract.driverPin.sha256), "actual_native_driver_contract_join");
  const success = m.adapterConfig.successfulCheckpoints;
  if (spec.originalSuccessKey)
    demand(!success?.[spec.originalSuccessKey], "successful_checkpoint_must_reuse");
  demand(!m.history.successfulStageProofs[c.stage]?.length, "successful_stage_must_reuse");
  const lockRoot = join(m.adapterConfig.taskLocks.lockRoot, "stage-operations"), hash = createHash2("sha256").update(m.bench + ":" + m.taskId + ":" + c.stage).digest("hex"), canonical = join(lockRoot, hash + ".json"), path = join(lockRoot, hash + "." + c.attemptId + ".json");
  demand(Buffer.byteLength(hash + "." + c.attemptId + ".json") <= 240, "short_operation_attempt_required");
  mkdirSync(lockRoot, { recursive: true });
  const gate = join(lockRoot, hash + ".claiming");
  const gateFd = openSync2(gate, "wx", 384);
  try {
    const prior = (policy.priorOperations ?? []).filter((x) => x.stage === c.stage);
    const reviewed = new Map;
    for (const p of prior) {
      const lock = read(p.operationPin), closed = read(p.closurePin);
      demand(lock.taskId === m.taskId && lock.bench === m.bench && lock.stage === c.stage && closed.attemptId === lock.attemptId && closed.taskId === m.taskId && closed.bench === m.bench && closed.stage === c.stage && equal(closed.operationPin, p.operationPin) && closed.nativeClosed === true && closed.financialClosed === true && closed.status === "retryable" && closed.candidateOrSubmissionPresent === false, "operation_previous_attempt_not_retryable_closed");
      for (const proof of closed.proofPins)
        verifyPin(proof);
      reviewed.set(resolve2(p.operationPin.path), p.operationPin);
      if (p.canonicalPin) {
        verifyPin(p.canonicalPin);
        reviewed.set(resolve2(p.canonicalPin.path), p.canonicalPin);
      }
    }
    for (const name of readdirSync(lockRoot).filter((n) => n === hash + ".json" || n.startsWith(hash + ".") && n.endsWith(".json"))) {
      const p = reviewed.get(resolve2(lockRoot, name));
      demand(p, "operation_custody_unresolved_or_successful");
      verifyPin(p);
    }
    const receipt = { protocol: "bench-stage-operation-lock-v1", taskId: m.taskId, bench: m.bench, stage: c.stage, attemptId: c.attemptId, manifestPin: c.manifestPin, signedEntryPin: pin(c.bindings.ENTRY_ENVELOPE), argv, modelAccess: "forbidden", guardSourcePin: policy.guardSourcePin, driverContractPin: policy.driverContractPin };
    const operationPin = wx(path, receipt);
    if (!existsSync(canonical))
      wx(canonical, { ...receipt, firstOperationPin: operationPin });
    return wx(join(c.runDir, "stage-operation-receipt.json"), { protocol: "bench-stage-operation-custody-receipt-v1", canonicalPin: pin(canonical), operationPin, modelAccess: "forbidden" });
  } finally {
    closeSync2(gateFd);
    unlinkSync(gate);
  }
}

// scripts/bench-runner/runtime-stage-custody.ts
import { readFileSync as readFileSync3, writeFileSync as writeFileSync2, mkdirSync as mkdirSync2, openSync as openSync3, closeSync as closeSync3, existsSync as existsSync2, readdirSync as readdirSync2 } from "fs";
import { createHash as createHash3 } from "crypto";
import { resolve as resolve3, join as join2, dirname } from "path";
import { spawn } from "child_process";
import { dlopen, FFIType, ptr, toArrayBuffer } from "bun:ffi";
import { Database } from "bun:sqlite";
function filePin(path) {
  return pin(path);
}
function checkPin(pin2) {
  verifyPin(pin2);
}
function readPinned(pin2) {
  checkPin(pin2);
  return JSON.parse(readFileSync3(pin2.path, "utf8").replace(/^\uFEFF/, ""));
}
function wxJson(path, value) {
  mkdirSync2(dirname(path), { recursive: true });
  writeFileSync2(path, JSON.stringify(value, null, 2) + `
`, { flag: "wx", mode: 384 });
}
function claimTaskAttemptLocks(m, c, argv) {
  const policy = m.adapterConfig.taskLocks;
  if (!policy?.lockRoot || !Array.isArray(policy.historicalLockPins) || !Array.isArray(policy.historicalClosureProofPins))
    throw Error("reviewed_global_lock_policy_required");
  if (!c.bindings?.ENTRY_ENVELOPE)
    throw Error("signed_context_required_before_lock");
  const signed = JSON.parse(readFileSync3(c.bindings.ENTRY_ENVELOPE, "utf8"));
  if (JSON.stringify(signed.entry?.argv) !== JSON.stringify(argv))
    throw Error("actual_command_differs_from_root_signed_argv");
  for (const p of [...policy.historicalLockPins, ...policy.historicalClosureProofPins])
    checkPin(p);
  const hash = createHash3("sha256").update(m.bench + ":" + m.taskId).digest("hex"), root = resolve3(policy.lockRoot);
  mkdirSync2(root, { recursive: true });
  const canonical = join2(root, hash + ".json"), attempt = join2(root, hash + "." + c.attemptId + ".json");
  if (Buffer.byteLength(hash + "." + c.attemptId + ".json") > 240)
    throw Error("short_attempt_lock_required");
  const reviewed = new Map(policy.historicalLockPins.map((p) => [resolve3(p.path), p]));
  for (const name of readdirSync2(root).filter((n) => n === hash + ".json" || n.startsWith(hash + ".") && n.endsWith(".json"))) {
    const path2 = join2(root, name), p = reviewed.get(path2);
    if (!p)
      throw Error("unreviewed_existing_task_lock_custody_unknown");
    checkPin(p);
  }
  if (existsSync2(canonical)) {
    if (policy.historicalClosureProofPins.length === 0 || !c.originalRecoveryProofPin)
      throw Error("existing_canonical_requires_closed_original_recovery");
    checkPin(c.originalRecoveryProofPin);
  } else if (policy.legacyOriginalIdentityNull !== true || policy.historicalLockPins.length !== 0)
    throw Error("new_canonical_requires_honest_legacy_null_identity");
  const receipt = {
    protocol: "bench-permanent-task-attempt-lock-v1",
    taskId: m.taskId,
    bench: m.bench,
    attemptId: c.attemptId,
    manifestPin: c.manifestPin,
    signedEntryPin: filePin(c.bindings.ENTRY_ENVELOPE),
    argv,
    sourcePins: m.provenance.sourcePins,
    historicalNonce: policy.legacyOriginalIdentityNull ? null : policy.historicalNonce,
    historicalLockPins: policy.historicalLockPins,
    historicalClosureProofPins: policy.historicalClosureProofPins,
    originalRecoveryProofPin: c.originalRecoveryProofPin ?? null
  };
  wxJson(attempt, receipt);
  if (!existsSync2(canonical))
    wxJson(canonical, { ...receipt, protocol: "bench-first-truthful-canonical-lock-v1", firstAttemptLockPin: filePin(attempt) });
  const path = join2(c.runDir, "locks-receipt.json");
  wxJson(path, { canonicalPin: filePin(canonical), attemptLockPin: filePin(attempt), historicalLocksPreserved: true });
  return filePin(path);
}
function expand(value, context) {
  const fields = {
    attemptId: context.attemptId,
    taskId: context.taskId,
    bench: context.bench,
    stage: context.stage,
    runDir: context.runDir,
    manifestPath: context.manifestPath,
    "manifestPin.path": context.manifestPin.path,
    admissionControlPath: context.admissionControlPath
  };
  return value.replace(/\{\{([^{}]+)\}\}/g, (_, name) => {
    if (name.startsWith("bindings.")) {
      const key = name.slice("bindings.".length), bindings = context.bindings;
      if (!/^[A-Z][A-Z0-9_]*$/.test(key) || !bindings || !Object.hasOwn(bindings, key))
        throw Error("unverified_or_unknown_binding:" + key);
      return bindings[key];
    }
    if (!(name in fields))
      throw Error("unknown_template:" + name);
    return fields[name];
  });
}
function assertContext(manifest, context) {
  if (context.taskId !== manifest.taskId || context.bench !== manifest.bench)
    throw Error("context_identity_mismatch");
  checkPin(context.manifestPin);
  const frozen = JSON.parse(readFileSync3(context.manifestPin.path, "utf8").replace(/^\uFEFF/, ""));
  if (JSON.stringify(frozen) !== JSON.stringify(manifest))
    throw Error("context_manifest_object_changed");
  for (const pin2 of [...manifest.provenance.sourcePins, ...manifest.provenance.contractPins, manifest.provenance.inventoryPin])
    checkPin(pin2);
  if (manifest.provenance.authorizationPin)
    checkPin(manifest.provenance.authorizationPin);
  if (!manifest.history.stateKnown)
    throw Error("unknown_history_quarantined");
}
function processIdentity(pid) {
  if (process.platform === "win32") {
    const api = dlopen("kernel32.dll", {
      OpenProcess: { args: [FFIType.u32, FFIType.i32, FFIType.u32], returns: FFIType.u64 },
      GetProcessTimes: { args: [FFIType.u64, FFIType.ptr, FFIType.ptr, FFIType.ptr, FFIType.ptr], returns: FFIType.i32 },
      CloseHandle: { args: [FFIType.u64], returns: FFIType.i32 }
    });
    const handle = api.symbols.OpenProcess(4096, 0, pid);
    try {
      if (!handle)
        throw Error("process_incarnation_unavailable");
      const buffers = [0, 1, 2, 3].map(() => new Uint8Array(8));
      if (!api.symbols.GetProcessTimes(handle, ...buffers.map(ptr)))
        throw Error("process_creation_unavailable");
      const creation = new DataView(buffers[0].buffer).getBigUint64(0, true).toString();
      return { incarnation: creation, creation, kind: "windows-filetime" };
    } finally {
      if (handle)
        api.symbols.CloseHandle(handle);
      api.close();
    }
  }
  if (process.platform === "linux") {
    const stat = readFileSync3("/proc/" + pid + "/stat", "utf8");
    const start = stat.slice(stat.lastIndexOf(")") + 2).split(" ")[19];
    const boot = readFileSync3("/proc/sys/kernel/random/boot_id", "utf8").trim();
    return { incarnation: boot + ":" + start, creation: start, kind: "linux-boot-id-start-ticks" };
  }
  throw Error("unsupported_exact_process_identity");
}
function actualProcess(pid) {
  if (!Number.isSafeInteger(pid) || pid < 1)
    throw Error("exact_pid_required");
  const identity = processIdentity(pid);
  if (process.platform === "linux") {
    const stat = readFileSync3("/proc/" + pid + "/stat", "utf8"), parentPid = Number(stat.slice(stat.lastIndexOf(")") + 2).split(" ")[1]);
    const argv = readFileSync3("/proc/" + pid + "/cmdline", "utf8").split("\x00").filter(Boolean);
    if (processIdentity(pid).incarnation !== identity.incarnation)
      throw Error("process_reused_during_query");
    return { pid, parentPid, argv, incarnation: identity.incarnation };
  }
  if (process.platform !== "win32" || process.arch !== "x64")
    throw Error("exact_process_argv_platform");
  const kernel = dlopen("kernel32.dll", {
    OpenProcess: { args: [FFIType.u32, FFIType.i32, FFIType.u32], returns: FFIType.u64 },
    CloseHandle: { args: [FFIType.u64], returns: FFIType.i32 },
    LocalFree: { args: [FFIType.u64], returns: FFIType.u64 },
    lstrlenW: { args: [FFIType.u64], returns: FFIType.i32 }
  });
  const nt = dlopen("ntdll.dll", { NtQueryInformationProcess: { args: [FFIType.u64, FFIType.u32, FFIType.ptr, FFIType.u32, FFIType.ptr], returns: FFIType.i32 } });
  const shell = dlopen("shell32.dll", { CommandLineToArgvW: { args: [FFIType.ptr, FFIType.ptr], returns: FFIType.u64 } });
  const handle = kernel.symbols.OpenProcess(4096, 0, pid);
  let argvPointer;
  try {
    if (!handle)
      throw Error("process_query_handle");
    const basic = new Uint8Array(48), length = new Uint32Array(1);
    if (nt.symbols.NtQueryInformationProcess(handle, 0, ptr(basic), 48, ptr(length)) < 0)
      throw Error("process_parent_query");
    const parentPid = Number(new DataView(basic.buffer).getBigUint64(40, true));
    nt.symbols.NtQueryInformationProcess(handle, 60, 0, 0, ptr(length));
    if (length[0] < 16 || length[0] > 1024 * 1024)
      throw Error("bounded_process_command_line");
    const data = new Uint8Array(length[0]);
    const dataPointer = ptr(data);
    if (nt.symbols.NtQueryInformationProcess(handle, 60, dataPointer, data.length, ptr(length)) < 0)
      throw Error("process_command_line_query");
    const view = new DataView(data.buffer, data.byteOffset, data.byteLength), bytes = view.getUint16(0, true), offset = Number(view.getBigUint64(8, true)) - Number(dataPointer);
    if (offset < 0 || offset + bytes > data.length)
      throw Error("command_line_buffer_bounds");
    const wide = new Uint8Array(bytes + 2);
    wide.set(data.subarray(offset, offset + bytes));
    const argc = new Int32Array(1);
    argvPointer = shell.symbols.CommandLineToArgvW(ptr(wide), ptr(argc));
    if (!argvPointer || argc[0] < 1 || argc[0] > 16384)
      throw Error("command_line_argv");
    const pointers = new DataView(toArrayBuffer(Number(argvPointer), 0, argc[0] * 8)), argv = [];
    for (let i = 0;i < argc[0]; i++) {
      const p = pointers.getBigUint64(i * 8, true), n = kernel.symbols.lstrlenW(p);
      if (n < 0 || n > 32768)
        throw Error("command_line_arg_bound");
      argv.push(Buffer.from(toArrayBuffer(Number(p), 0, n * 2)).toString("utf16le"));
    }
    if (processIdentity(pid).incarnation !== identity.incarnation)
      throw Error("process_reused_during_query");
    return { pid, parentPid, argv, incarnation: identity.incarnation };
  } finally {
    if (argvPointer)
      kernel.symbols.LocalFree(argvPointer);
    if (handle)
      kernel.symbols.CloseHandle(handle);
    shell.close();
    nt.close();
    kernel.close();
  }
}
async function inspectActualSolver(evidencePin) {
  const e = readPinned(evidencePin);
  if (e.protocol !== "bench-actual-solver-evidence-v1")
    throw Error("solver_evidence_protocol");
  const worker = readPinned(e.workerProcessPin), engine = readPinned(e.engineProcessPin);
  const actual = [worker, engine].map((p) => actualProcess(p.pid));
  for (const [i, p] of [worker, engine].entries()) {
    if (!Number.isSafeInteger(p.pid) || !p.incarnation || actual[i].incarnation !== p.incarnation)
      throw Error("solver_process_incarnation");
    checkPin(p.sourcePin);
    if (JSON.stringify(actual[i].argv) !== JSON.stringify(p.argv))
      throw Error("solver_actual_os_argv_mismatch");
    if (!Array.isArray(p.argv) || !p.argv.some((x) => typeof x === "string" && resolve3(x) === resolve3(p.sourcePin.path)))
      throw Error("solver_source_argv");
  }
  let parent = actual[1].parentPid, joined = false;
  for (let depth = 0;depth < 16 && parent > 0; depth++) {
    if (parent === worker.pid) {
      joined = true;
      break;
    }
    parent = actualProcess(parent).parentPid;
  }
  if (!joined)
    throw Error("engine_not_in_worker_actual_parent_chain");
  const db = new Database(e.databasePath, { readonly: true });
  let task, active;
  try {
    task = db.query("select id,run,state from task where id=? and source='user'").get(e.mainTaskId);
    active = db.query("select count(*) as n from agent_bot_ctx where task=? and unit=1 and done=0").get(e.mainTaskId);
  } finally {
    db.close();
  }
  if (!task || task.run !== e.mainRun || !["claimed", "running", "doing"].includes(task.state) || active?.n < 1)
    throw Error("main_not_actively_solving");
  const healthResponse = await fetch(e.engineHealthUrl, { signal: AbortSignal.timeout(3000) });
  if (!healthResponse.ok)
    throw Error("engine_health_unavailable");
  const health = await healthResponse.json();
  if (resolve3(health.db) !== resolve3(e.databasePath))
    throw Error("engine_db_health_mismatch");
  const laneResponse = await fetch(e.brokerHealthUrl, { signal: AbortSignal.timeout(3000) });
  if (!laneResponse.ok)
    throw Error("broker_health_unavailable");
  const broker = await laneResponse.json();
  if (!broker.healthy || !broker.lanes?.some((l) => l.runId === e.runId && !l.closed && l.output === e.output))
    throw Error("live_lane_not_bound");
  return {
    workerPid: worker.pid,
    enginePid: engine.pid,
    runId: e.runId,
    mainTaskId: e.mainTaskId,
    workerIncarnation: worker.incarnation,
    mainActive: true,
    dbHealthBound: true,
    liveLaneBound: true
  };
}
async function executeCommand(manifest, spec, context) {
  assertContext(manifest, context);
  if (spec.effect === "model" && context.stage !== "solve")
    throw Error("model_command_only_solve");
  if (!Array.isArray(spec.command) || !spec.command.length || spec.command.some((x) => typeof x !== "string" || x.includes("\x00")))
    throw Error("command_array_required");
  if (!(spec.timeoutSeconds > 0) || !Number.isFinite(spec.timeoutSeconds))
    throw Error("bounded_stage_required");
  const argv = spec.command.map((x) => expand(x, context));
  const sources = manifest.provenance.sourcePins;
  const executable = resolve3(argv[0]);
  if (!sources.some((p) => resolve3(p.path) === executable))
    throw Error("executable_source_pin_required");
  mkdirSync2(context.runDir, { recursive: true });
  if (usesStageOperation(context, spec))
    claimStageOperationLocks(manifest, spec, context, argv);
  else if (spec.effect !== "read-only")
    claimTaskAttemptLocks(manifest, context, argv);
  const intent = join2(context.runDir, "command-intent.json"), processPath = join2(context.runDir, "process.json");
  wxJson(intent, {
    protocol: "bench-command-intent-v1",
    attemptId: context.attemptId,
    taskId: context.taskId,
    bench: context.bench,
    stage: context.stage,
    argv,
    cwd: manifest.root,
    manifestPin: context.manifestPin,
    sourcePins: sources,
    resourceMode: spec.resourceMode ?? "none",
    atUtc: new Date().toISOString()
  });
  const stdout = join2(context.runDir, "stdout.log"), stderr = join2(context.runDir, "stderr.log");
  const out = openSync3(stdout, "wx", 384), err = openSync3(stderr, "wx", 384);
  let child;
  try {
    child = spawn(argv[0], argv.slice(1), {
      cwd: manifest.root,
      shell: false,
      windowsHide: true,
      stdio: ["ignore", out, err],
      env: {
        ...process.env,
        BENCH_ATTEMPT_ID: context.attemptId,
        BENCH_MANIFEST_PATH: context.manifestPath,
        BENCH_STAGE: context.stage,
        BENCH_RUN_DIR: context.runDir,
        BENCH_MODELS_FORBIDDEN: usesStageOperation(context, spec) ? "1" : process.env.BENCH_MODELS_FORBIDDEN
      }
    });
  } finally {
    closeSync3(out);
    closeSync3(err);
  }
  let identity;
  try {
    if (child.pid)
      identity = processIdentity(child.pid);
  } catch {}
  wxJson(processPath, {
    protocol: "bench-process-custody-v1",
    pid: child.pid ?? null,
    parentPid: process.pid,
    argv,
    creationObservedAtUtc: new Date().toISOString(),
    creation: identity?.creation ?? null,
    incarnation: identity?.incarnation ?? null,
    incarnationKind: identity?.kind ?? null,
    incarnationStatus: identity ? "exact-os-observed" : "requires-driver-or-os-reconciliation",
    sourcePin: sources.find((p) => resolve3(p.path) === executable),
    manifestPin: context.manifestPin,
    intentPin: filePin(intent),
    attemptId: context.attemptId,
    stage: context.stage
  });
  return await new Promise((ok, bad) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled)
        return;
      settled = true;
      wxJson(join2(context.runDir, "timeout.json"), {
        pid: child.pid,
        timeoutSeconds: spec.timeoutSeconds,
        closeObserved: false,
        custody: "unknown",
        processNotKilled: true,
        atUtc: new Date().toISOString()
      });
      ok({ exitCode: null, signal: null, timedOut: true, closeObserved: false, processPin: filePin(processPath), stdoutPin: filePin(stdout), stderrPin: filePin(stderr) });
    }, spec.timeoutSeconds * 1000);
    child.once("error", (error) => {
      if (settled)
        return;
      settled = true;
      clearTimeout(timer);
      wxJson(join2(context.runDir, "spawn-error.json"), { error: String(error), pid: child.pid ?? null, custody: "unknown" });
      bad(error);
    });
    child.once("close", (code, signal) => {
      wxJson(join2(context.runDir, "exit.json"), { pid: child.pid, code, signal, closeObserved: true, atUtc: new Date().toISOString() });
      if (settled)
        return;
      settled = true;
      clearTimeout(timer);
      ok({ exitCode: code, signal, timedOut: false, closeObserved: true, processPin: filePin(processPath), stdoutPin: filePin(stdout), stderrPin: filePin(stderr) });
    });
  });
}
export {
  wxJson,
  readPinned,
  processIdentity,
  inspectActualSolver,
  filePin,
  expand,
  executeCommand,
  claimTaskAttemptLocks,
  checkPin,
  assertContext,
  actualProcess
};
