// @bun
var __defProp = Object.defineProperty;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __hasOwnProp = Object.prototype.hasOwnProperty;
function __accessProp(key) {
  return this[key];
}
var __toCommonJS = (from) => {
  var entry = (__moduleCache ??= new WeakMap).get(from), desc;
  if (entry)
    return entry;
  entry = __defProp({}, "__esModule", { value: true });
  if (from && typeof from === "object" || typeof from === "function") {
    for (var key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(entry, key))
        __defProp(entry, key, {
          get: __accessProp.bind(from, key),
          enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable
        });
  }
  __moduleCache.set(from, entry);
  return entry;
};
var __moduleCache;
var __returnValue = (v) => v;
function __exportSetter(name, newValue) {
  this[name] = __returnValue.bind(null, newValue);
}
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, {
      get: all[name],
      enumerable: true,
      configurable: true,
      set: __exportSetter.bind(all, name)
    });
};
var __esm = (fn, res) => () => (fn && (res = fn(fn = 0)), res);
var __promiseAll = (args) => Promise.all(args);

// scripts/bench-runner/types.ts
var STAGES;
var init_types = __esm(() => {
  STAGES = ["prepare", "qualify", "solve", "grade", "cleanup", "reconcile", "archive"];
});

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
function validateManifest(m) {
  demand(m?.schemaVersion === 1 && ["terminal-bench", "skillsbench"].includes(m.bench) && typeof m.taskId === "string" && /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,200}$/.test(m.taskId), "manifest_identity");
  demand(isAbsolute(m.root) && isAbsolute(m.artifactRoot) && realpathSync(m.root) === realpathSync(resolve(m.root)), "manifest_absolute_root");
  const o = m.original;
  demand(o && ["cpu", "memoryMb", "solveSeconds", "gradeSeconds", "toolSeconds", "providerSeconds"].every((k) => nonnegative(o[k]) && o[k] > 0), "original_limits_required");
  demand(["model", "provider", "reasoning"].every((k) => typeof o[k] === "string" && o[k].length > 0) && [o.taskCapUsd, o.priorKnownUsd, o.priorUnknownUsd].every(nonnegative) && o.priorKnownUsd + o.priorUnknownUsd <= o.taskCapUsd, "original_budget_required");
  demand(m.provenance?.sourcePins?.length > 0 && m.provenance.contractPins?.length > 0 && m.provenance.inventoryPin, "manifest_provenance_required");
  for (const p of [...m.provenance.sourcePins, ...m.provenance.contractPins, m.provenance.inventoryPin, ...m.provenance.authorizationPin ? [m.provenance.authorizationPin] : []])
    verifyPin(p);
  demand(typeof m.history?.stateKnown === "boolean" && typeof m.history.originalResultRecoveryRequired === "boolean" && Array.isArray(m.history.validResultPins) && Array.isArray(m.history.priorRunPins), "manifest_history_required");
  for (const p of [...m.history.validResultPins, ...m.history.priorRunPins, ...Object.values(m.history.successfulStageProofs).flat()])
    verifyPin(p);
  demand(m.stages && Object.keys(m.stages).every((k) => STAGES.includes(k)), "unknown_stage");
  for (const [stage, s] of Object.entries(m.stages)) {
    demand(s && ["reuse", "command"].includes(s.kind) && ["read-only", "native", "model", "grade", "oracle"].includes(s.effect) && Number.isInteger(s.timeoutSeconds) && s.timeoutSeconds > 0, "stage_contract");
    for (const p of s.evidencePins)
      verifyPin(p);
    if (s.kind === "reuse")
      demand(s.evidencePins.length > 0 && !!s.originalSuccessKey && !s.command, "reuse_requires_original_success_provenance");
    else
      demand(Array.isArray(s.command) && s.command.length > 0 && s.command.every((x) => typeof x === "string" && x.length > 0 && !x.includes("\x00")) && isAbsolute(s.command[0]), "command_array_absolute_executable_required");
    if (s.effect === "model")
      demand(stage === "solve" && s.timeoutSeconds <= o.solveSeconds, "model_only_original_solve_limit");
    if (s.effect === "grade")
      demand(stage === "grade" && s.timeoutSeconds <= o.gradeSeconds, "original_grade_limit");
    if (s.bundledStages) {
      demand(s.kind === "command" && s.bundledStages.length > 0 && new Set(s.bundledStages).size === s.bundledStages.length && s.bundledStages.every((k) => STAGES.includes(k)), "bundled_stage_names");
      demand(typeof s.outerTimeoutSeconds === "number" && s.outerTimeoutSeconds >= s.timeoutSeconds && s.outerTimeoutSeconds <= o.solveSeconds + o.gradeSeconds + o.toolSeconds * 2, "original_outer_custody_envelope");
    } else
      demand(s.outerTimeoutSeconds === undefined || s.outerTimeoutSeconds === s.timeoutSeconds, "outer_limit_requires_declared_bundle");
    if (s.kind === "command" && ["native", "model", "grade", "oracle"].includes(s.effect))
      demand(s.resourceMode === "driver-owned", "qualified_driver_must_own_original_pool_lease");
    if (s.effect === "oracle" && s.kind === "command") {
      demand(m.history.stateKnown && !!s.originalSuccessKey, "first_oracle_requires_known_history_and_checkpoint_key");
      const checkpoints = m.adapterConfig.successfulCheckpoints;
      demand(!checkpoints?.[s.originalSuccessKey], "successful_oracle_must_reuse_original_qualification");
    }
  }
  demand(m.adapterConfig && typeof m.adapterConfig === "object", "adapter_config_required");
  return m;
}
function loadManifest(path) {
  const before = pin(path), m = JSON.parse(readFileSync(path, "utf8"));
  validateManifest(m);
  verifyPin(before);
  return m;
}
var nonnegative = (n) => typeof n === "number" && Number.isFinite(n) && n >= 0;
var init_manifest = __esm(() => {
  init_types();
});

// scripts/bench-runner/stage-custody.ts
import { mkdirSync, existsSync, readdirSync, readFileSync as readFileSync2, writeFileSync, openSync as openSync2, closeSync as closeSync2, unlinkSync } from "fs";
import { join, resolve as resolve2 } from "path";
import { createHash as createHash2 } from "crypto";
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
function closeStageOperation(m, c, result) {
  demand(result.nativeClosed && result.financialClosed && result.proofPins.length > 0 && ["complete", "retryable"].includes(result.status), "independent_operation_closure_required");
  for (const p of result.proofPins)
    verifyPin(p);
  const receipt = read(pin(join(c.runDir, "stage-operation-receipt.json"))), lock = read(receipt.operationPin);
  demand(lock.attemptId === c.attemptId && lock.taskId === m.taskId && lock.bench === m.bench && lock.stage === c.stage, "operation_closure_identity");
  return wx(join(c.runDir, "stage-operation-closure.json"), { ...result, protocol: "bench-stage-operation-closure-v1", taskId: m.taskId, bench: m.bench, stage: c.stage, attemptId: c.attemptId, operationPin: receipt.operationPin, canonicalPin: receipt.canonicalPin });
}
var equal = (a, b) => JSON.stringify(a) === JSON.stringify(b), read = (p) => {
  verifyPin(p);
  return JSON.parse(readFileSync2(p.path, "utf8"));
}, wx = (p, v) => {
  writeFileSync(p, JSON.stringify(v, null, 2) + `
`, { flag: "wx", mode: 384 });
  return pin(p);
};
var init_stage_custody = __esm(() => {
  init_manifest();
});

// scripts/bench-runner/runtime.ts
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
var init_runtime = __esm(() => {
  init_stage_custody();
  init_manifest();
});

// scripts/bench-runner/bindings.ts
var exports_bindings = {};
__export(exports_bindings, {
  prepareContextDraft: () => prepareContextDraft,
  loadPreparedContext: () => loadPreparedContext
});
import { verify } from "crypto";
import { readFileSync as readFileSync4, existsSync as existsSync3 } from "fs";
import { join as join3, resolve as resolve4 } from "path";
function requireValue(value, message) {
  if (!value)
    throw Error(message);
}
function specFor(m, stage) {
  const scoped = m.adapterConfig.bindingSpecsByStage;
  const s = stage && scoped?.[stage] ? scoped[stage] : m.adapterConfig.bindingSpec;
  requireValue(s?.protocol === "bench-root-data-binding-v1", "binding_spec_protocol");
  checkPin(s.authorityPin);
  checkPin(s.entryTemplatePin);
  requireValue(Date.parse(s.expiresAtUtc) > Date.now(), "binding_spec_expired");
  requireValue(s.output && /^[a-zA-Z0-9._-]+$/.test(s.output.prefix), "safe_output_prefix");
  for (const [name, input] of Object.entries(s.inputs)) {
    requireValue(/^[A-Z][A-Z0-9_]*$/.test(name) && !["NONCE", "OUTPUT", "RECOVERY_ENTRY", "ENTRY_ENVELOPE", "MANIFEST_PATH", "CONTEXT_PATH", "MANIFEST", "CONTEXT"].includes(name), "binding_input_name");
    requireValue(input.select === "path" || input.select === "sha256", "binding_input_selection");
    checkPin(input.pin);
    requireValue([...m.provenance.sourcePins, ...m.provenance.contractPins].some((p) => p.path === input.pin.path && p.sha256 === input.pin.sha256), "binding_input_not_reviewed");
  }
  return s;
}
function valuesFor(s, c) {
  requireValue(/^[a-zA-Z0-9_-]+$/.test(c.attemptId), "safe_fresh_attempt_id");
  const values = {
    NONCE: c.attemptId,
    OUTPUT: resolve4(s.output.root, s.output.prefix + c.attemptId),
    RECOVERY_ENTRY: join3(c.runDir, "recovery.entry.json"),
    ENTRY_ENVELOPE: join3(c.runDir, "root-entry.signed.json"),
    MANIFEST_PATH: c.manifestPath,
    CONTEXT_PATH: join3(c.runDir, "intent-context.json"),
    MANIFEST: c.manifestPath,
    CONTEXT: join3(c.runDir, "intent-context.json")
  };
  for (const [key, input] of Object.entries(s.inputs))
    values[key] = input.select === "path" ? resolve4(input.pin.path) : input.pin.sha256;
  return values;
}
function substitute(value, values) {
  if (typeof value === "string")
    return value.replace(/\{\{bindings\.([A-Z][A-Z0-9_]*)\}\}/g, (_, key) => {
      requireValue(Object.hasOwn(values, key), "unknown_binding:" + key);
      return values[key];
    });
  if (Array.isArray(value))
    return value.map((x) => substitute(x, values));
  if (value && typeof value === "object")
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, substitute(v, values)]));
  return value;
}
function prepareContextDraft(m, c) {
  checkPin(c.manifestPin);
  const s = specFor(m, c.stage), values = valuesFor(s, c);
  const original = readPinned(s.entryTemplatePin), entry = substitute(original, values);
  requireValue(entry.taskId === m.taskId && entry.bench === m.bench && entry.nonce === c.attemptId, "fresh_template_entry_identity");
  requireValue(Array.isArray(entry.argv), "reviewed_driver_argv_required");
  const command = m.stages[c.stage]?.command;
  requireValue(Array.isArray(command) && JSON.stringify(entry.argv) === JSON.stringify(command.map((x) => expand(x, { ...c, bindings: values }))), "signed_argv_must_equal_manifest_expanded_command");
  entry.rootRuntimeBinding = {
    protocol: "bench-root-runtime-binding-v1",
    attemptId: c.attemptId,
    taskId: c.taskId,
    bench: c.bench,
    stage: c.stage,
    manifestPin: c.manifestPin,
    templatePin: s.entryTemplatePin,
    inputPins: Object.values(s.inputs).map((x) => x.pin),
    expiresAtUtc: s.expiresAtUtc,
    bindings: values
  };
  const draftPath = join3(c.runDir, "root-entry.draft.json");
  wxJson(draftPath, entry);
  const requestPath = join3(c.runDir, "binding-request.json");
  wxJson(requestPath, {
    protocol: "bench-root-signing-request-v1",
    draftPin: filePin(draftPath),
    authorityPin: s.authorityPin,
    signedEnvelopeDestination: values.ENTRY_ENVELOPE,
    signatureProtocol: "novaeve-root-signed-entry-v4",
    originalAuthorityMaySet: { coordinatorReviewed: true, phase: "ready" },
    newModelNativeLaneCalls: 0
  });
  return { draftPin: filePin(draftPath), requestPin: filePin(requestPath), bindings: values };
}
function loadPreparedContext(m, c, readOnly = false) {
  checkPin(c.manifestPin);
  const s = specFor(m, c.stage), values = valuesFor(s, c), envelope = JSON.parse(readFileSync4(values.ENTRY_ENVELOPE, "utf8").replace(/^\uFEFF/, ""));
  requireValue(envelope.protocol === "novaeve-root-signed-entry-v4" && envelope.entry && typeof envelope.signature === "string", "root_envelope_required");
  requireValue(verify(null, Buffer.from(JSON.stringify(envelope.entry)), readFileSync4(s.authorityPin.path), Buffer.from(envelope.signature, "base64")), "root_signature_invalid");
  const e = envelope.entry, b = e.rootRuntimeBinding;
  const command = m.stages[c.stage]?.command;
  requireValue(Array.isArray(command) && JSON.stringify(e.argv) === JSON.stringify(command.map((x) => expand(x, { ...c, bindings: values }))), "signed_argv_must_equal_manifest_expanded_command");
  requireValue(e.coordinatorReviewed === true && e.nonce === c.attemptId && e.taskId === m.taskId && e.bench === m.bench, "root_entry_identity");
  requireValue(b?.protocol === "bench-root-runtime-binding-v1" && b.attemptId === c.attemptId && b.taskId === c.taskId && b.bench === c.bench && b.stage === c.stage, "root_runtime_identity");
  requireValue(JSON.stringify(b.manifestPin) === JSON.stringify(c.manifestPin) && JSON.stringify(b.templatePin) === JSON.stringify(s.entryTemplatePin), "root_manifest_template_binding");
  requireValue(JSON.stringify(b.bindings) === JSON.stringify(values) && b.expiresAtUtc === s.expiresAtUtc && Date.parse(b.expiresAtUtc) > Date.now(), "root_binding_expired_or_changed");
  for (const p of b.inputPins)
    checkPin(p);
  requireValue(JSON.stringify(b.inputPins) === JSON.stringify(Object.values(s.inputs).map((x) => x.pin)), "root_input_pin_set");
  const expected = substitute(readPinned(s.entryTemplatePin), values);
  for (const [key, value] of Object.entries(expected))
    if (!["coordinatorReviewed", "phase", "rootRuntimeBinding"].includes(key))
      requireValue(JSON.stringify(e[key]) === JSON.stringify(value), "root_template_field_changed:" + key);
  if (!existsSync3(values.RECOVERY_ENTRY)) {
    requireValue(!readOnly, "original_plain_entry_missing_custody");
    wxJson(values.RECOVERY_ENTRY, e);
  } else
    requireValue(JSON.stringify(JSON.parse(readFileSync4(values.RECOVERY_ENTRY, "utf8"))) === JSON.stringify(e), "existing_plain_entry_changed");
  return { ...c, bindings: values };
}
var init_bindings = __esm(() => {
  init_runtime();
});

// app/src/H2H/db.ts
function all(db, sql, params) {
  return db.all(sql, params);
}
function run(db, sql, params) {
  return db.run(sql, params);
}
var init_db = () => {};

// app/src/engine/plugin.ts
import { statSync } from "fs";
import { resolve as resolve5 } from "path";
import { fileURLToPath, pathToFileURL } from "url";
function hostPath() {
  const given = process.env.TGENGIN_PLUGIN_HOST;
  if (given && given.trim())
    return given;
  try {
    const beside = fileURLToPath(new URL("./plugin-host.ts", "file:///F:/git/TgEngin-handoff-2026-10-07/TgEngin/app/src/engine/plugin.ts"));
    if (statSync(beside).isFile())
      return beside;
  } catch {}
  return "./engine/plugin-host.ts";
}

class Live {
  stamp;
  #w;
  #ready;
  #id = 0;
  #waiting = new Map;
  #dead = null;
  constructor(name, spec, stamp) {
    this.stamp = stamp;
    this.#w = new Worker(HOST);
    this.#ready = new Promise((ok, fail) => {
      const wall = setTimeout(() => fail(new Error(`${name}: the worker did not come up within ${READY_MS}ms (${HOST})`)), READY_MS);
      const up = () => {
        clearTimeout(wall);
        ok();
      };
      const no = (e) => {
        clearTimeout(wall);
        this.#die(e);
        fail(e);
      };
      this.#w.onmessage = (e) => {
        const m = e.data ?? {};
        if (m.kind === "ready")
          return up();
        if (m.kind === "failed")
          return no(new Error(`${name}: ${m.error}`));
        if (m.kind !== "done")
          return;
        const w = this.#waiting.get(Number(m.id));
        if (!w)
          return;
        this.#waiting.delete(Number(m.id));
        if (m.ok)
          w.ok(m.value);
        else
          w.fail(new Error(String(m.error)));
      };
      this.#w.onerror = (e) => no(new Error(`${name}: ${e.message}`));
    });
    this.#ready.catch(() => {});
    this.#w.postMessage({ kind: "load", module: spec });
  }
  #die(e) {
    this.#dead ??= e;
    for (const w of this.#waiting.values())
      w.fail(e);
    this.#waiting.clear();
  }
  async call(exp, arg) {
    await this.#ready;
    if (this.#dead)
      throw this.#dead;
    const id = ++this.#id;
    return await new Promise((ok, fail) => {
      this.#waiting.set(id, { ok, fail });
      this.#w.postMessage({ kind: "call", id, export: exp, arg });
    });
  }
  close() {
    this.#dead ??= new Error("already closed");
    this.#w.terminate();
  }
}

class Plugins {
  #live = new Map;
  #on = new Map;
  host = HOST;
  async probe() {
    const w = new Worker(HOST);
    try {
      await new Promise((ok, fail) => {
        const wall = setTimeout(() => fail(new Error(`did not come up within ${READY_MS}ms`)), READY_MS);
        w.onmessage = () => {
          clearTimeout(wall);
          ok();
        };
        w.onerror = (e) => {
          clearTimeout(wall);
          fail(new Error(e.message));
        };
        w.postMessage({ kind: "load", module: "file:///tgengin-probe-not-a-real-module" });
      });
      return null;
    } catch (e) {
      return `plugin path unusable (${HOST}): ${e instanceof Error ? e.message : String(e)} - point TGENGIN_PLUGIN_HOST at plugin-host.ts`;
    } finally {
      w.terminate();
    }
  }
  async call(name, spec, arg) {
    const hash = spec.lastIndexOf("#");
    const path = resolve5(hash === -1 ? spec : spec.slice(0, hash));
    const exp = hash === -1 ? "default" : spec.slice(hash + 1);
    let stamp = 0;
    try {
      stamp = statSync(path).mtimeMs;
    } catch {
      throw new Error(`${name}: cannot find ${path}`);
    }
    this.#on.set(name, path);
    const had = this.#live.get(path);
    if (!had || had.stamp !== stamp) {
      had?.close();
      this.#live.set(path, new Live(name, pathToFileURL(path).href, stamp));
    }
    return await this.#live.get(path).call(exp, arg);
  }
  drop(name) {
    const path = this.#on.get(name);
    if (path === undefined)
      return false;
    this.#on.delete(name);
    if ([...this.#on.values()].includes(path))
      return false;
    this.#live.get(path)?.close();
    this.#live.delete(path);
    return true;
  }
  names() {
    return [...this.#live.keys()].sort();
  }
  closeAll() {
    for (const l of this.#live.values())
      l.close();
    this.#live.clear();
    this.#on.clear();
  }
}
var HOST, READY_MS = 1e4;
var init_plugin = __esm(() => {
  HOST = hostPath();
});

// app/src/engine/registry.ts
class Registry {
  #by = new Map;
  plugins = new Plugins;
  beforeSync = null;
  register(db, name, expectMs, fn) {
    if (!IN.test(name))
      throw new Error(`an in-process handle name must start with fn: - got ${name}`);
    if (!Number.isFinite(expectMs) || expectMs <= 0)
      throw new Error(`expect_ms for ${name} must be a positive number`);
    this.#by.set(name, { name, expectMs, call: fn, where: "in" });
    run(db, `insert into handle (name, expect_ms, module) values (?, ?, null)
             on conflict(name) do update set expect_ms = excluded.expect_ms`, [name, expectMs]);
  }
  adopt(name, expectMs, fn) {
    this.#by.set(name, { name, expectMs, call: fn, where: "out" });
  }
  sync(db) {
    this.beforeSync?.();
    const rows = all(db, `select name, expect_ms, module from handle`);
    const added = [];
    const missing = [];
    for (const r of rows) {
      if (this.#by.has(r.name)) {
        this.#by.get(r.name).expectMs = r.expect_ms;
        continue;
      }
      if (OUT.test(r.name)) {
        this.#by.set(r.name, { name: r.name, expectMs: r.expect_ms, where: "out", call: remote(r.name) });
        added.push(r.name);
      } else if (IN.test(r.name) && r.module) {
        const spec = r.module;
        this.#by.set(r.name, {
          name: r.name,
          expectMs: r.expect_ms,
          where: "in",
          plugin: spec,
          call: (arg) => this.plugins.call(r.name, spec, arg)
        });
        added.push(r.name);
      } else {
        missing.push(r.name);
      }
    }
    const inDb = new Set(rows.map((r) => r.name));
    const dropped = [];
    for (const [name, e] of this.#by) {
      if (e.plugin === undefined || inDb.has(name))
        continue;
      this.plugins.drop(name);
      this.#by.delete(name);
      dropped.push(name);
    }
    if (missing.length) {
      throw new Error(`registered in the database but never registered in this process: ${missing.join(", ")}`);
    }
    return { added, missing, dropped };
  }
  get(name) {
    const e = this.#by.get(name);
    if (!e)
      throw new Error(`no such handle: ${name}`);
    return e;
  }
  has(name) {
    return this.#by.has(name);
  }
  names() {
    return [...this.#by.keys()].sort();
  }
}
async function graderFetch(url, init) {
  const token = process.env.TGENGIN_GRADER_TOKEN;
  if (!token)
    return fetch(url, init);
  const raw = process.env.TGENGIN_GRADER_ORIGINS?.trim();
  if (!raw)
    throw new Error("TGENGIN_GRADER_ORIGINS is required when TGENGIN_GRADER_TOKEN is configured");
  let entries;
  try {
    entries = raw.startsWith("[") ? JSON.parse(raw) : raw.split(",");
  } catch {
    throw new Error("TGENGIN_GRADER_ORIGINS must be a list of URL origins");
  }
  if (!Array.isArray(entries) || entries.length === 0)
    throw new Error("TGENGIN_GRADER_ORIGINS must be a nonempty list of URL origins");
  const origins = new Set(entries.map((entry) => {
    try {
      const parsed = new URL(String(entry).trim());
      if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash)
        throw new Error;
      return parsed.origin;
    } catch {
      throw new Error("TGENGIN_GRADER_ORIGINS contains an invalid URL origin");
    }
  }));
  const headers = new Headers(init.headers);
  headers.delete("X-ObjRun-Grader-Token");
  const trusted = origins.has(new URL(url).origin);
  if (trusted)
    headers.set("X-ObjRun-Grader-Token", token);
  return fetch(url, { ...init, headers, ...trusted ? { redirect: "error" } : {} });
}
function remote(url) {
  return async (arg) => {
    const res = await graderFetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(arg ?? {})
    });
    if (!res.ok)
      throw Object.assign(new Error(`${url} returned ${res.status}`), { statusCode: res.status });
    return await res.json();
  };
}
var IN, OUT;
var init_registry = __esm(() => {
  init_db();
  init_plugin();
  IN = /^fn:/;
  OUT = /^https?:\/\//;
});

// app/src/objective/spec.ts
var init_spec = () => {};

// app/src/objective/run.ts
var init_run = __esm(() => {
  init_spec();
});

// scripts/repair-2026-10-08/campaign-contract.ts
function checkedOutputTokens(body) {
  const values = [body.max_tokens, body.max_completion_tokens].filter((value) => value !== undefined && value !== null);
  if (!values.length || values.some((value) => !count(value) || value < 1 || value > MAX_OUTPUT_TOKENS))
    throw new Error(`Output token limit must be a finite positive integer at most ${MAX_OUTPUT_TOKENS}`);
  if (values.length > 1 && values[0] !== values[1])
    throw new Error("Conflicting output token limits");
  return values[0];
}
function completionFault(value) {
  const data = object(value);
  if (!data || data.error)
    return "InvalidCompletionEnvelope";
  if (!Array.isArray(data.choices) || data.choices.length === 0)
    return "MissingCompletionChoices";
  for (const entry of data.choices) {
    const choice = object(entry), message = object(choice?.message);
    if (!message || message.role !== "assistant")
      return "InvalidCompletionMessage";
    const tools = message.tool_calls;
    if (tools !== undefined && tools !== null) {
      if (!Array.isArray(tools))
        return "InvalidCompletionToolCalls";
      for (const item of tools) {
        const call = object(item), fn = object(call?.function);
        if (call?.type !== "function" || typeof call.id !== "string" || !call.id || typeof fn?.name !== "string" || !fn.name || typeof fn.arguments !== "string")
          return "InvalidCompletionToolCall";
      }
    }
    const hasText = typeof message.content === "string";
    const hasTools = Array.isArray(tools) && tools.length > 0;
    const hasReasoning = [message.reasoning_content, message.reasoning].some((value2) => typeof value2 === "string" && value2.length > 0);
    if (!hasText && !hasTools && !hasReasoning)
      return "MissingCompletionMessagePayload";
    if (message.content !== undefined && message.content !== null && !hasText)
      return "InvalidCompletionContent";
  }
  return;
}
function usageCounts(value) {
  const usage = object(value);
  const input = usage?.prompt_tokens, output = usage?.completion_tokens;
  const cached = usage?.prompt_cache_hit_tokens ?? object(usage?.prompt_tokens_details)?.cached_tokens ?? 0;
  if (!count(input) || !count(output) || !count(cached) || cached > input)
    throw new Error("InvalidProviderTokenUsage");
  return { input, output, cached };
}
function validTokenUsage(value) {
  try {
    usageCounts(value);
    return true;
  } catch {
    return false;
  }
}
function tokenCostUpperBound(usage, rates = PEAK_RATES) {
  if (Object.values(rates).some((rate) => !Number.isFinite(rate) || rate < 0))
    throw new Error("Invalid frozen price rates");
  const { input, output, cached } = usageCounts(usage);
  return ((input - cached) * rates.input + cached * rates.cachedInput + output * rates.output) / 1e6;
}
function isNonGenerationRateRejection(call) {
  return call.nonGenerationRejection === "upstream_rate_limit" && call.httpStatus === 429 && call.providerAttempted === true && call.costBasis === "known_uncharged" && call.usdUpperBound === 0 && !call.usage && !call.requestId && !call.fault && !!call.finishedAt;
}
function reconcileReceiptCost(receipt, reservationUsd, options = {}) {
  if (!Number.isFinite(reservationUsd) || reservationUsd < 0)
    throw new Error("Invalid request cost reservation");
  const before = receipt.accountedUpperBoundUsd ?? 0;
  if (!Number.isFinite(before) || before < 0)
    throw new Error("Invalid accounted request cost");
  let upper = reservationUsd;
  let basis = options.knownUncharged ? "known_uncharged" : "reservation";
  if (options.knownUncharged)
    upper = 0;
  if (options.provider && !options.knownUncharged) {
    const usage = object(receipt.usage), cost = usage?.cost;
    if (typeof cost === "number" && Number.isFinite(cost) && cost >= 0) {
      upper = cost;
      basis = "provider_reported_usd";
      receipt.billedCostUsd = cost;
      if (!validTokenUsage(usage))
        receipt.fault ??= "InvalidProviderTokenUsage";
    } else {
      receipt.fault ??= "MissingOrInvalidOpenRouterUsdCost";
    }
  } else if (receipt.usage !== undefined) {
    if (validTokenUsage(receipt.usage)) {
      upper = tokenCostUpperBound(receipt.usage, options.rates);
      basis = "reported_usage";
    } else {
      upper = reservationUsd;
      basis = "reservation";
      receipt.fault ??= "InvalidProviderTokenUsage";
    }
  }
  receipt.reservationUsd = reservationUsd;
  receipt.usdUpperBound = upper;
  receipt.accountedUpperBoundUsd = upper;
  receipt.costBasis = basis;
  return { usdUpperBound: upper, deltaUsd: upper - before, costBasis: basis };
}
var MAX_OUTPUT_TOKENS = 16384, PEAK_RATES, object = (value) => value !== null && typeof value === "object" && !Array.isArray(value) ? value : undefined, count = (value) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
var init_campaign_contract = __esm(() => {
  init_registry();
  init_run();
  init_spec();
  PEAK_RATES = Object.freeze({ input: 0.3, cachedInput: 0.006, output: 1.2 });
});

// scripts/repair-2026-10-10/full-f/shared/digitalocean-provider.ts
function officialOpenRouterFault(data, expectedProvider = BENCHMARK_PROVIDER.providerName) {
  if (data?.provider !== expectedProvider)
    return "UnexpectedOpenRouterProvider";
  if (![BENCHMARK_PROVIDER.model, BENCHMARK_PROVIDER.canonicalModel].includes(data?.model))
    return "UnexpectedOpenRouterModel";
  if (typeof data?.id !== "string" || !data.id)
    return "MissingOpenRouterGenerationId";
  const cost = data?.usage?.cost;
  if (typeof cost !== "number" || !Number.isFinite(cost) || cost < 0)
    return "MissingOrInvalidOpenRouterUsdCost";
}
function openRouterRateLimitRejection(data, status, providerName) {
  return status === 429 && data?.error?.code === 429 && data.error.metadata?.limit_source === "upstream_provider_shared_pool" && data.error.metadata.provider_name === providerName && typeof data.error.metadata.raw === "string" && data.error.metadata.raw.includes("temporarily rate-limited upstream") && !data.id && !data.usage && !data.choices;
}
var BENCHMARK_PROVIDER;
var init_digitalocean_provider = __esm(() => {
  BENCHMARK_PROVIDER = Object.freeze({
    kind: "openrouter-deepseek",
    model: "deepseek/deepseek-v4.1-flash",
    canonicalModel: "deepseek/deepseek-v4.1-flash-20260910",
    baseURL: "https://openrouter.ai/api/v1",
    endpoint: "https://openrouter.ai/api/v1/chat/completions",
    keyEnv: "OPENROUTER_API_KEY",
    currency: "USD",
    providerName: "DigitalOcean",
    providerSlug: "digitalocean",
    peakRates: Object.freeze({ input: 0.3, cachedInput: 0.006, output: 1.2 }),
    routing: Object.freeze({ only: ["digitalocean"], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } }),
    forcedToolMode: "constrained-auto"
  });
});

// scripts/repair-2026-10-10/full-f/shared/digitalocean-journal.ts
import { createHash as createHash4, randomBytes } from "crypto";
import { closeSync as closeSync4, existsSync as existsSync4, fstatSync, fsyncSync, lstatSync as lstatSync2, mkdirSync as mkdirSync3, openSync as openSync4, readFileSync as readFileSync5, readSync as readSync2, readdirSync as readdirSync3, realpathSync as realpathSync2, renameSync, statSync as statSync2, writeSync } from "fs";
import { isAbsolute as isAbsolute2, join as join4, relative, resolve as resolve6 } from "path";
import { gunzipSync, gzipSync } from "zlib";
function demand2(ok, code) {
  if (!ok)
    throw new CampaignJournalError(code);
}
function ordinaryDirectory(path) {
  demand2(isAbsolute2(path), "absolute_directory_required");
  mkdirSync3(path, { recursive: true });
  demand2(lstatSync2(path).isDirectory() && !lstatSync2(path).isSymbolicLink(), "ordinary_directory_required");
  return realpathSync2(path);
}
function regularInStore(path, store) {
  const full = resolve6(path), rel = relative(store, full);
  demand2(rel && !rel.startsWith("..") && !isAbsolute2(rel), "raw_outside_store");
  let current = store;
  for (const component of rel.split(/[\\/]/)) {
    current = join4(current, component);
    const s = lstatSync2(current);
    demand2(!s.isSymbolicLink(), "raw_reparse");
  }
  demand2(lstatSync2(full).isFile() && realpathSync2(full) === full, "raw_not_regular");
  return full;
}
function fileHash(path) {
  const before = statSync2(path), fd = openSync4(path, "r"), digest = createHash4("sha256"), buffer = Buffer.alloc(64 * 1024);
  let at = 0;
  try {
    while (at < before.size) {
      const n = readSync2(fd, buffer, 0, Math.min(buffer.length, before.size - at), at);
      demand2(n > 0, "hash_short_read");
      digest.update(buffer.subarray(0, n));
      at += n;
    }
  } finally {
    closeSync4(fd);
  }
  const after = statSync2(path);
  demand2(before.size === after.size && before.mtimeMs === after.mtimeMs, "hash_file_changed");
  return digest.digest("hex");
}
function rawEvidence(path, expected, compressedExpected, store, parse = true) {
  regularInStore(path, store);
  const before = statSync2(path);
  const zipped = readFileSync5(path);
  demand2(zipped.length <= MAX_RESPONSE + 1024 * 1024, "raw_resource_limit");
  const raw = gunzipSync(zipped, { maxOutputLength: MAX_RESPONSE });
  const after = statSync2(path);
  demand2(before.size === after.size && before.mtimeMs === after.mtimeMs && hash(zipped) === compressedExpected && hash(raw) === expected, "raw_digest_changed");
  const data = parse ? JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)) : undefined;
  return { raw, data };
}
function frozenRouting(config) {
  const slug = config.providerSlug ?? "deepseek";
  demand2(config.zeroChargePolicy === undefined || config.zeroChargePolicy === "explicit-rate-rejection-v2", "journal_zero_charge_policy");
  demand2(["deepseek", "relace", "digitalocean"].includes(slug) && (config.providerName === undefined || config.providerName === { relace: "Relace", deepseek: "DeepSeek", digitalocean: "DigitalOcean" }[slug]), "journal_provider_identity");
  const route = { only: [slug], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } };
  demand2(config.providerRouting === undefined || same(config.providerRouting, route), "journal_provider_route");
  return route;
}
function requestValues(raw, data, config) {
  demand2(data && typeof data === "object" && !Array.isArray(data) && data.model === (config?.model ?? "deepseek-flash") && data.stream !== true, "invalid_frozen_request");
  if (config?.provider)
    demand2(same(data.provider, frozenRouting(config)) && data.models === undefined && data.route === undefined && data.plugins === undefined, "pinned_provider_routing_required");
  const limit = checkedOutputTokens(data);
  demand2(Array.isArray(data.messages), "invalid_request_messages");
  const reservationUsd = ((raw.length + 2048 + data.messages.length * 256) * 0.3 + limit * 1.2) / 1e6;
  return { reservationUsd, wireParameters: Object.fromEntries(WIRE.filter((k) => (k in data)).map((k) => [k, data[k]])) };
}
function checkedStart(c, seq, store, config) {
  demand2(typeof c.route === "string" && c.route.length > 0 && Buffer.byteLength(c.route) <= 1024 && !/[\r\n\0]/.test(c.route), "invalid_route");
  demand2(Number.isFinite(Date.parse(c.startedAt)) && c.providerAttempted === false, "invalid_start_receipt");
  demand2(c.requestFile === join4(store, `provider-${seq}-request.json.gz`), "request_sequence_path");
  const { raw, data } = rawEvidence(c.requestFile, c.requestSha256, c.requestCompressedSha256, store);
  const expected = requestValues(raw, data, config);
  demand2(raw.length === c.requestBytes && c.requestedModel === data.model && same(c.wireParameters, expected.wireParameters) && finite(c.reservationUsd) && Math.abs(c.reservationUsd - expected.reservationUsd) <= EPS, "request_receipt_mismatch");
}
function routingRejection(config, data, status) {
  return !!config.provider && status === 404 && Array.isArray(data?.error?.metadata?.routing_funnel) && typeof data?.error?.metadata?.failed_routing_step === "string" && data.error.metadata.failed_routing_step.startsWith("Filter by ") && !data.usage;
}
function rateRejection(config, data, status) {
  return !!config.provider && config.zeroChargePolicy === "explicit-rate-rejection-v2" && openRouterRateLimitRejection(data, status, config.providerName ?? "DeepSeek");
}
function checkedFinish(c, start, seq, store, config) {
  for (const key of ["route", "startedAt", "requestSha256", "requestedModel", "requestFile", "wireParameters", "requestCompressedSha256", "requestBytes"])
    demand2(same(c[key], start[key]), "finish_start_mismatch");
  demand2(typeof c.providerAttempted === "boolean" && typeof c.finishedAt === "string" && Number.isFinite(Date.parse(c.finishedAt)) && Date.parse(c.finishedAt) >= Date.parse(c.startedAt), "invalid_finish_time");
  if (!c.providerAttempted)
    demand2(c.confirmedNoForward === true && !c.responseFile && !c.usage, "unproven_zero_charge");
  let rejectedBeforeGeneration = false, rateLimited = false;
  if (c.responseFile) {
    demand2(c.providerAttempted && c.responseFile === join4(store, `provider-${seq}-response.json.gz`) && c.responseSha256 && c.responseCompressedSha256, "response_sequence_path");
    const { raw } = rawEvidence(c.responseFile, c.responseSha256, c.responseCompressedSha256, store, false);
    let data;
    try {
      data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
    } catch {}
    if (data && typeof data === "object") {
      rejectedBeforeGeneration = routingRejection(config, data, c.httpStatus);
      rateLimited = rateRejection(config, data, c.httpStatus);
      demand2(same(data.usage, c.usage) && (typeof data.model === "string" ? data.model : undefined) === c.servedModel && (typeof data.id === "string" ? data.id : undefined) === c.requestId, "response_receipt_mismatch");
      if (config.provider) {
        demand2((typeof data.provider === "string" ? data.provider : undefined) === c.providerName, "provider_receipt_mismatch");
        const routeFault = c.httpStatus === 200 ? officialOpenRouterFault(data, config.providerName ?? "DeepSeek") : undefined;
        if (routeFault)
          demand2(c.fault === routeFault, "official_provider_fault_missing");
      }
      if (c.httpStatus === 200)
        demand2(c.completionValid === !completionFault(data) && c.completionFault === completionFault(data), "completion_receipt_mismatch");
    } else
      demand2(c.fault && c.usage === undefined && c.servedModel === undefined && c.requestId === undefined && c.completionValid === undefined, "invalid_json_receipt_mismatch");
  } else
    demand2(c.fault && !c.usage && c.servedModel === undefined && c.requestId === undefined, "missing_response_evidence");
  demand2(c.nonGenerationRejection === (rateLimited ? "upstream_rate_limit" : undefined), "rate_rejection_raw_binding");
  const expected = { usage: c.usage };
  reconcileReceiptCost(expected, start.reservationUsd, { provider: config.provider, knownUncharged: rateLimited || rejectedBeforeGeneration || !c.providerAttempted || !c.usage && [401, 402, 403].includes(c.httpStatus ?? 0) });
  demand2(c.billedCostUsd === expected.billedCostUsd, "reported_usd_cost_mismatch");
  demand2(c.reservationUsd === start.reservationUsd && c.costBasis === expected.costBasis && finite(c.usdUpperBound) && finite(c.accountedUpperBoundUsd) && Math.abs(c.usdUpperBound - expected.usdUpperBound) <= EPS && c.usdUpperBound === c.accountedUpperBoundUsd, "cost_receipt_mismatch");
}
function pendingOf(active) {
  const result = new Map;
  for (const c of active.values())
    result.set(c.route, (result.get(c.route) ?? 0) + 1);
  return Object.fromEntries(result);
}
function reserveOf(active) {
  let n = 0;
  for (const c of active.values())
    n += c.reservationUsd;
  return n;
}
function financialState(config, configSha256, active, accepted, finished, spent, prefix, stopReason) {
  return { protocol: config.protocol, ...config.provider ? { currency: "USD", provider: config.provider } : {}, campaign: config.campaign, configSha256, capUsd: config.capUsd, priorCampaignCostUpperBoundUsd: config.priorCampaignCostUpperBoundUsd, recordedUsageUpperBoundUsd: spent, reservedUpperBoundUsd: reserveOf(active), pending: pendingOf(active), active: [...active].map(([requestSeq, c]) => ({ requestSeq, route: c.route, requestSha256: c.requestSha256, reservationUsd: c.reservationUsd })), acceptedRequestCount: accepted, finishedRequestCount: finished, durablePrefix: { ...prefix }, ...stopReason ? { stopReason } : {} };
}
function* lines(fd, length) {
  let offset = 0, at = 0, carry = Buffer.alloc(0);
  const buffer = Buffer.alloc(16 * 1024);
  while (at < length) {
    const n = readSync2(fd, buffer, 0, Math.min(buffer.length, length - at), at);
    demand2(n > 0, "journal_short_read");
    at += n;
    carry = Buffer.concat([carry, buffer.subarray(0, n)]);
    for (;; ) {
      const newline = carry.indexOf(10);
      if (newline < 0)
        break;
      const line = carry.subarray(0, newline + 1);
      demand2(line.length <= MAX_LINE, "journal_line_limit");
      yield { offset, line };
      offset += line.length;
      carry = carry.subarray(newline + 1);
    }
    demand2(carry.length <= MAX_LINE, "journal_line_limit");
  }
  demand2(carry.length === 0, "truncated_journal");
}
function inspectCampaignJournal(directory) {
  return inspect(directory);
}
function inspect(directory, ownedExport) {
  const result = { valid: false, accountingClosed: false, eligibleForScoreCertification: false, errors: [], offsets: new Map, routes: new Map, journalPath: join4(resolve6(directory), "api-events.jsonl"), directory: resolve6(directory) };
  let fd;
  try {
    const store = realpathSync2(directory);
    demand2(store === resolve6(directory), "journal_directory_identity");
    const configBytes = readFileSync5(join4(store, "journal-config.json")), config = JSON.parse(configBytes.toString("utf8"));
    const providerValid = config.provider === "openrouter-deepseek" ? config.protocol === OPENROUTER_JOURNAL_PROTOCOL && config.model === BENCHMARK_PROVIDER.model && config.currency === "USD" : config.provider === undefined && config.protocol === CAMPAIGN_JOURNAL_PROTOCOL && config.model === "deepseek-flash";
    if (config.provider)
      frozenRouting(config);
    demand2(providerValid && Number.isSafeInteger(config.pendingLimit) && config.pendingLimit >= 4 && config.pendingLimit <= 50 && config.maxLineBytes === MAX_LINE && config.maxJournalBytes === MAX_JOURNAL && finite(config.capUsd) && config.capUsd > 0 && finite(config.priorCampaignCostUpperBoundUsd), "journal_config_invalid");
    const configSha = hash(configBytes), before = statSync2(result.journalPath);
    demand2(before.size <= MAX_JOURNAL && lstatSync2(result.journalPath).isFile() && !lstatSync2(result.journalPath).isSymbolicLink(), "journal_resource_or_identity");
    fd = openSync4(result.journalPath, "r");
    const active = new Map, ids = new Set;
    let accepted = 0, finished = 0, spent = 0, allProviderValid = true;
    let prefix = { bytes: 0, eventCount: 0, lastSha256: configSha };
    for (const { offset, line } of lines(fd, before.size)) {
      const e = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line.subarray(0, -1)));
      demand2(same(Object.keys(e), ["protocol", "eventSeq", "previousEventSha256", "kind", "requestSeq", "record"]) && Buffer.from(json(e) + `
`).equals(line), "unknown_or_noncanonical_event");
      demand2(e.protocol === config.protocol && e.eventSeq === prefix.eventCount && e.previousEventSha256 === prefix.lastSha256 && Number.isSafeInteger(e.requestSeq) && e.requestSeq >= 0, "journal_chain_or_sequence");
      if (e.kind === "start") {
        demand2(e.requestSeq === accepted && active.size < config.pendingLimit && !active.has(e.requestSeq), "duplicate_or_unbounded_start");
        checkedStart(e.record, e.requestSeq, store, config);
        demand2(config.priorCampaignCostUpperBoundUsd + spent + reserveOf(active) + e.record.reservationUsd <= config.capUsd + EPS, "admission_exceeded_cap");
        active.set(e.requestSeq, e.record);
        accepted++;
      } else if (e.kind === "finish") {
        const start = active.get(e.requestSeq);
        demand2(start && !result.offsets.has(e.requestSeq), "duplicate_or_unknown_finish");
        checkedFinish(e.record, start, e.requestSeq, store, config);
        if (e.record.requestId) {
          demand2(!ids.has(e.record.requestId), "duplicate_provider_id");
          ids.add(e.record.requestId);
        }
        spent += e.record.usdUpperBound;
        active.delete(e.requestSeq);
        finished++;
        allProviderValid &&= isNonGenerationRateRejection(e.record) || e.record.providerAttempted && e.record.httpStatus === 200 && e.record.completionValid === true && validTokenUsage(e.record.usage) && !e.record.fault;
        result.offsets.set(e.requestSeq, { offset, bytes: line.length, sha256: hash(line) });
        const route = result.routes.get(e.record.route) ?? [];
        route.push(e.requestSeq);
        result.routes.set(e.record.route, route);
      } else
        throw new CampaignJournalError("unknown_event");
      prefix = { bytes: offset + line.length, eventCount: prefix.eventCount + 1, lastSha256: hash(line) };
      result.snapshot = financialState(config, configSha, active, accepted, finished, spent, prefix);
    }
    result.snapshot ??= financialState(config, configSha, active, accepted, finished, spent, prefix);
    result.prefix = prefix;
    result.config = config;
    const checkpoint = JSON.parse(readFileSync5(join4(store, "api-state.json"), "utf8"));
    const expected = { ...result.snapshot, ...checkpoint.stopReason ? { stopReason: checkpoint.stopReason } : {} };
    demand2(same(checkpoint, expected), "checkpoint_prefix_or_accounting");
    const requests = readdirSync3(store).filter((n) => /^provider-\d+-request\.json\.gz$/.test(n));
    const responses = readdirSync3(store).filter((n) => /^provider-\d+-response\.json\.gz$/.test(n));
    demand2(requests.length === accepted && requests.every((n) => Number(n.match(/\d+/)[0]) < accepted), "unindexed_raw_request");
    demand2(responses.every((n) => result.offsets.has(Number(n.match(/\d+/)[0]))), "unindexed_raw_response");
    if (ownedExport)
      demand2(ownedExport.path === join4(store, "api-ledger.json.partial") && statSync2(ownedExport.path).size === ownedExport.bytes && fileHash(ownedExport.path) === ownedExport.sha256, "owned_export_partial_changed");
    demand2(!existsSync4(join4(store, "journal-error.json")) && !readdirSync3(store).some((n) => n.includes(".partial") && join4(store, n) !== ownedExport?.path || n.startsWith("api-state.json.new-")), "unclosed_error_or_partial");
    const after = statSync2(result.journalPath);
    demand2(before.size === after.size && before.mtimeMs === after.mtimeMs && hash(readFileSync5(join4(store, "journal-config.json"))) === configSha, "journal_changed_during_inspection");
    result.valid = true;
    result.accountingClosed = active.size === 0 && accepted === finished;
    result.eligibleForScoreCertification = result.accountingClosed && allProviderValid && !checkpoint.stopReason && config.priorCampaignCostUpperBoundUsd + spent <= config.capUsd + EPS;
  } catch (e) {
    result.errors.push(e instanceof CampaignJournalError ? e.code : e.code ?? e.name);
  } finally {
    if (fd !== undefined)
      closeSync4(fd);
  }
  return result;
}

class CampaignJournal {
  hooks;
  directory;
  outputDirectory;
  config;
  configSha256;
  journalPath;
  fd = -1;
  prefix;
  journalMtime = 0;
  lastLine;
  active = new Map;
  accepted = 0;
  finished = 0;
  spent = 0;
  stopReason;
  poisoned;
  exported = false;
  closedProof;
  closed = false;
  providerIds = new Set;
  metrics = { journalBytesWritten: 0, checkpointBytesWritten: 0, rawGzipBytesWritten: 0, exportBytesWritten: 0, fsyncCallsReturned: 0, maxHotMetadataBytes: 0 };
  constructor(options, hooks) {
    this.hooks = hooks;
    demand2(finite(options.capUsd) && options.capUsd > 0 && finite(options.priorCampaignCostUpperBoundUsd) && /^repair-[0-9TZ-]+$/.test(options.campaign), "invalid_journal_options");
    this.directory = ordinaryDirectory(resolve6(options.directory));
    this.outputDirectory = ordinaryDirectory(resolve6(options.outputDirectory ?? options.directory));
    demand2(!readdirSync3(this.directory).some((n) => ["api-events.jsonl", "journal-config.json", "api-state.json", "journal-error.json"].includes(n) || /^provider-\d+-/.test(n)), "existing_journal");
    if (options.provider)
      demand2(options.provider.kind === BENCHMARK_PROVIDER.kind && options.provider.model === BENCHMARK_PROVIDER.model, "unsupported_journal_provider");
    this.config = { protocol: options.provider ? OPENROUTER_JOURNAL_PROTOCOL : CAMPAIGN_JOURNAL_PROTOCOL, campaign: options.campaign, capUsd: options.capUsd, priorCampaignCostUpperBoundUsd: options.priorCampaignCostUpperBoundUsd, pendingLimit: 50, model: options.provider?.model ?? "deepseek-flash", ...options.provider ? {
      provider: options.provider.kind,
      currency: "USD",
      providerName: options.provider.providerName,
      providerSlug: options.provider.providerSlug,
      providerRouting: options.provider.routing,
      zeroChargePolicy: "explicit-rate-rejection-v2"
    } : {}, maxLineBytes: MAX_LINE, maxJournalBytes: MAX_JOURNAL, createdAt: new Date().toISOString() };
    const configRaw = Buffer.from(JSON.stringify(this.config, null, 2) + `
`);
    this.configSha256 = hash(configRaw);
    this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configSha256 };
    this.journalPath = join4(this.directory, "api-events.jsonl");
    try {
      this.persistExclusive(join4(this.directory, "journal-config.json"), configRaw, "config", "checkpointBytesWritten");
      this.fd = openSync4(this.journalPath, "wx+");
      this.sync(this.fd, this.journalPath, "journal:create");
      this.journalMtime = fstatSync(this.fd).mtimeMs;
      this.checkpoint("create");
    } catch (e) {
      this.close();
      if (e instanceof CampaignJournalError)
        throw e;
      throw new CampaignJournalError("journal_create_io", e.code);
    }
  }
  write(fd, path, raw, stage, metric) {
    let at = 0;
    while (at < raw.length) {
      const op = { kind: "write", stage, path, fd, bytes: raw.length - at };
      this.hooks.before?.(op);
      const n = writeSync(fd, raw, at, raw.length - at);
      demand2(n > 0, "short_write");
      this.metrics[metric] += n;
      at += n;
      this.hooks.after?.({ ...op, bytes: n });
    }
  }
  sync(fd, path, stage) {
    const op = { kind: "fsync", stage, path, fd };
    this.hooks.before?.(op);
    fsyncSync(fd);
    this.metrics.fsyncCallsReturned++;
    this.hooks.after?.(op);
  }
  persistExclusive(path, raw, stage, metric) {
    const fd = openSync4(path, "wx", 384);
    try {
      this.write(fd, path, raw, stage, metric);
      this.sync(fd, path, stage);
    } finally {
      try {
        closeSync4(fd);
      } catch {}
    }
  }
  state() {
    return financialState(this.config, this.configSha256, this.active, this.accepted, this.finished, this.spent, this.prefix, this.stopReason);
  }
  snapshot() {
    return { ...this.state(), ...this.poisoned ? { error: this.poisoned.code } : {}, metrics: { ...this.metrics } };
  }
  poison(code, stage, uncommittedReceipt) {
    const error = this.poisoned ?? new CampaignJournalError(code, stage);
    this.poisoned = error;
    try {
      this.persistExclusive(join4(this.directory, "journal-error.json"), Buffer.from(json({ protocol: CAMPAIGN_JOURNAL_PROTOCOL, error: error.code, stage, state: this.state(), ...uncommittedReceipt ? { uncommittedReceipt } : {} }) + `
`), "error_diagnostic", "checkpointBytesWritten");
    } catch {}
    throw error;
  }
  writable() {
    if (this.poisoned)
      throw new CampaignJournalError("journal_poisoned", this.poisoned.code);
    demand2(!this.closed, "writer_closed");
    demand2(!this.exported, "already_exported");
    try {
      const checkpointPath = join4(this.directory, "api-state.json");
      regularInStore(checkpointPath, this.directory);
      const checkpoint = readFileSync5(checkpointPath);
      if (checkpoint.length > MAX_LINE || !checkpoint.equals(Buffer.from(json(this.state()) + `
`)))
        this.poison("checkpoint_changed", "before_append");
    } catch {
      this.poison("checkpoint_changed", "before_append");
    }
    if (existsSync4(join4(this.directory, "journal-error.json")))
      this.poison("journal_changed", "unexpected_error_marker");
    try {
      regularInStore(join4(this.directory, "journal-config.json"), this.directory);
      if (fileHash(join4(this.directory, "journal-config.json")) !== this.configSha256)
        this.poison("journal_changed", "config_changed");
    } catch {
      this.poison("journal_changed", "config_changed");
    }
    try {
      const s = fstatSync(this.fd), disk = lstatSync2(this.journalPath);
      if (!disk.isFile() || disk.isSymbolicLink() || disk.ino !== s.ino || disk.dev !== s.dev || s.size !== this.prefix.bytes || s.mtimeMs !== this.journalMtime)
        this.poison("journal_changed", "before_append");
      if (this.lastLine) {
        const raw = Buffer.alloc(this.lastLine.bytes);
        const n = readSync2(this.fd, raw, 0, raw.length, this.lastLine.offset);
        if (n !== raw.length || hash(raw) !== this.lastLine.sha256)
          this.poison("journal_changed", "last_durable_line");
      }
    } catch (e) {
      if (this.poisoned)
        throw e;
      this.poison("journal_identity_io", "before_append");
    }
  }
  checkpoint(stage) {
    const target = join4(this.directory, "api-state.json"), temp = target + ".new-" + randomBytes(8).toString("hex");
    const raw = Buffer.from(json(this.state()) + `
`);
    demand2(raw.length <= MAX_LINE, "checkpoint_resource_limit");
    this.metrics.maxHotMetadataBytes = Math.max(this.metrics.maxHotMetadataBytes, raw.length);
    try {
      this.persistExclusive(temp, raw, "checkpoint:" + stage, "checkpointBytesWritten");
      const op = { kind: "rename", stage: "checkpoint:" + stage, path: target };
      this.hooks.before?.(op);
      renameSync(temp, target);
      this.hooks.after?.(op);
    } catch {
      this.poison("checkpoint_io", stage);
    }
  }
  append(kind, seq, receipt, apply) {
    const e = { protocol: this.config.protocol, eventSeq: this.prefix.eventCount, previousEventSha256: this.prefix.lastSha256, kind, requestSeq: seq, record: receipt };
    const raw = Buffer.from(json(e) + `
`);
    if (raw.length > MAX_LINE || this.prefix.bytes + raw.length > MAX_JOURNAL)
      this.poison("journal_resource_limit", `${kind}:${seq}`, receipt);
    this.metrics.maxHotMetadataBytes = Math.max(this.metrics.maxHotMetadataBytes, raw.length);
    const offset = this.prefix.bytes, fsyncBefore = this.metrics.fsyncCallsReturned;
    const commit = () => {
      this.prefix = { bytes: offset + raw.length, eventCount: this.prefix.eventCount + 1, lastSha256: hash(raw) };
      this.lastLine = { offset, bytes: raw.length, sha256: this.prefix.lastSha256 };
      apply();
    };
    try {
      this.write(this.fd, this.journalPath, raw, `journal:${kind}:${seq}`, "journalBytesWritten");
      this.sync(this.fd, this.journalPath, `journal:${kind}:${seq}`);
    } catch {
      if (this.metrics.fsyncCallsReturned > fsyncBefore)
        commit();
      this.poison("journal_io", `${kind}:${seq}`, receipt);
    }
    commit();
    try {
      this.journalMtime = fstatSync(this.fd).mtimeMs;
    } catch {
      this.poison("journal_identity_io", `${kind}:${seq}`, receipt);
    }
    this.checkpoint(`${kind}:${seq}`);
  }
  admit(input) {
    this.writable();
    if (this.stopReason)
      return { admitted: false, reason: this.stopReason };
    if (this.active.size >= this.config.pendingLimit)
      return { admitted: false, reason: "pending_limit" };
    demand2(typeof input.rawRequest === "string" && Buffer.byteLength(input.rawRequest) <= MAX_REQUEST, "request_resource_limit");
    demand2(typeof input.route === "string" && input.route.length > 0 && Buffer.byteLength(input.route) <= 1024 && !/[\r\n\0]/.test(input.route), "invalid_route");
    const raw = Buffer.from(input.rawRequest), data = JSON.parse(input.rawRequest), values = requestValues(raw, data, this.config);
    if (this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf(this.active) + values.reservationUsd > this.config.capUsd) {
      this.stopReason = "local_budget_exhausted";
      this.checkpoint("budget_stop");
      return { admitted: false, reason: this.stopReason };
    }
    const seq = this.accepted, requestFile = join4(this.directory, `provider-${seq}-request.json.gz`), zipped = gzipSync(raw);
    const c = { route: input.route, startedAt: input.startedAt ?? new Date().toISOString(), requestSha256: hash(raw), requestedModel: String(data.model), requestFile, providerAttempted: false, wireParameters: values.wireParameters, requestCompressedSha256: hash(zipped), requestBytes: raw.length, reservationUsd: values.reservationUsd };
    demand2(Number.isFinite(Date.parse(c.startedAt)), "invalid_start_time");
    this.active.set(seq, c);
    try {
      this.persistExclusive(requestFile, zipped, `raw_request:${seq}`, "rawGzipBytesWritten");
    } catch {
      this.poison("raw_capture_io", `start:${seq}`, c);
    }
    this.append("start", seq, c, () => {
      this.accepted++;
    });
    return { admitted: true, requestSeq: seq, reservationUsd: values.reservationUsd, requestFile, requestSha256: c.requestSha256 };
  }
  finish(input) {
    this.writable();
    try {
      return this.finishReceipt(input);
    } catch (e) {
      if (this.poisoned)
        throw e;
      this.poison(e instanceof CampaignJournalError ? e.code : "finish_input_error", "finish_input");
    }
  }
  finishReceipt(input) {
    const start = this.active.get(input.requestSeq);
    if (!start)
      this.poison(input.requestSeq < this.accepted ? "duplicate_finish" : "unknown_finish", "finish");
    const c = { ...start, providerAttempted: input.providerAttempted };
    demand2(typeof input.providerAttempted === "boolean", "invalid_provider_attempt");
    if (!input.providerAttempted) {
      demand2(input.confirmedNoForward === true && input.rawResponse === undefined, "unproven_zero_charge");
      c.confirmedNoForward = true;
    }
    if (input.httpStatus !== undefined) {
      demand2(Number.isInteger(input.httpStatus) && input.httpStatus >= 100 && input.httpStatus <= 599, "invalid_http_status");
      c.httpStatus = input.httpStatus;
    }
    let rejectedBeforeGeneration = false;
    if (input.rawResponse !== undefined) {
      demand2(input.providerAttempted && typeof input.rawResponse === "string" && Buffer.byteLength(input.rawResponse) <= MAX_RESPONSE, "response_resource_limit");
      const raw = Buffer.from(input.rawResponse), zipped = gzipSync(raw), responseFile = join4(this.directory, `provider-${input.requestSeq}-response.json.gz`);
      c.responseFile = responseFile;
      c.responseSha256 = hash(raw);
      c.responseCompressedSha256 = hash(zipped);
      try {
        this.persistExclusive(responseFile, zipped, `raw_response:${input.requestSeq}`, "rawGzipBytesWritten");
      } catch {
        this.poison("raw_capture_io", `finish:${input.requestSeq}`, c);
      }
      try {
        const data = JSON.parse(input.rawResponse);
        rejectedBeforeGeneration = routingRejection(this.config, data, input.httpStatus);
        if (rateRejection(this.config, data, input.httpStatus)) {
          c.nonGenerationRejection = "upstream_rate_limit";
          rejectedBeforeGeneration = true;
        }
        if (this.config.provider) {
          c.providerName = typeof data.provider === "string" ? data.provider : undefined;
          if (input.httpStatus === 200)
            c.fault = officialOpenRouterFault(data, this.config.providerName ?? "DeepSeek");
        }
        c.servedModel = typeof data.model === "string" ? data.model : undefined;
        c.requestId = typeof data.id === "string" ? data.id : undefined;
        if (data.usage && typeof data.usage === "object")
          c.usage = data.usage;
        if (input.httpStatus === 200) {
          c.completionFault = completionFault(data);
          c.completionValid = !c.completionFault;
        }
      } catch {
        c.fault = "InvalidProviderJSON";
      }
    }
    if (input.fault) {
      demand2(typeof input.fault === "string" && Buffer.byteLength(input.fault) <= 2048, "fault_resource_limit");
      c.fault = input.fault;
    }
    if (!c.responseFile && !c.fault)
      c.fault = input.providerAttempted ? "UncapturedProviderTransport" : "LocalBeforeForwardError";
    reconcileReceiptCost(c, start.reservationUsd, { provider: this.config.provider, knownUncharged: rejectedBeforeGeneration || !c.providerAttempted || !c.usage && [401, 402, 403].includes(c.httpStatus ?? 0) });
    c.finishedAt = input.finishedAt ?? new Date().toISOString();
    demand2(Number.isFinite(Date.parse(c.finishedAt)) && Date.parse(c.finishedAt) >= Date.parse(c.startedAt), "invalid_finish_time");
    if (c.requestId && this.providerIds.has(c.requestId))
      this.poison("duplicate_provider_id", "finish", c);
    this.append("finish", input.requestSeq, c, () => {
      this.spent += c.usdUpperBound;
      this.active.delete(input.requestSeq);
      this.finished++;
      if (c.requestId)
        this.providerIds.add(c.requestId);
      if (c.usdUpperBound > start.reservationUsd + EPS)
        this.stopReason ??= "usage_exceeded_reservation";
      if (this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf(this.active) > this.config.capUsd + EPS)
        this.stopReason ??= "actual_cost_exceeded_cap";
      if (!isNonGenerationRateRejection(c) && (c.fault || c.httpStatus !== 200 || c.completionValid !== true || !validTokenUsage(c.usage)))
        this.stopReason ??= "provider_fault";
    });
    return { requestSeq: input.requestSeq, receipt: { ...c }, accountingCommitted: true };
  }
  readReceipt(fd, offset) {
    const line = Buffer.alloc(offset.bytes);
    demand2(readSync2(fd, line, 0, line.length, offset.offset) === line.length && hash(line) === offset.sha256, "export_receipt_changed");
    return JSON.parse(line.toString("utf8")).record;
  }
  *closedCalls(route) {
    demand2(this.exported && this.closedProof, "not_exported");
    const proof = this.closedProof;
    demand2(statSync2(this.journalPath).size === proof.prefix.bytes, "exported_journal_changed");
    const fd = openSync4(this.journalPath, "r");
    const indices = route === undefined ? Array.from({ length: this.accepted }, (_, i) => i) : [...proof.routes.get(route) ?? []].sort((a, b) => a - b);
    try {
      for (const seq of indices) {
        const offset = proof.offsets.get(seq);
        demand2(offset, "missing_finish_offset");
        const c = this.readReceipt(fd, offset);
        const start = { ...c, providerAttempted: false };
        checkedStart(start, seq, this.directory, this.config);
        checkedFinish(c, start, seq, this.directory, this.config);
        yield c;
      }
    } finally {
      closeSync4(fd);
    }
  }
  exportLegacyLedger() {
    this.writable();
    demand2(this.active.size === 0 && this.accepted === this.finished, "journal_not_closed");
    const proof = inspectCampaignJournal(this.directory);
    if (!proof.valid || !proof.accountingClosed || !same(proof.prefix, this.prefix) || Math.abs(proof.snapshot.recordedUsageUpperBoundUsd - this.spent) > EPS)
      this.poison("export_integrity", "before_export");
    const target = join4(this.outputDirectory, "api-ledger.json"), temp = target + ".partial";
    demand2(!existsSync4(target) && !existsSync4(temp), "existing_export");
    const fd = openSync4(temp, "wx", 384), journalFd = openSync4(this.journalPath, "r");
    try {
      const header = { ...this.config.provider ? { protocol: this.config.protocol, currency: "USD", provider: this.config.provider, model: this.config.model } : {}, campaign: this.config.campaign, capUsd: this.config.capUsd, priorCampaignCostUpperBoundUsd: this.config.priorCampaignCostUpperBoundUsd, recordedUsageUpperBoundUsd: this.spent, reservedUpperBoundUsd: 0, ...this.stopReason ? { fatal: this.stopReason } : {}, pending: {}, captureErrors: [], calls: [] };
      const opening = JSON.stringify(header, null, 2).replace(/\[\]\n}$/, `[
`);
      this.write(fd, temp, Buffer.from(opening), "legacy_export", "exportBytesWritten");
      for (let seq = 0;seq < this.accepted; seq++) {
        const offset = proof.offsets.get(seq);
        demand2(offset, "missing_finish_offset");
        const text = JSON.stringify(this.readReceipt(journalFd, offset), null, 2).split(`
`).map((line) => "    " + line).join(`
`);
        this.write(fd, temp, Buffer.from(text + (seq + 1 < this.accepted ? `,
` : `
`)), "legacy_export", "exportBytesWritten");
      }
      this.write(fd, temp, Buffer.from(`  ]
}
`), "legacy_export", "exportBytesWritten");
      this.sync(fd, temp, "legacy_export");
    } catch {
      this.poison("export_io", "legacy_export");
    } finally {
      try {
        closeSync4(fd);
      } catch {}
      closeSync4(journalFd);
    }
    const ownPartial = this.outputDirectory === this.directory ? { path: temp, bytes: statSync2(temp).size, sha256: fileHash(temp) } : undefined;
    const after = inspect(this.directory, ownPartial);
    if (!after.valid || !after.accountingClosed || !same(after.prefix, proof.prefix))
      this.poison("export_integrity", "after_export");
    try {
      const op = { kind: "rename", stage: "legacy_export", path: target };
      this.hooks.before?.(op);
      renameSync(temp, target);
      this.hooks.after?.(op);
    } catch {
      this.poison("export_io", "legacy_rename");
    }
    this.exported = true;
    this.closedProof = after;
    return { path: target, bytes: statSync2(target).size, sha256: fileHash(target), accountingClosed: true, eligibleForScoreCertification: proof.eligibleForScoreCertification, durablePrefix: { ...this.prefix }, legacyCompletedNotSet: true };
  }
  close() {
    if (!this.closed) {
      try {
        closeSync4(this.fd);
      } catch {}
      this.closed = true;
    }
  }
}
var CAMPAIGN_JOURNAL_PROTOCOL = "campaign-api-journal-v1", OPENROUTER_JOURNAL_PROTOCOL = "campaign-api-journal-openrouter-v1", MAX_LINE, MAX_REQUEST, MAX_RESPONSE, MAX_JOURNAL, EPS = 0.000000001, WIRE, hash = (data) => createHash4("sha256").update(data).digest("hex"), json = (value) => JSON.stringify(value), same = (a, b) => json(a) === json(b), finite = (n) => typeof n === "number" && Number.isFinite(n) && n >= 0, CampaignJournalError;
var init_digitalocean_journal = __esm(() => {
  init_campaign_contract();
  init_digitalocean_provider();
  MAX_LINE = 64 * 1024;
  MAX_REQUEST = 4 * 1024 * 1024;
  MAX_RESPONSE = 64 * 1024 * 1024;
  MAX_JOURNAL = 2 * 1024 * 1024 * 1024;
  WIRE = ["model", "temperature", "seed", "reasoning_effort", "thinking", "reasoning", "provider", "max_tokens", "max_completion_tokens", "tool_choice", "response_format", "stream"];
  CampaignJournalError = class CampaignJournalError extends Error {
    code;
    stage;
    constructor(code, stage) {
      super(code + (stage ? ":" + stage : ""));
      this.name = "CampaignJournalError";
      this.code = code;
      this.stage = stage;
    }
  };
});

// scripts/repair-2026-10-08/benchmark-provider.ts
function officialOpenRouterFault2(data, expectedProvider = BENCHMARK_PROVIDER2.providerName) {
  if (data?.provider !== expectedProvider)
    return "UnexpectedOpenRouterProvider";
  if (![BENCHMARK_PROVIDER2.model, BENCHMARK_PROVIDER2.canonicalModel].includes(data?.model))
    return "UnexpectedOpenRouterModel";
  if (typeof data?.id !== "string" || !data.id)
    return "MissingOpenRouterGenerationId";
  const cost = data?.usage?.cost;
  if (typeof cost !== "number" || !Number.isFinite(cost) || cost < 0)
    return "MissingOrInvalidOpenRouterUsdCost";
}
function openRouterRateLimitRejection2(data, status, providerName) {
  return status === 429 && data?.error?.code === 429 && data.error.metadata?.limit_source === "upstream_provider_shared_pool" && data.error.metadata.provider_name === providerName && typeof data.error.metadata.raw === "string" && data.error.metadata.raw.includes("temporarily rate-limited upstream") && !data.id && !data.usage && !data.choices;
}
var BENCHMARK_PROVIDER2;
var init_benchmark_provider = __esm(() => {
  BENCHMARK_PROVIDER2 = Object.freeze({
    kind: "openrouter-deepseek",
    model: "deepseek/deepseek-v4.1-flash",
    canonicalModel: "deepseek/deepseek-v4.1-flash-20260910",
    baseURL: "https://openrouter.ai/api/v1",
    endpoint: "https://openrouter.ai/api/v1/chat/completions",
    keyEnv: "OPENROUTER_API_KEY",
    currency: "USD",
    providerName: "Relace",
    providerSlug: "relace",
    peakRates: Object.freeze({ input: 0.3, cachedInput: 0.006, output: 1.2 }),
    routing: Object.freeze({ only: ["relace"], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } }),
    forcedToolMode: "constrained-auto"
  });
});

// scripts/repair-2026-10-08/campaign-journal.ts
import { createHash as createHash5, randomBytes as randomBytes2 } from "crypto";
import { closeSync as closeSync5, existsSync as existsSync5, fstatSync as fstatSync2, fsyncSync as fsyncSync2, lstatSync as lstatSync3, mkdirSync as mkdirSync4, openSync as openSync5, readFileSync as readFileSync6, readSync as readSync3, readdirSync as readdirSync4, realpathSync as realpathSync3, renameSync as renameSync2, statSync as statSync3, writeSync as writeSync2 } from "fs";
import { isAbsolute as isAbsolute3, join as join5, relative as relative2, resolve as resolve7 } from "path";
import { gunzipSync as gunzipSync2, gzipSync as gzipSync2 } from "zlib";
function demand3(ok, code) {
  if (!ok)
    throw new CampaignJournalError2(code);
}
function ordinaryDirectory2(path) {
  demand3(isAbsolute3(path), "absolute_directory_required");
  mkdirSync4(path, { recursive: true });
  demand3(lstatSync3(path).isDirectory() && !lstatSync3(path).isSymbolicLink(), "ordinary_directory_required");
  return realpathSync3(path);
}
function regularInStore2(path, store) {
  const full = resolve7(path), rel = relative2(store, full);
  demand3(rel && !rel.startsWith("..") && !isAbsolute3(rel), "raw_outside_store");
  let current = store;
  for (const component of rel.split(/[\\/]/)) {
    current = join5(current, component);
    const s = lstatSync3(current);
    demand3(!s.isSymbolicLink(), "raw_reparse");
  }
  demand3(lstatSync3(full).isFile() && realpathSync3(full) === full, "raw_not_regular");
  return full;
}
function fileHash2(path) {
  const before = statSync3(path), fd = openSync5(path, "r"), digest = createHash5("sha256"), buffer = Buffer.alloc(64 * 1024);
  let at = 0;
  try {
    while (at < before.size) {
      const n = readSync3(fd, buffer, 0, Math.min(buffer.length, before.size - at), at);
      demand3(n > 0, "hash_short_read");
      digest.update(buffer.subarray(0, n));
      at += n;
    }
  } finally {
    closeSync5(fd);
  }
  const after = statSync3(path);
  demand3(before.size === after.size && before.mtimeMs === after.mtimeMs, "hash_file_changed");
  return digest.digest("hex");
}
function rawEvidence2(path, expected, compressedExpected, store, parse = true) {
  regularInStore2(path, store);
  const before = statSync3(path);
  const zipped = readFileSync6(path);
  demand3(zipped.length <= MAX_RESPONSE2 + 1024 * 1024, "raw_resource_limit");
  const raw = gunzipSync2(zipped, { maxOutputLength: MAX_RESPONSE2 });
  const after = statSync3(path);
  demand3(before.size === after.size && before.mtimeMs === after.mtimeMs && hash2(zipped) === compressedExpected && hash2(raw) === expected, "raw_digest_changed");
  const data = parse ? JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)) : undefined;
  return { raw, data };
}
function frozenRouting2(config) {
  const slug = config.providerSlug ?? "deepseek";
  demand3(config.zeroChargePolicy === undefined || config.zeroChargePolicy === "explicit-rate-rejection-v2", "journal_zero_charge_policy");
  demand3(["deepseek", "relace"].includes(slug) && (config.providerName === undefined || config.providerName === (slug === "relace" ? "Relace" : "DeepSeek")), "journal_provider_identity");
  const route = { only: [slug], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } };
  demand3(config.providerRouting === undefined || same2(config.providerRouting, route), "journal_provider_route");
  return route;
}
function requestValues2(raw, data, config) {
  demand3(data && typeof data === "object" && !Array.isArray(data) && data.model === (config?.model ?? "deepseek-flash") && data.stream !== true, "invalid_frozen_request");
  if (config?.provider)
    demand3(same2(data.provider, frozenRouting2(config)) && data.models === undefined && data.route === undefined && data.plugins === undefined, "pinned_provider_routing_required");
  const limit = checkedOutputTokens(data);
  demand3(Array.isArray(data.messages), "invalid_request_messages");
  const reservationUsd = ((raw.length + 2048 + data.messages.length * 256) * 0.3 + limit * 1.2) / 1e6;
  return { reservationUsd, wireParameters: Object.fromEntries(WIRE2.filter((k) => (k in data)).map((k) => [k, data[k]])) };
}
function checkedStart2(c, seq, store, config) {
  demand3(typeof c.route === "string" && c.route.length > 0 && Buffer.byteLength(c.route) <= 1024 && !/[\r\n\0]/.test(c.route), "invalid_route");
  demand3(Number.isFinite(Date.parse(c.startedAt)) && c.providerAttempted === false, "invalid_start_receipt");
  demand3(c.requestFile === join5(store, `provider-${seq}-request.json.gz`), "request_sequence_path");
  const { raw, data } = rawEvidence2(c.requestFile, c.requestSha256, c.requestCompressedSha256, store);
  const expected = requestValues2(raw, data, config);
  demand3(raw.length === c.requestBytes && c.requestedModel === data.model && same2(c.wireParameters, expected.wireParameters) && finite2(c.reservationUsd) && Math.abs(c.reservationUsd - expected.reservationUsd) <= EPS2, "request_receipt_mismatch");
}
function routingRejection2(config, data, status) {
  return !!config.provider && status === 404 && Array.isArray(data?.error?.metadata?.routing_funnel) && typeof data?.error?.metadata?.failed_routing_step === "string" && data.error.metadata.failed_routing_step.startsWith("Filter by ") && !data.usage;
}
function rateRejection2(config, data, status) {
  return !!config.provider && config.zeroChargePolicy === "explicit-rate-rejection-v2" && openRouterRateLimitRejection2(data, status, config.providerName ?? "DeepSeek");
}
function checkedFinish2(c, start, seq, store, config) {
  for (const key of ["route", "startedAt", "requestSha256", "requestedModel", "requestFile", "wireParameters", "requestCompressedSha256", "requestBytes"])
    demand3(same2(c[key], start[key]), "finish_start_mismatch");
  demand3(typeof c.providerAttempted === "boolean" && typeof c.finishedAt === "string" && Number.isFinite(Date.parse(c.finishedAt)) && Date.parse(c.finishedAt) >= Date.parse(c.startedAt), "invalid_finish_time");
  if (!c.providerAttempted)
    demand3(c.confirmedNoForward === true && !c.responseFile && !c.usage, "unproven_zero_charge");
  let rejectedBeforeGeneration = false, rateLimited = false;
  if (c.responseFile) {
    demand3(c.providerAttempted && c.responseFile === join5(store, `provider-${seq}-response.json.gz`) && c.responseSha256 && c.responseCompressedSha256, "response_sequence_path");
    const { raw } = rawEvidence2(c.responseFile, c.responseSha256, c.responseCompressedSha256, store, false);
    let data;
    try {
      data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
    } catch {}
    if (data && typeof data === "object") {
      rejectedBeforeGeneration = routingRejection2(config, data, c.httpStatus);
      rateLimited = rateRejection2(config, data, c.httpStatus);
      demand3(same2(data.usage, c.usage) && (typeof data.model === "string" ? data.model : undefined) === c.servedModel && (typeof data.id === "string" ? data.id : undefined) === c.requestId, "response_receipt_mismatch");
      if (config.provider) {
        demand3((typeof data.provider === "string" ? data.provider : undefined) === c.providerName, "provider_receipt_mismatch");
        const routeFault = c.httpStatus === 200 ? officialOpenRouterFault2(data, config.providerName ?? "DeepSeek") : undefined;
        if (routeFault)
          demand3(c.fault === routeFault, "official_provider_fault_missing");
      }
      if (c.httpStatus === 200)
        demand3(c.completionValid === !completionFault(data) && c.completionFault === completionFault(data), "completion_receipt_mismatch");
    } else
      demand3(c.fault && c.usage === undefined && c.servedModel === undefined && c.requestId === undefined && c.completionValid === undefined, "invalid_json_receipt_mismatch");
  } else
    demand3(c.fault && !c.usage && c.servedModel === undefined && c.requestId === undefined, "missing_response_evidence");
  demand3(c.nonGenerationRejection === (rateLimited ? "upstream_rate_limit" : undefined), "rate_rejection_raw_binding");
  const expected = { usage: c.usage };
  reconcileReceiptCost(expected, start.reservationUsd, { provider: config.provider, knownUncharged: rateLimited || rejectedBeforeGeneration || !c.providerAttempted || !c.usage && [401, 402, 403].includes(c.httpStatus ?? 0) });
  demand3(c.billedCostUsd === expected.billedCostUsd, "reported_usd_cost_mismatch");
  demand3(c.reservationUsd === start.reservationUsd && c.costBasis === expected.costBasis && finite2(c.usdUpperBound) && finite2(c.accountedUpperBoundUsd) && Math.abs(c.usdUpperBound - expected.usdUpperBound) <= EPS2 && c.usdUpperBound === c.accountedUpperBoundUsd, "cost_receipt_mismatch");
}
function pendingOf2(active) {
  const result = new Map;
  for (const c of active.values())
    result.set(c.route, (result.get(c.route) ?? 0) + 1);
  return Object.fromEntries(result);
}
function reserveOf2(active) {
  let n = 0;
  for (const c of active.values())
    n += c.reservationUsd;
  return n;
}
function financialState2(config, configSha256, active, accepted, finished, spent, prefix, stopReason) {
  return { protocol: config.protocol, ...config.provider ? { currency: "USD", provider: config.provider } : {}, campaign: config.campaign, configSha256, capUsd: config.capUsd, priorCampaignCostUpperBoundUsd: config.priorCampaignCostUpperBoundUsd, recordedUsageUpperBoundUsd: spent, reservedUpperBoundUsd: reserveOf2(active), pending: pendingOf2(active), active: [...active].map(([requestSeq, c]) => ({ requestSeq, route: c.route, requestSha256: c.requestSha256, reservationUsd: c.reservationUsd })), acceptedRequestCount: accepted, finishedRequestCount: finished, durablePrefix: { ...prefix }, ...stopReason ? { stopReason } : {} };
}
function* lines2(fd, length) {
  let offset = 0, at = 0, carry = Buffer.alloc(0);
  const buffer = Buffer.alloc(16 * 1024);
  while (at < length) {
    const n = readSync3(fd, buffer, 0, Math.min(buffer.length, length - at), at);
    demand3(n > 0, "journal_short_read");
    at += n;
    carry = Buffer.concat([carry, buffer.subarray(0, n)]);
    for (;; ) {
      const newline = carry.indexOf(10);
      if (newline < 0)
        break;
      const line = carry.subarray(0, newline + 1);
      demand3(line.length <= MAX_LINE2, "journal_line_limit");
      yield { offset, line };
      offset += line.length;
      carry = carry.subarray(newline + 1);
    }
    demand3(carry.length <= MAX_LINE2, "journal_line_limit");
  }
  demand3(carry.length === 0, "truncated_journal");
}
function inspectCampaignJournal2(directory) {
  return inspect2(directory);
}
function inspect2(directory, ownedExport) {
  const result = { valid: false, accountingClosed: false, eligibleForScoreCertification: false, errors: [], offsets: new Map, routes: new Map, journalPath: join5(resolve7(directory), "api-events.jsonl"), directory: resolve7(directory) };
  let fd;
  try {
    const store = realpathSync3(directory);
    demand3(store === resolve7(directory), "journal_directory_identity");
    const configBytes = readFileSync6(join5(store, "journal-config.json")), config = JSON.parse(configBytes.toString("utf8"));
    const providerValid = config.provider === "openrouter-deepseek" ? config.protocol === OPENROUTER_JOURNAL_PROTOCOL2 && config.model === BENCHMARK_PROVIDER2.model && config.currency === "USD" : config.provider === undefined && config.protocol === CAMPAIGN_JOURNAL_PROTOCOL2 && config.model === "deepseek-flash";
    if (config.provider)
      frozenRouting2(config);
    demand3(providerValid && config.pendingLimit === 4 && config.maxLineBytes === MAX_LINE2 && config.maxJournalBytes === MAX_JOURNAL2 && finite2(config.capUsd) && config.capUsd > 0 && finite2(config.priorCampaignCostUpperBoundUsd), "journal_config_invalid");
    const configSha = hash2(configBytes), before = statSync3(result.journalPath);
    demand3(before.size <= MAX_JOURNAL2 && lstatSync3(result.journalPath).isFile() && !lstatSync3(result.journalPath).isSymbolicLink(), "journal_resource_or_identity");
    fd = openSync5(result.journalPath, "r");
    const active = new Map, ids = new Set;
    let accepted = 0, finished = 0, spent = 0, allProviderValid = true;
    let prefix = { bytes: 0, eventCount: 0, lastSha256: configSha };
    for (const { offset, line } of lines2(fd, before.size)) {
      const e = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line.subarray(0, -1)));
      demand3(same2(Object.keys(e), ["protocol", "eventSeq", "previousEventSha256", "kind", "requestSeq", "record"]) && Buffer.from(json2(e) + `
`).equals(line), "unknown_or_noncanonical_event");
      demand3(e.protocol === config.protocol && e.eventSeq === prefix.eventCount && e.previousEventSha256 === prefix.lastSha256 && Number.isSafeInteger(e.requestSeq) && e.requestSeq >= 0, "journal_chain_or_sequence");
      if (e.kind === "start") {
        demand3(e.requestSeq === accepted && active.size < 4 && !active.has(e.requestSeq), "duplicate_or_unbounded_start");
        checkedStart2(e.record, e.requestSeq, store, config);
        demand3(config.priorCampaignCostUpperBoundUsd + spent + reserveOf2(active) + e.record.reservationUsd <= config.capUsd + EPS2, "admission_exceeded_cap");
        active.set(e.requestSeq, e.record);
        accepted++;
      } else if (e.kind === "finish") {
        const start = active.get(e.requestSeq);
        demand3(start && !result.offsets.has(e.requestSeq), "duplicate_or_unknown_finish");
        checkedFinish2(e.record, start, e.requestSeq, store, config);
        if (e.record.requestId) {
          demand3(!ids.has(e.record.requestId), "duplicate_provider_id");
          ids.add(e.record.requestId);
        }
        spent += e.record.usdUpperBound;
        active.delete(e.requestSeq);
        finished++;
        allProviderValid &&= isNonGenerationRateRejection(e.record) || e.record.providerAttempted && e.record.httpStatus === 200 && e.record.completionValid === true && validTokenUsage(e.record.usage) && !e.record.fault;
        result.offsets.set(e.requestSeq, { offset, bytes: line.length, sha256: hash2(line) });
        const route = result.routes.get(e.record.route) ?? [];
        route.push(e.requestSeq);
        result.routes.set(e.record.route, route);
      } else
        throw new CampaignJournalError2("unknown_event");
      prefix = { bytes: offset + line.length, eventCount: prefix.eventCount + 1, lastSha256: hash2(line) };
      result.snapshot = financialState2(config, configSha, active, accepted, finished, spent, prefix);
    }
    result.snapshot ??= financialState2(config, configSha, active, accepted, finished, spent, prefix);
    result.prefix = prefix;
    result.config = config;
    const checkpoint = JSON.parse(readFileSync6(join5(store, "api-state.json"), "utf8"));
    const expected = { ...result.snapshot, ...checkpoint.stopReason ? { stopReason: checkpoint.stopReason } : {} };
    demand3(same2(checkpoint, expected), "checkpoint_prefix_or_accounting");
    const requests = readdirSync4(store).filter((n) => /^provider-\d+-request\.json\.gz$/.test(n));
    const responses = readdirSync4(store).filter((n) => /^provider-\d+-response\.json\.gz$/.test(n));
    demand3(requests.length === accepted && requests.every((n) => Number(n.match(/\d+/)[0]) < accepted), "unindexed_raw_request");
    demand3(responses.every((n) => result.offsets.has(Number(n.match(/\d+/)[0]))), "unindexed_raw_response");
    if (ownedExport)
      demand3(ownedExport.path === join5(store, "api-ledger.json.partial") && statSync3(ownedExport.path).size === ownedExport.bytes && fileHash2(ownedExport.path) === ownedExport.sha256, "owned_export_partial_changed");
    demand3(!existsSync5(join5(store, "journal-error.json")) && !readdirSync4(store).some((n) => n.includes(".partial") && join5(store, n) !== ownedExport?.path || n.startsWith("api-state.json.new-")), "unclosed_error_or_partial");
    const after = statSync3(result.journalPath);
    demand3(before.size === after.size && before.mtimeMs === after.mtimeMs && hash2(readFileSync6(join5(store, "journal-config.json"))) === configSha, "journal_changed_during_inspection");
    result.valid = true;
    result.accountingClosed = active.size === 0 && accepted === finished;
    result.eligibleForScoreCertification = result.accountingClosed && allProviderValid && !checkpoint.stopReason && config.priorCampaignCostUpperBoundUsd + spent <= config.capUsd + EPS2;
  } catch (e) {
    result.errors.push(e instanceof CampaignJournalError2 ? e.code : e.code ?? e.name);
  } finally {
    if (fd !== undefined)
      closeSync5(fd);
  }
  return result;
}

class CampaignJournal2 {
  hooks;
  directory;
  outputDirectory;
  config;
  configSha256;
  journalPath;
  fd = -1;
  prefix;
  journalMtime = 0;
  lastLine;
  active = new Map;
  accepted = 0;
  finished = 0;
  spent = 0;
  stopReason;
  poisoned;
  exported = false;
  closedProof;
  closed = false;
  providerIds = new Set;
  metrics = { journalBytesWritten: 0, checkpointBytesWritten: 0, rawGzipBytesWritten: 0, exportBytesWritten: 0, fsyncCallsReturned: 0, maxHotMetadataBytes: 0 };
  constructor(options, hooks) {
    this.hooks = hooks;
    demand3(finite2(options.capUsd) && options.capUsd > 0 && finite2(options.priorCampaignCostUpperBoundUsd) && /^repair-[0-9TZ-]+$/.test(options.campaign), "invalid_journal_options");
    this.directory = ordinaryDirectory2(resolve7(options.directory));
    this.outputDirectory = ordinaryDirectory2(resolve7(options.outputDirectory ?? options.directory));
    demand3(!readdirSync4(this.directory).some((n) => ["api-events.jsonl", "journal-config.json", "api-state.json", "journal-error.json"].includes(n) || /^provider-\d+-/.test(n)), "existing_journal");
    if (options.provider)
      demand3(options.provider.kind === BENCHMARK_PROVIDER2.kind && options.provider.model === BENCHMARK_PROVIDER2.model, "unsupported_journal_provider");
    this.config = { protocol: options.provider ? OPENROUTER_JOURNAL_PROTOCOL2 : CAMPAIGN_JOURNAL_PROTOCOL2, campaign: options.campaign, capUsd: options.capUsd, priorCampaignCostUpperBoundUsd: options.priorCampaignCostUpperBoundUsd, pendingLimit: 4, model: options.provider?.model ?? "deepseek-flash", ...options.provider ? {
      provider: options.provider.kind,
      currency: "USD",
      providerName: options.provider.providerName,
      providerSlug: options.provider.providerSlug,
      providerRouting: options.provider.routing,
      zeroChargePolicy: "explicit-rate-rejection-v2"
    } : {}, maxLineBytes: MAX_LINE2, maxJournalBytes: MAX_JOURNAL2, createdAt: new Date().toISOString() };
    const configRaw = Buffer.from(JSON.stringify(this.config, null, 2) + `
`);
    this.configSha256 = hash2(configRaw);
    this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configSha256 };
    this.journalPath = join5(this.directory, "api-events.jsonl");
    try {
      this.persistExclusive(join5(this.directory, "journal-config.json"), configRaw, "config", "checkpointBytesWritten");
      this.fd = openSync5(this.journalPath, "wx+");
      this.sync(this.fd, this.journalPath, "journal:create");
      this.journalMtime = fstatSync2(this.fd).mtimeMs;
      this.checkpoint("create");
    } catch (e) {
      this.close();
      if (e instanceof CampaignJournalError2)
        throw e;
      throw new CampaignJournalError2("journal_create_io", e.code);
    }
  }
  write(fd, path, raw, stage, metric) {
    let at = 0;
    while (at < raw.length) {
      const op = { kind: "write", stage, path, fd, bytes: raw.length - at };
      this.hooks.before?.(op);
      const n = writeSync2(fd, raw, at, raw.length - at);
      demand3(n > 0, "short_write");
      this.metrics[metric] += n;
      at += n;
      this.hooks.after?.({ ...op, bytes: n });
    }
  }
  sync(fd, path, stage) {
    const op = { kind: "fsync", stage, path, fd };
    this.hooks.before?.(op);
    fsyncSync2(fd);
    this.metrics.fsyncCallsReturned++;
    this.hooks.after?.(op);
  }
  persistExclusive(path, raw, stage, metric) {
    const fd = openSync5(path, "wx", 384);
    try {
      this.write(fd, path, raw, stage, metric);
      this.sync(fd, path, stage);
    } finally {
      try {
        closeSync5(fd);
      } catch {}
    }
  }
  state() {
    return financialState2(this.config, this.configSha256, this.active, this.accepted, this.finished, this.spent, this.prefix, this.stopReason);
  }
  snapshot() {
    return { ...this.state(), ...this.poisoned ? { error: this.poisoned.code } : {}, metrics: { ...this.metrics } };
  }
  poison(code, stage, uncommittedReceipt) {
    const error = this.poisoned ?? new CampaignJournalError2(code, stage);
    this.poisoned = error;
    try {
      this.persistExclusive(join5(this.directory, "journal-error.json"), Buffer.from(json2({ protocol: CAMPAIGN_JOURNAL_PROTOCOL2, error: error.code, stage, state: this.state(), ...uncommittedReceipt ? { uncommittedReceipt } : {} }) + `
`), "error_diagnostic", "checkpointBytesWritten");
    } catch {}
    throw error;
  }
  writable() {
    if (this.poisoned)
      throw new CampaignJournalError2("journal_poisoned", this.poisoned.code);
    demand3(!this.closed, "writer_closed");
    demand3(!this.exported, "already_exported");
    try {
      const checkpointPath = join5(this.directory, "api-state.json");
      regularInStore2(checkpointPath, this.directory);
      const checkpoint = readFileSync6(checkpointPath);
      if (checkpoint.length > MAX_LINE2 || !checkpoint.equals(Buffer.from(json2(this.state()) + `
`)))
        this.poison("checkpoint_changed", "before_append");
    } catch {
      this.poison("checkpoint_changed", "before_append");
    }
    if (existsSync5(join5(this.directory, "journal-error.json")))
      this.poison("journal_changed", "unexpected_error_marker");
    try {
      regularInStore2(join5(this.directory, "journal-config.json"), this.directory);
      if (fileHash2(join5(this.directory, "journal-config.json")) !== this.configSha256)
        this.poison("journal_changed", "config_changed");
    } catch {
      this.poison("journal_changed", "config_changed");
    }
    try {
      const s = fstatSync2(this.fd), disk = lstatSync3(this.journalPath);
      if (!disk.isFile() || disk.isSymbolicLink() || disk.ino !== s.ino || disk.dev !== s.dev || s.size !== this.prefix.bytes || s.mtimeMs !== this.journalMtime)
        this.poison("journal_changed", "before_append");
      if (this.lastLine) {
        const raw = Buffer.alloc(this.lastLine.bytes);
        const n = readSync3(this.fd, raw, 0, raw.length, this.lastLine.offset);
        if (n !== raw.length || hash2(raw) !== this.lastLine.sha256)
          this.poison("journal_changed", "last_durable_line");
      }
    } catch (e) {
      if (this.poisoned)
        throw e;
      this.poison("journal_identity_io", "before_append");
    }
  }
  checkpoint(stage) {
    const target = join5(this.directory, "api-state.json"), temp = target + ".new-" + randomBytes2(8).toString("hex");
    const raw = Buffer.from(json2(this.state()) + `
`);
    demand3(raw.length <= MAX_LINE2, "checkpoint_resource_limit");
    this.metrics.maxHotMetadataBytes = Math.max(this.metrics.maxHotMetadataBytes, raw.length);
    try {
      this.persistExclusive(temp, raw, "checkpoint:" + stage, "checkpointBytesWritten");
      const op = { kind: "rename", stage: "checkpoint:" + stage, path: target };
      this.hooks.before?.(op);
      renameSync2(temp, target);
      this.hooks.after?.(op);
    } catch {
      this.poison("checkpoint_io", stage);
    }
  }
  append(kind, seq, receipt, apply) {
    const e = { protocol: this.config.protocol, eventSeq: this.prefix.eventCount, previousEventSha256: this.prefix.lastSha256, kind, requestSeq: seq, record: receipt };
    const raw = Buffer.from(json2(e) + `
`);
    if (raw.length > MAX_LINE2 || this.prefix.bytes + raw.length > MAX_JOURNAL2)
      this.poison("journal_resource_limit", `${kind}:${seq}`, receipt);
    this.metrics.maxHotMetadataBytes = Math.max(this.metrics.maxHotMetadataBytes, raw.length);
    const offset = this.prefix.bytes, fsyncBefore = this.metrics.fsyncCallsReturned;
    const commit = () => {
      this.prefix = { bytes: offset + raw.length, eventCount: this.prefix.eventCount + 1, lastSha256: hash2(raw) };
      this.lastLine = { offset, bytes: raw.length, sha256: this.prefix.lastSha256 };
      apply();
    };
    try {
      this.write(this.fd, this.journalPath, raw, `journal:${kind}:${seq}`, "journalBytesWritten");
      this.sync(this.fd, this.journalPath, `journal:${kind}:${seq}`);
    } catch {
      if (this.metrics.fsyncCallsReturned > fsyncBefore)
        commit();
      this.poison("journal_io", `${kind}:${seq}`, receipt);
    }
    commit();
    try {
      this.journalMtime = fstatSync2(this.fd).mtimeMs;
    } catch {
      this.poison("journal_identity_io", `${kind}:${seq}`, receipt);
    }
    this.checkpoint(`${kind}:${seq}`);
  }
  admit(input) {
    this.writable();
    if (this.stopReason)
      return { admitted: false, reason: this.stopReason };
    if (this.active.size >= 4)
      return { admitted: false, reason: "pending_limit" };
    demand3(typeof input.rawRequest === "string" && Buffer.byteLength(input.rawRequest) <= MAX_REQUEST2, "request_resource_limit");
    demand3(typeof input.route === "string" && input.route.length > 0 && Buffer.byteLength(input.route) <= 1024 && !/[\r\n\0]/.test(input.route), "invalid_route");
    const raw = Buffer.from(input.rawRequest), data = JSON.parse(input.rawRequest), values = requestValues2(raw, data, this.config);
    if (this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf2(this.active) + values.reservationUsd > this.config.capUsd) {
      this.stopReason = "local_budget_exhausted";
      this.checkpoint("budget_stop");
      return { admitted: false, reason: this.stopReason };
    }
    const seq = this.accepted, requestFile = join5(this.directory, `provider-${seq}-request.json.gz`), zipped = gzipSync2(raw);
    const c = { route: input.route, startedAt: input.startedAt ?? new Date().toISOString(), requestSha256: hash2(raw), requestedModel: String(data.model), requestFile, providerAttempted: false, wireParameters: values.wireParameters, requestCompressedSha256: hash2(zipped), requestBytes: raw.length, reservationUsd: values.reservationUsd };
    demand3(Number.isFinite(Date.parse(c.startedAt)), "invalid_start_time");
    this.active.set(seq, c);
    try {
      this.persistExclusive(requestFile, zipped, `raw_request:${seq}`, "rawGzipBytesWritten");
    } catch {
      this.poison("raw_capture_io", `start:${seq}`, c);
    }
    this.append("start", seq, c, () => {
      this.accepted++;
    });
    return { admitted: true, requestSeq: seq, reservationUsd: values.reservationUsd, requestFile, requestSha256: c.requestSha256 };
  }
  finish(input) {
    this.writable();
    try {
      return this.finishReceipt(input);
    } catch (e) {
      if (this.poisoned)
        throw e;
      this.poison(e instanceof CampaignJournalError2 ? e.code : "finish_input_error", "finish_input");
    }
  }
  finishReceipt(input) {
    const start = this.active.get(input.requestSeq);
    if (!start)
      this.poison(input.requestSeq < this.accepted ? "duplicate_finish" : "unknown_finish", "finish");
    const c = { ...start, providerAttempted: input.providerAttempted };
    demand3(typeof input.providerAttempted === "boolean", "invalid_provider_attempt");
    if (!input.providerAttempted) {
      demand3(input.confirmedNoForward === true && input.rawResponse === undefined, "unproven_zero_charge");
      c.confirmedNoForward = true;
    }
    if (input.httpStatus !== undefined) {
      demand3(Number.isInteger(input.httpStatus) && input.httpStatus >= 100 && input.httpStatus <= 599, "invalid_http_status");
      c.httpStatus = input.httpStatus;
    }
    let rejectedBeforeGeneration = false;
    if (input.rawResponse !== undefined) {
      demand3(input.providerAttempted && typeof input.rawResponse === "string" && Buffer.byteLength(input.rawResponse) <= MAX_RESPONSE2, "response_resource_limit");
      const raw = Buffer.from(input.rawResponse), zipped = gzipSync2(raw), responseFile = join5(this.directory, `provider-${input.requestSeq}-response.json.gz`);
      c.responseFile = responseFile;
      c.responseSha256 = hash2(raw);
      c.responseCompressedSha256 = hash2(zipped);
      try {
        this.persistExclusive(responseFile, zipped, `raw_response:${input.requestSeq}`, "rawGzipBytesWritten");
      } catch {
        this.poison("raw_capture_io", `finish:${input.requestSeq}`, c);
      }
      try {
        const data = JSON.parse(input.rawResponse);
        rejectedBeforeGeneration = routingRejection2(this.config, data, input.httpStatus);
        if (rateRejection2(this.config, data, input.httpStatus)) {
          c.nonGenerationRejection = "upstream_rate_limit";
          rejectedBeforeGeneration = true;
        }
        if (this.config.provider) {
          c.providerName = typeof data.provider === "string" ? data.provider : undefined;
          if (input.httpStatus === 200)
            c.fault = officialOpenRouterFault2(data, this.config.providerName ?? "DeepSeek");
        }
        c.servedModel = typeof data.model === "string" ? data.model : undefined;
        c.requestId = typeof data.id === "string" ? data.id : undefined;
        if (data.usage && typeof data.usage === "object")
          c.usage = data.usage;
        if (input.httpStatus === 200) {
          c.completionFault = completionFault(data);
          c.completionValid = !c.completionFault;
        }
      } catch {
        c.fault = "InvalidProviderJSON";
      }
    }
    if (input.fault) {
      demand3(typeof input.fault === "string" && Buffer.byteLength(input.fault) <= 2048, "fault_resource_limit");
      c.fault = input.fault;
    }
    if (!c.responseFile && !c.fault)
      c.fault = input.providerAttempted ? "UncapturedProviderTransport" : "LocalBeforeForwardError";
    reconcileReceiptCost(c, start.reservationUsd, { provider: this.config.provider, knownUncharged: rejectedBeforeGeneration || !c.providerAttempted || !c.usage && [401, 402, 403].includes(c.httpStatus ?? 0) });
    c.finishedAt = input.finishedAt ?? new Date().toISOString();
    demand3(Number.isFinite(Date.parse(c.finishedAt)) && Date.parse(c.finishedAt) >= Date.parse(c.startedAt), "invalid_finish_time");
    if (c.requestId && this.providerIds.has(c.requestId))
      this.poison("duplicate_provider_id", "finish", c);
    this.append("finish", input.requestSeq, c, () => {
      this.spent += c.usdUpperBound;
      this.active.delete(input.requestSeq);
      this.finished++;
      if (c.requestId)
        this.providerIds.add(c.requestId);
      if (c.usdUpperBound > start.reservationUsd + EPS2)
        this.stopReason ??= "usage_exceeded_reservation";
      if (this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf2(this.active) > this.config.capUsd + EPS2)
        this.stopReason ??= "actual_cost_exceeded_cap";
      if (!isNonGenerationRateRejection(c) && (c.fault || c.httpStatus !== 200 || c.completionValid !== true || !validTokenUsage(c.usage)))
        this.stopReason ??= "provider_fault";
    });
    return { requestSeq: input.requestSeq, receipt: { ...c }, accountingCommitted: true };
  }
  readReceipt(fd, offset) {
    const line = Buffer.alloc(offset.bytes);
    demand3(readSync3(fd, line, 0, line.length, offset.offset) === line.length && hash2(line) === offset.sha256, "export_receipt_changed");
    return JSON.parse(line.toString("utf8")).record;
  }
  *closedCalls(route) {
    demand3(this.exported && this.closedProof, "not_exported");
    const proof = this.closedProof;
    demand3(statSync3(this.journalPath).size === proof.prefix.bytes, "exported_journal_changed");
    const fd = openSync5(this.journalPath, "r");
    const indices = route === undefined ? Array.from({ length: this.accepted }, (_, i) => i) : [...proof.routes.get(route) ?? []].sort((a, b) => a - b);
    try {
      for (const seq of indices) {
        const offset = proof.offsets.get(seq);
        demand3(offset, "missing_finish_offset");
        const c = this.readReceipt(fd, offset);
        const start = { ...c, providerAttempted: false };
        checkedStart2(start, seq, this.directory, this.config);
        checkedFinish2(c, start, seq, this.directory, this.config);
        yield c;
      }
    } finally {
      closeSync5(fd);
    }
  }
  exportLegacyLedger() {
    this.writable();
    demand3(this.active.size === 0 && this.accepted === this.finished, "journal_not_closed");
    const proof = inspectCampaignJournal2(this.directory);
    if (!proof.valid || !proof.accountingClosed || !same2(proof.prefix, this.prefix) || Math.abs(proof.snapshot.recordedUsageUpperBoundUsd - this.spent) > EPS2)
      this.poison("export_integrity", "before_export");
    const target = join5(this.outputDirectory, "api-ledger.json"), temp = target + ".partial";
    demand3(!existsSync5(target) && !existsSync5(temp), "existing_export");
    const fd = openSync5(temp, "wx", 384), journalFd = openSync5(this.journalPath, "r");
    try {
      const header = { ...this.config.provider ? { protocol: this.config.protocol, currency: "USD", provider: this.config.provider, model: this.config.model } : {}, campaign: this.config.campaign, capUsd: this.config.capUsd, priorCampaignCostUpperBoundUsd: this.config.priorCampaignCostUpperBoundUsd, recordedUsageUpperBoundUsd: this.spent, reservedUpperBoundUsd: 0, ...this.stopReason ? { fatal: this.stopReason } : {}, pending: {}, captureErrors: [], calls: [] };
      const opening = JSON.stringify(header, null, 2).replace(/\[\]\n}$/, `[
`);
      this.write(fd, temp, Buffer.from(opening), "legacy_export", "exportBytesWritten");
      for (let seq = 0;seq < this.accepted; seq++) {
        const offset = proof.offsets.get(seq);
        demand3(offset, "missing_finish_offset");
        const text = JSON.stringify(this.readReceipt(journalFd, offset), null, 2).split(`
`).map((line) => "    " + line).join(`
`);
        this.write(fd, temp, Buffer.from(text + (seq + 1 < this.accepted ? `,
` : `
`)), "legacy_export", "exportBytesWritten");
      }
      this.write(fd, temp, Buffer.from(`  ]
}
`), "legacy_export", "exportBytesWritten");
      this.sync(fd, temp, "legacy_export");
    } catch {
      this.poison("export_io", "legacy_export");
    } finally {
      try {
        closeSync5(fd);
      } catch {}
      closeSync5(journalFd);
    }
    const ownPartial = this.outputDirectory === this.directory ? { path: temp, bytes: statSync3(temp).size, sha256: fileHash2(temp) } : undefined;
    const after = inspect2(this.directory, ownPartial);
    if (!after.valid || !after.accountingClosed || !same2(after.prefix, proof.prefix))
      this.poison("export_integrity", "after_export");
    try {
      const op = { kind: "rename", stage: "legacy_export", path: target };
      this.hooks.before?.(op);
      renameSync2(temp, target);
      this.hooks.after?.(op);
    } catch {
      this.poison("export_io", "legacy_rename");
    }
    this.exported = true;
    this.closedProof = after;
    return { path: target, bytes: statSync3(target).size, sha256: fileHash2(target), accountingClosed: true, eligibleForScoreCertification: proof.eligibleForScoreCertification, durablePrefix: { ...this.prefix }, legacyCompletedNotSet: true };
  }
  close() {
    if (!this.closed) {
      try {
        closeSync5(this.fd);
      } catch {}
      this.closed = true;
    }
  }
}
var CAMPAIGN_JOURNAL_PROTOCOL2 = "campaign-api-journal-v1", OPENROUTER_JOURNAL_PROTOCOL2 = "campaign-api-journal-openrouter-v1", MAX_LINE2, MAX_REQUEST2, MAX_RESPONSE2, MAX_JOURNAL2, EPS2 = 0.000000001, WIRE2, hash2 = (data) => createHash5("sha256").update(data).digest("hex"), json2 = (value) => JSON.stringify(value), same2 = (a, b) => json2(a) === json2(b), finite2 = (n) => typeof n === "number" && Number.isFinite(n) && n >= 0, CampaignJournalError2;
var init_campaign_journal = __esm(() => {
  init_campaign_contract();
  init_benchmark_provider();
  MAX_LINE2 = 64 * 1024;
  MAX_REQUEST2 = 4 * 1024 * 1024;
  MAX_RESPONSE2 = 64 * 1024 * 1024;
  MAX_JOURNAL2 = 2 * 1024 * 1024 * 1024;
  WIRE2 = ["model", "temperature", "seed", "reasoning_effort", "thinking", "reasoning", "provider", "max_tokens", "max_completion_tokens", "tool_choice", "response_format", "stream"];
  CampaignJournalError2 = class CampaignJournalError2 extends Error {
    code;
    stage;
    constructor(code, stage) {
      super(code + (stage ? ":" + stage : ""));
      this.name = "CampaignJournalError";
      this.code = code;
      this.stage = stage;
    }
  };
});

// scripts/repair-2026-10-08/paid-resource-proof-v2.ts
import { createHash as createHash6 } from "crypto";
import { closeSync as closeSync6, existsSync as existsSync6, lstatSync as lstatSync4, mkdirSync as mkdirSync5, openSync as openSync6, readFileSync as readFileSync7, readSync as readSync4, realpathSync as realpathSync4, statSync as statSync4 } from "fs";
import { isAbsolute as isAbsolute4, join as join6, relative as relative3, resolve as resolve8 } from "path";
import { gunzipSync as gunzipSync3 } from "zlib";
function demand4(value, code) {
  if (!value)
    throw new ResourceAdmissionError(code);
}
function ordinaryDirectory3(path) {
  const p = resolve8(path);
  mkdirSync5(p, { recursive: true });
  demand4(lstatSync4(p).isDirectory() && !lstatSync4(p).isSymbolicLink() && realpathSync4(p) === p, "ordinary_directory_required");
  return p;
}
function fileHash3(path) {
  const before = statSync4(path), fd = openSync6(path, "r"), digest = createHash6("sha256"), buffer = Buffer.alloc(65536);
  let at = 0;
  try {
    while (at < before.size) {
      const n = readSync4(fd, buffer, 0, Math.min(buffer.length, before.size - at), at);
      demand4(n > 0, "hash_short_read");
      digest.update(buffer.subarray(0, n));
      at += n;
    }
  } finally {
    closeSync6(fd);
  }
  const after = statSync4(path);
  demand4(before.size === after.size && before.mtimeMs === after.mtimeMs, "file_changed_during_hash");
  return digest.digest("hex");
}
function verifyPin2(pin2, base, maxBytes = 128 * 1024 ** 2) {
  demand4(pin2 && typeof pin2.path === "string" && /^[a-f0-9]{64}$/.test(pin2.sha256), "invalid_pin");
  const path = isAbsolute4(pin2.path) ? resolve8(pin2.path) : resolve8(base ?? ".", pin2.path);
  demand4(lstatSync4(path).isFile() && !lstatSync4(path).isSymbolicLink(), "pin_not_regular");
  const size = statSync4(path).size;
  demand4(size <= maxBytes && (pin2.bytes === undefined || pin2.bytes === size) && fileHash3(path) === pin2.sha256, "pin_changed");
  return path;
}
function actualPin(path) {
  return { path: resolve8(path), bytes: statSync4(path).size, sha256: fileHash3(path) };
}
function jsonPin(pin2, base) {
  return JSON.parse(readFileSync7(verifyPin2(pin2, base), "utf8"));
}
function integer(n) {
  return typeof n === "number" && Number.isSafeInteger(n) && n >= 0;
}
function requestValues3(raw) {
  demand4(raw.byteLength > 0 && raw.byteLength <= 4 * 1024 ** 2, "request_size");
  const data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
  demand4(data.model === "deepseek-flash" && data.stream !== true && Array.isArray(data.messages), "request_profile");
  const { max_tokens: a, max_completion_tokens: b } = data;
  demand4((a === undefined || integer(a)) && (b === undefined || integer(b)) && (a === undefined || b === undefined || a === b), "output_limit");
  const output = a ?? b;
  demand4(integer(output) && output > 0 && output <= 16384, "output_limit");
  const upper = raw.byteLength + 2048 + data.messages.length * 256;
  demand4(integer(upper), "input_bound");
  return { data, inputUpper: upper, output, peakNano: BigInt(upper) * 2000n + BigInt(output) * 8000n };
}
function gzipProof(pin2, rawSha, base, maxRaw = 64 * 1024 ** 2) {
  const path = verifyPin2(pin2, base, 65 * 1024 ** 2), before = statSync4(path), raw = gunzipSync3(readFileSync7(path), { maxOutputLength: maxRaw });
  demand4(hash3(raw) === rawSha && statSync4(path).mtimeMs === before.mtimeMs && statSync4(path).size === before.size, "raw_digest_changed");
  return raw;
}
function validatePrices(pin2, base) {
  const p = jsonPin(pin2, base);
  demand4(p.protocol === "deepseek-cny-pricing-source-snapshot-v1" && p.currency === "CNY" && p.model === "deepseek-flash" && p.modelCalls === 0, "price_profile");
  demand4(p.officialSource === "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/" && same3(p.peak, { uncachedInput: 2, cachedInput: 0.04, output: 8 }) && same3(p.offPeak, { uncachedInput: 1, cachedInput: 0.02, output: 4 }), "price_rates");
  return p;
}
function peakWindow(start, end) {
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start)
    return { peak: true, clockFault: true };
  if (end - start > 32 * 86400000)
    return { peak: true, clockFault: false };
  const shifted = start + 8 * 3600000, last = end + 8 * 3600000;
  let day = Math.floor(shifted / 86400000) * 86400000;
  for (;day <= last; day += 86400000) {
    const weekday = new Date(day).getUTCDay();
    if (weekday === 0 || weekday === 6)
      continue;
    for (const [s, e] of [[9, 12], [14, 18]])
      if (last >= day + s * 3600000 && shifted <= day + e * 3600000)
        return { peak: true, clockFault: false };
  }
  return { peak: false, clockFault: false };
}
function pricedUsage(usage, peak) {
  demand4(usage && integer(usage.prompt_tokens) && integer(usage.completion_tokens), "usage_missing_or_invalid");
  const hit = usage.prompt_cache_hit_tokens ?? 0;
  demand4(integer(hit) && hit <= usage.prompt_tokens, "cache_usage_invalid");
  if (usage.prompt_cache_miss_tokens !== undefined)
    demand4(integer(usage.prompt_cache_miss_tokens) && usage.prompt_cache_miss_tokens + hit === usage.prompt_tokens, "cache_usage_invalid");
  const miss = usage.prompt_tokens - hit;
  return BigInt(miss) * (peak ? 2000n : 1000n) + BigInt(hit) * (peak ? 40n : 20n) + BigInt(usage.completion_tokens) * (peak ? 8000n : 4000n);
}

class JournalBinding {
  directory;
  configPin;
  sourcePin;
  config;
  configPath;
  path;
  configSha;
  prefix;
  checkpoints = new Map;
  starts = new Map;
  finishes = new Map;
  constructor(directory, configPin, sourcePin) {
    this.directory = directory;
    this.configPin = configPin;
    this.sourcePin = sourcePin;
    demand4(sourcePin.sha256 === JOURNAL_SOURCE_SHA, "journal_source_version");
    verifyPin2(sourcePin);
    this.configPath = verifyPin2(configPin);
    demand4(resolve8(this.configPath) === join6(resolve8(directory), "journal-config.json"), "journal_config_path");
    this.config = JSON.parse(readFileSync7(this.configPath, "utf8"));
    demand4(this.config.protocol === "campaign-api-journal-v1" && this.config.pendingLimit === 4 && this.config.model === "deepseek-flash", "journal_config_profile");
    this.configSha = configPin.sha256;
    this.path = join6(resolve8(directory), "api-events.jsonl");
    this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configSha };
    this.checkpoints.set(0, this.prefix);
  }
  consume(target) {
    demand4(integer(target.bytes) && integer(target.eventCount) && /^[a-f0-9]{64}$/.test(target.lastSha256), "invalid_journal_prefix");
    if (target.bytes <= this.prefix.bytes) {
      demand4(same3(this.checkpoints.get(target.bytes), target), "unknown_historical_prefix");
      return;
    }
    demand4(existsSync6(this.path) && statSync4(this.path).size >= target.bytes, "journal_prefix_missing");
    const fd = openSync6(this.path, "r");
    let at = this.prefix.bytes, carry = Buffer.alloc(0);
    try {
      while (at < target.bytes) {
        const b = Buffer.alloc(Math.min(16384, target.bytes - at));
        const n = readSync4(fd, b, 0, b.length, at);
        demand4(n > 0, "journal_short_read");
        at += n;
        carry = Buffer.concat([carry, b.subarray(0, n)]);
        let nl;
        while ((nl = carry.indexOf(10)) >= 0) {
          const line = carry.subarray(0, nl + 1);
          demand4(line.length <= 65536, "journal_line_limit");
          const frame = JSON.parse(line.subarray(0, -1).toString("utf8"));
          demand4(Buffer.from(JSON.stringify(frame) + `
`).equals(line) && frame.protocol === "campaign-api-journal-v1" && frame.eventSeq === this.prefix.eventCount && frame.previousEventSha256 === this.prefix.lastSha256 && integer(frame.requestSeq), "journal_chain");
          const offset = this.prefix.bytes, end = offset + line.length, sha = hash3(line);
          if (frame.kind === "start") {
            demand4(!this.starts.has(frame.requestSeq), "duplicate_start");
            this.starts.set(frame.requestSeq, frame);
          } else if (frame.kind === "finish") {
            demand4(this.starts.has(frame.requestSeq) && !this.finishes.has(frame.requestSeq), "duplicate_or_unknown_finish");
            this.finishes.set(frame.requestSeq, { frame, offset, end, sha });
          } else
            demand4(false, "journal_kind");
          this.prefix = { bytes: end, eventCount: this.prefix.eventCount + 1, lastSha256: sha };
          this.checkpoints.set(end, this.prefix);
          carry = carry.subarray(nl + 1);
        }
        demand4(carry.length <= 65536, "journal_line_limit");
      }
    } finally {
      closeSync6(fd);
    }
    demand4(carry.length === 0 && same3(this.prefix, target), "journal_prefix_mismatch");
  }
  start(seq, prefix) {
    this.consume(prefix);
    const frame = this.starts.get(seq);
    demand4(frame && frame.eventSeq === prefix.eventCount - 1, "not_this_start_prefix");
    return frame.record;
  }
  finish(seq, ref) {
    demand4(integer(ref.finishOffset) && integer(ref.finishEnd) && ref.finishEnd > ref.finishOffset && ref.finishEnd - ref.finishOffset <= 65536, "finish_offset");
    const fd = openSync6(this.path, "r"), line = Buffer.alloc(ref.finishEnd - ref.finishOffset);
    try {
      demand4(readSync4(fd, line, 0, line.length, ref.finishOffset) === line.length, "finish_short_read");
    } finally {
      closeSync6(fd);
    }
    demand4(hash3(line) === ref.finishLineSha256 && line.at(-1) === 10, "finish_digest");
    const f = JSON.parse(line.subarray(0, -1).toString("utf8"));
    demand4(f.kind === "finish" && f.requestSeq === seq, "finish_sequence");
    this.consume({ bytes: ref.finishEnd, eventCount: f.eventSeq + 1, lastSha256: ref.finishLineSha256 });
    const known = this.finishes.get(seq);
    demand4(known && known.offset === ref.finishOffset && known.end === ref.finishEnd && known.sha === ref.finishLineSha256, "finish_chain_membership");
    return known.frame.record;
  }
  current() {
    return { ...this.prefix };
  }
}
var REAL_CLOCK, JOURNAL_SOURCE_SHA, ResourceAdmissionError, hash3 = (b) => createHash6("sha256").update(b).digest("hex"), same3 = (a, b) => JSON.stringify(a) === JSON.stringify(b);
var init_paid_resource_proof_v2 = __esm(() => {
  REAL_CLOCK = Object.freeze({ wallUnixMs: () => Date.now(), monotonicNs: () => process.hrtime.bigint() });
  JOURNAL_SOURCE_SHA = createHash6("sha256").update(readFileSync7(new URL("./campaign-journal.ts", "file:///F:/git/TgEngin-handoff-2026-10-07/TgEngin/scripts/repair-2026-10-08/paid-resource-proof-v2.ts"))).digest("hex");
  ResourceAdmissionError = class ResourceAdmissionError extends Error {
    code;
    constructor(code) {
      super(code);
      this.code = code;
      this.name = "ResourceAdmissionError";
    }
  };
});

// scripts/repair-2026-10-08/cny-cash-shadow-v2.ts
import { closeSync as closeSync7, existsSync as existsSync7, fsyncSync as fsyncSync3, openSync as openSync7, readFileSync as readFileSync8, readSync as readSync5, statSync as statSync5, writeFileSync as writeFileSync3, writeSync as writeSync3 } from "fs";
import { join as join7, resolve as resolve9 } from "path";

class CashWriter {
  directory;
  hook;
  path;
  configPin;
  fd;
  prefix;
  failed = false;
  closed = false;
  constructor(directory, config, hook) {
    this.directory = directory;
    this.hook = hook;
    const path = join7(directory, "cash-config.json"), raw = Buffer.from(JSON.stringify(config) + `
`), fd = openSync7(path, "wx", 384);
    try {
      writeFileSync3(fd, raw);
      fsyncSync3(fd);
    } finally {
      closeSync7(fd);
    }
    demand4(readFileSync8(path).equals(raw), "cash_config_readback");
    this.configPin = actualPin(path);
    this.path = join7(directory, "cash-events.jsonl");
    this.fd = openSync7(this.path, "wx+", 384);
    fsyncSync3(this.fd);
    this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configPin.sha256 };
  }
  append(kind, data) {
    demand4(!this.failed && !this.closed, "cash_writer_unclosed_fault");
    const event = { protocol: "cny-shadow-event-v2", eventSeq: this.prefix.eventCount, previousEventSha256: this.prefix.lastSha256, kind, data }, raw = Buffer.from(JSON.stringify(event) + `
`);
    demand4(raw.length <= 65536 && this.prefix.bytes + raw.length <= 256 * 1024 ** 2, "cash_metadata_bound");
    const offset = this.prefix.bytes;
    try {
      this.hook?.("cash_write");
      let n = 0;
      while (n < raw.length) {
        const got = writeSync3(this.fd, raw, n, raw.length - n, offset + n);
        demand4(got > 0, "cash_short_write");
        n += got;
      }
      this.hook?.("cash_fsync");
      fsyncSync3(this.fd);
      this.hook?.("cash_readback");
      const read2 = Buffer.alloc(raw.length);
      demand4(readSync5(this.fd, read2, 0, read2.length, offset) === read2.length && read2.equals(raw) && statSync5(this.path).size === offset + raw.length, "cash_event_readback");
      this.prefix = { bytes: offset + raw.length, eventCount: this.prefix.eventCount + 1, lastSha256: hash3(raw) };
      return { ...this.prefix };
    } catch (error) {
      this.failed = true;
      throw error;
    }
  }
  snapshot() {
    return { ...this.prefix };
  }
  fault() {
    return this.failed;
  }
  close() {
    if (this.closed)
      return;
    try {
      fsyncSync3(this.fd);
    } finally {
      closeSync7(this.fd);
      this.closed = true;
    }
  }
}

class CnyCashShadow {
  options;
  directory;
  writer;
  binding;
  clock;
  states = new Map;
  ticketStates = new WeakMap;
  poisonReason;
  clockWall;
  clockMono;
  closedPin;
  nextSeq = 0;
  prices;
  config;
  configPin;
  constructor(given) {
    const options = Object.freeze({ ...given, prices: Object.freeze({ ...given.prices }), journal: Object.freeze({ ...given.journal, configPin: Object.freeze({ ...given.journal.configPin }), sourcePin: Object.freeze({ ...given.journal.sourcePin }) }) });
    this.options = options;
    demand4(options.providerKind === "local-mock" || options.admission, "real_provider_admission_required");
    demand4(options.providerKind !== "local-mock" || !options.admission || options.admission.scope === "f-fixture", "production_admission_cannot_zero_mock");
    if (options.fixtureIo)
      demand4(options.admission?.scope === "f-fixture", "cash_fault_hooks_fixture_only");
    this.directory = ordinaryDirectory3(options.directory);
    this.clock = options.admission?.clock ?? options.clock ?? REAL_CLOCK;
    this.prices = validatePrices(options.prices);
    this.binding = new JournalBinding(resolve9(options.journal.directory), options.journal.configPin, options.journal.sourcePin);
    demand4(this.binding.config.campaign === options.runId, "cash_journal_run_binding");
    this.config = { protocol: "cny-shadow-config-v2", runId: options.runId, providerKind: options.providerKind, scope: options.admission?.scope ?? "local-mock", ownerNonce: options.admission?.owned.ownerNonce ?? null, admissionPin: options.admission?.proofPin ?? null, envelopeNanoCny: (options.admission?.envelopeNanoCny ?? 0n).toString(), carryNanoCny: (options.admission?.carryNanoCny ?? 0n).toString(), pricesPin: options.prices, journalDirectory: resolve9(options.journal.directory), journalConfigPin: options.journal.configPin, journalSourcePin: options.journal.sourcePin, cashSourcePins: [SELF, PROOF_SOURCE], createdAt: new Date(this.clock.wallUnixMs()).toISOString(), priceTTL: "real-beforeForward24h", moneyUnit: "nanoCNY", invoice: false, foreignExchangeConversion: false };
    this.writer = new CashWriter(this.directory, this.config, options.fixtureIo);
    this.configPin = this.writer.configPin;
    try {
      options.admission?.registerCash(this.configPin);
    } catch (error) {
      this.writer.close();
      throw error;
    }
  }
  clockNow() {
    const wall = this.clock.wallUnixMs(), mono = this.clock.monotonicNs();
    const fault = !Number.isFinite(wall) || this.clockWall !== undefined && wall < this.clockWall || this.clockMono !== undefined && mono < this.clockMono;
    if (fault)
      this.poisonReason ??= "clock_rollback_or_unknown";
    this.clockWall = wall;
    this.clockMono = mono;
    return { wall, mono, fault };
  }
  count() {
    let known = 0n, pending = 0n, unknown = 0n, pendingCount = 0, unknownCount = 0;
    for (const s of this.states.values()) {
      if (s.phase === "known")
        known += s.amount;
      else if (s.phase === "unknown") {
        unknown += s.amount;
        unknownCount++;
      } else if (s.phase === "pending" || s.phase === "denied") {
        pending += s.reservation;
        pendingCount++;
      }
    }
    return { known, pending, unknown, pendingCount, unknownCount };
  }
  snapshot() {
    const t = this.count(), envelope = this.options.admission?.envelopeNanoCny ?? 0n;
    return { protocol: "cny-shadow-cash-v2", runId: this.options.runId, currency: "CNY", providerKind: this.options.providerKind, carriedOriginalUnknownNanoCny: this.config.carryNanoCny, newKnownEstimatedNanoCny: t.known.toString(), newPendingPeakNanoCny: t.pending.toString(), newUnknownPeakNanoCny: t.unknown.toString(), newExposureNanoCny: (t.known + t.pending + t.unknown).toString(), remainingNewEnvelopeNanoCny: (envelope - t.known - t.pending - t.unknown).toString(), pendingCount: t.pendingCount, newUnknownCount: t.unknownCount, poisoned: !!this.poisonReason, poisonReason: this.poisonReason ?? null, invoice: false, foreignExchangeConversion: false };
  }
  beforeForward(input) {
    demand4(!this.closedPin && !this.writer.fault(), "cash_closed_or_faulted");
    const j = input.journal.admitted;
    demand4(j.admitted === true && integer(j.requestSeq) && j.requestSeq === this.nextSeq && !this.states.has(j.requestSeq), "cash_request_sequence");
    const start = this.binding.start(j.requestSeq, input.journal.startPrefix), raw = gzipProof(input.capturedRequest, j.requestSha256, undefined, 4 * 1024 ** 2), v = requestValues3(raw);
    demand4(Buffer.from(input.rawRequest).equals(raw) && resolve9(input.capturedRequest.path) === resolve9(j.requestFile) && start.requestFile === j.requestFile && start.requestSha256 === j.requestSha256 && start.requestCompressedSha256 === input.capturedRequest.sha256 && start.requestBytes === raw.length && start.route === input.route && start.providerAttempted === false && Math.abs(start.reservationUsd - j.reservationUsd) < 0.000000001, "cash_actual_admission_binding");
    demand4(Math.abs(j.reservationUsd - (v.inputUpper * 0.3 + v.output * 1.2) / 1e6) < 0.000000001, "legacy_usd_reservation_binding");
    const checkpoint = jsonPin(actualPin(join7(this.binding.directory, "api-state.json")));
    demand4(checkpoint.configSha256 === this.binding.configSha && !existsSync7(join7(this.binding.directory, "journal-error.json")), "journal_checkpoint_unacknowledged");
    this.binding.consume(checkpoint.durablePrefix);
    for (const path of [j.requestFile, this.binding.path, join7(this.binding.directory, "api-state.json")]) {
      const fd = openSync7(path, "r+");
      try {
        fsyncSync3(fd);
      } finally {
        closeSync7(fd);
      }
    }
    const now = this.clockNow();
    let reason = this.poisonReason;
    try {
      verifyPin2(SELF);
      verifyPin2(PROOF_SOURCE);
      verifyPin2(this.options.prices);
      this.options.admission?.validateForwardSource();
    } catch {
      reason ??= "cash_owner_or_source_or_price_expired";
    }
    if (now.fault)
      reason ??= "cash_clock_fault";
    if (!Number.isFinite(Date.parse(start.startedAt)) || now.wall < Date.parse(start.startedAt))
      reason ??= "cash_start_clock_invalid";
    if (this.options.providerKind === "real-provider" && (!Number.isFinite(Date.parse(this.prices.observedAtUtc)) || now.wall - Date.parse(this.prices.observedAtUtc) > 24 * 3600000 || now.wall < Date.parse(this.prices.observedAtUtc)))
      reason ??= "price_expired_or_clock_invalid";
    const r = this.options.providerKind === "local-mock" ? 0n : v.peakNano, t = this.count();
    if (t.known + t.pending + t.unknown + r > (this.options.admission?.envelopeNanoCny ?? 0n))
      reason ??= "cash_envelope_exhausted";
    const ticket = Object.freeze({ id: input.id, requestSeq: j.requestSeq, route: input.route, dispatchAllowed: !reason, peakReservationNanoCny: r.toString() });
    const state = { id: input.id, seq: j.requestSeq, route: input.route, start, reservation: reason ? 0n : r, phase: reason ? "denied" : "pending", amount: 0n, ticket };
    try {
      this.writer.append("start", { id: input.id, requestSeq: j.requestSeq, route: input.route, requestPin: input.capturedRequest, rawRequestSha256: j.requestSha256, startPrefix: input.journal.startPrefix, inputUpper: v.inputUpper, outputLimit: v.output, peakReservationNanoCny: r.toString(), reservedNanoCny: state.reservation.toString(), dispatchAllowed: !reason, reason: reason ?? null, hostWallUnixMs: now.wall, hostMonotonicNs: now.mono.toString() });
    } catch (error) {
      this.poisonReason ??= "cash_admission_persistence_failed";
      throw error;
    }
    this.nextSeq++;
    this.states.set(j.requestSeq, state);
    this.ticketStates.set(ticket, state);
    if (reason)
      this.poisonReason ??= reason;
    return { admitted: !reason, ticket, ...reason ? { reason } : {} };
  }
  poison(reason) {
    demand4(reason.length > 0 && reason.length <= 1024, "poison_reason");
    this.poisonReason ??= reason;
    if (!this.writer.fault())
      this.writer.append("poison", { reason });
    return this.snapshot();
  }
  finish(ticket, input) {
    try {
      return this.finishInternal(ticket, input);
    } catch (error) {
      this.poisonReason ??= "cash_finish_validation_failed";
      if (!this.writer.fault() && !this.closedPin)
        this.writer.append("poison", { reason: this.poisonReason, requestSeq: ticket.requestSeq });
      throw error;
    }
  }
  finishInternal(ticket, input) {
    demand4(!this.closedPin, "cash_already_closed");
    const s = this.ticketStates.get(ticket);
    demand4(s && s.seq === ticket.requestSeq && s.ticket === ticket, "cash_ticket_identity");
    const now = this.clockNow();
    let record, signature, source, unknown = false;
    if (input.kind === "journal-finish") {
      record = this.binding.finish(s.seq, input.journalRef);
      demand4(record.requestSha256 === s.start.requestSha256 && record.requestFile === s.start.requestFile && record.route === s.route, "cash_finish_start_binding");
      signature = input.journalRef.finishLineSha256;
      source = { kind: "journal-finish", journalRef: input.journalRef };
    } else {
      demand4(input.requestSeq === s.seq && input.evidence.files.length > 0, "failed_capture_binding");
      for (const p of input.evidence.files)
        verifyPin2(p);
      this.binding.consume(input.evidence.originalPrefix);
      record = { ...s.start, ...input.evidence };
      signature = hash3(JSON.stringify(input.evidence));
      source = { kind: "failed-capture", evidence: input.evidence };
      unknown = true;
      this.poisonReason ??= "source_journal_poisoned_capture";
    }
    if (s.finishSignature === signature)
      return this.snapshot();
    try {
      this.options.admission?.assertOwned();
    } catch {
      this.poisonReason ??= "cash_owner_lost";
    }
    let amount = s.reservation, observedUsage, estimate, responsePin, rawResponseSha;
    if (record.providerAttempted === false && record.confirmedNoForward === true && input.kind === "journal-finish")
      amount = 0n;
    else {
      if (!ticket.dispatchAllowed)
        this.poisonReason ??= "provider_forward_after_cash_denial";
      try {
        responsePin = input.kind === "journal-finish" && record.responseFile ? { path: record.responseFile, sha256: record.responseCompressedSha256 } : input.kind === "failed-capture" ? input.evidence.responsePin : undefined;
        rawResponseSha = input.kind === "journal-finish" ? record.responseSha256 : input.evidence.rawResponseSha256;
        demand4(responsePin && rawResponseSha, "complete_response_missing");
        const raw = gzipProof(responsePin, rawResponseSha), data2 = JSON.parse(raw.toString("utf8"));
        observedUsage = data2.usage;
        demand4(same3(data2.usage, record.usage) && data2.model === record.servedModel || input.kind === "failed-capture" && same3(data2.usage, input.evidence.usage), "response_usage_binding");
        const window = peakWindow(Date.parse(s.start.startedAt), now.wall), expired = now.wall - Date.parse(this.prices.observedAtUtc) > 24 * 3600000 || now.wall < Date.parse(this.prices.observedAtUtc);
        const peak = window.peak || window.clockFault || now.fault || expired;
        estimate = this.options.providerKind === "local-mock" ? 0n : pricedUsage(observedUsage, peak);
        amount = estimate;
        if (input.kind === "journal-finish" && (record.httpStatus !== 200 || record.fault || record.completionValid !== true)) {
          unknown = true;
          this.poisonReason ??= "provider_body_or_completion_not_complete";
        }
        if (window.clockFault || now.fault || expired) {
          unknown = true;
          this.poisonReason ??= "clock_or_price_unknown_at_capture";
        }
      } catch {
        unknown = true;
        this.poisonReason ??= "missing_or_invalid_complete_usage";
      }
    }
    if (input.kind === "failed-capture" && s.phase === "known" && responsePin && observedUsage && estimate === s.amount && rawResponseSha && rawResponseSha === s.lastResponseRawSha) {
      this.writer.append("late-evidence", { id: s.id, requestSeq: s.seq, source, responsePin, rawResponseSha256: rawResponseSha, observedUsage, amountNanoCny: s.amount.toString(), reason: "overlapping_known_finish_retained_once" });
      return this.snapshot();
    }
    if (input.kind === "failed-capture")
      unknown = true;
    if (s.phase === "unknown" || s.phase === "known" && s.finishSignature) {
      unknown = true;
      this.poisonReason ??= "conflicting_or_late_cash_finish";
    }
    if (unknown)
      amount = [s.reservation, s.amount, estimate ?? 0n].reduce((a, b) => a > b ? a : b);
    const phase = unknown ? "unknown" : "known";
    const data = { id: s.id, requestSeq: s.seq, phase, amountNanoCny: amount.toString(), peakReservationNanoCny: s.reservation.toString(), source, signature, responsePin: responsePin ?? null, rawResponseSha256: rawResponseSha ?? null, observedUsage: observedUsage ?? null, observedEstimatedNanoCny: estimate?.toString() ?? null, hostCaptureWallUnixMs: now.wall, hostMonotonicNs: now.mono.toString(), clockFault: now.fault, poisonReason: this.poisonReason ?? null };
    try {
      this.writer.append("finish", data);
    } catch (error) {
      this.poisonReason ??= "cash_finish_persistence_failed";
      throw error;
    }
    s.phase = phase;
    s.amount = amount;
    s.finishSignature = signature;
    s.lastResponseRawSha = rawResponseSha;
    if (amount > s.reservation && record.providerAttempted !== false)
      this.poisonReason ??= "actual_estimate_exceeds_reservation";
    if (BigInt(this.snapshot().newExposureNanoCny) > (this.options.admission?.envelopeNanoCny ?? 0n))
      this.poisonReason ??= "actual_estimate_exceeds_envelope";
    return this.snapshot();
  }
  close() {
    if (this.closedPin)
      return this.closedPin;
    const inspection = inspectCampaignJournal2(this.options.journal.directory), snapshot = this.snapshot();
    const cashPrefix = this.writer.snapshot();
    let good = !this.writer.fault() && inspection.valid && inspection.accountingClosed && snapshot.pendingCount === 0 && snapshot.newUnknownCount === 0;
    try {
      this.options.admission?.assertOwned();
    } catch {
      good = false;
    }
    this.writer.close();
    const cashEvents = actualPin(this.writer.path);
    const value = { protocol: "cny-shadow-close-v2", runId: this.options.runId, ownerNonce: this.config.ownerNonce, configPin: this.configPin, cashEventsPin: cashEvents, cashPrefix, journalConfigPin: this.options.journal.configPin, journalSourcePin: this.options.journal.sourcePin, journalDirectory: resolve9(this.options.journal.directory), journalPrefix: inspection.prefix ?? this.binding.current(), journalValid: inspection.valid, journalAccountingClosed: inspection.accountingClosed, snapshot, releasePermitted: good, poisonReason: this.poisonReason ?? null, invoice: false, foreignExchangeConversion: false };
    const path = join7(this.directory, "cash-close.json"), fd = openSync7(path, "wx", 384);
    try {
      writeFileSync3(fd, JSON.stringify(value, null, 2) + `
`);
      fsyncSync3(fd);
    } finally {
      closeSync7(fd);
    }
    this.closedPin = actualPin(path);
    if (good)
      verifyCashClosure(this.closedPin);
    return this.closedPin;
  }
}
function verifyCashClosure(pin2) {
  const proof = jsonPin(pin2), config = jsonPin(proof.configPin);
  demand4(proof.protocol === "cny-shadow-close-v2" && config.protocol === "cny-shadow-config-v2" && proof.runId === config.runId && proof.ownerNonce === config.ownerNonce, "cash_close_config");
  demand4(config.providerKind === "real-provider" || config.providerKind === "local-mock", "cash_provider_kind");
  for (const p of config.cashSourcePins)
    verifyPin2(p);
  const prices = validatePrices(config.pricesPin);
  verifyPin2(proof.cashEventsPin);
  verifyPin2(config.journalSourcePin);
  if (config.admissionPin) {
    const admission = jsonPin(config.admissionPin);
    demand4(admission.protocol === "paid-resource-admission-v2" && admission.runId === config.runId && admission.owned.ownerNonce === config.ownerNonce && admission.selectedNewEnvelopeNanoCny === config.envelopeNanoCny && admission.carryNanoCny === config.carryNanoCny, "cash_admission_config_binding");
  }
  const binding = new JournalBinding(config.journalDirectory, config.journalConfigPin, config.journalSourcePin), raw = readFileSync8(proof.cashEventsPin.path);
  let at = 0, seq = 0, last = proof.configPin.sha256;
  const states = new Map;
  for (const lineText of raw.toString("utf8").split(`
`)) {
    if (!lineText)
      continue;
    const line = Buffer.from(lineText + `
`), e = JSON.parse(lineText);
    demand4(Buffer.from(JSON.stringify(e) + `
`).equals(line) && e.protocol === "cny-shadow-event-v2" && e.eventSeq === seq && e.previousEventSha256 === last, "cash_event_chain");
    const d = e.data;
    if (e.kind === "start") {
      demand4(!states.has(d.requestSeq) && d.requestSeq === states.size, "cash_start_sequence");
      const start = binding.start(d.requestSeq, d.startPrefix), body = gzipProof(d.requestPin, d.rawRequestSha256, undefined, 4 * 1024 ** 2), v = requestValues3(body);
      demand4(start.requestSha256 === d.rawRequestSha256 && start.requestCompressedSha256 === d.requestPin.sha256 && resolve9(start.requestFile) === resolve9(d.requestPin.path) && start.requestBytes === body.length && start.route === d.route && v.inputUpper === d.inputUpper && v.output === d.outputLimit, "cash_start_proof");
      const r = config.providerKind === "local-mock" ? 0n : v.peakNano;
      demand4(typeof d.dispatchAllowed === "boolean" && r.toString() === d.peakReservationNanoCny && d.reservedNanoCny === (d.dispatchAllowed ? r : 0n).toString(), "cash_peak_reservation");
      states.set(d.requestSeq, { phase: d.dispatchAllowed ? "pending" : "denied", amount: 0n, reservation: BigInt(d.reservedNanoCny), start });
    } else if (e.kind === "finish") {
      const s = states.get(d.requestSeq);
      demand4(s, "cash_finish_unknown");
      let min = 0n;
      if (d.source.kind === "journal-finish") {
        const receipt = binding.finish(d.requestSeq, d.source.journalRef);
        demand4(d.signature === d.source.journalRef.finishLineSha256 && receipt.requestSha256 === s.start.requestSha256, "cash_finish_member");
        if (!(receipt.providerAttempted === false && receipt.confirmedNoForward === true)) {
          if (receipt.httpStatus !== 200 || receipt.fault || receipt.completionValid !== true)
            demand4(d.phase === "unknown", "incomplete_provider_receipt_settled");
          demand4(d.responsePin && d.rawResponseSha256 && resolve9(d.responsePin.path) === resolve9(receipt.responseFile) && d.responsePin.sha256 === receipt.responseCompressedSha256 && d.rawResponseSha256 === receipt.responseSha256, "cash_known_response_missing");
          const body = gzipProof(d.responsePin, d.rawResponseSha256), data = JSON.parse(body.toString("utf8"));
          demand4(same3(data.usage, d.observedUsage) && same3(data.usage, receipt.usage) && data.model === receipt.servedModel, "cash_usage_proof");
          const window = peakWindow(Date.parse(s.start.startedAt), d.hostCaptureWallUnixMs), expired = !Number.isFinite(Date.parse(prices.observedAtUtc)) || d.hostCaptureWallUnixMs - Date.parse(prices.observedAtUtc) > 24 * 3600000 || d.hostCaptureWallUnixMs < Date.parse(prices.observedAtUtc);
          if (window.clockFault || d.clockFault || expired)
            demand4(d.phase === "unknown", "cash_clock_unknown_settled");
          try {
            min = config.providerKind === "local-mock" ? 0n : pricedUsage(data.usage, window.peak || window.clockFault || d.clockFault || expired);
          } catch {
            demand4(d.phase === "unknown", "invalid_usage_settled");
            min = s.reservation;
          }
        }
      } else {
        demand4(d.source.kind === "failed-capture" && d.phase === "unknown", "failed_capture_settled");
        for (const p of d.source.evidence.files)
          verifyPin2(p);
        min = s.reservation;
        if (d.responsePin && d.rawResponseSha256) {
          const body = gzipProof(d.responsePin, d.rawResponseSha256), data = JSON.parse(body.toString("utf8"));
          demand4(same3(data.usage, d.observedUsage), "late_usage_proof");
          try {
            const w = peakWindow(Date.parse(s.start.startedAt), d.hostCaptureWallUnixMs);
            min = config.providerKind === "local-mock" ? 0n : pricedUsage(data.usage, w.peak || d.clockFault);
          } catch {}
        }
      }
      if (s.phase === "unknown")
        demand4(d.phase === "unknown", "sealed_unknown_reopened");
      if (d.phase === "unknown")
        min = [min, s.reservation, s.amount].reduce((a, b) => a > b ? a : b);
      demand4((d.phase === "known" || d.phase === "unknown") && BigInt(d.amountNanoCny) >= min && (d.phase !== "known" || BigInt(d.amountNanoCny) === min), "cash_cost_replay");
      s.phase = d.phase;
      s.amount = BigInt(d.amountNanoCny);
      s.signature = d.signature;
      s.rawSha = d.rawResponseSha256;
    } else if (e.kind === "late-evidence") {
      const s = states.get(d.requestSeq);
      demand4(s && s.phase === "known" && s.rawSha === d.rawResponseSha256 && d.source.kind === "failed-capture" && BigInt(d.amountNanoCny) === s.amount, "late_overlap_binding");
      for (const p of d.source.evidence.files)
        verifyPin2(p);
      const body = gzipProof(d.responsePin, d.rawResponseSha256), data = JSON.parse(body.toString("utf8"));
      demand4(same3(data.usage, d.observedUsage), "late_overlap_usage");
    } else
      demand4(e.kind === "poison", "cash_event_kind");
    at += line.length;
    seq++;
    last = hash3(line);
  }
  demand4(at === raw.length && same3(proof.cashPrefix, { bytes: at, eventCount: seq, lastSha256: last }), "cash_exact_prefix");
  let known = 0n, pending = 0n, unknown = 0n, pendingCount = 0, unknownCount = 0;
  for (const s of states.values()) {
    if (s.phase === "known")
      known += s.amount;
    else if (s.phase === "unknown") {
      unknown += s.amount;
      unknownCount++;
    } else {
      pending += s.reservation;
      pendingCount++;
    }
  }
  const exposure = known + pending + unknown;
  demand4(proof.snapshot.protocol === "cny-shadow-cash-v2" && proof.snapshot.runId === config.runId && proof.snapshot.currency === "CNY" && proof.snapshot.providerKind === config.providerKind && proof.snapshot.carriedOriginalUnknownNanoCny === config.carryNanoCny && proof.snapshot.newKnownEstimatedNanoCny === known.toString() && proof.snapshot.newPendingPeakNanoCny === pending.toString() && proof.snapshot.newUnknownPeakNanoCny === unknown.toString() && proof.snapshot.newExposureNanoCny === exposure.toString() && proof.snapshot.remainingNewEnvelopeNanoCny === (BigInt(config.envelopeNanoCny) - exposure).toString() && proof.snapshot.pendingCount === pendingCount && proof.snapshot.newUnknownCount === unknownCount && proof.snapshot.invoice === false && proof.snapshot.foreignExchangeConversion === false, "cash_snapshot_replay");
  const journal = inspectCampaignJournal2(config.journalDirectory);
  demand4(journal.valid && journal.accountingClosed && journal.snapshot?.acceptedRequestCount === states.size && same3(journal.prefix, proof.journalPrefix) && pendingCount === 0 && unknownCount === 0 && proof.releasePermitted === true, "cash_or_peer_not_closed");
  return { proof, config, states };
}
var SELF, PROOF_SOURCE;
var init_cny_cash_shadow_v2 = __esm(() => {
  init_campaign_journal();
  init_paid_resource_proof_v2();
  SELF = actualPin(import.meta.path);
  PROOF_SOURCE = actualPin(join7("F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\repair-2026-10-08", "paid-resource-proof-v2.ts"));
});

// scripts/repair-2026-10-10/full-f/shared/digitalocean-usd-cash.ts
import { closeSync as closeSync8, fsyncSync as fsyncSync4, openSync as openSync8, readFileSync as readFileSync9, readSync as readSync6, statSync as statSync6, writeSync as writeSync4 } from "fs";
import { join as join8, resolve as resolve10 } from "path";
function durable(path, value) {
  const raw = Buffer.from(JSON.stringify(value, null, 2) + `
`), fd = openSync8(path, "wx", 384);
  try {
    let at = 0;
    while (at < raw.length) {
      const count2 = writeSync4(fd, raw, at, raw.length - at);
      demand4(count2 > 0, "usd_cash_short_write");
      at += count2;
    }
    fsyncSync4(fd);
  } finally {
    closeSync8(fd);
  }
  demand4(readFileSync9(path).equals(raw), "usd_cash_readback");
  return actualPin(path);
}
function validateUsdPrices(pin2, providerSlug = BENCHMARK_PROVIDER.providerSlug) {
  const data = jsonPin(pin2);
  demand4(data.protocol === "openrouter-usd-pricing-source-snapshot-v1" && data.model === BENCHMARK_PROVIDER.model && data.currency === "USD" && data.providerSlug === providerSlug && data.actualOfficialGET === true && data.modelCalls === 0, "openrouter_price_profile");
  demand4(same3(data.reservationRates, BENCHMARK_PROVIDER.peakRates), "openrouter_reservation_rates");
  const raw = jsonPin(data.originalResponsePin);
  demand4(raw.data?.endpoints?.some((row) => row.provider_name === { relace: "Relace", deepseek: "DeepSeek", digitalocean: "DigitalOcean" }[providerSlug] && row.tag === providerSlug && row.model_id === BENCHMARK_PROVIDER.model), "openrouter_price_raw_binding");
  return data;
}
function boundStart(directory, data) {
  const raw = readFileSync9(join8(directory, "api-events.jsonl")), end = data.startPrefix.bytes;
  demand4(Number.isSafeInteger(end) && end > 0 && end <= raw.length && raw[end - 1] === 10, "usd_start_prefix_bounds");
  const begin = raw.lastIndexOf(10, end - 2) + 1, line = raw.subarray(begin, end), event = JSON.parse(line.toString("utf8"));
  demand4(hash3(line) === data.startPrefix.lastSha256 && event.kind === "start" && event.eventSeq + 1 === data.startPrefix.eventCount && event.requestSeq === data.ticket.requestSeq && event.record.route === data.ticket.route && same3(data.requestPin, actualPin(event.record.requestFile)) && data.requestSha256 === event.record.requestSha256, "usd_start_journal_binding");
  gzipProof(data.requestPin, data.requestSha256, undefined, 4 * 1024 ** 2);
  return event.record;
}

class UsdCash {
  options;
  states = new Map;
  tickets = new WeakSet;
  events = [];
  poisonReason;
  closed;
  fd;
  previousHash;
  capUsd;
  bytes = 0;
  directory;
  configPin;
  prices;
  config;
  constructor(options) {
    this.options = options;
    const admission = options.admission;
    demand4(options.providerKind === "local-mock" || admission?.currency === "USD", "openrouter_usd_admission_required");
    this.directory = ordinaryDirectory3(options.directory);
    this.prices = validateUsdPrices(options.prices);
    const config = jsonPin(options.journal.configPin);
    demand4(config.provider === "openrouter-deepseek" && config.currency === "USD" && config.campaign === options.runId && config.priorCampaignCostUpperBoundUsd === 0, "openrouter_cash_journal_binding");
    this.capUsd = admission?.capUsd ?? config.capUsd;
    demand4(Number.isFinite(this.capUsd) && this.capUsd > 0 && config.capUsd <= this.capUsd, "openrouter_cash_cap_binding");
    this.config = {
      protocol: "openrouter-usd-cash-config-v1",
      runId: options.runId,
      currency: "USD",
      providerKind: options.providerKind,
      capUsd: this.capUsd,
      ownerNonce: admission?.owned.ownerNonce ?? null,
      scope: admission?.scope ?? "local-mock",
      admissionPin: admission?.proofPin ?? null,
      pricesPin: options.prices,
      journal: options.journal,
      sourcePin: actualPin(import.meta.path),
      createdAt: new Date().toISOString(),
      invoice: false,
      foreignExchangeConversion: false
    };
    this.configPin = durable(join8(this.directory, "cash-config.json"), this.config);
    this.previousHash = this.configPin.sha256;
    this.fd = openSync8(join8(this.directory, "cash-events.jsonl"), "wx+", 384);
    fsyncSync4(this.fd);
    try {
      admission?.registerCash(this.configPin);
    } catch (error) {
      closeSync8(this.fd);
      throw error;
    }
  }
  append(kind, data) {
    const event = { protocol: "openrouter-usd-cash-event-v1", index: this.events.length, previousSha256: this.previousHash, kind, data };
    const raw = Buffer.from(JSON.stringify(event) + `
`);
    demand4(raw.length <= 65536 && this.bytes + raw.length <= 256 * 1024 ** 2, "usd_cash_event_limit");
    let at = 0;
    while (at < raw.length) {
      const count2 = writeSync4(this.fd, raw, at, raw.length - at, this.bytes + at);
      demand4(count2 > 0, "usd_cash_short_write");
      at += count2;
    }
    fsyncSync4(this.fd);
    const readback = Buffer.alloc(raw.length);
    demand4(readSync6(this.fd, readback, 0, raw.length, this.bytes) === raw.length && readback.equals(raw) && statSync6(join8(this.directory, "cash-events.jsonl")).size === this.bytes + raw.length, "usd_cash_event_readback");
    this.bytes += raw.length;
    this.previousHash = hash3(raw);
    this.events.push(event);
  }
  snapshot() {
    let known = 0, pending = 0, unknown = 0, pendingCount = 0, unknownCount = 0;
    for (const state of this.states.values()) {
      if (state.phase === "known")
        known += state.amount;
      if (state.phase === "pending") {
        pending += state.ticket.reservationUsd;
        pendingCount++;
      }
      if (state.phase === "unknown") {
        unknown += state.amount;
        unknownCount++;
      }
    }
    return {
      protocol: "openrouter-usd-cash-state-v1",
      currency: "USD",
      runId: this.options.runId,
      capUsd: this.capUsd,
      billedUsd: known,
      pendingReservationUsd: pending,
      unknownReservationUsd: unknown,
      exposureUpperBoundUsd: known + pending + unknown,
      remainingUsd: this.capUsd - known - pending - unknown,
      pendingCount,
      newUnknownCount: unknownCount,
      poisoned: !!this.poisonReason,
      poisonReason: this.poisonReason ?? null,
      invoice: false,
      foreignExchangeConversion: false
    };
  }
  poison(reason) {
    this.poisonReason ??= reason;
  }
  beforeForward(input) {
    demand4(!this.closed && !this.poisonReason, "usd_cash_closed_or_poisoned");
    const admission = this.options.admission;
    admission?.validateForwardSource();
    verifyPin2(this.options.prices);
    verifyPin2(this.config.sourcePin);
    verifyPin2(this.options.journal.sourcePin);
    const observed = Date.parse(this.prices.observedAtUtc);
    if (this.options.providerKind === "real-provider")
      demand4(Number.isFinite(observed) && Date.now() >= observed && Date.now() - observed <= 86400000, "openrouter_price_expired");
    const j = input.journal.admitted, raw = gzipProof(input.capturedRequest, j.requestSha256, undefined, 4 * 1024 ** 2);
    const inspected = inspectCampaignJournal(this.options.journal.directory);
    demand4(inspected.valid && Buffer.from(input.rawRequest).equals(raw) && resolve10(input.capturedRequest.path) === resolve10(j.requestFile) && j.requestSeq === this.states.size, "usd_actual_request_binding");
    const reservationUsd = this.options.providerKind === "local-mock" ? 0 : j.reservationUsd;
    const permitted = this.snapshot().exposureUpperBoundUsd + reservationUsd <= this.capUsd + 0.000000001;
    const ticket = Object.freeze({
      requestSeq: j.requestSeq,
      route: input.route,
      reservationUsd,
      currency: "USD",
      dispatchAllowed: permitted
    });
    const start = { ticket, requestPin: input.capturedRequest, requestSha256: j.requestSha256, startPrefix: input.journal.startPrefix };
    demand4(boundStart(this.options.journal.directory, start).reservationUsd === j.reservationUsd, "usd_actual_reservation_binding");
    this.append("start", start);
    this.states.set(j.requestSeq, { ticket, phase: permitted ? "pending" : "denied", amount: 0 });
    this.tickets.add(ticket);
    if (!permitted)
      this.poison("usd_envelope_exhausted");
    return { admitted: permitted, ticket, ...!permitted ? { reason: "usd_envelope_exhausted" } : {} };
  }
  finish(given, finish) {
    demand4(!this.closed && this.tickets.has(given), "usd_ticket_not_owned");
    const ticket = given, state = this.states.get(ticket.requestSeq);
    const signature = hash3(JSON.stringify(finish));
    if (state.signature) {
      demand4(state.signature === signature, "usd_duplicate_finish_changed");
      return this.snapshot();
    }
    let phase, amount, receipt;
    if (finish.kind === "journal-finish") {
      const ref = finish.journalRef;
      const bytes = readFileSync9(join8(this.options.journal.directory, "api-events.jsonl"));
      const line = bytes.subarray(ref.finishOffset, ref.finishEnd);
      demand4(hash3(line) === ref.finishLineSha256, "usd_finish_line_changed");
      const event = JSON.parse(line.toString("utf8"));
      receipt = event.record;
      demand4(event.kind === "finish" && event.requestSeq === ticket.requestSeq && receipt.route === ticket.route && inspectCampaignJournal(this.options.journal.directory).valid, "usd_finish_journal_binding");
      phase = receipt.costBasis === "reservation" ? "unknown" : "known";
      amount = this.options.providerKind === "local-mock" ? 0 : receipt.usdUpperBound;
    } else {
      phase = "unknown";
      amount = ticket.reservationUsd;
      this.poison("usd_failed_capture_unsettled");
    }
    demand4(Number.isFinite(amount) && amount >= 0, "usd_finish_amount_invalid");
    this.append("finish", {
      ticket,
      signature,
      phase,
      amountUsd: amount,
      finish,
      costBasis: receipt?.costBasis ?? "reservation",
      generationId: receipt?.requestId ?? null,
      providerName: receipt?.providerName ?? null,
      servedModel: receipt?.servedModel ?? null
    });
    state.phase = phase;
    state.amount = amount;
    state.signature = signature;
    if (phase === "unknown")
      this.poison("usd_unknown_charge");
    if (this.snapshot().exposureUpperBoundUsd > this.capUsd + 0.000000001)
      this.poison("usd_cost_exceeded_cap");
    return this.snapshot();
  }
  close() {
    if (this.closed)
      return this.closed;
    fsyncSync4(this.fd);
    closeSync8(this.fd);
    const inspection = inspectCampaignJournal(this.options.journal.directory), state = this.snapshot();
    this.closed = durable(join8(this.directory, "cash-close.json"), {
      protocol: "openrouter-usd-cash-close-v1",
      currency: "USD",
      configPin: this.configPin,
      cashEventsPin: actualPin(join8(this.directory, "cash-events.jsonl")),
      snapshot: state,
      journalDirectory: this.options.journal.directory,
      journalPrefix: inspection.prefix,
      releasePermitted: inspection.valid && inspection.accountingClosed && state.pendingCount === 0 && state.newUnknownCount === 0,
      scoreCertificate: false,
      invoice: false,
      foreignExchangeConversion: false
    });
    return this.closed;
  }
}
function verifyBenchmarkCashClosure(closePin) {
  const proof = jsonPin(closePin);
  if (proof.protocol !== "openrouter-usd-cash-close-v1")
    throw Error("Expected OpenRouter USD cash closure");
  const config = jsonPin(proof.configPin), eventsRaw = readFileSync9(verifyPin2(proof.cashEventsPin));
  const journalConfig = jsonPin(config.journal.configPin);
  validateUsdPrices(config.pricesPin, journalConfig.providerSlug ?? "deepseek");
  verifyPin2(config.sourcePin);
  verifyPin2(config.journal.sourcePin);
  demand4(config.currency === "USD" && config.protocol === "openrouter-usd-cash-config-v1" && Number.isFinite(config.capUsd) && config.capUsd > 0 && resolve10(config.journal.directory) === resolve10(proof.journalDirectory) && journalConfig.currency === "USD" && journalConfig.provider === BENCHMARK_PROVIDER.kind && journalConfig.campaign === config.runId && journalConfig.priorCampaignCostUpperBoundUsd === 0 && journalConfig.capUsd <= config.capUsd, "usd_close_config");
  const journal = inspectCampaignJournal(proof.journalDirectory);
  demand4(journal.valid && journal.accountingClosed && same3(journal.prefix, proof.journalPrefix), "usd_close_journal");
  demand4(eventsRaw.length <= 256 * 1024 ** 2 && (eventsRaw.length === 0 || eventsRaw.at(-1) === 10), "usd_cash_complete_events");
  let previous = proof.configPin.sha256, seq = 0, starts = 0, known = 0, unknown = 0, unknownCount = 0;
  const active = new Map;
  for (const text of eventsRaw.toString("utf8").trimEnd().split(`
`).filter(Boolean)) {
    const event = JSON.parse(text);
    demand4(JSON.stringify(event) === text && Buffer.byteLength(text) <= 65536 && event.index === seq++ && event.previousSha256 === previous && event.protocol === "openrouter-usd-cash-event-v1", "usd_cash_chain");
    previous = hash3(text + `
`);
    const { data } = event;
    if (event.kind === "start") {
      const ticket = data.ticket, start = boundStart(proof.journalDirectory, data);
      demand4(ticket.requestSeq === starts++ && ticket.currency === "USD" && ticket.reservationUsd === (config.providerKind === "local-mock" ? 0 : start.reservationUsd), "usd_start_reservation");
      const pending = [...active.values()].reduce((sum, row) => sum + (row.dispatchAllowed ? row.reservationUsd : 0), 0);
      demand4(ticket.dispatchAllowed === known + unknown + pending + ticket.reservationUsd <= config.capUsd + 0.000000001, "usd_start_budget_replay");
      active.set(ticket.requestSeq, ticket);
    } else {
      demand4(event.kind === "finish" && same3(active.get(data.ticket.requestSeq), data.ticket) && data.signature === hash3(JSON.stringify(data.finish)) && Number.isFinite(data.amountUsd) && data.amountUsd >= 0, "usd_cash_finish_without_start");
      if (data.finish.kind === "journal-finish") {
        const ref = data.finish.journalRef, raw = readFileSync9(join8(proof.journalDirectory, "api-events.jsonl")).subarray(ref.finishOffset, ref.finishEnd);
        const offset = journal.offsets.get(data.ticket.requestSeq);
        demand4(offset && offset.offset === ref.finishOffset && offset.offset + offset.bytes === ref.finishEnd && offset.sha256 === ref.finishLineSha256 && hash3(raw) === ref.finishLineSha256, "usd_cash_raw_finish");
        const source = JSON.parse(raw.toString("utf8"));
        demand4(source.kind === "finish" && source.requestSeq === data.ticket.requestSeq && source.record.route === data.ticket.route && data.phase === (source.record.costBasis === "reservation" ? "unknown" : "known") && data.costBasis === source.record.costBasis && data.generationId === (source.record.requestId ?? null) && data.providerName === (source.record.providerName ?? null) && data.servedModel === (source.record.servedModel ?? null) && (config.providerKind === "local-mock" ? data.amountUsd === 0 : source.record.usdUpperBound === data.amountUsd), "usd_cash_amount_binding");
      } else
        demand4(data.finish.kind === "failed-capture" && data.finish.requestSeq === data.ticket.requestSeq && data.phase === "unknown" && data.amountUsd === data.ticket.reservationUsd, "usd_unknown_reservation_binding");
      active.delete(data.ticket.requestSeq);
      if (data.phase === "known")
        known += data.amountUsd;
      else {
        unknown += data.amountUsd;
        unknownCount++;
      }
    }
  }
  demand4(active.size === 0 && starts === journal.snapshot.acceptedRequestCount && proof.snapshot.pendingCount === 0 && proof.snapshot.pendingReservationUsd === 0 && proof.snapshot.currency === "USD" && proof.snapshot.runId === config.runId && proof.snapshot.capUsd === config.capUsd && proof.snapshot.newUnknownCount === unknownCount && Math.abs(proof.snapshot.billedUsd - known) < 0.000000001 && Math.abs(proof.snapshot.unknownReservationUsd - unknown) < 0.000000001 && Math.abs(proof.snapshot.exposureUpperBoundUsd - known - unknown) < 0.000000001 && Math.abs(proof.snapshot.remainingUsd - config.capUsd + known + unknown) < 0.000000001 && (config.providerKind === "local-mock" || Math.abs(journal.snapshot.recordedUsageUpperBoundUsd - known - unknown) < 0.000000001), "usd_cash_replay_totals");
  demand4(proof.releasePermitted === (unknownCount === 0) && (!(unknownCount || known + unknown > config.capUsd + 0.000000001) || proof.snapshot.poisoned === true), "usd_release_consistency");
  return { proof, config };
}
var init_digitalocean_usd_cash = __esm(() => {
  init_digitalocean_journal();
  init_cny_cash_shadow_v2();
  init_paid_resource_proof_v2();
  init_digitalocean_provider();
});

// scripts/bench-runner/pre-native-history.ts
import { verify as verify2 } from "crypto";
import { readFileSync as readFileSync10 } from "fs";
function inspectPreNativeHistory(m, budget, seen) {
  let knownUsd = 0, unknownUsd = 0, calls = 0;
  const need = (x, s) => {
    if (!x)
      throw Error(s);
  };
  for (const h of m.adapterConfig.preNativeRecoveryHistory ?? []) {
    const envelope = readPinned(h.reviewEnvelopePin), r = envelope.review, authority = m.adapterConfig.bindingSpec?.authorityPin;
    checkPin(authority);
    need(envelope.protocol === "bench-root-signed-pre-native-reconciliation-v1" && r?.protocol === "bench-pre-native-reconciliation-v1" && verify2(null, Buffer.from(JSON.stringify(r)), readFileSync10(authority.path), Buffer.from(envelope.signature, "base64")), "pre_native_root_signature");
    need(r.taskId === m.taskId && r.bench === m.bench && r.attemptId === h.attemptId && r.runId === h.runId && r.cashClosePin.sha256 === h.cashClosePin.sha256 && r.closureAuditPin.sha256 === h.closureAuditPin.sha256, "pre_native_history_identity");
    const audit = readPinned(h.closureAuditPin), context = readPinned(r.contextPin), process2 = readPinned(r.processReceiptPin);
    checkPin(r.manifestPin);
    need(context.attemptId === h.attemptId && context.manifestPin.sha256 === r.manifestPin.sha256 && process2.attemptId === h.attemptId && process2.manifestPin.sha256 === r.manifestPin.sha256, "pre_native_actual_context");
    need(audit.taskId === m.taskId && audit.bench === m.bench && audit.attemptId === h.attemptId && audit.runId === h.runId && audit.nativeCommandCount === 0 && audit.actorsEverCreated === false && audit.candidateOrSubmissionPresent === false && audit.resourceReleased === true && audit.brokerLaneClosed === true, "pre_native_zero_custody");
    need(audit.evidencePins?.length > 0, "pre_native_raw_evidence");
    for (const p of audit.evidencePins)
      checkPin(p);
    for (const p of r.permanentLockPins)
      checkPin(p);
    need(audit.exactPidAbsence?.some((x) => x.pid === process2.pid && x.incarnation === process2.incarnation), "pre_native_incarnation_closure");
    const cash = verifyBenchmarkCashClosure(h.cashClosePin), j = inspectCampaignJournal(cash.proof.journalDirectory), s = cash.proof.snapshot;
    need(!seen.has(cash.config.runId) && cash.config.runId === h.runId && budget.cashClosePins.some((p) => p.path === h.cashClosePin.path && p.sha256 === h.cashClosePin.sha256), "pre_native_cash_chain");
    seen.add(h.runId);
    need(j.valid && j.accountingClosed && j.snapshot?.acceptedRequestCount === 0 && j.snapshot?.finishedRequestCount === 0 && s.pendingCount === 0 && s.billedUsd === 0 && s.unknownReservationUsd === 0 && cash.config.capUsd <= m.original.taskCapUsd, "pre_native_actual_zero_cash");
    knownUsd += s.billedUsd;
    unknownUsd += s.unknownReservationUsd;
    calls += j.snapshot.acceptedRequestCount;
  }
  return { knownUsd, unknownUsd, calls };
}
var init_pre_native_history = __esm(() => {
  init_runtime();
  init_digitalocean_usd_cash();
  init_digitalocean_journal();
});

// scripts/bench-runner/original-history.ts
import { existsSync as existsSync8 } from "fs";
import { resolve as resolve11 } from "path";
import { Database as Database2 } from "bun:sqlite";
import { createHash as createHash7 } from "crypto";
function checkedPin(m, p) {
  checkPin(p);
  need([...m.provenance.sourcePins, ...m.provenance.contractPins, ...m.history.priorRunPins].some((x) => same4(x, p)), "original_history_pin_not_manifest_bound:" + p.path);
}
function streams(m, p) {
  checkedPin(m, p);
  const c = readPinned(p);
  need(c.exitObserved === true && c.closeObserved === true, "original_process_close_unproven");
  for (const s of [c.stdout, c.stderr])
    checkPin(s);
  return c;
}
function finalHandIn(database, id) {
  const task = database.query("select id,run,mode,result,created_at,solve_seconds from task where id=?").get(id);
  need(task, "original_main_task_missing");
  if (task.result !== null)
    return { task, resultPresent: true, submitPresent: false, submits: [] };
  need(/^[A-Za-z0-9_]+$/.test(task.mode), "original_mode_identifier");
  const deadline = Number(task.created_at) + Number(task.solve_seconds) * 1000;
  need(Number.isFinite(deadline) && task.solve_seconds > 0, "original_task_clock");
  const units = database.query('select agent,instance,unit from "task_' + task.mode + '" where task=?').all(id);
  const submits = [];
  for (const u of units) {
    need(/^[A-Za-z0-9_]+$/.test(u.agent), "original_agent_identifier");
    for (const row of database.query('select seq,at,body from "agent_' + u.agent + `_msg" where instance=? and unit=? and kind='call' and at<=?`).all(u.instance, u.unit, deadline)) {
      let payload;
      try {
        payload = JSON.parse(row.body);
      } catch {
        throw Error("original_call_payload_unparseable");
      }
      for (const call of payload.calls ?? [])
        if (call.name === "submit")
          submits.push({ agent: u.agent, instance: u.instance, unit: u.unit, seq: row.seq, at: row.at, callId: call.id, answerSha256: createHash7("sha256").update(typeof call.input?.answer === "string" ? call.input.answer : "").digest("hex") });
    }
  }
  const station = database.query("select count(*) n from cycle where mode=? and cycle='submit'").get(task.mode);
  need(station.n > 0, "original_final_candidate_policy_requires_adapter_recovery");
  return { task, resultPresent: false, submitPresent: submits.length > 0, submits };
}
function auditOriginalHistory(m, c) {
  need(c?.protocol === "bench-original-history-v1" && c.taskId === m.taskId && c.bench === m.bench, "original_history_identity");
  need(c.attempts.length > 0 && c.attempts.length + (m.adapterConfig.preNativeRecoveryHistory ?? []).length === c.cashClosePins.length, "original_history_complete_cash_attempts");
  need(m.history.validResultPins.length === 0, "valid_wrong_must_never_repeat");
  checkedPin(m, c.reviewPin);
  const review = readPinned(c.reviewPin);
  need(review.protocol === "bench-original-history-review-v1" && review.taskId === m.taskId && review.bench === m.bench, "original_history_review_identity");
  need(JSON.stringify(review.cashClosePins) === JSON.stringify(c.cashClosePins) && JSON.stringify(review.attemptRunIds) === JSON.stringify(c.attempts.map((x) => x.runId)), "original_history_review_coverage");
  checkedPin(m, c.originalTaskCashConfigPin);
  const original = readPinned(c.originalTaskCashConfigPin);
  need(original.capUsd === m.original.taskCapUsd, "original_task_cap_config");
  let knownUsd = 0, unknownUsd = 0, calls = 0, resultPresent = false, submitPresent = false;
  const seen = new Set, actorCids = [], nativeRows = [], mainObservations = [];
  for (const a of c.attempts) {
    need(c.cashClosePins.some((p) => same4(p, a.cashClosePin)), "original_cash_coverage");
    checkedPin(m, a.cashClosePin);
    const cash = verifyBenchmarkCashClosure(a.cashClosePin), journal = inspectCampaignJournal(cash.proof.journalDirectory), s = cash.proof.snapshot;
    need(!seen.has(a.runId) && cash.config.runId === a.runId, "original_history_unique_actual_run");
    seen.add(a.runId);
    need(cash.config.capUsd <= m.original.taskCapUsd + 0.000000001 && journal.valid && journal.accountingClosed && s.pendingCount === 0 && s.pendingReservationUsd === 0, "original_history_cash_not_closed");
    knownUsd += s.billedUsd;
    unknownUsd += s.unknownReservationUsd;
    calls += journal.snapshot.acceptedRequestCount;
    checkedPin(m, a.summaryPin);
    const summary = readPinned(a.summaryPin);
    need(summary.runId === a.runId, "original_summary_run");
    if (summary.taskPins?.length)
      resultPresent = true;
    checkedPin(m, a.processPin);
    const process2 = readPinned(a.processPin);
    need(process2.runId === a.runId, "original_process_run");
    streams(m, a.standClosePin);
    for (const p of a.engineClosePins)
      streams(m, p);
    need(a.ownedLedgerPins.length > 0 && a.closureProofPins.length > 0, "original_native_custody_required");
    for (const p of [...a.ownedLedgerPins, ...a.closureProofPins])
      checkedPin(m, p);
    const custody = review.attemptClosures?.find((x) => x.runId === a.runId);
    need(custody && custody.brokerLaneClosed === true && custody.resourceReleased === true && custody.originalProcessesClosed === true && JSON.stringify(custody.proofPins) === JSON.stringify(a.closureProofPins), "original_custody_review_coverage");
    const ledger = a.ownedLedgerPins.find((p) => p.path.endsWith(".sqlite"));
    need(ledger, "original_native_ledger_required");
    for (const suffix of ["-wal", "-shm"])
      if (existsSync8(ledger.path + suffix))
        need(a.ownedLedgerPins.some((p) => resolve11(p.path) === resolve11(ledger.path + suffix)), "original_native_sidecar_unpinned");
    const db = new Database2(ledger.path, { readonly: true });
    let actors = 0, commands = 0;
    const runActorCids = [];
    try {
      for (const row of db.query("select cid,closed from actor").all()) {
        need(row.closed === 1 && /^[a-f0-9]{64}$/.test(row.cid), "original_actor_custody_open");
        actorCids.push(row.cid);
        runActorCids.push(row.cid);
        actors++;
      }
      for (const row of db.query("select json from command").all()) {
        const command = JSON.parse(row.json);
        need(command.closeObserved === true && Number.isInteger(command.exitCode) && !command.captureFaults?.length, "original_command_capture_open");
        commands++;
      }
    } finally {
      db.close();
    }
    nativeRows.push({ runId: a.runId, actors, commands, actorCids: runActorCids });
    for (const d of a.mainDatabases) {
      checkedPin(m, d.pin);
      for (const p of d.sidecarPins)
        checkedPin(m, p);
      for (const suffix of ["-wal", "-shm"])
        if (existsSync8(d.pin.path + suffix))
          need(d.sidecarPins.some((p) => resolve11(p.path) === resolve11(d.pin.path + suffix)), "original_main_db_sidecar_unpinned");
      const db2 = new Database2(d.pin.path, { readonly: true });
      try {
        const f = finalHandIn(db2, d.mainTaskId);
        need(f.task.run === a.runId, "original_main_run");
        resultPresent ||= f.resultPresent;
        submitPresent ||= f.submitPresent;
        mainObservations.push({ runId: a.runId, mainTaskId: d.mainTaskId, databasePin: d.pin, resultPresent: f.resultPresent, submitPresent: f.submitPresent, submits: f.submits });
      } finally {
        db2.close();
      }
    }
    for (const p of a.gradePins) {
      checkedPin(m, p);
      const grade = readPinned(p);
      need(grade.taskId === m.taskId, "original_grade_task_identity");
      if (grade.result)
        resultPresent = true;
    }
  }
  const preNative = inspectPreNativeHistory(m, { cashClosePins: c.cashClosePins }, seen);
  knownUsd += preNative.knownUsd;
  unknownUsd += preNative.unknownUsd;
  calls += preNative.calls;
  need(seen.size === c.cashClosePins.length && Math.abs(knownUsd - m.original.priorKnownUsd) < 0.000000001 && Math.abs(unknownUsd - m.original.priorUnknownUsd) < 0.000000001, "original_all_cash_exposure_preserved");
  need(c.canonicalLocks.length > 0, "real_historical_canonical_required");
  for (const l of c.canonicalLocks) {
    checkedPin(m, l.pin);
    checkedPin(m, l.entryPin);
    const lock = readPinned(l.pin), entry = readPinned(l.entryPin);
    need(lock.taskId === m.taskId && lock.bench === m.bench && lock.nonce === l.nonce && same4(lock.entryPin, l.entryPin), "real_canonical_nonce_entry_join");
    const e = entry.entry ?? entry;
    need(e.taskId === m.taskId && e.nonce === l.nonce, "historical_entry_identity");
  }
  need(JSON.stringify(review.canonicalLockPins) === JSON.stringify(c.canonicalLocks.map((x) => x.pin)), "review_canonical_coverage");
  for (const p of c.preservedSnapshotPins)
    checkedPin(m, p);
  let resolvedSubmits = 0, dispositionApproved = false;
  const resolutionProofPins = [];
  if (c.originalResultDispositionPin) {
    checkedPin(m, c.originalResultDispositionPin);
    const disposition = readPinned(c.originalResultDispositionPin);
    need(disposition.protocol === "bench-original-result-disposition-v1" && disposition.taskId === m.taskId && disposition.bench === m.bench, "original_disposition_identity");
    for (const resolution of disposition.resolutions ?? []) {
      checkedPin(m, resolution.proofPin);
      const proof = readPinned(resolution.proofPin);
      need(proof.protocol === "bench-original-result-recovery-readonly-review-v1" && proof.taskId === m.taskId && proof.bench === m.bench && proof.runId === resolution.runId, "original_disposition_proof_identity");
      need(proof.validResultRecoverableFromExistingGrade === false && proof.originalGrade?.standGradeRows === 0 && proof.originalGrade?.gradeJsonFiles?.length === 0 && proof.originalGrade?.taskResult === null && proof.originalCandidate?.existed === true && proof.originalCandidate?.ownedLedgerClosed === true && proof.originalCandidate?.filesystemSnapshotOrCapsulePresentInRun === false && proof.originalSubmit?.ran === false && proof.originalSubmit?.exactOriginalToolReason === "this station ended before the call was run", "original_disposition_not_unexecuted_destroyed_candidate");
      const observation = mainObservations.find((x) => x.runId === resolution.runId && x.mainTaskId === resolution.mainTaskId);
      need(observation && !observation.resultPresent, "original_disposition_main_identity");
      checkPin(proof.originalSubmit.extractPin);
      const extract = readPinned(proof.originalSubmit.extractPin), call = extract.assistantSubmit, tool = extract.matchingToolResponse;
      need(nativeRows.some((x) => x.runId === resolution.runId && x.actorCids.includes(proof.originalCandidate.cid)), "original_disposition_destroyed_candidate_identity");
      need(extract.task?.id === observation.mainTaskId && extract.task?.run === observation.runId && extract.databasePins?.some((p) => same4(p, observation.databasePin)), "original_submit_extract_database_join");
      const agent = observation.submits.find((s) => s.callId === proof.originalSubmit.callId)?.agent;
      need(typeof agent === "string" && /^[A-Za-z0-9_]+$/.test(agent), "original_disposition_agent_identity");
      const db = new Database2(observation.databasePin.path, { readonly: true });
      try {
        for (const row of [call, tool]) {
          const actual = db.query('select body,at,kind from "agent_' + agent + '_msg" where instance=? and unit=? and seq=?').get(row.instance, row.unit, row.seq);
          need(actual && actual.body === row.body && actual.at === row.at && actual.kind === row.kind, "original_submit_extract_actual_row_mismatch");
        }
      } finally {
        db.close();
      }
      const response = JSON.parse(tool.body);
      need(response.id === proof.originalSubmit.callId && response.name === "submit" && response.value?.ran === false && response.value?.why === proof.originalSubmit.exactOriginalToolReason, "original_submit_tool_not_unexecuted");
      const matches = observation.submits.filter((s) => s.callId === response.id && s.instance === call.instance && s.unit === call.unit && s.seq === call.seq && s.answerSha256 === proof.originalSubmit.answerSha256);
      need(matches.length === 1, "original_submit_resolution_not_exact");
      need(!resolutionProofPins.some((p) => same4(p, resolution.proofPin)), "duplicate_original_submit_resolution");
      resolutionProofPins.push(resolution.proofPin);
      resolvedSubmits++;
    }
    dispositionApproved = disposition.rootReviewed === true;
  }
  const submitCount = mainObservations.reduce((n, x) => n + x.submits.length, 0), unresolvedSubmitPresent = submitCount > 0 && (!dispositionApproved || resolvedSubmits !== submitCount);
  return {
    knownUsd,
    unknownUsd,
    calls,
    remainingUsd: m.original.taskCapUsd - knownUsd - unknownUsd,
    actorCids: [...new Set(actorCids)],
    nativeRows,
    mainObservations,
    resultPresent,
    submitPresent,
    unresolvedSubmitPresent,
    resolvedSubmits,
    dispositionApproved,
    resolutionProofPins,
    candidateOrSubmissionPresent: resultPresent || submitPresent,
    preservedIntermediateSnapshotCount: c.preservedSnapshotPins.length,
    canonicalIdentityPreserved: true,
    rootDispositionApproved: review.rootReviewed === true && review.resultDisposition === "closed-failure-no-final-handin"
  };
}
function inspectOriginalHistory(m, c) {
  const actual = auditOriginalHistory(m, c);
  need(!actual.resultPresent && !actual.unresolvedSubmitPresent, "original_result_requires_adapter_recovery");
  need(actual.rootDispositionApproved, "original_result_disposition_requires_root_review");
  return { ...actual, candidateOrSubmissionPresent: false, historicalSubmitPresent: actual.submitPresent, legacyIdentityPreserved: false };
}
var need = (x, message) => {
  if (!x)
    throw Error(message);
}, same4 = (a, b) => a?.path === b?.path && a?.sha256 === b?.sha256 && a?.bytes === b?.bytes;
var init_original_history = __esm(() => {
  init_runtime();
  init_digitalocean_usd_cash();
  init_digitalocean_journal();
  init_pre_native_history();
});

// scripts/bench-runner/campaign-stand-adapter.ts
var init_campaign_stand_adapter = __esm(() => {
  init_runtime();
});

// scripts/bench-runner/admission.ts
import { readFileSync as readFileSync12, writeFileSync as writeFileSync4, renameSync as renameSync3, existsSync as existsSync9, openSync as openSync9, closeSync as closeSync9, unlinkSync as unlinkSync2 } from "fs";
import { dirname as dirname4, resolve as resolve12 } from "path";
import { randomUUID } from "crypto";
function readAdmission(path) {
  demand(existsSync9(path), "admission_control_missing_closed");
  const x = JSON.parse(readFileSync12(path, "utf8"));
  demand(x.schemaVersion === 1 && ["newAdmissionsAllowed", "automaticRefillAllowed", "automaticRetryAllowed", "subsequentStageStartsAllowed"].every((k) => typeof x[k] === "boolean") && (x.revision === undefined || Number.isInteger(x.revision)), "invalid_admission_control");
  return { ...x, revision: x.revision ?? 0 };
}
function assertAdmission(path, key, stage, retry = false) {
  const x = readAdmission(path);
  demand(x.newAdmissionsAllowed && x.automaticRefillAllowed && x.subsequentStageStartsAllowed, "new_admission_closed");
  demand(!retry || x.automaticRetryAllowed, "retry_admission_closed");
  demand(!x.allowedTaskKeys || x.allowedTaskKeys.includes(key), "task_not_in_resume_scope");
  return x;
}
function assertContinuation(path, stage) {
  const x = readAdmission(path);
  const field = stage === "grade" ? "inFlightGradingAllowed" : stage === "cleanup" ? "inFlightCleanupAllowed" : null;
  demand(field ? x[field] === true : ["reconcile", "archive"].includes(stage), "inflight_continuation_not_allowed");
  return x;
}
function update(path, mutate) {
  const lock = path + ".universal-write-lock", fd = openSync9(lock, "wx");
  try {
    const old = readAdmission(path), p = pin(path), next = mutate(old);
    demand(next.brokerGlobalPauseForbidden === old.brokerGlobalPauseForbidden && ["inFlightRequestsAllowed", "inFlightToolsAllowed", "inFlightGradingAllowed", "inFlightCleanupAllowed"].every((k) => next[k] === old[k]), "intake_must_not_change_inflight_or_broker");
    verifyPin(p);
    const tmp = resolve12(dirname4(path), ".admission-" + randomUUID() + ".tmp");
    writeFileSync4(tmp, JSON.stringify(next, null, 2) + `
`, { flag: "wx" });
    verifyPin(p);
    renameSync3(tmp, path);
    return next;
  } finally {
    closeSync9(fd);
    unlinkSync2(lock);
  }
}
function drainAdmission(path) {
  return update(path, (x) => ({ ...x, phase: "draining", newAdmissionsAllowed: false, automaticRefillAllowed: false, automaticRetryAllowed: false, subsequentStageStartsAllowed: false, revision: x.revision + 1, updatedAtUtc: new Date().toISOString() }));
}
function resumeAdmission(path, approvalPath, unresolved) {
  const a = JSON.parse(readFileSync12(approvalPath, "utf8"));
  demand(a.protocol === "universal-runner-resume-approval-v1" && a.rootReviewed === true && a.allowNewAdmission === true && a.allowRetry === true && Array.isArray(a.allowedTaskKeys) && a.allowedTaskKeys.length > 0, "explicit_root_resume_approval_required");
  demand(unresolved === 0, "unresolved_attempts_prevent_resume");
  demand(a.evidencePins?.length > 0 && Date.parse(a.expiresAtUtc) > Date.now(), "fresh_resume_evidence_required");
  for (const p of a.evidencePins)
    verifyPin(p);
  const approvalPin = pin(approvalPath);
  return update(path, (x) => ({ ...x, phase: "running", newAdmissionsAllowed: true, automaticRefillAllowed: true, automaticRetryAllowed: true, subsequentStageStartsAllowed: true, allowedTaskKeys: a.allowedTaskKeys, resumeApprovalPin: approvalPin, revision: x.revision + 1, updatedAtUtc: new Date().toISOString() }));
}
var init_admission = __esm(() => {
  init_manifest();
});

// scripts/bench-runner/terminal-driver.ts
import { resolve as resolve13, join as join9, relative as relative4, isAbsolute as isAbsolute5 } from "path";
import { Database as Database3 } from "bun:sqlite";
function demand5(x, message) {
  if (!x)
    throw Error(message);
}
function codePath(m, path) {
  const rel = relative4(resolve13(m.root), resolve13(path));
  return !!rel && !rel.startsWith("..") && !isAbsolute5(rel);
}
function validateTerminalDriverData(m) {
  demand5(m.bench === "terminal-bench", "terminal_driver_bench");
  const d = m.adapterConfig.terminalDriver;
  demand5(d?.protocol === "bench-terminal-driver-v1", "terminal_driver_protocol");
  for (const key of ["campaign", "formalRunId", "formalExecuteOptions", "activated", "resource", "ownedGuard", "hostGuard", "acquireAdmission", "freshHistory", "historyContract", "provider", "inspectClosedCash"]) {
    const binding = d.imports?.[key];
    demand5(binding && /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(binding.export), "reviewed_import_export:" + key);
    checkPin(binding.pin);
    demand5(codePath(m, binding.pin.path) && m.provenance.sourcePins.some((p) => p.path === binding.pin.path && p.sha256 === binding.pin.sha256), "reviewed_import_source:" + key);
  }
  for (const pin2 of [d.activationPin, d.readinessPin, d.identityPin, d.closureReviewPin, d.aggregateBudgetPin, d.retainedAuditPin, d.assetProjectionPin])
    checkPin(pin2);
  demand5(d.resource?.slots === 1 && Number.isSafeInteger(d.resource.memoryMb) && d.resource.memoryMb >= m.original.memoryMb && Number.isSafeInteger(d.resource.growthBytes) && d.resource.growthBytes > 0, "original_aggregate_resource_data");
  demand5(/^[A-Z][A-Z0-9_]*$/.test(d.outputBinding), "output_binding_name");
  return d;
}
async function inspectLegacyActorAbsence(d, actorCids) {
  const activation = readPinned(d.activationPin), docker = activation.dockerHost?.replace(/^tcp:/, "http:");
  demand5(typeof docker === "string" && /^http:\/\/127\.0\.0\.1:\d+$/.test(docker), "reviewed_private_docker_endpoint");
  const evidence = [];
  for (const cid of actorCids) {
    const response = await fetch(docker + "/containers/" + cid + "/json", { signal: AbortSignal.timeout(5000) });
    demand5(response.status === 404, "legacy_actor_current_custody_not_closed");
    evidence.push({ cid, status: 404 });
  }
  return evidence;
}
function inspectLegacyHistory(m, d) {
  if (m.adapterConfig.originalHistory)
    return inspectOriginalHistory(m, m.adapterConfig.originalHistory);
  const identity = readPinned(d.identityPin), closure = readPinned(d.closureReviewPin), budget = readPinned(d.aggregateBudgetPin), retained = readPinned(d.retainedAuditPin);
  demand5(identity.taskId === m.taskId && identity.bench === m.bench && closure.taskId === m.taskId && budget.taskId === m.taskId, "legacy_task_identity");
  demand5(identity.originalCoordinatorNonce === null && identity.originalRootTaskLockPin === null, "honest_legacy_null_identity_required");
  demand5(!retained.tasks?.some((x) => (x.officialId ?? x.taskId) === m.taskId && x.valid === true) && !retained.validTaskIds?.includes(m.taskId), "valid_wrong_must_never_repeat");
  const retries = m.adapterConfig.retryHistory ?? [];
  demand5(Array.isArray(retries) && Array.isArray(identity.attempts) && identity.attempts.length > 0 && identity.attempts.length + retries.length + (m.adapterConfig.preNativeRecoveryHistory ?? []).length === budget.cashClosePins?.length, "complete_legacy_attempts");
  let known = 0, unknown = 0, calls = 0;
  const seen = new Set, actorCids = [];
  for (const attempt of identity.attempts) {
    const cash = verifyBenchmarkCashClosure(attempt.cashClosePin), journal = inspectCampaignJournal(cash.proof.journalDirectory);
    demand5(!seen.has(cash.config.runId) && cash.config.runId === attempt.runId, "unique_actual_legacy_cash_run");
    seen.add(cash.config.runId);
    demand5(budget.cashClosePins.some((p) => p.path === attempt.cashClosePin.path && p.sha256 === attempt.cashClosePin.sha256), "legacy_cash_not_omitted");
    demand5(journal.valid && journal.accountingClosed && cash.proof.snapshot.pendingCount === 0, "legacy_cash_pending");
    known += cash.proof.snapshot.billedUsd;
    unknown += cash.proof.snapshot.unknownReservationUsd;
    calls += journal.snapshot.acceptedRequestCount;
    const summary = readPinned(attempt.summaryPin);
    demand5(summary.fatal, "original_failed_summary_required");
    for (const p of [attempt.processPin, ...attempt.databasePins, ...attempt.ownedLedgerPins])
      checkPin(p);
    for (const p of [attempt.standClosePin, attempt.engineClosePin]) {
      const close = readPinned(p);
      demand5(close.exitObserved === true && close.closeObserved === true, "legacy_original_process_not_closed");
      for (const stream of [close.stdout, close.stderr])
        checkPin(stream);
    }
    const ledgerPin = attempt.ownedLedgerPins.find((p) => p.path.endsWith(".sqlite"));
    demand5(ledgerPin, "legacy_ledger_required");
    const db = new Database3(ledgerPin.path, { readonly: true });
    try {
      demand5(db.query("select count(*) as n from actor where closed<>1").get().n === 0, "legacy_actor_open");
      for (const a of db.query("select cid from actor").all()) {
        demand5(/^[a-f0-9]{64}$/.test(a.cid), "legacy_exact_actor_cid");
        actorCids.push(a.cid);
      }
      for (const row of db.query("select json from command").all()) {
        const c = JSON.parse(row.json);
        demand5(c.closeObserved === true && Number.isInteger(c.exitCode) && !c.captureFaults?.length, "legacy_native_command_unclosed");
      }
    } finally {
      db.close();
    }
    const reviewed = closure.attempts?.find((x) => x.runId === attempt.runId);
    demand5(reviewed?.closed === true && reviewed.noRecordedOriginalGrade === true && reviewed.allCommandsCloseObserved === true, "legacy_closure_attempt_missing");
    demand5(Array.isArray(summary.taskPins) && summary.taskPins.length === 0, "original_task_results_require_recovery");
    const mainDbPin = attempt.databasePins.find((p) => p.path.endsWith(".sqlite"));
    demand5(mainDbPin, "legacy_original_main_db_required");
    const mainDb = new Database3(mainDbPin.path, { readonly: true });
    try {
      const rows = mainDb.query("select id,result from task where source='user'").all();
      demand5(rows.length > 0 && rows.every((x) => x.result === null), "original_candidate_result_must_recover");
    } finally {
      mainDb.close();
    }
  }
  for (const retry of retries) {
    const proof = readPinned(retry.proofPin);
    demand5(proof.protocol === "bench-data-retry-derivation-v1" && proof.predecessorAttemptId === retry.attemptId && proof.predecessorRunId === retry.runId, "retry_history_identity");
    const evidence = readPinned(proof.evidencePin), native = readPinned(proof.nativeClosurePin);
    checkPin(proof.faultReceiptPin);
    demand5(evidence.protocol === "bench-retryable-closure-v1" && evidence.taskId === m.taskId && evidence.bench === m.bench && evidence.attemptId === retry.attemptId && evidence.runId === retry.runId, "retry_original_evidence_identity");
    demand5(evidence.cashClosePin.sha256 === proof.cashClosePin.sha256 && evidence.nativeClosurePin.sha256 === proof.nativeClosurePin.sha256 && evidence.faultReceiptPin.sha256 === proof.faultReceiptPin.sha256, "retry_original_evidence_join");
    demand5(native.taskId === m.taskId && native.runId === retry.runId && native.resourceReleased === true && native.brokerLaneClosed === true && (native.allNativeCommandStreamsClosed === true || native.allNativeCommandsClosed === true), "retry_actual_custody_not_closed");
    checkPin(native.ownedLedgerPin);
    for (const p of native.ownedLedgerPins ?? [])
      checkPin(p);
    const db = new Database3(native.ownedLedgerPin.path, { readonly: true });
    try {
      for (const a of db.query("select cid,closed from actor").all()) {
        demand5(a.closed === 1, "retry_actor_open");
        actorCids.push(a.cid);
      }
      for (const row of db.query("select json from command").all()) {
        const command = JSON.parse(row.json);
        demand5(command.closeObserved === true && Number.isInteger(command.exitCode) && !command.captureFaults?.length, "retry_command_unclosed");
      }
    } finally {
      db.close();
    }
    const cash = verifyBenchmarkCashClosure(proof.cashClosePin), journal = inspectCampaignJournal(cash.proof.journalDirectory);
    demand5(!seen.has(cash.config.runId) && cash.config.runId === retry.runId && budget.cashClosePins.some((p) => p.path === proof.cashClosePin.path && p.sha256 === proof.cashClosePin.sha256), "retry_cash_chain_identity");
    seen.add(cash.config.runId);
    demand5(journal.valid && journal.accountingClosed && cash.proof.snapshot.pendingCount === 0 && cash.config.capUsd <= m.original.taskCapUsd, "retry_cash_not_closed");
    known += cash.proof.snapshot.billedUsd;
    unknown += cash.proof.snapshot.unknownReservationUsd;
    calls += journal.snapshot.acceptedRequestCount;
  }
  const preNative = inspectPreNativeHistory(m, budget, seen);
  known += preNative.knownUsd;
  unknown += preNative.unknownUsd;
  calls += preNative.calls;
  demand5(typeof closure.originalResultRecoveryFinding === "string" && closure.originalResultRecoveryFinding.length > 0, "explicit_no_original_result_recovery_finding");
  demand5(Math.abs(known - m.original.priorKnownUsd) < 0.000000001 && Math.abs(unknown - m.original.priorUnknownUsd) < 0.000000001 && budget.originalTaskCapUsd === m.original.taskCapUsd && Math.abs(budget.knownUsd - known) < 0.000000001 && Math.abs(budget.unknownReservationUsd - unknown) < 0.000000001, "all_original_cost_unknown_preserved");
  return { knownUsd: known, unknownUsd: unknown, calls, remainingUsd: m.original.taskCapUsd - known - unknown, legacyIdentityPreserved: true, actorCids: [...new Set(actorCids)] };
}
var init_terminal_driver = __esm(async () => {
  init_original_history();
  init_pre_native_history();
  init_campaign_stand_adapter();
  init_campaign_stand_adapter();
  init_manifest();
  init_runtime();
  init_bindings();
  init_admission();
  init_digitalocean_usd_cash();
  init_digitalocean_journal();
  if (false) {}
});

// scripts/bench-runner/adapters/terminal-bench.ts
var terminalBenchAdapter;
var init_terminal_bench = __esm(async () => {
  await init_adapters();
  terminalBenchAdapter = {
    bench: "terminal-bench",
    validate: (m) => validateFor("terminal-bench", m),
    execute: (m, s, c) => executeFor("terminal-bench", m, s, c),
    recover: (m, c) => recoverFor("terminal-bench", m, c)
  };
});

// scripts/bench-runner/adapters/skillsbench.ts
var skillsbenchAdapter;
var init_skillsbench = __esm(async () => {
  await init_adapters();
  skillsbenchAdapter = {
    bench: "skillsbench",
    validate: (m) => validateFor("skillsbench", m),
    execute: (m, s, c) => executeFor("skillsbench", m, s, c),
    recover: (m, c) => recoverFor("skillsbench", m, c)
  };
});

// scripts/bench-runner/adapters/index.ts
import { existsSync as existsSync10, readFileSync as readFileSync13 } from "fs";
import { resolve as resolve14 } from "path";
import { createHash as createHash8 } from "crypto";
import { join as join10 } from "path";
import { Database as Database4 } from "bun:sqlite";
function requireTrue(value, message) {
  if (!value)
    throw Error(message);
}
function validateFor(bench, m) {
  requireTrue(m.bench === bench && m.schemaVersion === 1 && m.taskId.length > 0, "adapter_identity");
  const o = m.original;
  for (const n of [o.cpu, o.memoryMb, o.solveSeconds, o.gradeSeconds, o.toolSeconds, o.providerSeconds, o.taskCapUsd])
    requireTrue(Number.isFinite(n) && n > 0, "original_positive_contract");
  requireTrue(o.providerSeconds === 600 && o.priorKnownUsd >= 0 && o.priorUnknownUsd >= 0 && o.priorKnownUsd + o.priorUnknownUsd <= o.taskCapUsd, "original_cost_provider_contract");
  requireTrue(m.provenance.sourcePins.length && m.provenance.contractPins.length, "source_and_contract_required");
  for (const [stage, spec] of Object.entries(m.stages)) {
    if (!spec)
      continue;
    requireTrue(spec.kind === "reuse" || spec.kind === "command", "stage_kind");
    requireTrue(spec.timeoutSeconds > 0, "stage_deadline");
    if (stage === "solve")
      requireTrue(spec.timeoutSeconds <= o.solveSeconds, "solve_timeout_expansion");
    if (stage === "grade")
      requireTrue(spec.timeoutSeconds <= o.gradeSeconds, "grade_timeout_expansion");
    if (spec.bundledStages?.length) {
      requireTrue(new Set(spec.bundledStages).size === spec.bundledStages.length && spec.bundledStages.includes(stage), "bundled_stage_identity");
      requireTrue(Number.isFinite(spec.outerTimeoutSeconds) && spec.outerTimeoutSeconds >= spec.timeoutSeconds, "explicit_bundled_custody_deadline");
    } else
      requireTrue(spec.outerTimeoutSeconds === undefined, "outer_deadline_requires_bundle");
    if (spec.effect === "oracle" && spec.kind === "command") {
      requireTrue(m.history.stateKnown && !!spec.originalSuccessKey, "oracle_requires_known_checkpoint_identity");
      const checkpoints = m.adapterConfig.successfulCheckpoints;
      requireTrue(!checkpoints?.[spec.originalSuccessKey], "successful_reference_is_reuse_only");
    }
    if (spec.kind === "reuse")
      requireTrue(spec.evidencePins.length > 0 && !!spec.successEvidence, "reuse_requires_pinned_success_predicates");
    if (spec.kind === "command" && spec.effect !== "read-only")
      requireTrue(spec.resourceMode === "driver-owned", "original_driver_owned_resource_required");
  }
}
function at(value, path) {
  return path.split(".").reduce((x, k) => x?.[k], value);
}
function predicates(value, equals) {
  return Object.entries(equals).every(([key, v]) => JSON.stringify(at(value, key)) === JSON.stringify(v));
}
function nativeClosed(pin2, taskId, runId) {
  const p = readPinned(pin2);
  requireTrue((!p.taskId || !taskId || p.taskId === taskId) && (!p.runId || !runId || p.runId === runId), "native_closure_task_run_identity");
  const closed = p.allExactOwnedActorsAbsent === true || p.allActorsClosed === true || p.resourceReleased === true && p.brokerLaneClosed === true && Array.isArray(p.exactOwnedContainerApi404) && p.exactOwnedContainerApi404.length > 0 && p.exactOwnedContainerApi404.every((x) => x.status === 404);
  const rootRetained = p.rootReviewed === true && Number.isSafeInteger(p.nativeActorsClosed) && p.nativeActorsClosed >= 0 && p.workerAbsent === true && p.originalEngineExitCloseObserved === true && p.laneClosed === true && p.resourceReleased === true && p.rootDerivedCleanupPin && p.originalGradeAuditPin;
  if (rootRetained) {
    const cleanup = readPinned(p.rootDerivedCleanupPin), audit = readPinned(p.originalGradeAuditPin);
    requireTrue(cleanup.taskId === p.taskId && cleanup.runId === p.runId && cleanup.laneClosed === true && cleanup.resourceReleased === true && cleanup.exactProcessHandleTerminated === true, "root_exact_custody_cleanup");
    requireTrue(audit.taskId === p.taskId && audit.runId === p.runId && audit.nativeActorsClosed === true && audit.nativeCommandsAllCloseObserved === true && audit.currentActorApi404?.length === p.nativeActorsClosed && audit.currentActorApi404.every((x) => x.status === 404), "root_original_actor_command_audit");
    checkPin(cleanup.originalEngineClosePin);
  }
  requireTrue(rootRetained || closed && (p.allNativeCommandsClosed === true || p.allNativeCommandStreamsClosed === true || p.nativeClosed === true), "native_closure_not_proven");
  return true;
}
function linkedPins(value, seen = new Set, depth = 0) {
  requireTrue(depth <= 12 && seen.size <= 2048, "bounded_grade_receipt_links");
  if (!value || typeof value !== "object")
    return;
  if (typeof value.path === "string" && Number.isSafeInteger(value.bytes) && typeof value.sha256 === "string") {
    const key = value.path + "|" + value.sha256;
    if (seen.has(key))
      return;
    seen.add(key);
    checkPin(value);
    if (value.path.endsWith(".json") && value.bytes <= 4 * 1024 ** 2)
      linkedPins(readPinned(value), seen, depth + 1);
    return;
  }
  for (const item of Object.values(value))
    linkedPins(item, seen, depth + 1);
}
function financeClosed(pin2, runId, cap) {
  const cash = verifyBenchmarkCashClosure(pin2), journal = inspectCampaignJournal(cash.proof.journalDirectory);
  requireTrue(journal.valid && journal.accountingClosed && cash.proof.snapshot.pendingCount === 0, "original_cash_journal_not_closed");
  requireTrue((!runId || cash.config.runId === runId) && (cap === undefined || cash.config.capUsd <= cap), "original_cash_run_cap_identity");
  return true;
}
async function mappedNative(m, c, mapping) {
  const names = ["standClosePath", "engineClosePath", "ownedLedgerPath"];
  for (const name of names)
    requireTrue(typeof mapping?.[name] === "string", "native_mapping_" + name);
  const stand = filePin(expand(mapping.standClosePath, c)), engine = filePin(expand(mapping.engineClosePath, c)), ledger = filePin(expand(mapping.ownedLedgerPath, c));
  for (const p of [stand, engine]) {
    const close = readPinned(p);
    requireTrue(close.exitObserved === true && close.closeObserved === true && Number.isSafeInteger(close.pid), "original_process_close_receipt");
    for (const stream of [close.stdout, close.stderr])
      checkPin(stream);
  }
  const db = new Database4(ledger.path, { readonly: true });
  let actors, commands;
  try {
    actors = db.query("select cid,closed from actor").all();
    commands = db.query("select json from command").all();
  } finally {
    db.close();
  }
  requireTrue(actors.every((x) => x.closed === 1), "original_owned_actor_open");
  for (const row of commands) {
    const command = JSON.parse(row.json);
    requireTrue(command.closeObserved === true && Number.isInteger(command.exitCode) && !command.captureFaults?.length, "original_native_command_unclosed");
  }
  requireTrue(typeof mapping.dockerEndpoint === "string" && /^http:\/\/127\.0\.0\.1:\d+$/.test(mapping.dockerEndpoint), "reviewed_private_docker_endpoint");
  const absent = [];
  for (const actor of actors) {
    requireTrue(/^[a-f0-9]{64}$/.test(actor.cid), "original_exact_actor_cid");
    const response = await fetch(mapping.dockerEndpoint + "/containers/" + actor.cid + "/json", { signal: AbortSignal.timeout(5000) });
    requireTrue(response.status === 404, "original_actor_custody_pending");
    absent.push({ cid: actor.cid, status: 404 });
  }
  requireTrue(typeof mapping.brokerHealthUrl === "string" && typeof mapping.resourceOwnerProcessPath === "string", "native_resource_owner_mapping_required");
  const ownerPin = filePin(expand(mapping.resourceOwnerProcessPath, c)), owner = readPinned(ownerPin);
  requireTrue(Number.isSafeInteger(owner.pid) && typeof owner.incarnation === "string", "exact_original_resource_owner");
  const brokerResponse = await fetch(mapping.brokerHealthUrl, { signal: AbortSignal.timeout(3000) });
  requireTrue(brokerResponse.ok, "native_broker_health_unavailable");
  const broker = await brokerResponse.json();
  requireTrue(broker.healthy === true && !broker.resourceSlots?.some((x) => x.pid === owner.pid && x.ownerIncarnation === owner.incarnation), "original_resource_still_held");
  const path = join10(c.runDir, "derived-native-closure.json");
  const value = {
    protocol: "bench-derived-original-native-closure-v1",
    artifactOrigin: "derived-from-original-receipts",
    taskId: m.taskId,
    standClosePin: stand,
    engineClosePin: engine,
    ownedLedgerPin: ledger,
    allActorsClosed: true,
    allNativeCommandsClosed: true,
    exactOwnedContainerApi404: absent,
    originalCommands: commands.length,
    resourceOwnerProcessPin: ownerPin,
    resourceReleased: true
  };
  if (!existsSync10(path))
    wxJson(path, value);
  else
    requireTrue(JSON.stringify(JSON.parse(readFileSync13(path, "utf8"))) === JSON.stringify(value), "derived_native_changed");
  return filePin(path);
}
async function originalRecords(m, c) {
  const records = Array.isArray(m.adapterConfig.originalResults) ? [...m.adapterConfig.originalResults] : [];
  const paths = m.adapterConfig.originalResultsPaths;
  if (c.attemptId !== "original-recovery" && Array.isArray(paths))
    for (const r of paths) {
      const record = {};
      for (const [field, name] of Object.entries({ taskPin: "taskPath", summaryPin: "summaryPath", financialClosurePin: "financialClosurePath", nativeClosurePin: "nativeClosurePath", gradePin: "gradePath", standReceiptsPin: "standReceiptPath" })) {
        if (r[name])
          record[field] = filePin(expand(r[name], c));
      }
      if (!record.nativeClosurePin && r.nativeMapping)
        record.nativeClosurePin = await mappedNative(m, c, r.nativeMapping);
      record.candidateSha256 = r.candidateSha256;
      record.output = r.output ? expand(r.output, c) : undefined;
      records.push(record);
    }
  return records;
}
async function recoverFor(bench, m, c) {
  validateFor(bench, m);
  assertContext(m, c);
  if (bench === "terminal-bench" && c.attemptId === "original-recovery" && m.adapterConfig.terminalDriver && m.history.validResultPins.length === 0)
    try {
      const data = validateTerminalDriverData(m), history = inspectLegacyHistory(m, data), actors = await inspectLegacyActorAbsence(data, history.actorCids);
      const path = join10(c.runDir, "original-legacy-recovery.json");
      wxJson(path, {
        protocol: "bench-actual-legacy-original-recovery-v1",
        taskId: m.taskId,
        bench,
        manifestPin: c.manifestPin,
        identityPin: data.identityPin,
        closureReviewPin: data.closureReviewPin,
        aggregateBudgetPin: data.aggregateBudgetPin,
        history,
        actualActorApi404: actors,
        noOriginalCandidateOrGrade: true,
        originalNullIdentityPreserved: true,
        newModelGradeNativeMutations: 0
      });
      return { status: "retryable", proofPins: [filePin(path), data.identityPin, data.closureReviewPin, data.aggregateBudgetPin], nativeClosed: true, financialClosed: true, candidateOrSubmissionPresent: false, reason: "strict_original_legacy_cash_native_no_result_reconciled" };
    } catch (error) {
      return unknown("original_legacy_reconciliation_failed:" + String(error));
    }
  if (c.attemptId !== "original-recovery" && m.adapterConfig.bindingSpec && !c.bindings)
    try {
      c = loadPreparedContext(m, c, true);
    } catch (error) {
      return unknown("original_binding_custody_pending:" + String(error));
    }
  let records;
  try {
    records = await originalRecords(m, c);
  } catch (error) {
    return unknown("original_artifact_mapping_pending:" + String(error));
  }
  if ((!Array.isArray(records) || records.length === 0) && !m.adapterConfig.closedFailure)
    return unknown("original_result_mapping_required");
  const failures = [];
  for (const r of records) {
    try {
      const task = readPinned(r.taskPin), summary = readPinned(r.summaryPin);
      requireTrue((bench === "terminal-bench" ? task.officialId ?? task.taskId : task.taskId) === m.taskId && (summary.runId === task.runId || summary.output === r.output), "original_run_identity");
      const acceptance = bench === "skillsbench" ? task.officialAcceptance : task.acceptance;
      const generationValid = bench === "skillsbench" ? task.generation?.valid : task.generationValid;
      requireTrue(generationValid === true && acceptance?.valid === true && (bench !== "skillsbench" || task.protocolValid === true), "original_generation_and_acceptance_required");
      const budget = acceptance.outcome === "budget_exhausted" || task.outcome === "budget_exhausted" || task.generation?.outcome === "budget_exhausted";
      let gradePin = acceptance.gradeOwnerPin ?? r.gradePin;
      const proofs = [r.taskPin, r.summaryPin, r.financialClosurePin, r.nativeClosurePin];
      if (!budget) {
        const text = bench === "terminal-bench" ? task.answer : task.candidate;
        const candidate = typeof text === "string" ? createHash8("sha256").update(text).digest("hex") : task.candidateSha256 ?? task.candidate?.sha256;
        requireTrue(typeof candidate === "string" && (!r.candidateSha256 || candidate === r.candidateSha256), "original_candidate_content_binding");
        if (bench === "terminal-bench") {
          requireTrue(candidate === task.candidateLabelSha256 && candidate === acceptance.candidateSha256, "original_tb_answer_acceptance_binding");
          requireTrue(r.standReceiptsPin, "original_tb_stand_receipts_required");
          const stand = readPinned(r.standReceiptsPin);
          const rows = stand.rows?.filter((x) => ["grade", "snapshot-grade"].includes(x.kind) && x.taskId === m.taskId && x.place === task.place && x.attemptId === task.taskId && x.labelSha256 === candidate && x.protectedInputsUnchanged === true);
          requireTrue(rows?.length > 0, "original_tb_grade_row_missing");
          const row = rows[rows.length - 1];
          gradePin = filePin(row.gradePath);
          requireTrue(gradePin.sha256 === row.gradeSha256, "original_tb_grade_row_hash");
          const grade = readPinned(gradePin), result = grade.result, ctrf = result?.ctrf?.results;
          requireTrue(grade.protocol === "tb12-snapshot-grade-v1" && grade.taskId === m.taskId && grade.candidateCid === task.candidateCid && grade.invocationId === row.invocationId && result?.invocationId === row.invocationId, "original_tb_candidate_invocation_identity");
          requireTrue(result.collectOnly === false && [0, 1].includes(result.exitCode) && [0, 1].includes(result.reward) && result.reward === row.originalReward && result.reward === 1 === acceptance.passed, "original_tb_grader_reward");
          requireTrue(ctrf?.summary?.tests > 0 && Array.isArray(ctrf.tests) && ctrf.tests.length === ctrf.summary.tests && ctrf.summary.pending === 0 && ctrf.summary.other === 0, "original_tb_collection_complete");
          requireTrue(grade.removal?.exitCode === 0 && grade.removal.closeObserved === true && grade.absence?.exitCode === 1 && grade.absence.closeObserved === true, "original_tb_checker_closed");
          proofs.push(r.standReceiptsPin);
        } else {
          requireTrue(gradePin, "same_candidate_original_grade_required");
          const grade = readPinned(gradePin), result = grade.result ?? grade;
          requireTrue(result.complete === true && grade.candidateAnswerSha256 === candidate, "original_sb_grade_complete_candidate");
          requireTrue(!result.taskId || result.taskId === m.taskId, "original_sb_grade_task_identity");
          for (const p of [result.ownerReceiptPin, result.ownerClosurePin, grade.builtImagesPin, grade.controlPin])
            if (p) {
              linkedPins(p);
              proofs.push(p);
            }
          requireTrue(task.toolQuiescence?.sealed === true && task.toolQuiescence?.outstanding === 0 && task.solverClosure?.ok === true && task.solverClosure?.ownedContainersRemaining === 0, "original_sb_quiescence_native_closure");
        }
        proofs.push(gradePin);
      }
      financeClosed(r.financialClosurePin, task.runId ?? summary.runId, m.original.taskCapUsd);
      nativeClosed(r.nativeClosurePin, m.taskId, task.runId ?? summary.runId);
      return {
        status: "valid",
        proofPins: proofs,
        nativeClosed: true,
        financialClosed: true,
        candidateOrSubmissionPresent: !budget,
        validResult: { passed: acceptance.passed === true, outcome: budget ? "budget_exhausted" : acceptance.passed ? "passed" : "wrong", proofPin: r.taskPin }
      };
    } catch (error) {
      failures.push(String(error));
    }
  }
  const failure = m.adapterConfig.closedFailure;
  if (failure && c.attemptId === "original-recovery")
    try {
      const p = readPinned(failure.proofPin);
      requireTrue(p.taskId === m.taskId && p.noOriginalGradeToRecover === true && p.candidateOrSubmissionPresent === false, "no_candidate_recovery_required");
      requireTrue(p.valid === false && p.rootReviewed === true, "reviewed_failed_original_required");
      financeClosed(failure.financialClosurePin, p.runId, m.original.taskCapUsd);
      nativeClosed(failure.nativeClosurePin);
      return { status: "retryable", proofPins: [failure.proofPin, failure.financialClosurePin, failure.nativeClosurePin], nativeClosed: true, financialClosed: true, candidateOrSubmissionPresent: false, reason: "original_failed_attempt_explicitly_closed_new_attempt_only" };
    } catch (error) {
      failures.push(String(error));
    }
  return unknown("original_result_unverified:" + failures.join(";"), records.map((r) => r.taskPin).filter(Boolean));
}
async function executeFor(bench, m, spec, c) {
  validateFor(bench, m);
  assertContext(m, c);
  if (m.history.validResultPins.length)
    return recoverFor(bench, m, c);
  if (m.history.originalResultRecoveryRequired || c.inventoryTask.state === "recoverable") {
    if (!c.originalRecoveryProofPin)
      return recoverFor(bench, m, c);
    const proof = readPinned(c.originalRecoveryProofPin), r = proof.result;
    requireTrue(proof.taskId === m.taskId && proof.bench === bench && JSON.stringify(proof.manifestPin) === JSON.stringify(c.manifestPin), "original_recovery_identity");
    requireTrue(["retryable", "complete"].includes(r?.status) && r.nativeClosed === true && r.financialClosed === true && r.candidateOrSubmissionPresent === false && !r.validResult, "original_recovery_closed_no_candidate");
    requireTrue(Array.isArray(r.proofPins) && r.proofPins.length > 0, "original_recovery_proofs_required");
    for (const p of r.proofPins)
      checkPin(p);
  }
  for (const pin2 of spec.evidencePins)
    checkPin(pin2);
  if (spec.kind === "reuse") {
    const path2 = resolve14(expand(spec.successEvidence.path, c));
    requireTrue(spec.evidencePins.some((p) => resolve14(p.path) === path2), "reuse_success_file_not_pinned");
    const value = JSON.parse(readFileSync13(path2, "utf8").replace(/^\uFEFF/, ""));
    requireTrue(predicates(value, spec.successEvidence.equals), "reuse_success_predicate_failed");
    return { status: "complete", proofPins: spec.evidencePins, nativeClosed: false, financialClosed: false, candidateOrSubmissionPresent: false, reason: "verified_prior_stage_reused_no_execution" };
  }
  if (m.adapterConfig.bindingSpec)
    c = loadPreparedContext(m, c);
  const contract = m.adapterConfig.driverContract;
  requireTrue(contract?.ownedLease === true && contract?.beforeJournal === true && contract?.beforeForward === true && contract?.originalBudget === true, "qualified_deep_driver_contract_required");
  requireTrue(contract.pin && m.provenance.contractPins.some((p) => p.sha256 === contract.pin.sha256 && resolve14(p.path) === resolve14(contract.pin.path)), "driver_contract_pin_required");
  checkPin(contract.pin);
  const receipt = await executeCommand(m, { ...spec, timeoutSeconds: spec.outerTimeoutSeconds ?? spec.timeoutSeconds }, c);
  const custody = [receipt.processPin, receipt.stdoutPin, receipt.stderrPin];
  if (!receipt.closeObserved || receipt.timedOut)
    return unknown("driver_custody_unresolved_no_retry", custody);
  if (Array.isArray(m.adapterConfig.originalResultsPaths)) {
    const recovered = await recoverFor(bench, m, c);
    if (recovered.status === "valid") {
      const completedStages = {};
      for (const stage of spec.bundledStages ?? [c.stage])
        if (["solve", "grade", "cleanup", "reconcile"].includes(stage))
          completedStages[stage] = { proofPins: recovered.proofPins };
      return { ...recovered, proofPins: [...custody, ...recovered.proofPins], completedStages };
    }
    return { ...recovered, proofPins: [...custody, ...recovered.proofPins] };
  }
  const config = m.adapterConfig.driverResult;
  if (!config?.path || config.protocol !== "bench-driver-result-v1")
    return unknown("driver_result_protocol_mapping_required", custody);
  const path = expand(config.path, c);
  if (!existsSync10(path))
    return unknown("driver_result_missing", custody);
  const envelope = JSON.parse(readFileSync13(path, "utf8").replace(/^\uFEFF/, ""));
  requireTrue(envelope.protocol === config.protocol && envelope.taskId === c.taskId && envelope.bench === bench && envelope.attemptId === c.attemptId && envelope.stage === c.stage, "driver_result_identity");
  const result = envelope.result;
  requireTrue(["complete", "retryable", "invalid", "unknown", "valid"].includes(result?.status) && Array.isArray(result.proofPins), "driver_result_shape");
  for (const pin2 of result.proofPins)
    checkPin(pin2);
  if (receipt.exitCode !== 0 && result.status !== "valid")
    return unknown("driver_nonzero_exit_not_success", [filePin(path), ...custody, ...result.proofPins]);
  if (result.status === "valid" || result.validResult || result.nativeClosed || result.financialClosed || result.status === "retryable") {
    const recovery = await recoverFor(bench, m, c);
    return recovery.status === "valid" ? recovery : unknown("driver_closure_requires_original_artifact_mapping", [filePin(path), ...custody, ...result.proofPins]);
  }
  let actualSolver;
  if (envelope.actualSolverEvidencePin)
    actualSolver = await inspectActualSolver(envelope.actualSolverEvidencePin);
  return { ...result, proofPins: [filePin(path), ...custody, ...result.proofPins], actualSolver, nativeClosed: false, financialClosed: false };
}
function getAdapter(bench) {
  if (bench === "terminal-bench")
    return terminalBenchAdapter;
  if (bench === "skillsbench")
    return skillsbenchAdapter;
  throw Error("unknown_bench");
}
var unknown = (reason, proofPins = []) => ({ status: "unknown", proofPins, nativeClosed: false, financialClosed: false, candidateOrSubmissionPresent: false, reason });
var init_adapters = __esm(async () => {
  init_runtime();
  init_bindings();
  init_digitalocean_usd_cash();
  init_digitalocean_journal();
  await __promiseAll([
    init_terminal_driver(),
    init_terminal_bench(),
    init_skillsbench()
  ]);
});

// scripts/bench-runner/runtime-stage-custody.ts
import { readFileSync as readFileSync14, writeFileSync as writeFileSync5, mkdirSync as mkdirSync6, openSync as openSync10, closeSync as closeSync10, existsSync as existsSync11, readdirSync as readdirSync5 } from "fs";
import { createHash as createHash9 } from "crypto";
import { resolve as resolve15, join as join11, dirname as dirname5 } from "path";
import { spawn as spawn2 } from "child_process";
import { dlopen as dlopen2, FFIType as FFIType2, ptr as ptr2, toArrayBuffer as toArrayBuffer2 } from "bun:ffi";
function filePin2(path) {
  return pin(path);
}
function checkPin2(pin2) {
  verifyPin(pin2);
}
function readPinned2(pin2) {
  checkPin2(pin2);
  return JSON.parse(readFileSync14(pin2.path, "utf8").replace(/^\uFEFF/, ""));
}
function wxJson2(path, value) {
  mkdirSync6(dirname5(path), { recursive: true });
  writeFileSync5(path, JSON.stringify(value, null, 2) + `
`, { flag: "wx", mode: 384 });
}
function claimTaskAttemptLocks2(m, c, argv) {
  const policy = m.adapterConfig.taskLocks;
  if (!policy?.lockRoot || !Array.isArray(policy.historicalLockPins) || !Array.isArray(policy.historicalClosureProofPins))
    throw Error("reviewed_global_lock_policy_required");
  if (!c.bindings?.ENTRY_ENVELOPE)
    throw Error("signed_context_required_before_lock");
  const signed = JSON.parse(readFileSync14(c.bindings.ENTRY_ENVELOPE, "utf8"));
  if (JSON.stringify(signed.entry?.argv) !== JSON.stringify(argv))
    throw Error("actual_command_differs_from_root_signed_argv");
  for (const p of [...policy.historicalLockPins, ...policy.historicalClosureProofPins])
    checkPin2(p);
  const hash4 = createHash9("sha256").update(m.bench + ":" + m.taskId).digest("hex"), root = resolve15(policy.lockRoot);
  mkdirSync6(root, { recursive: true });
  const canonical = join11(root, hash4 + ".json"), attempt = join11(root, hash4 + "." + c.attemptId + ".json");
  if (Buffer.byteLength(hash4 + "." + c.attemptId + ".json") > 240)
    throw Error("short_attempt_lock_required");
  const reviewed = new Map(policy.historicalLockPins.map((p) => [resolve15(p.path), p]));
  for (const name of readdirSync5(root).filter((n) => n === hash4 + ".json" || n.startsWith(hash4 + ".") && n.endsWith(".json"))) {
    const path2 = join11(root, name), p = reviewed.get(path2);
    if (!p)
      throw Error("unreviewed_existing_task_lock_custody_unknown");
    checkPin2(p);
  }
  if (existsSync11(canonical)) {
    if (policy.historicalClosureProofPins.length === 0 || !c.originalRecoveryProofPin)
      throw Error("existing_canonical_requires_closed_original_recovery");
    checkPin2(c.originalRecoveryProofPin);
  } else if (policy.legacyOriginalIdentityNull !== true || policy.historicalLockPins.length !== 0)
    throw Error("new_canonical_requires_honest_legacy_null_identity");
  const receipt = {
    protocol: "bench-permanent-task-attempt-lock-v1",
    taskId: m.taskId,
    bench: m.bench,
    attemptId: c.attemptId,
    manifestPin: c.manifestPin,
    signedEntryPin: filePin2(c.bindings.ENTRY_ENVELOPE),
    argv,
    sourcePins: m.provenance.sourcePins,
    historicalNonce: policy.legacyOriginalIdentityNull ? null : policy.historicalNonce,
    historicalLockPins: policy.historicalLockPins,
    historicalClosureProofPins: policy.historicalClosureProofPins,
    originalRecoveryProofPin: c.originalRecoveryProofPin ?? null
  };
  wxJson2(attempt, receipt);
  if (!existsSync11(canonical))
    wxJson2(canonical, { ...receipt, protocol: "bench-first-truthful-canonical-lock-v1", firstAttemptLockPin: filePin2(attempt) });
  const path = join11(c.runDir, "locks-receipt.json");
  wxJson2(path, { canonicalPin: filePin2(canonical), attemptLockPin: filePin2(attempt), historicalLocksPreserved: true });
  return filePin2(path);
}
function expand2(value, context) {
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
function assertContext2(manifest, context) {
  if (context.taskId !== manifest.taskId || context.bench !== manifest.bench)
    throw Error("context_identity_mismatch");
  checkPin2(context.manifestPin);
  const frozen = JSON.parse(readFileSync14(context.manifestPin.path, "utf8").replace(/^\uFEFF/, ""));
  if (JSON.stringify(frozen) !== JSON.stringify(manifest))
    throw Error("context_manifest_object_changed");
  for (const pin2 of [...manifest.provenance.sourcePins, ...manifest.provenance.contractPins, manifest.provenance.inventoryPin])
    checkPin2(pin2);
  if (manifest.provenance.authorizationPin)
    checkPin2(manifest.provenance.authorizationPin);
  if (!manifest.history.stateKnown)
    throw Error("unknown_history_quarantined");
}
function processIdentity2(pid) {
  if (process.platform === "win32") {
    const api = dlopen2("kernel32.dll", {
      OpenProcess: { args: [FFIType2.u32, FFIType2.i32, FFIType2.u32], returns: FFIType2.u64 },
      GetProcessTimes: { args: [FFIType2.u64, FFIType2.ptr, FFIType2.ptr, FFIType2.ptr, FFIType2.ptr], returns: FFIType2.i32 },
      CloseHandle: { args: [FFIType2.u64], returns: FFIType2.i32 }
    });
    const handle = api.symbols.OpenProcess(4096, 0, pid);
    try {
      if (!handle)
        throw Error("process_incarnation_unavailable");
      const buffers = [0, 1, 2, 3].map(() => new Uint8Array(8));
      if (!api.symbols.GetProcessTimes(handle, ...buffers.map(ptr2)))
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
    const stat = readFileSync14("/proc/" + pid + "/stat", "utf8");
    const start = stat.slice(stat.lastIndexOf(")") + 2).split(" ")[19];
    const boot = readFileSync14("/proc/sys/kernel/random/boot_id", "utf8").trim();
    return { incarnation: boot + ":" + start, creation: start, kind: "linux-boot-id-start-ticks" };
  }
  throw Error("unsupported_exact_process_identity");
}
async function executeCommand2(manifest, spec, context) {
  assertContext2(manifest, context);
  if (spec.effect === "model" && context.stage !== "solve")
    throw Error("model_command_only_solve");
  if (!Array.isArray(spec.command) || !spec.command.length || spec.command.some((x) => typeof x !== "string" || x.includes("\x00")))
    throw Error("command_array_required");
  if (!(spec.timeoutSeconds > 0) || !Number.isFinite(spec.timeoutSeconds))
    throw Error("bounded_stage_required");
  const argv = spec.command.map((x) => expand2(x, context));
  const sources = manifest.provenance.sourcePins;
  const executable = resolve15(argv[0]);
  if (!sources.some((p) => resolve15(p.path) === executable))
    throw Error("executable_source_pin_required");
  mkdirSync6(context.runDir, { recursive: true });
  if (usesStageOperation(context, spec))
    claimStageOperationLocks(manifest, spec, context, argv);
  else if (spec.effect !== "read-only")
    claimTaskAttemptLocks2(manifest, context, argv);
  const intent = join11(context.runDir, "command-intent.json"), processPath = join11(context.runDir, "process.json");
  wxJson2(intent, {
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
  const stdout = join11(context.runDir, "stdout.log"), stderr = join11(context.runDir, "stderr.log");
  const out = openSync10(stdout, "wx", 384), err = openSync10(stderr, "wx", 384);
  let child;
  try {
    child = spawn2(argv[0], argv.slice(1), {
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
    closeSync10(out);
    closeSync10(err);
  }
  let identity;
  try {
    if (child.pid)
      identity = processIdentity2(child.pid);
  } catch {}
  wxJson2(processPath, {
    protocol: "bench-process-custody-v1",
    pid: child.pid ?? null,
    parentPid: process.pid,
    argv,
    creationObservedAtUtc: new Date().toISOString(),
    creation: identity?.creation ?? null,
    incarnation: identity?.incarnation ?? null,
    incarnationKind: identity?.kind ?? null,
    incarnationStatus: identity ? "exact-os-observed" : "requires-driver-or-os-reconciliation",
    sourcePin: sources.find((p) => resolve15(p.path) === executable),
    manifestPin: context.manifestPin,
    intentPin: filePin2(intent),
    attemptId: context.attemptId,
    stage: context.stage
  });
  return await new Promise((ok, bad) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled)
        return;
      settled = true;
      wxJson2(join11(context.runDir, "timeout.json"), {
        pid: child.pid,
        timeoutSeconds: spec.timeoutSeconds,
        closeObserved: false,
        custody: "unknown",
        processNotKilled: true,
        atUtc: new Date().toISOString()
      });
      ok({ exitCode: null, signal: null, timedOut: true, closeObserved: false, processPin: filePin2(processPath), stdoutPin: filePin2(stdout), stderrPin: filePin2(stderr) });
    }, spec.timeoutSeconds * 1000);
    child.once("error", (error) => {
      if (settled)
        return;
      settled = true;
      clearTimeout(timer);
      wxJson2(join11(context.runDir, "spawn-error.json"), { error: String(error), pid: child.pid ?? null, custody: "unknown" });
      bad(error);
    });
    child.once("close", (code, signal) => {
      wxJson2(join11(context.runDir, "exit.json"), { pid: child.pid, code, signal, closeObserved: true, atUtc: new Date().toISOString() });
      if (settled)
        return;
      settled = true;
      clearTimeout(timer);
      ok({ exitCode: code, signal, timedOut: false, closeObserved: true, processPin: filePin2(processPath), stdoutPin: filePin2(stdout), stderrPin: filePin2(stderr) });
    });
  });
}
var init_runtime_stage_custody = __esm(() => {
  init_stage_custody();
  init_manifest();
});

// scripts/bench-runner/native-owner-observation.ts
function verifyNativeOwnerChain(root, owner, snapshot, expectedOwnerArgv) {
  demand(snapshot.protocol === "bench-process-subtrees-readonly-v1" && snapshot.errors.length === 0 && snapshot.roots.includes(root.pid), "native_owner_os_snapshot_required");
  const rows = new Map(snapshot.processes.map((p2) => [p2.pid, p2])), r = rows.get(root.pid), o = rows.get(owner.pid);
  demand(r?.live && r.incarnation === root.incarnation && same5(r.argv, root.argv), "native_root_os_identity_mismatch");
  demand(o?.live && o.incarnation === owner.incarnation && same5(o.argv, expectedOwnerArgv), "native_owner_os_identity_mismatch");
  const chain = [], seen = new Set;
  let p = o;
  while (p) {
    demand(!seen.has(p.pid), "native_owner_parent_cycle");
    seen.add(p.pid);
    chain.push({ pid: p.pid, parentPid: p.parentPid, incarnation: p.incarnation, argv: p.argv });
    if (p.pid === r.pid)
      return chain;
    p = rows.get(p.parentPid);
  }
  throw Error("native_owner_not_actual_root_descendant");
}
var same5 = (a, b) => JSON.stringify(a) === JSON.stringify(b);
var init_native_owner_observation = __esm(() => {
  init_manifest();
  init_runtime_stage_custody();
});

// scripts/bench-runner/native-receipt-mapping.ts
import { readFileSync as readFileSync15, writeFileSync as writeFileSync6, existsSync as existsSync12 } from "fs";
import { resolve as resolve16 } from "path";
function normalizeNativeStageReceipts(m, c) {
  const policy = m.adapterConfig.stageCustody, mapping = policy?.receiptsByStage?.[c.stage], n = mapping?.normalization;
  demand(n?.protocol === "bench-native-receipt-normalization-v1" && n.fields, "explicit_native_normalization_required");
  const e = { protocol: "bench-native-stage-result-v1", artifactOrigin: "derived-from-original-receipts-not-original-envelope" }, sources = new Map;
  for (const [field, rule] of Object.entries(n.fields)) {
    demand([...required, "noProviderLaneCreated", "cashClosePin", "ownerChainCapturePin"].includes(field) && typeof rule.artifactPath === "string" && typeof rule.selector === "string", "native_receipt_normalization_field");
    const path2 = resolve16(expand2(rule.artifactPath, c));
    demand(existsSync12(path2), "native_original_receipt_missing:" + field);
    const p = pin(path2), value = at2(JSON.parse(readFileSync15(path2, "utf8")), rule.selector);
    demand(value !== undefined, "native_original_receipt_field_missing:" + field);
    sources.set(p.path, p);
    e[field] = value;
  }
  for (const field of required)
    demand(e[field] !== undefined, "native_normalization_missing:" + field);
  demand(e.taskId === m.taskId && e.bench === m.bench && e.stage === c.stage && e.attemptId === c.attemptId, "original_native_identity_not_current_stage");
  for (const field of ["resourceOwnerPin", "resourceAcquirePin", "resourceReleasePin", "ownedLedgerPin", "checkpointPin"])
    verifyPin(e[field]);
  e.originalReceiptPins = [...sources.values()];
  const path = resolve16(expand2(mapping.resultPath, c));
  demand(!existsSync12(path), "normalized_native_envelope_already_exists");
  writeFileSync6(path, JSON.stringify(e, null, 2) + `
`, { flag: "wx" });
  return pin(path);
}
var at2 = (x, path) => path.split(".").reduce((v, k) => v && Object.hasOwn(v, k) ? v[k] : undefined, x), required;
var init_native_receipt_mapping = __esm(() => {
  init_manifest();
  init_runtime_stage_custody();
  required = ["taskId", "bench", "stage", "attemptId", "manifestPin", "status", "output", "candidateOrSubmissionPresent", "modelForwardCount", "resourceOwnerPin", "resourceAcquirePin", "resourceReleasePin", "ownedLedgerPin", "checkpointPin"];
});

// scripts/repair-2026-10-10/full-f/novaeve_formal_v1/broker/sign-adoption-v76.ts
import { readFileSync as readFileSync16 } from "fs";
import { resolve as resolve17, join as join12 } from "path";
import { verify as verify3 } from "crypto";
function verifyAdoptionV76(envelope) {
  if (envelope.protocol !== "novaeve-root-signed-state-adoption-v76" || !verify3(null, Buffer.from(JSON.stringify(envelope.plan)), readFileSync16(join12(base, "review-authority.public.pem")), Buffer.from(envelope.signature, "base64")))
    throw Error("actual_root_adoption_v76_signature_required");
  return envelope.plan;
}
var root, base;
var init_sign_adoption_v76 = __esm(() => {
  root = resolve17("F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\repair-2026-10-10\\full-f\\novaeve_formal_v1\\broker", "../../../../..");
  base = join12(root, "docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator");
  if (false) {}
});

// scripts/repair-2026-10-10/full-f/novaeve_formal_v1/broker/adopted-consumer-guard-v76.ts
import { readFileSync as readFileSync17 } from "fs";
function assertSnapshotV76(h, c, p, owner) {
  demand4(h.healthy && h.pid === c.pid && h.runId === c.runId && h.targetMax === 16 && Number.isInteger(h.maxInFlight) && h.maxInFlight >= 1 && h.maxInFlight <= 16, "actual_live_health");
  demand4(h.adoption?.protocol === "novaeve-truthful-broker-adoption-v76" && h.adoption.liveExecutorPid === c.pid && h.adoption.singleResourcePool && h.adoption.exactOwnedLeaseLaneBinding && same3(h.adoption.signedAdoptionPlanPin, c.adoption.signedAdoptionPlanPin) && same3(h.canonicalOwner, owner) && same3(h.adoption.resourceEndpoints, [17889, 17895]), "truthful_signed_shared_pool");
  demand4(h.allocation.capUsd === 418.777826378 && h.allocation.allocatedUsd >= p.oldInheritedRetainedUsd && h.allocation.allocatedUsd <= 418.777826378, "original_cap_carry");
  const used = h.resourceSlots.filter((r) => r.kind === "heavy-container").reduce((n, r) => n + r.slots, 0);
  demand4(used + h.availableResourceSlots["heavy-container"] === 16, "actual_sixteen_pool");
}
async function verifyAdoptedConnection(connection, initialPublication = false) {
  demand4(connection.endpoint === "http://127.0.0.1:17895" && connection.pid > 0 && connection.adoption?.liveExecutorPid === connection.pid, "actual_connection");
  verifyPin2(connection.adoption.signedAdoptionPlanPin);
  const plan = verifyAdoptionV76(jsonPin(connection.adoption.signedAdoptionPlanPin));
  for (const pin2 of [plan.rehydrateProofPin, ...plan.sourcePins])
    verifyPin2(pin2);
  const proof = jsonPin(plan.rehydrateProofPin);
  for (const pin2 of [proof.originalParentPin, proof.canonicalOwnerPin, proof.originalHistory42Pin, proof.oldGuardPin, proof.originalAllocationPin, proof.originalPoolPin])
    verifyPin2(pin2);
  const owner = jsonPin(proof.canonicalOwnerPin), parent = jsonPin(proof.originalParentPin);
  demand4(same3(owner, parent.owned), "same_original_parent");
  const healths = await Promise.all([17895, 17889].map(async (port) => {
    const r = await fetch("http://127.0.0.1:" + port + "/health", { signal: AbortSignal.timeout(5000) });
    demand4(r.ok, "actual_http");
    return r.json();
  }));
  for (const h of healths)
    assertSnapshotV76(h, connection, proof, owner);
  if (initialPublication) {
    const holds = healths[0].resourceSlots.filter((r) => r.adoptedOrphanHold);
    demand4(same3(holds, jsonPin(proof.poolCopyPin).rows), "all_actual_inherited_holds");
  }
  return { connection, health: healths[0], proof, plan, owner, sourcePin: actualPin(import.meta.path) };
}
async function verifyAdoptedActivation(path) {
  const a = JSON.parse(readFileSync17(path, "utf8"));
  demand4(a.active && a.activated && !a.delegation && !a.broker && a.adoption.protocol === "novaeve-truthful-broker-adoption-v76", "public_no_secret_truthful_activation");
  verifyPin2(a.consumerGuardPin);
  const c = jsonPin(a.controlPin);
  demand4(c.paidReady && c.broker.pid === a.adoption.liveExecutorPid, "actual_private_control");
  return verifyAdoptedConnection(c.broker);
}
var init_adopted_consumer_guard_v76 = __esm(() => {
  init_paid_resource_proof_v2();
  init_sign_adoption_v76();
});

// scripts/bench-runner/native-stage-result.ts
import { Database as Database5 } from "bun:sqlite";
import { existsSync as existsSync13, readFileSync as readFileSync18 } from "fs";
import { resolve as resolve18, join as join13 } from "path";
async function verifyNativeStageReceipt(m, c, receipt, observations) {
  const policy = m.adapterConfig.stageCustody;
  demand(["prepare", "qualify"].includes(c.stage), "native_stage_scope");
  demand(receipt.closeObserved && !receipt.timedOut && receipt.exitCode === 0, "native_driver_not_closed_successfully");
  const mapping = policy?.receiptsByStage?.[c.stage];
  demand(mapping?.resultPath && policy.activationPin && policy.dockerIdentityPin && policy.dockerEndpoint, "native_receipt_mapping_required");
  const resultPath = resolve18(expand2(mapping.resultPath, c));
  if (!existsSync13(resultPath) && mapping.normalization)
    normalizeNativeStageReceipts(m, c);
  demand(existsSync13(resultPath), "native_stage_result_missing_or_original_normalization_unavailable");
  const envelopePin = pin(resultPath), e = read2(envelopePin);
  if (mapping.normalization) {
    demand(e.artifactOrigin === "derived-from-original-receipts-not-original-envelope" && e.originalReceiptPins?.length > 0, "native_normalization_custody_links_required");
    for (const p of e.originalReceiptPins)
      verifyPin(p);
  }
  demand(e.protocol === "bench-native-stage-result-v1" && e.taskId === m.taskId && e.bench === m.bench && e.stage === c.stage && e.attemptId === c.attemptId && same6(e.manifestPin, c.manifestPin) && ["complete", "retryable"].includes(e.status), "native_stage_result_identity");
  demand(e.candidateOrSubmissionPresent === false && e.modelForwardCount === 0, "native_stage_cannot_submit_or_model");
  const process2 = read2(receipt.processPin), owner = read2(e.resourceOwnerPin);
  demand(Number.isSafeInteger(owner.pid) && owner.pid > 0 && typeof owner.incarnation === "string" && owner.incarnation.length > 0 && owner.attemptId === c.attemptId && owner.taskId === m.taskId && owner.bench === m.bench && owner.stage === c.stage, "native_resource_owner_stage_identity");
  if (owner.pid !== process2.pid || owner.incarnation !== process2.incarnation) {
    const capture = read2(e.ownerChainCapturePin);
    demand(capture.protocol === "bench-native-owner-chain-capture-v1" && capture.attemptId === c.attemptId && capture.taskId === m.taskId && capture.stage === c.stage && same6(capture.manifestPin, c.manifestPin) && same6(capture.rootProcessPin, receipt.processPin), "native_nested_owner_signed_output_chain");
    verifyPin(capture.helperSourcePin);
    demand(capture.helperSourcePin.sha256 === pin(join13("F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\bench-runner", "processes.py")).sha256 && Array.isArray(mapping.ownerArgv), "native_owner_observer_source_and_argv_required");
    verifyPin(mapping.ownerSourcePin);
    demand(m.provenance.sourcePins.some((p) => p.path === mapping.ownerSourcePin.path && p.sha256 === mapping.ownerSourcePin.sha256) && mapping.ownerArgv.some((x) => resolve18(expand2(x, c)) === resolve18(mapping.ownerSourcePin.path)), "native_nested_owner_actual_source_required");
    verifyNativeOwnerChain(process2, owner, capture.snapshot, mapping.ownerArgv.map((x) => expand2(x, c)));
  }
  const acquire = read2(e.resourceAcquirePin), release = read2(e.resourceReleasePin);
  demand(acquire.pid === owner.pid && acquire.ownerIncarnation === owner.incarnation && acquire.slots === 1 && typeof acquire.token === "string" && acquire.token.length > 0, "native_actual_resource_acquire_receipt");
  demand(release.released === true && release.pid === owner.pid && release.ownerIncarnation === owner.incarnation && release.token === acquire.token, "native_exact_resource_release_receipt");
  verifyPin(policy.activationPin);
  verifyPin(policy.dockerIdentityPin);
  demand(/^http:\/\/127\.0\.0\.1:\d+$/.test(policy.dockerEndpoint), "private_docker_endpoint_required");
  const live = observations ?? await (async () => {
    const activation = await verifyAdoptedActivation(policy.activationPin.path), info = await fetch(policy.dockerEndpoint + "/info", { signal: AbortSignal.timeout(5000) });
    demand(info.ok, "private_docker_identity_unavailable");
    return { health: activation.health, dockerInfo: await info.json(), actorStatus: async (cid) => (await fetch(policy.dockerEndpoint + "/containers/" + cid + "/json", { signal: AbortSignal.timeout(5000) })).status };
  })();
  demand(live.health.healthy === true && !live.health.resourceSlots.some((r) => r.pid === owner.pid && r.ownerIncarnation === owner.incarnation), "native_resource_custody_pending");
  const expected = read2(policy.dockerIdentityPin);
  demand(live.dockerInfo.ID === expected.ID && live.dockerInfo.DockerRootDir === expected.DockerRootDir, "same_private_docker_daemon_required");
  verifyPin(e.ownedLedgerPin);
  const db = new Database5(e.ownedLedgerPin.path, { readonly: true });
  let actors, commands;
  try {
    const a = db.prepare("SELECT cid,closed FROM actor"), q = db.prepare("SELECT json FROM command");
    try {
      actors = a.all();
      commands = q.all();
    } finally {
      a.finalize();
      q.finalize();
    }
  } finally {
    db.close();
  }
  const absence = [];
  for (const actor of actors) {
    demand(actor.closed === 1 && /^[a-f0-9]{64}$/.test(actor.cid), "native_actor_unclosed");
    demand(await live.actorStatus(actor.cid) === 404, "native_actor_still_present");
    absence.push({ cid: actor.cid, status: 404 });
  }
  for (const row of commands) {
    const command = JSON.parse(row.json);
    demand(command.closeObserved === true && Number.isInteger(command.exitCode) && !command.captureFaults?.length, "native_command_not_closed");
    for (const stream of [command.stdout, command.stderr])
      if (stream?.path)
        verifyPin(stream);
  }
  const output = resolve18(expand2(mapping.outputPath ?? "{{runDir}}", c));
  demand(resolve18(e.output) === output, "native_stage_output_binding");
  const lanes = live.health.lanes.filter((l) => resolve18(l.output) === output);
  const proofs = [envelopePin, receipt.processPin, receipt.stdoutPin, receipt.stderrPin, e.resourceOwnerPin, e.resourceAcquirePin, e.resourceReleasePin, e.ownedLedgerPin];
  if (e.cashClosePin) {
    const cash = verifyBenchmarkCashClosure(e.cashClosePin), journal = inspectCampaignJournal(cash.proof.journalDirectory);
    demand(journal.valid && journal.accountingClosed && journal.snapshot?.acceptedRequestCount === 0 && journal.snapshot?.finishedRequestCount === 0 && cash.proof.snapshot.pendingCount === 0 && cash.proof.snapshot.billedUsd === 0 && cash.proof.snapshot.unknownReservationUsd === 0, "native_actual_zero_cash_required");
    demand(lanes.length === 1 && lanes[0].runId === cash.config.runId && lanes[0].closed === true && lanes[0].cashRegistered && lanes[0].dispatched === 0 && lanes[0].active === 0, "native_actual_zero_lane_closed");
    proofs.push(e.cashClosePin);
  } else
    demand(e.noProviderLaneCreated === true && lanes.length === 0, "native_no_provider_lane_not_proven");
  const checkpoint = read2(e.checkpointPin);
  demand(checkpoint.protocol === "bench-native-stage-checkpoint-v1" && checkpoint.taskId === m.taskId && checkpoint.bench === m.bench && checkpoint.stage === c.stage && checkpoint.attemptId === c.attemptId && checkpoint.complete === (e.status === "complete") && checkpoint.originalSuccessKey === m.stages[c.stage]?.originalSuccessKey, "native_original_checkpoint_identity");
  proofs.push(e.checkpointPin);
  return { status: e.status, proofPins: proofs, nativeClosed: true, financialClosed: true, candidateOrSubmissionPresent: false, reason: "verified_original_native_stage_receipts_no_model" };
}
var read2 = (p) => {
  verifyPin(p);
  return JSON.parse(readFileSync18(p.path, "utf8"));
}, same6 = (a, b) => JSON.stringify(a) === JSON.stringify(b);
var init_native_stage_result = __esm(() => {
  init_native_owner_observation();
  init_native_receipt_mapping();
  init_manifest();
  init_runtime_stage_custody();
  init_adopted_consumer_guard_v76();
  init_digitalocean_usd_cash();
  init_digitalocean_journal();
});

// scripts/bench-runner/native-stage-adapter.ts
var exports_native_stage_adapter = {};
__export(exports_native_stage_adapter, {
  nativeStageAdapter: () => nativeStageAdapter,
  getAdapter: () => getAdapter2
});
function nativeStageAdapter(original, observe) {
  return { ...original, async execute(m, spec, initial) {
    if (!usesStageOperation(initial, spec))
      return original.execute(m, spec, initial);
    original.validate(m);
    assertContext2(m, initial);
    demand(!m.history.validResultPins.length, "valid_task_native_stage_forbidden");
    if (m.history.originalResultRecoveryRequired || initial.inventoryTask.state === "recoverable") {
      demand(initial.originalRecoveryProofPin, "native_original_recovery_receipt_required");
      const proof = readPinned2(initial.originalRecoveryProofPin), r = proof.result;
      demand(proof.taskId === m.taskId && proof.bench === m.bench && JSON.stringify(proof.manifestPin) === JSON.stringify(initial.manifestPin) && ["retryable", "complete"].includes(r?.status) && r.nativeClosed && r.financialClosed && !r.candidateOrSubmissionPresent && !r.validResult, "native_original_recovery_not_closed");
      for (const p of r.proofPins)
        checkPin2(p);
    }
    for (const p of spec.evidencePins)
      checkPin2(p);
    const c = m.adapterConfig.bindingSpec ? loadPreparedContext(m, initial) : initial;
    demand(c.bindings?.ENTRY_ENVELOPE, "native_root_signature_required");
    const contract = m.adapterConfig.driverContract;
    demand(contract?.ownedLease && contract.beforeJournal && contract.beforeForward && contract.originalBudget, "qualified_native_driver_contract");
    checkPin2(contract.pin);
    demand(m.provenance.contractPins.some((p) => p.path === contract.pin.path && p.sha256 === contract.pin.sha256), "native_driver_contract_not_bound");
    const receipt = await executeCommand2(m, { ...spec, timeoutSeconds: spec.outerTimeoutSeconds ?? spec.timeoutSeconds }, c);
    const custody = [receipt.processPin, receipt.stdoutPin, receipt.stderrPin];
    if (!receipt.closeObserved || receipt.timedOut)
      return { status: "unknown", proofPins: custody, nativeClosed: false, financialClosed: false, candidateOrSubmissionPresent: false, reason: "native_operation_custody_unknown_no_retry" };
    try {
      const result = await verifyNativeStageReceipt(m, c, receipt, observe ? await observe() : undefined);
      const closurePin = closeStageOperation(m, c, result);
      return { ...result, proofPins: [...result.proofPins, closurePin] };
    } catch (error) {
      return { status: "unknown", proofPins: custody, nativeClosed: false, financialClosed: false, candidateOrSubmissionPresent: false, reason: "native_stage_receipts_unverified:" + String(error) };
    }
  } };
}
function getAdapter2(bench) {
  return nativeStageAdapter(getAdapter(bench));
}
var init_native_stage_adapter = __esm(async () => {
  init_runtime_stage_custody();
  init_bindings();
  init_stage_custody();
  init_native_stage_result();
  init_manifest();
  await init_adapters();
});

// scripts/bench-runner/recovery.ts
var exports_recovery = {};
__export(exports_recovery, {
  deriveRetryManifest: () => deriveRetryManifest
});
import { readFileSync as readFileSync20, mkdirSync as mkdirSync8, writeFileSync as writeFileSync9, existsSync as existsSync15 } from "fs";
import { join as join15, resolve as resolve20 } from "path";
import { verify as verify4, createHash as createHash11 } from "crypto";
import { Database as Database6 } from "bun:sqlite";
function nativeClosure(p, e) {
  const n = read3(p);
  demand(n.taskId === e.taskId && n.runId === e.runId, "retry_native_identity");
  demand(n.resourceReleased === true && n.brokerLaneClosed === true, "retry_native_lease_or_lane_open");
  demand(n.allNativeCommandStreamsClosed === true || n.allNativeCommandsClosed === true, "retry_native_commands_open");
  const ledger = n.ownedLedgerPin;
  demand(ledger, "retry_original_owned_ledger_required");
  verifyPin(ledger);
  for (const suffix of ["-wal", "-shm"])
    if (existsSync15(ledger.path + suffix)) {
      const sidecar = n.ownedLedgerPins?.find((p2) => resolve20(p2.path) === resolve20(ledger.path + suffix));
      demand(sidecar, "retry_native_ledger_sidecar_unpinned");
      verifyPin(sidecar);
    }
  const db = new Database6(ledger.path, { readonly: true });
  let actors;
  try {
    actors = db.query("select cid,closed from actor").all();
    demand(actors.every((a) => a.closed === 1), "retry_owned_actor_open");
    for (const row of db.query("select json from command").all()) {
      const c = JSON.parse(row.json);
      demand(c.closeObserved === true && Number.isInteger(c.exitCode) && !c.captureFaults?.length, "retry_native_command_receipt_open");
    }
  } finally {
    db.close();
  }
  verifyPin(ledger);
  for (const p2 of n.ownedLedgerPins ?? [])
    verifyPin(p2);
  const absent = n.exactOwnedContainerApi404 ?? [];
  demand(actors.every((a) => absent.some((x) => x.cid === a.cid && x.status === 404)), "retry_actor_absence_not_bound");
  if (!actors.length)
    demand(n.noActorsEverCreated === true, "retry_empty_ledger_is_not_no_actor_proof");
  if (actors.length)
    demand(n.standClosePin && n.engineClosePin, "retry_actor_process_receipts_required");
  for (const p2 of [n.standClosePin, n.engineClosePin].filter(Boolean)) {
    const c = read3(p2);
    demand(c.exitObserved === true && c.closeObserved === true, "retry_original_process_stream_open");
    for (const s of [c.stdout, c.stderr])
      verifyPin(s);
  }
  demand(Array.isArray(n.exactPidAbsence) && n.exactPidAbsence.length > 0 && n.exactPidAbsence.every((x) => Number.isSafeInteger(x.pid) && x.pid > 0 && x.currentlyAbsent === true), "retry_exact_process_closure_required");
  return n;
}
function actualFault(p, e, now) {
  const f = read3(p);
  demand(f.runId === e.runId && f.taskId === e.taskId && f.attemptId === e.attemptId, "retry_fault_identity");
  const at3 = Date.parse(f.atUtc ?? f.finishedAtUtc);
  demand(Number.isFinite(at3) && at3 <= now, "retry_fault_time");
  const code = f.transportFault ?? f.error?.code ?? f.code;
  const status = f.httpStatus;
  demand(f.providerAttempted === true, "retry_actual_provider_attempt_not_proven");
  demand(["ECONNRESET", "ETIMEDOUT"].includes(code) || [502, 503, 504].includes(status), "retry_unclassified_fault");
  demand(Number.isSafeInteger(f.requestSeq) && f.requestSeq >= 0, "retry_fault_request_sequence");
  return { at: at3, transportFault: code ?? null, httpStatus: status ?? null, requestSeq: f.requestSeq };
}
function replacePin(value, old, next) {
  if (old && value && typeof value === "object" && same7(value, old))
    return next;
  if (Array.isArray(value))
    return value.map((x) => replacePin(x, old, next));
  if (value && typeof value === "object")
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, replacePin(v, old, next)]));
  return value;
}
function deriveRetryManifest(input) {
  const { context: c, result: r } = input, now = input.now instanceof Date ? input.now.getTime() : input.now ?? Date.now();
  demand(Number.isFinite(now), "retry_now");
  const manifestPin = pin(input.manifestPath), m = loadManifest(input.manifestPath);
  demand(same7(manifestPin, c.manifestPin) && c.taskId === m.taskId && c.bench === m.bench, "retry_context_identity");
  demand(r.status === "retryable" && r.nativeClosed === true && r.financialClosed === true && r.candidateOrSubmissionPresent === false && !r.validResult, "retry_only_closed_no_candidate");
  demand(!m.history.validResultPins.length, "valid_never_retry");
  const authority = m.adapterConfig.bindingSpec?.authorityPin ?? m.adapterConfig.retryAuthorityPin;
  demand(authority && m.provenance.contractPins.some((p) => same7(p, authority)), "retry_root_authority_not_bound");
  verifyPin(authority);
  const envelope = read3(input.policyPin);
  demand(envelope.protocol === "bench-root-signed-retry-policy-v1", "retry_signed_policy_required");
  demand(verify4(null, Buffer.from(JSON.stringify(envelope.policy)), readFileSync20(authority.path), Buffer.from(envelope.signature, "base64")), "retry_policy_signature");
  const policy = envelope.policy;
  demand(policy.protocol === "bench-automatic-retry-policy-v1" && policy.scope.benches.includes(m.bench) && policy.scope.taskIds.includes(m.taskId), "retry_policy_scope");
  demand(Number.isSafeInteger(policy.maxAttempts) && policy.maxAttempts > 0 && policy.maxAttempts <= 3 && Number.isSafeInteger(policy.minBackoffMs) && policy.minBackoffMs >= 30000 && Date.parse(policy.expiresAtUtc) > now, "retry_policy_bounds");
  const history = Array.isArray(m.adapterConfig.retryHistory) ? m.adapterConfig.retryHistory : [];
  demand(history.length < policy.maxAttempts, "retry_attempt_limit");
  if (r.retryEvidencePin)
    demand(r.proofPins.some((p) => same7(p, r.retryEvidencePin)), "retry_evidence_not_in_result_proofs");
  const proofs = (r.retryEvidencePin ? [r.retryEvidencePin] : r.proofPins).map((p) => {
    verifyPin(p);
    let value = null;
    if (p.bytes <= 2 * 1024 ** 2)
      try {
        value = JSON.parse(readFileSync20(p.path, "utf8").replace(/^\uFEFF/, ""));
      } catch {}
    return { pin: p, value };
  });
  const candidates = proofs.filter((x) => x.value?.protocol === "bench-retryable-closure-v1");
  demand(candidates.length === 1, "retry_explicit_closure_evidence_required");
  const { pin: evidencePin, value: e } = candidates[0];
  demand(e.taskId === m.taskId && e.bench === m.bench && e.attemptId === c.attemptId && typeof e.runId === "string" && e.runId.length > 0, "retry_closed_attempt_identity");
  demand(policy.allowedFailureClasses.includes(e.failureClass), "retry_failure_class_not_approved");
  const fault = actualFault(e.faultReceiptPin, e, now);
  nativeClosure(e.nativeClosurePin, e);
  const config = m.adapterConfig, oldBudgetPin = config.aggregateBudgetPin ?? config.terminalDriver?.aggregateBudgetPin;
  const oldBudget = oldBudgetPin ? read3(oldBudgetPin) : undefined;
  const oldPins = config.historicalCashPins ?? oldBudget?.cashClosePins ?? [];
  demand(Array.isArray(oldPins), "retry_historical_cash_pins_required");
  if (oldBudget)
    demand(Array.isArray(oldBudget.cashClosePins) && equal2(oldBudget.cashClosePins, oldPins), "retry_history_chain_not_exact");
  let known = 0, unknown2 = 0, unknownCount = 0;
  const seen = new Set;
  const cashRows = [];
  const replay = (p) => {
    const cash = verifyBenchmarkCashClosure(p), journal = inspectCampaignJournal(cash.proof.journalDirectory), s = cash.proof.snapshot;
    demand(cash.config.protocol === "openrouter-usd-cash-config-v1" && cash.config.currency === "USD" && journal.valid && journal.accountingClosed && s.pendingCount === 0 && s.pendingReservationUsd === 0, "retry_cash_journal_not_closed");
    demand(!seen.has(cash.config.runId), "retry_duplicate_cash_run");
    seen.add(cash.config.runId);
    demand(cash.config.capUsd <= m.original.taskCapUsd + 0.000000001 && s.billedUsd >= 0 && s.unknownReservationUsd >= 0, "retry_original_task_cap");
    known += s.billedUsd;
    unknown2 += s.unknownReservationUsd;
    unknownCount += s.newUnknownCount;
    cashRows.push({ runId: cash.config.runId, cashClosePin: p, knownUsd: s.billedUsd, unknownUsd: s.unknownReservationUsd });
    return cash;
  };
  for (const p of oldPins)
    replay(p);
  demand(Math.abs(known - m.original.priorKnownUsd) < 0.000000001 && Math.abs(unknown2 - m.original.priorUnknownUsd) < 0.000000001, "retry_previous_expense_coverage");
  const current = replay(e.cashClosePin);
  demand(current.config.runId === e.runId, "retry_cash_failed_run_identity");
  const actualJournal = inspectCampaignJournal(current.proof.journalDirectory), offset = actualJournal.offsets.get(fault.requestSeq);
  demand(offset, "retry_fault_not_in_actual_journal");
  const event = JSON.parse(readFileSync20(actualJournal.journalPath).subarray(offset.offset, offset.offset + offset.bytes).toString("utf8"));
  demand(event.kind === "finish" && event.requestSeq === fault.requestSeq && event.record.providerAttempted === true && (fault.transportFault ? event.record.fault === fault.transportFault : event.record.httpStatus === fault.httpStatus), "retry_fault_actual_journal_mismatch");
  const finishedAt = Date.parse(event.record.finishedAt);
  demand(Number.isFinite(finishedAt) && finishedAt <= now, "retry_actual_fault_finish_time");
  const allPins = [...oldPins, e.cashClosePin], first = verifyBenchmarkCashClosure(allPins[0]);
  demand(first.config.capUsd === m.original.taskCapUsd, "retry_first_actual_task_cap");
  const remaining = m.original.taskCapUsd - known - unknown2;
  demand(remaining > 0, "retry_original_budget_exhausted");
  const notBeforeUtc = new Date(Math.max(now, Math.max(fault.at, finishedAt) + policy.minBackoffMs)).toISOString();
  const identity = { manifestPin, attemptId: c.attemptId, runId: e.runId, policyPin: input.policyPin, evidencePin };
  const key = createHash11("sha256").update(JSON.stringify([m.bench, m.taskId, manifestPin.sha256, c.attemptId, e.runId])).digest("hex");
  const directory = join15(resolve20(c.runDir), "retry-data-" + key.slice(0, 32)), completedPath = join15(directory, "derivation-complete.json");
  if (existsSync15(directory)) {
    demand(existsSync15(completedPath), "retry_partial_derivation_quarantined");
    const completed = read3(pin(completedPath));
    demand(equal2(completed.inputIdentity, identity), "retry_existing_derivation_identity_changed");
    for (const p of completed.outputPins)
      verifyPin(p);
    demand(completed.result.directory === directory && completed.result.rootSignatureRequired === true && completed.result.spawned === false && completed.outputPins.some((p) => same7(p, completed.result.successorManifestPin)) && completed.outputPins.some((p) => same7(p, completed.result.retryProofPin)), "retry_completed_output_binding");
    const savedProof = read3(completed.result.retryProofPin);
    demand(same7(savedProof.predecessorManifestPin, manifestPin) && savedProof.predecessorAttemptId === c.attemptId && savedProof.predecessorRunId === e.runId, "retry_completed_lineage");
    loadManifest(completed.result.successorManifestPin.path);
    return completed.result;
  }
  mkdirSync8(directory, { recursive: false });
  const save = (name, v) => {
    const p = join15(directory, name);
    writeFileSync9(p, JSON.stringify(v, null, 2) + `
`, { flag: "wx" });
    return pin(p);
  };
  const aggregateBudgetPin = save("aggregate-budget.pending-root.json", { ...oldBudget ?? {}, protocol: oldBudget?.protocol ?? "bench-original-task-budget-v1", rootReviewed: false, derivedFromReviewedPolicyPin: input.policyPin, taskId: m.taskId, cashClosePins: allPins, originalTaskCashConfigPin: first.proof.configPin, originalTaskCapUsd: m.original.taskCapUsd, knownUsd: known, unknownReservationUsd: unknown2, unknownCount, exposureUpperBoundUsd: known + unknown2, newAttemptMaxSpendUsd: remaining });
  const retryProofPin = save("retry-derivation.json", { protocol: "bench-data-retry-derivation-v1", rootReviewed: false, derivedFromReviewedPolicyPin: input.policyPin, predecessorManifestPin: manifestPin, predecessorAttemptId: c.attemptId, predecessorRunId: e.runId, evidencePin, cashClosePin: e.cashClosePin, faultReceiptPin: e.faultReceiptPin, nativeClosurePin: e.nativeClosurePin, cashRows, aggregateBudgetPin, notBeforeUtc, ordinal: history.length + 1, newSignatureRequired: true, modelCalls: 0 });
  let successor = replacePin(structuredClone(m), oldBudgetPin, aggregateBudgetPin);
  successor.original.priorKnownUsd = known;
  successor.original.priorUnknownUsd = unknown2;
  successor.adapterConfig.historicalCashPins = allPins;
  successor.adapterConfig.aggregateBudgetPin = aggregateBudgetPin;
  successor.adapterConfig.retryHistory = [...history, { proofPin: retryProofPin, attemptId: c.attemptId, runId: e.runId, notBeforeUtc }];
  successor.adapterConfig.pendingRootSignature = true;
  successor.adapterConfig.retryNotBeforeUtc = notBeforeUtc;
  let templatePin;
  if (config.bindingSpec) {
    const oldTemplate = read3(config.bindingSpec.entryTemplatePin);
    let template = replacePin(oldTemplate, oldBudgetPin, aggregateBudgetPin);
    template.coordinatorReviewed = false;
    template.phase = "draft";
    template.nonce = "{{bindings.NONCE}}";
    template.retryDerivationPin = retryProofPin;
    templatePin = save("entry-template.pending-root.json", template);
    successor.adapterConfig.bindingSpec.entryTemplatePin = templatePin;
    successor.provenance.contractPins = successor.provenance.contractPins.map((p) => same7(p, config.bindingSpec.entryTemplatePin) ? templatePin : p);
  }
  successor.history.originalResultRecoveryRequired = true;
  successor.history.priorRunPins = [...m.history.priorRunPins, evidencePin, e.cashClosePin, e.faultReceiptPin, e.nativeClosurePin, retryProofPin];
  successor.provenance.contractPins.push(input.policyPin, retryProofPin, aggregateBudgetPin);
  demand(equal2(successor.provenance.sourcePins, m.provenance.sourcePins) && successor.original.taskCapUsd === m.original.taskCapUsd && equal2(successor.history.successfulStageProofs, m.history.successfulStageProofs), "retry_original_source_checkpoint_changed");
  const successorManifestPin = save("manifest.pending-root.json", successor);
  loadManifest(successorManifestPin.path);
  const result = { directory, successorManifestPin, templatePin, aggregateBudgetPin, retryProofPin, notBeforeUtc, remainingUsd: remaining, rootSignatureRequired: true, spawned: false };
  save("derivation-complete.json", { protocol: "bench-data-retry-output-v1", inputIdentity: identity, result, outputPins: [successorManifestPin, aggregateBudgetPin, retryProofPin, ...templatePin ? [templatePin] : []] });
  return result;
}
var read3 = (p) => {
  verifyPin(p);
  return JSON.parse(readFileSync20(p.path, "utf8").replace(/^\uFEFF/, ""));
}, same7 = (a, b) => a?.path === b?.path && a?.bytes === b?.bytes && a?.sha256 === b?.sha256, equal2 = (a, b) => JSON.stringify(a) === JSON.stringify(b);
var init_recovery = __esm(() => {
  init_manifest();
  init_digitalocean_usd_cash();
  init_digitalocean_journal();
});

// scripts/bench-runner/observer.ts
var exports_observer = {};
__export(exports_observer, {
  selectMainTask: () => selectMainTask,
  observe: () => observe,
  inTree: () => inTree,
  deduplicateTasks: () => deduplicateTasks
});
import { Database as Database8 } from "bun:sqlite";
import { readFileSync as readFileSync23, existsSync as existsSync17, mkdirSync as mkdirSync11, writeFileSync as writeFileSync11, copyFileSync as copyFileSync2, renameSync as renameSync4 } from "fs";
import { join as join17, resolve as resolve22, dirname as dirname7, isAbsolute as isAbsolute7 } from "path";
import { execFileSync } from "child_process";
import { createHash as createHash12, verify as verify5, randomUUID as randomUUID3 } from "crypto";
function read4(path) {
  return JSON.parse(readFileSync23(path, "utf8").replace(/^\uFEFF/, ""));
}
function same8(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}
function fileEquals(a, b) {
  return process.platform === "win32" ? resolve22(a).toLowerCase() === resolve22(b).toLowerCase() : resolve22(a) === resolve22(b);
}
function inTree(pid, root2, rows) {
  const seen = new Set;
  while (pid > 0 && !seen.has(pid)) {
    if (pid === root2)
      return true;
    seen.add(pid);
    pid = rows.get(pid)?.parentPid ?? 0;
  }
  return false;
}
function selectMainTask(db, m, bench, taskId, runId) {
  demand(m.runId === runId, "manifest_lane_run_mismatch");
  let mainId;
  if (bench === "skillsbench") {
    const schedule = m.taskSchedule?.filter((x) => x.taskId === taskId && x.arm === "F");
    demand(schedule?.length === 1, "manifest_main_not_unique");
    mainId = schedule[0].id;
  } else {
    demand(same8(m.executingTaskIds, [taskId]), "manifest_executing_scope_not_single");
    mainId = "tb12-" + createHash12("sha256").update(JSON.stringify([runId, "F", taskId])).digest("hex").slice(0, 32);
  }
  const rows = db.query("SELECT id,run,state,mode,source,result FROM task WHERE id=? AND run=?").all(mainId, runId);
  demand(rows.length === 1 && rows[0].source === "user", "published_main_missing_or_ambiguous");
  const task = rows[0];
  demand(/^[A-Za-z0-9_]+$/.test(task.mode), "unsafe_mode_table");
  const roots = db.query('SELECT cycle,unit,node,from_cycle,from_unit FROM "task_' + task.mode + '" WHERE task=? AND unit=1 AND node=1 AND from_cycle IS NULL AND from_unit IS NULL').all(mainId);
  demand(roots.length === 1, "published_execution_root_not_unique");
  const active = db.query("SELECT COUNT(*) AS n FROM agent_bot_ctx WHERE task=? AND unit=1 AND done=0").get(mainId).n;
  return { task, activeUnits: active, selection: "exact_manifest_published_main_and_execution_root", ignoredChildTasks: db.query("SELECT COUNT(*) AS n FROM task").get().n - 1 };
}
function signedBindings(m, c) {
  const s = m.adapterConfig.bindingSpec;
  demand(s?.protocol === "bench-root-data-binding-v1", "signed_binding_scope_required");
  verifyPin(s.authorityPin);
  verifyPin(s.entryTemplatePin);
  const path = join17(c.runDir, "root-entry.signed.json"), envelope = read4(path), e = envelope.entry, b = e?.rootRuntimeBinding;
  demand(envelope.protocol === "novaeve-root-signed-entry-v4" && verify5(null, Buffer.from(JSON.stringify(e)), readFileSync23(s.authorityPin.path), Buffer.from(envelope.signature, "base64")), "actual_root_binding_signature");
  demand(e.taskId === m.taskId && e.bench === m.bench && e.nonce === c.attemptId && e.coordinatorReviewed === true, "signed_attempt_identity");
  demand(b?.attemptId === c.attemptId && b.taskId === c.taskId && b.bench === c.bench && b.stage === c.stage && same8(b.manifestPin, c.manifestPin) && same8(b.templatePin, s.entryTemplatePin), "signed_manifest_context_binding");
  const values = { NONCE: c.attemptId, OUTPUT: resolve22(s.output.root, s.output.prefix + c.attemptId), RECOVERY_ENTRY: join17(c.runDir, "recovery.entry.json"), ENTRY_ENVELOPE: path, MANIFEST_PATH: c.manifestPath, CONTEXT_PATH: join17(c.runDir, "intent-context.json"), MANIFEST: c.manifestPath, CONTEXT: join17(c.runDir, "intent-context.json") };
  for (const [k, v] of Object.entries(s.inputs)) {
    verifyPin(v.pin);
    values[k] = v.select === "path" ? resolve22(v.pin.path) : v.pin.sha256;
  }
  demand(same8(b.bindings, values), "signed_values_changed");
  demand(same8(b.inputPins, Object.values(s.inputs).map((v) => v.pin)), "signed_input_set_changed");
  for (const p of b.inputPins)
    verifyPin(p);
  const replace = (v) => typeof v === "string" ? v.replace(/\{\{bindings\.([A-Z][A-Z0-9_]*)\}\}/g, (_, k) => {
    demand(Object.hasOwn(values, k), "unknown_binding");
    return values[k];
  }) : Array.isArray(v) ? v.map(replace) : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, replace(x)])) : v;
  for (const [k, v] of Object.entries(replace(read4(s.entryTemplatePin.path))))
    if (!["coordinatorReviewed", "phase", "rootRuntimeBinding"].includes(k))
      demand(same8(e[k], v), "signed_template_changed:" + k);
  return { bindings: values, signedPin: pin(path), signatureExpired: Date.parse(b.expiresAtUtc) <= Date.now() };
}
function collectScope(a) {
  const mp = JSON.parse(a.manifest_pin);
  verifyPin(mp);
  const m = loadManifest(mp.path), cp = join17(a.run_dir, "intent-context.json"), c = read4(cp);
  demand(c.attemptId === a.id && c.taskId === m.taskId && c.bench === m.bench && c.stage === a.stage && same8(c.manifestPin, mp) && fileEquals(c.runDir, a.run_dir), "queue_context_mismatch");
  const signed = signedBindings(m, c);
  c.bindings = signed.bindings;
  const rp = join17(a.run_dir, "process.json"), r = read4(rp), intent = read4(r.intentPin.path);
  verifyPin(r.intentPin);
  verifyPin(r.sourcePin);
  demand(r.protocol === "bench-process-custody-v1" && r.attemptId === a.id && r.stage === a.stage && same8(r.manifestPin, mp) && r.incarnation, "exact_process_custody_required");
  demand(intent.attemptId === a.id && intent.taskId === m.taskId && intent.bench === m.bench && intent.stage === a.stage && same8(intent.manifestPin, mp), "command_intent_identity");
  const spec = m.stages[a.stage];
  demand(spec?.kind === "command" && same8(spec.command.map((x) => expand(x, c)), r.argv) && same8(intent.argv, r.argv), "actual_manifest_argv_binding");
  demand(m.provenance.sourcePins.some((p) => fileEquals(p.path, r.sourcePin.path) && p.sha256 === r.sourcePin.sha256), "process_source_not_reviewed");
  return { attempt: a, manifest: m, context: c, receipt: r, receiptPin: pin(rp), ...signed };
}
function knownPins(value, result = []) {
  if (!value || typeof value !== "object")
    return result;
  if (typeof value.path === "string" && Number.isSafeInteger(value.bytes) && typeof value.sha256 === "string")
    result.push(value);
  else
    for (const v of Object.values(value))
      knownPins(v, result);
  return result;
}
async function jsonUrl(url) {
  const r = await fetch(url, { signal: AbortSignal.timeout(3000) });
  demand(r.ok, "health_http_" + r.status);
  return await r.json();
}
function deduplicateTasks(rows) {
  const groups = new Map;
  for (const row of rows) {
    const key = row.bench + ":" + row.taskId;
    if (!groups.has(key))
      groups.set(key, []);
    groups.get(key).push(row);
  }
  return [...groups.values()].map((group) => {
    const live = group.filter((r) => r.workerLive);
    if (live.length > 1)
      return { taskId: group[0].taskId, bench: group[0].bench, state: "unknown", countsAsSolving: false, reason: "multiple_live_scoped_attempts", attemptIds: group.map((r) => r.attemptId) };
    return live[0] ?? group.find((r) => r.state !== "planned") ?? group[0];
  });
}
async function observe(options) {
  const db = new Database8(options.databasePath, { readonly: true });
  let attempts, eventSequence;
  try {
    attempts = db.query("SELECT * FROM attempts WHERE state IN ('planned','intent','running','unknown') ORDER BY created_at").all();
    eventSequence = db.query("SELECT MAX(seq) AS seq FROM events").get();
  } finally {
    db.close();
  }
  const rows = [], scopes = [];
  for (const a of attempts) {
    const row = { taskId: a.task_key.slice(a.task_key.indexOf(":") + 1), bench: a.task_key.slice(0, a.task_key.indexOf(":")), attemptId: a.id, stage: a.stage, queueClass: a.queue_class, queueState: a.state, state: a.state === "planned" ? "planned" : "unknown", countsAsSolving: false, workerLive: false };
    rows.push(row);
    if (a.state === "planned")
      continue;
    try {
      const s = collectScope(a);
      scopes.push(s);
      row.scopedSourceVerified = true;
      row.signedEntryPin = s.signedPin;
      row.processPin = s.receiptPin;
    } catch (error) {
      row.observationError = String(error);
    }
  }
  let processes = { protocol: "bench-process-subtrees-readonly-v1", processes: [], errors: [], roots: [] };
  if (scopes.length)
    processes = JSON.parse(execFileSync(options.pythonExecutable ?? process.env.BENCH_OBSERVER_PYTHON ?? "python", [join17("F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\bench-runner", "processes.py")], { input: JSON.stringify({ roots: scopes.map((s) => s.receipt.pid) }), encoding: "utf8", windowsHide: true, timeout: 15000, maxBuffer: 16 * 1024 ** 2 }));
  const map = new Map(processes.processes.map((x) => [x.pid, x]));
  const connections = new Map;
  for (const s of scopes) {
    const row = rows.find((x) => x.attemptId === s.attempt.id), m = s.manifest;
    try {
      const root2 = map.get(s.receipt.pid);
      demand(root2?.live && root2.incarnation === s.receipt.incarnation && same8(root2.argv, s.receipt.argv), "exact_custody_process_not_live_or_reused");
      row.workerLive = true;
      row.rootProcess = { pid: root2.pid, incarnation: root2.incarnation, argv: root2.argv, createdEpoch: root2.createdEpoch };
      const config = m.adapterConfig.observation ?? {}, activationPath = config.activationPath ?? join17(m.root, "docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/activation-adopted-v76.json");
      if (!connections.has(activationPath))
        connections.set(activationPath, verifyAdoptedActivation(activationPath));
      const live = await connections.get(activationPath), health = live.health;
      row.broker = { pid: live.connection.pid, runId: live.connection.runId, healthy: health.healthy };
      const held = health.resourceSlots.filter((r) => !r.adoptedOrphanHold && !r.inheritedResourceHold && r.slug === m.bench && map.get(r.pid)?.live && map.get(r.pid)?.incarnation === r.ownerIncarnation && inTree(r.pid, root2.pid, map));
      row.actualOwnedLeases = held.map((r) => ({ pid: r.pid, ownerIncarnation: r.ownerIncarnation, slots: r.slots, memoryMb: r.memoryMb, plannedGrowthBytes: r.plannedGrowthBytes }));
      const isPrep = ["prepare", "qualify"].includes(s.attempt.stage);
      if (isPrep) {
        row.state = held.length ? "native_preparing" : "preparing_without_verified_lease";
        row.countsAsPreparationTask = held.length > 0;
        continue;
      }
      row.state = "formal_preparing";
      const candidates = [];
      for (const lane2 of health.lanes ?? []) {
        if (lane2.closed || lane2.slug !== m.bench)
          continue;
        const output2 = resolve22(lane2.output), path3 = join17(output2, m.bench === "skillsbench" ? "parent-process.json" : "process.json");
        if (!existsSync17(path3))
          continue;
        const p2 = read4(path3), worker2 = map.get(p2.pid);
        if (!worker2?.live || !inTree(worker2.pid, root2.pid, map))
          continue;
        if (p2.runId !== lane2.runId || p2.output !== undefined && !fileEquals(p2.output, output2))
          continue;
        if (config.outputMode !== "driver-auto" && s.bindings?.OUTPUT && !fileEquals(s.bindings.OUTPUT, output2))
          continue;
        const tasks = p2.executingTaskIds ?? (p2.taskId ? [p2.taskId] : []);
        if (!same8(tasks, [m.taskId]))
          continue;
        candidates.push({ lane: lane2, output: output2, path: path3, p: p2, worker: worker2 });
      }
      demand(candidates.length <= 1, "multiple_live_lane_outputs_in_scope");
      if (!candidates.length)
        continue;
      const { lane, output, path: path2, p, worker } = candidates[0], runManifestPath = join17(output, "manifest.json"), runManifest = read4(runManifestPath);
      demand(runManifest.runId === lane.runId, "run_manifest_lane_join");
      row.runId = lane.runId;
      row.output = output;
      row.workerPid = worker.pid;
      row.workerIncarnation = worker.incarnation;
      row.runtimeProcessPin = pin(path2);
      row.runtimeManifestPin = pin(runManifestPath);
      row.lane = { runId: lane.runId, closed: false, active: lane.active, dispatched: lane.dispatched };
      if (existsSync17(join17(output, "summary.json"))) {
        row.state = "formal_finalizing";
        row.summaryPin = pin(join17(output, "summary.json"));
        continue;
      }
      let engineDir = join17(output, "workers/0-F"), expected = join17(output, "frozen-engine/main.js");
      if (m.bench === "skillsbench") {
        const schedule = runManifest.taskSchedule?.filter((t) => t.taskId === m.taskId && t.arm === "F");
        demand(schedule?.length === 1, "sb_main_schedule");
        engineDir = join17(output, "workers", String(schedule[0].index));
        expected = join17(m.root, "app/src/main.ts");
      }
      const engines = [...map.values()].filter((x) => x.live && inTree(x.pid, worker.pid, map) && x.argv?.some((a) => isAbsolute7(a) && fileEquals(a, expected)));
      demand(engines.length <= 1, "multiple_engine_processes");
      if (!engines.length)
        continue;
      const engine = engines[0], enginePin = knownPins(runManifest).find((p2) => fileEquals(p2.path, expected)) ?? m.provenance.sourcePins.find((p2) => fileEquals(p2.path, expected));
      demand(enginePin, "engine_source_pin_missing");
      verifyPin(enginePin);
      if (m.bench === "skillsbench") {
        const i = runManifest.taskSchedule.find((t) => t.taskId === m.taskId && t.arm === "F").index;
        demand(read4(join17(output, "engine-" + i + "-process.json")).pid === engine.pid, "sb_engine_native_receipt_join");
      }
      const database = join17(engineDir, "data/h2h.sqlite"), engineDb = new Database8(database, { readonly: true });
      let main;
      try {
        main = selectMainTask(engineDb, runManifest, m.bench, m.taskId, lane.runId);
      } finally {
        engineDb.close();
      }
      row.mainTaskEvidence = main;
      row.enginePid = engine.pid;
      row.engineIncarnation = engine.incarnation;
      row.engineArgv = engine.argv;
      row.engineSourcePin = enginePin;
      row.databasePath = database;
      if (["done", "failed"].includes(main.task.state) || main.task.result !== null) {
        row.state = "formal_grading";
        continue;
      }
      const publicConfig = join17(engineDir, "config-public.json");
      let port;
      if (existsSync17(publicConfig))
        port = read4(publicConfig).server.port;
      else {
        const text = readFileSync23(join17(engineDir, "config.yaml"), "utf8"), match = /server:\s*\{host:\s*127\.0\.0\.1,\s*port:\s*(\d+),/.exec(text);
        demand(match, "engine_loopback_port");
        port = Number(match[1]);
      }
      demand(Number.isInteger(port) && port > 0 && port < 65536, "engine_health_port");
      const eh = await jsonUrl("http://127.0.0.1:" + port + "/api/health");
      demand(fileEquals(eh.db, database), "engine_health_database_join");
      row.dbHealthBound = true;
      if (["claimed", "running", "doing"].includes(main.task.state) && main.activeUnits > 0) {
        row.state = "formal_solving";
        row.countsAsSolving = true;
      }
    } catch (error) {
      row.observationError = String(error);
      row.countsAsSolving = false;
      if (!row.workerLive)
        row.state = "closed_or_closure_pending";
    }
  }
  const dedup = deduplicateTasks(rows), formalTasks = dedup.filter((r) => r.queueClass !== "preparation"), preparationTasks = dedup.filter((r) => r.queueClass === "preparation");
  const snapshot = { protocol: "novaeve-universal-actual-task-status-v1", atUtc: new Date().toISOString(), scope: "durable-universal-queue-attempts-only", queueDatabasePath: resolve22(options.databasePath), queueEventSequence: eventSequence, formalTasks, preparationTasks, actualSolving: formalTasks.filter((r) => r.state === "formal_solving" && r.countsAsSolving).length, actualFormalPreparing: formalTasks.filter((r) => r.state === "formal_preparing").length, actualFormalGrading: formalTasks.filter((r) => r.state === "formal_grading").length, actualNativePreparation: preparationTasks.filter((r) => r.countsAsPreparationTask).length, attemptRows: rows, processSnapshotErrors: processes.errors, independentProcessesExcluded: true, newModelCalls: 0, newResources: 0, nativeMutations: 0 };
  mkdirSync11(options.snapshotDirectory, { recursive: true });
  const path = join17(options.snapshotDirectory, "actual-task-status-" + Date.now() + "-" + randomUUID3() + ".json");
  writeFileSync11(path, JSON.stringify(snapshot, null, 2) + `
`, { flag: "wx" });
  if (options.canonicalPath) {
    mkdirSync11(dirname7(options.canonicalPath), { recursive: true });
    const tmp = options.canonicalPath + "." + randomUUID3() + ".tmp";
    copyFileSync2(path, tmp);
    renameSync4(tmp, options.canonicalPath);
  }
  return { snapshotPin: pin(path), snapshot };
}
var init_observer = __esm(() => {
  init_manifest();
  init_runtime();
  init_adopted_consumer_guard_v76();
});

// scripts/bench-runner/inventory.ts
var exports_inventory = {};
__export(exports_inventory, {
  scanInventory: () => scanInventory,
  reconcileInventory: () => reconcileInventory,
  loadInventory: () => loadInventory,
  inventoryPin: () => pin
});
import { readFileSync as readFileSync24 } from "fs";
function reconcileInventory(catalog, facts) {
  const keys = new Set;
  return catalog.map((c) => {
    const key = c.bench + ":" + c.taskId;
    if (keys.has(key))
      throw Error("duplicate_catalog_task:" + key);
    keys.add(key);
    const rows = facts.filter((f) => f.taskId === c.taskId && f.bench === c.bench);
    const evidence = [c.evidencePin, ...rows.map((f) => f.evidencePin)];
    const unique = [...new Map(evidence.map((p) => [p.path + "|" + p.sha256, p])).values()];
    const successfulStages = {};
    for (const r of rows)
      if (r.kind === "success" && r.stage)
        (successfulStages[r.stage] ??= []).push(r.evidencePin);
    const valid = rows.some((f) => f.kind === "valid"), inflight = rows.some((f) => f.kind === "inflight"), hist = rows.filter((f) => f.kind === "history");
    let state = "quarantined", reason = "No exhaustive historical absence proof; never-started is not inferred from missing ready/records";
    if (valid) {
      state = "valid";
      reason = "Permanent original valid result including wrong/budget exhaustion; no stage replay";
    } else if (inflight) {
      state = "inflight";
      reason = "Exact current process/native/ledger evidence; no respawn";
    } else if (hist.length && hist.every((f) => f.closed === true)) {
      state = "recoverable";
      reason = hist.some((f) => f.candidateOrGrade) ? "Original candidate/submit/grade recovery precedes solve" : "Closed historical attempt; preserve all expenses and original constraints";
    } else if (!hist.length && rows.some((f) => f.kind === "never-started")) {
      state = "never-started";
      reason = "Explicit root historical absence attestation, not missing-files inference";
    } else if (hist.length) {
      reason = "Historical attempts exist; finance/native closure or original-result custody unresolved";
    }
    const priced = new Map;
    for (const f of hist.filter((f2) => f2.runId)) {
      const old = priced.get(f.runId);
      if (old && (old.knownUsd !== f.knownUsd || old.unknownUsd !== f.unknownUsd))
        throw Error("conflicting_run_finance:" + f.runId);
      priced.set(f.runId, f);
    }
    return { taskId: c.taskId, bench: c.bench, state, reason, evidencePins: unique, successfulStages, priorRunIds: [...priced.keys()], ...hist.length && [...priced.values()].every((f) => f.knownUsd !== undefined && f.unknownUsd !== undefined) ? { priorKnownUsd: [...priced.values()].reduce((n, f) => n + (f.knownUsd ?? 0), 0), priorUnknownUsd: [...priced.values()].reduce((n, f) => n + (f.unknownUsd ?? 0), 0) } : {} };
  });
}
function loadInventory(path) {
  const data = read5(path), tasks = Array.isArray(data) ? data : data.tasks;
  if (!Array.isArray(tasks))
    throw Error("inventory_tasks_required");
  const seen = new Set, verified = new Set;
  for (const t of tasks) {
    const k = t.bench + ":" + t.taskId;
    if (seen.has(k) || !["terminal-bench", "skillsbench"].includes(t.bench) || !["valid", "inflight", "recoverable", "never-started", "quarantined"].includes(t.state) || !t.evidencePins?.length)
      throw Error("invalid_inventory_task:" + k);
    seen.add(k);
    for (const p of [...t.evidencePins, ...Object.values(t.successfulStages ?? {}).flat()]) {
      const key = p.path + "|" + p.sha256;
      if (!verified.has(key)) {
        verifyPin(p);
        verified.add(key);
      }
    }
  }
  return tasks;
}
function scanInventory(input) {
  const catalog = input.catalogs.flatMap((c) => {
    const doc = read5(c.path), ids = doc.taskIds ?? doc.taskSchedule?.map((t) => t.taskId);
    if (!ids || ids.length !== c.expectedCount || new Set(ids).size !== ids.length)
      throw Error("original_catalog_count");
    return ids.map((taskId) => ({ taskId, bench: c.bench, evidencePin: pin(c.path) }));
  });
  for (const p of [...input.inputEvidencePins ?? [], ...input.facts.map((f) => f.evidencePin)])
    verifyPin(p);
  return reconcileInventory(catalog, input.facts).map((t) => ({ ...t, evidencePins: [...new Map([...t.evidencePins, ...input.inputEvidencePins ?? []].map((p) => [p.path + "|" + p.sha256, p])).values()] }));
}
var read5 = (path) => JSON.parse(readFileSync24(path, "utf8").replace(/^\uFEFF/, ""));
var init_inventory = __esm(() => {
  init_manifest();
  init_manifest();
  if (false) {}
});

// scripts/bench-runner/cli.ts
await init_native_stage_adapter();

// scripts/bench-runner/runner.ts
init_types();
init_manifest();
init_admission();
import { mkdirSync as mkdirSync9, writeFileSync as writeFileSync10, existsSync as existsSync16, copyFileSync, constants } from "fs";
import { join as join16, resolve as resolve21 } from "path";

// scripts/bench-runner/retention.ts
init_manifest();
import { createHash as createHash10 } from "crypto";
import { existsSync as existsSync14, mkdirSync as mkdirSync7, readFileSync as readFileSync19, writeFileSync as writeFileSync8 } from "fs";
import { isAbsolute as isAbsolute6, join as join14, relative as relative5, resolve as resolve19 } from "path";
function retainValidResult(m, c, r) {
  if (r.status !== "valid")
    return;
  demand(r.validResult && r.nativeClosed && r.financialClosed, "retain_requires_original_valid_and_exact_closure");
  const configured = m.adapterConfig.retainedRegistryDirectory;
  demand(typeof configured === "string" && isAbsolute6(configured), "retained_registry_directory_required");
  const directory = resolve19(configured), within = relative5(m.root, directory);
  demand(within && !within.startsWith("..") && !isAbsolute6(within), "registry_must_be_inside_reviewed_workspace");
  verifyPin(c.manifestPin);
  verifyPin(r.validResult.proofPin);
  for (const p of r.proofPins)
    verifyPin(p);
  const custody = pin(join14(c.runDir, "archived-result.json"));
  const key = createHash10("sha256").update(m.bench + ":" + m.taskId).digest("hex");
  const attempt = createHash10("sha256").update(c.attemptId).digest("hex").slice(0, 20);
  const record = {
    protocol: "novaeve-universal-retained-valid-v1",
    taskId: m.taskId,
    bench: m.bench,
    valid: true,
    rerunForbidden: true,
    passed: r.validResult.passed,
    outcome: r.validResult.outcome,
    taskPin: r.validResult.proofPin,
    proofPin: custody,
    manifestPin: c.manifestPin,
    originalConstraints: m.original,
    originalProofPins: r.proofPins,
    nativeClosed: true,
    financialClosed: true,
    attemptId: c.attemptId,
    scoreClassificationSource: "original-contract-and-original-candidate-artifacts",
    noNewGradeOrModelForRetention: true
  };
  mkdirSync7(directory, { recursive: true });
  const path = join14(directory, "universal-" + key + "-" + attempt + ".json");
  if (existsSync14(path)) {
    demand(JSON.stringify(JSON.parse(readFileSync19(path, "utf8"))) === JSON.stringify(record), "retained_result_conflict");
  } else
    writeFileSync8(path, JSON.stringify(record, null, 2) + `
`, { flag: "wx", mode: 384 });
  return pin(path);
}

// scripts/bench-runner/runner.ts
function validateResult(r) {
  demand(r && ["complete", "retryable", "invalid", "unknown", "valid"].includes(r.status) && typeof r.nativeClosed === "boolean" && typeof r.financialClosed === "boolean" && typeof r.candidateOrSubmissionPresent === "boolean", "adapter_result_schema");
  demand(r.proofPins.length > 0, "adapter_result_proof_required");
  for (const p of r.proofPins)
    verifyPin(p);
  if (r.status === "valid")
    demand(r.validResult && typeof r.validResult.passed === "boolean" && typeof r.validResult.outcome === "string", "valid_requires_original_acceptance_proof");
}
function archiveResult(r, runDir, context) {
  const directory = join16(runDir, "archived-proofs");
  mkdirSync9(directory, { recursive: true });
  const copies = [];
  const proofs = [...r.proofPins, ...r.validResult ? [r.validResult.proofPin] : [], ...Object.values(r.completedStages ?? {}).flatMap((x) => x.proofPins)];
  for (const p of proofs) {
    verifyPin(p);
    const target = join16(directory, p.sha256 + ".artifact");
    if (!existsSync16(target))
      copyFileSync(p.path, target, constants.COPYFILE_EXCL);
    const copy = pin(target);
    demand(copy.bytes === p.bytes && copy.sha256 === p.sha256, "archive_custody_mismatch");
    verifyPin(p);
    copies.push({ original: p, archived: copy });
  }
  const receipt = join16(runDir, "archived-result.json");
  writeFileSync10(receipt, JSON.stringify({ taskId: context?.taskId, bench: context?.bench, manifestPin: context?.manifestPin, result: r, copies }, null, 2) + `
`, { flag: "wx" });
  return { ...r, proofPins: [...r.proofPins, ...copies.map((p) => p.archived), pin(receipt)] };
}

class Runner {
  queue;
  getAdapter;
  constructor(queue, getAdapter3) {
    this.queue = queue;
    this.getAdapter = getAdapter3;
  }
  check(path) {
    const m = loadManifest(path);
    this.getAdapter(m.bench).validate(m);
    const key = this.queue.key(m.bench, m.taskId), t = this.queue.task(key);
    return { valid: true, taskKey: key, imported: !!t, permanentValid: !!t?.valid, quarantined: !!t?.quarantined, stages: STAGES.filter((s) => m.stages[s]).map((s) => ({ stage: s, queue: ["prepare", "qualify"].includes(s) ? "preparation" : "formal", effect: m.stages[s].effect, kind: m.stages[s].kind })), spawned: false, modelCalls: 0 };
  }
  nextStage(m) {
    const key = this.queue.key(m.bench, m.taskId), valid = !!this.queue.task(key)?.valid;
    return STAGES.find((s) => m.stages[s] && this.queue.stage(key, s)?.state !== "complete" && (!valid || ["cleanup", "reconcile", "archive"].includes(s)));
  }
  continuation(key, stage, spec) {
    if (!["grade", "cleanup", "reconcile", "archive"].includes(stage))
      return false;
    if (stage === "grade")
      return !!this.queue.task(key)?.valid || ["running", "complete"].includes(this.queue.stage(key, "solve")?.state);
    return !!this.queue.task(key)?.valid || !!this.queue.stage(key, "solve") || spec?.kind === "reuse" || spec?.effect === "read-only";
  }
  context(m, path, admission, id, stage, runDir) {
    return { attemptId: id, taskId: m.taskId, bench: m.bench, stage, runDir, manifestPath: resolve21(path), manifestPin: pin(path), admissionControlPath: resolve21(admission), inventoryTask: this.queue.inventory(this.queue.key(m.bench, m.taskId)) };
  }
  retrySuccessor(m, c, r) {
    if (r.status !== "retryable")
      return;
    const policyPin = m.adapterConfig.retryPolicyPin;
    if (!policyPin)
      return { retryBlocked: "reviewed_retry_policy_required" };
    try {
      const { deriveRetryManifest: deriveRetryManifest2 } = (init_recovery(), __toCommonJS(exports_recovery));
      const successor = deriveRetryManifest2({ manifestPath: c.manifestPath, context: c, result: r, policyPin });
      this.queue.event("retry-successor-awaiting-root-signature", this.queue.key(m.bench, m.taskId), c.attemptId, successor);
      return { retrySuccessor: successor };
    } catch (error) {
      const reason = String(error);
      this.queue.event("retry-derivation-blocked", this.queue.key(m.bench, m.taskId), c.attemptId, { reason });
      return { retryBlocked: reason };
    }
  }
  retention(m, c, r) {
    if (r.status !== "valid" || !r.nativeClosed || !r.financialClosed)
      return;
    try {
      return { retainedPin: retainValidResult(m, c, r) };
    } catch (error) {
      const pending = { reason: String(error), permanentValidNoRetry: true, manifestPin: c.manifestPin, proofPins: r.proofPins };
      this.queue.event("retention-sync-pending", this.queue.key(m.bench, m.taskId), c.attemptId, pending);
      return { retentionSyncPending: pending };
    }
  }
  async plan(o) {
    const m = loadManifest(o.manifestPath);
    this.getAdapter(m.bench).validate(m);
    const key = this.queue.key(m.bench, m.taskId), stage = o.stage ?? this.nextStage(m);
    demand(stage, "no_unfinished_stage");
    demand(!this.queue.task(key)?.valid || ["cleanup", "reconcile", "archive"].includes(stage), "valid_task_never_rerun");
    const existing = this.queue.planned(key, stage);
    const claim = existing ? { id: existing.id, runDir: existing.run_dir } : this.queue.claim(key, stage, pin(o.manifestPath), (id) => join16(m.artifactRoot, m.bench, m.taskId, id, stage), true);
    if (existing)
      demand(JSON.parse(existing.manifest_pin).sha256 === pin(o.manifestPath).sha256, "planned_manifest_changed");
    const context = this.context(m, o.manifestPath, o.admissionControlPath, claim.id, stage, claim.runDir);
    mkdirSync9(context.runDir, { recursive: true });
    const cp = join16(context.runDir, "planned-context.json");
    if (!existsSync16(cp))
      writeFileSync10(cp, JSON.stringify(context, null, 2) + `
`, { flag: "wx" });
    let binding;
    if (m.adapterConfig.bindingSpec && m.stages[stage].kind === "command") {
      const request = join16(context.runDir, "binding-request.json");
      if (existsSync16(request))
        binding = { requestPin: pin(request), draftPin: pin(join16(context.runDir, "root-entry.draft.json")) };
      else {
        const { prepareContextDraft: prepareContextDraft2 } = await Promise.resolve().then(() => (init_bindings(), exports_bindings));
        binding = prepareContextDraft2(m, context);
      }
    }
    return { state: "planned", attemptId: claim.id, contextPin: pin(cp), binding, spawned: false, newNativeModelCalls: 0 };
  }
  async runOne(o) {
    const m = loadManifest(o.manifestPath), adapter = this.getAdapter(m.bench);
    adapter.validate(m);
    if (o.checkOnly || o.dryRun)
      return this.check(o.manifestPath);
    if (m.adapterConfig.retryNotBeforeUtc)
      demand(Date.now() >= Date.parse(String(m.adapterConfig.retryNotBeforeUtc)), "retry_backoff_not_elapsed");
    const key = this.queue.key(m.bench, m.taskId), task = this.queue.task(key);
    demand(task, "inventory_import_required");
    demand(!task.quarantined && m.history.stateKnown, "unknown_history_quarantined");
    const prepared = o.attemptId ? this.queue.attempt(o.attemptId) : null;
    if (o.attemptId)
      demand(prepared?.state === "planned" && prepared.task_key === key && JSON.parse(prepared.manifest_pin).sha256 === pin(o.manifestPath).sha256, "exact_planned_attempt_required");
    const selectedStage = prepared?.stage ?? o.stage;
    if (task.valid && selectedStage)
      demand(["cleanup", "reconcile", "archive"].includes(selectedStage), "valid_task_never_rerun");
    const inventory = this.queue.inventory(key);
    demand(!["inflight", "quarantined"].includes(inventory.state), "inventory_not_admissible");
    demand((inventory.priorKnownUsd === undefined || m.original.priorKnownUsd >= inventory.priorKnownUsd) && (inventory.priorUnknownUsd === undefined || m.original.priorUnknownUsd >= inventory.priorUnknownUsd), "inventory_cost_exposure_cannot_reset");
    const first = selectedStage ?? this.nextStage(m);
    if (!first)
      return { taskKey: key, state: task.valid ? "valid-archived" : "complete", results: [], spawned: false };
    if (this.continuation(key, first, m.stages[first]))
      assertContinuation(o.admissionControlPath, first);
    else {
      demand(!task.valid && !m.history.validResultPins.length && inventory.state !== "valid", "valid_task_never_rerun");
      assertAdmission(o.admissionControlPath, key, first, inventory.state === "recoverable");
    }
    let originalRecoveryProofPin;
    if (!task.valid && (m.history.originalResultRecoveryRequired || inventory.state === "recoverable")) {
      demand(adapter.recover, "original_candidate_recovery_required");
      const c = this.context(m, o.manifestPath, o.admissionControlPath, "original-recovery", "reconcile", join16(m.artifactRoot, m.bench, m.taskId, "original-recovery-" + crypto.randomUUID()));
      const raw = await adapter.recover(m, c);
      validateResult(raw);
      const r = archiveResult(raw, c.runDir, c), retention = this.retention(m, c, r), state = this.queue.originalRecovery(key, r);
      originalRecoveryProofPin = pin(join16(c.runDir, "archived-result.json"));
      if (state === "valid")
        return { taskKey: key, state: "retained-valid", result: r, spawned: false, ...retention };
    }
    const results = [];
    for (const stage of STAGES) {
      if (selectedStage && stage !== selectedStage)
        continue;
      const spec = m.stages[stage];
      if (!spec)
        continue;
      const prior = this.queue.stage(key, stage);
      if (prior?.state === "complete") {
        const r = JSON.parse(prior.result);
        for (const p of r.proofPins)
          verifyPin(p);
        results.push({ stage, reused: true, proofPins: r.proofPins });
        continue;
      }
      if (this.queue.task(key).valid && !["cleanup", "reconcile", "archive"].includes(stage))
        continue;
      if (this.continuation(key, stage, m.stages[stage]))
        assertContinuation(o.admissionControlPath, stage);
      else
        assertAdmission(o.admissionControlPath, key, stage, !!prior && prior.state !== "planned");
      if (stage === "solve") {
        demand(!results.some((x) => x.result?.candidateOrSubmissionPresent), "candidate_requires_original_result_recovery");
        for (const before of ["prepare", "qualify"])
          if (m.stages[before])
            demand(this.queue.stage(key, before)?.state === "complete", "prerequisite_stage_not_complete");
      }
      if (m.adapterConfig.bindingSpec && spec.kind === "command" && !prepared) {
        const planned = await this.plan({ ...o, stage });
        return { ...planned, taskKey: key, state: "planned-awaiting-root-signature", results };
      }
      const claim = prepared ? { id: prepared.id, runDir: prepared.run_dir } : this.queue.claim(key, stage, pin(o.manifestPath), (id) => join16(m.artifactRoot, m.bench, m.taskId, id, stage));
      mkdirSync9(claim.runDir, { recursive: true });
      let context = this.context(m, o.manifestPath, o.admissionControlPath, claim.id, stage, claim.runDir);
      if (originalRecoveryProofPin)
        context.originalRecoveryProofPin = originalRecoveryProofPin;
      if (m.adapterConfig.bindingSpec && spec.kind === "command") {
        const { loadPreparedContext: loadPreparedContext2 } = await Promise.resolve().then(() => (init_bindings(), exports_bindings));
        context = loadPreparedContext2(m, context);
      }
      if (prepared)
        this.queue.activatePlanned(claim.id);
      writeFileSync10(join16(claim.runDir, "intent-context.json"), JSON.stringify(context, null, 2) + `
`, { flag: "wx" });
      this.queue.started(claim.id);
      try {
        const raw = await adapter.execute(m, spec, context);
        validateResult(raw);
        const r = archiveResult(raw, claim.runDir, context), retention = this.retention(m, context, r), state = this.queue.finish(claim.id, r, spec);
        results.push({ stage, attemptId: claim.id, state, result: r, ...retention, ...this.retrySuccessor(m, context, r) });
        if (state !== "complete")
          return { taskKey: key, state, results };
      } catch (error) {
        this.queue.quarantine(claim.id, String(error));
        return { taskKey: key, state: "unknown", attemptId: claim.id, reason: String(error), results, noAutomaticRespawn: true };
      }
    }
    return { taskKey: key, state: this.queue.task(key).valid ? "valid-archived" : "complete", results };
  }
  async reconcile(attemptId, manifestPath, admissionControlPath) {
    const a = this.queue.attempt(attemptId);
    demand(a?.state === "unknown", "unknown_attempt_required");
    const m = loadManifest(manifestPath);
    demand(this.queue.key(m.bench, m.taskId) === a.task_key, "reconcile_identity");
    verifyPin(JSON.parse(a.manifest_pin));
    demand(pin(manifestPath).sha256 === JSON.parse(a.manifest_pin).sha256, "reconcile_original_manifest");
    const adapter = this.getAdapter(m.bench);
    demand(adapter.recover, "adapter_cannot_prove_recovery");
    const c = this.context(m, manifestPath, admissionControlPath, attemptId, a.stage, a.run_dir);
    const raw = await adapter.recover(m, c);
    validateResult(raw);
    const archivedContext = { ...c, runDir: join16(a.run_dir, "reconciliation-" + crypto.randomUUID()) }, result = archiveResult(raw, archivedContext.runDir, archivedContext), retention = this.retention(m, archivedContext, result);
    return { attemptId, state: this.queue.reconcile(attemptId, result), result, ...retention, ...this.retrySuccessor(m, c, result) };
  }
  enqueue(manifestPath, admissionPath) {
    const m = loadManifest(manifestPath);
    this.getAdapter(m.bench).validate(m);
    const stage = this.nextStage(m);
    demand(stage, "no_unfinished_stage");
    const key = this.queue.key(m.bench, m.taskId);
    this.queue.enqueue(key, resolve21(manifestPath), pin(manifestPath), resolve21(admissionPath), ["prepare", "qualify"].includes(stage) ? "preparation" : "formal");
    return { taskKey: key, queued: true, stage, spawned: false };
  }
  async dispatch(options = {}) {
    const running = new Map;
    const errors = [];
    do {
      let launched = 0;
      for (const job of this.queue.queuedJobs()) {
        if (options.signal?.aborted)
          break;
        try {
          verifyPin(JSON.parse(job.manifest_pin));
          const m = loadManifest(job.manifest_path);
          demand(job.task_key === this.queue.key(m.bench, m.taskId), "queued_manifest_task_identity");
          const stage = this.nextStage(m);
          if (!stage) {
            this.queue.finishJob(job.task_key, "closed", { complete: true });
            continue;
          }
          if (this.continuation(job.task_key, stage, m.stages[stage]))
            assertContinuation(job.admission_path, stage);
          else
            assertAdmission(job.admission_path, job.task_key, stage, !!this.queue.stage(job.task_key, stage) && !this.queue.planned(job.task_key, stage));
          const planned = this.queue.planned(job.task_key, stage);
          if (m.adapterConfig.bindingSpec && m.stages[stage].kind === "command") {
            if (!planned) {
              await this.plan({ manifestPath: job.manifest_path, admissionControlPath: job.admission_path, stage });
              this.queue.finishJob(job.task_key, "blocked", { reason: "awaiting_root_signature" });
              continue;
            }
            const { loadPreparedContext: loadPreparedContext2 } = await Promise.resolve().then(() => (init_bindings(), exports_bindings));
            loadPreparedContext2(m, this.context(m, job.manifest_path, job.admission_path, planned.id, stage, planned.run_dir));
          }
          this.queue.claimJob(job.task_key, options.maxConcurrentStages ?? 16, options.preparationLimit ?? 4);
          launched++;
          const work = (async () => {
            try {
              const result = await this.runOne({ manifestPath: job.manifest_path, admissionControlPath: job.admission_path, stage, attemptId: planned?.id });
              const next = this.nextStage(m), blocked = ["unknown", "retryable", "planned-awaiting-root-signature"].includes(result.state);
              this.queue.finishJob(job.task_key, blocked ? "blocked" : next ? "queued" : "closed", result, next ? ["prepare", "qualify"].includes(next) ? "preparation" : "formal" : undefined);
            } catch (error) {
              this.queue.finishJob(job.task_key, "blocked", { reason: String(error), noAutomaticRetry: true });
            } finally {
              running.delete(job.task_key);
            }
          })();
          running.set(job.task_key, work);
        } catch (error) {
          errors.push({ taskKey: job.task_key, error: String(error) });
          if (errors.length > 64)
            errors.shift();
          if (!/admission_closed|not_allowed|priority|preparation_limit|dispatcher_stage_limit/.test(String(error)))
            this.queue.finishJob(job.task_key, "blocked", { reason: String(error) });
        }
      }
      if (!options.watch) {
        await Promise.all(running.values());
        if (launched > 0 && this.queue.queuedJobs().length > 0)
          continue;
        return { dispatchCompleted: true, errors, status: this.queue.status() };
      }
      if (!options.signal?.aborted)
        await new Promise((r) => setTimeout(r, Math.min(1000, Math.max(10, options.pollMs ?? 250))));
    } while (!options.signal?.aborted);
    await Promise.all(running.values());
    return { stoppedIntake: true, existingStagesNaturallyFinished: true, errors, status: this.queue.status() };
  }
}
// scripts/bench-runner/queue.ts
init_types();
init_manifest();
import { Database as Database7 } from "bun:sqlite";
import { randomUUID as randomUUID2 } from "crypto";
import { mkdirSync as mkdirSync10, readFileSync as readFileSync22 } from "fs";
import { dirname as dirname6 } from "path";

class DurableQueue {
  db;
  closed = false;
  constructor(path) {
    mkdirSync10(dirname6(path), { recursive: true });
    this.db = new Database7(path, { create: true });
    this.db.exec(`PRAGMA journal_mode=WAL;PRAGMA synchronous=FULL;PRAGMA busy_timeout=5000;
 CREATE TABLE IF NOT EXISTS tasks(key TEXT PRIMARY KEY,bench TEXT NOT NULL,task_id TEXT NOT NULL,inventory TEXT NOT NULL,valid INTEGER NOT NULL DEFAULT 0,quarantined INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS stages(task_key TEXT NOT NULL,stage TEXT NOT NULL,state TEXT NOT NULL,attempt_id TEXT,result TEXT,PRIMARY KEY(task_key,stage));
 CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,task_key TEXT NOT NULL,stage TEXT NOT NULL,queue_class TEXT NOT NULL CHECK(queue_class IN ('preparation','formal')),state TEXT NOT NULL,manifest_pin TEXT NOT NULL,run_dir TEXT NOT NULL,created_at TEXT NOT NULL,closed_at TEXT,result TEXT);
 CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,kind TEXT NOT NULL,task_key TEXT,attempt_id TEXT,data TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS jobs(task_key TEXT PRIMARY KEY,manifest_path TEXT NOT NULL,manifest_pin TEXT NOT NULL,admission_path TEXT NOT NULL,queue_class TEXT NOT NULL,state TEXT NOT NULL,updated_at TEXT NOT NULL,last_result TEXT);`);
  }
  close() {
    if (this.closed)
      return;
    this.db.clearQueryCache();
    this.db.close(true);
    this.closed = true;
  }
  query(sql) {
    const db = this.db;
    return Object.fromEntries(["get", "all", "run"].map((method) => [method, (...args) => {
      const statement = db.prepare(sql);
      try {
        return statement[method](...args);
      } finally {
        statement.finalize();
      }
    }]));
  }
  key(bench, taskId) {
    return bench + ":" + taskId;
  }
  transaction(fn) {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const x = fn();
      this.db.exec("COMMIT");
      return x;
    } catch (e) {
      this.db.exec("ROLLBACK");
      throw e;
    }
  }
  event(kind, key, id, data) {
    this.query("INSERT INTO events(at,kind,task_key,attempt_id,data) VALUES(?,?,?,?,?)").run(new Date().toISOString(), kind, key, id, JSON.stringify(data));
  }
  importInventory(rows) {
    this.transaction(() => {
      for (const r of rows) {
        demand(["terminal-bench", "skillsbench"].includes(r.bench) && typeof r.taskId === "string" && r.taskId.length > 0 && r.evidencePins.length > 0 && ["valid", "inflight", "recoverable", "never-started", "quarantined"].includes(r.state), "inventory_state");
        demand(Object.keys(r.successfulStages).every((s) => STAGES.includes(s)), "inventory_unknown_stage");
        for (const p of r.evidencePins)
          verifyPin(p);
        for (const p of Object.values(r.successfulStages).flat())
          verifyPin(p);
        const key = this.key(r.bench, r.taskId), old = this.task(key);
        demand(!old || !old.valid || r.state === "valid", "valid_inventory_cannot_regress");
        this.query("INSERT INTO tasks(key,bench,task_id,inventory,valid,quarantined) VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET inventory=excluded.inventory,valid=MAX(tasks.valid,excluded.valid),quarantined=MAX(tasks.quarantined,excluded.quarantined)").run(key, r.bench, r.taskId, JSON.stringify(r), r.state === "valid" ? 1 : 0, ["inflight", "quarantined"].includes(r.state) ? 1 : 0);
        for (const [stage, pins] of Object.entries(r.successfulStages)) {
          demand(pins.length > 0, "empty_stage_success");
          this.query("INSERT INTO stages(task_key,stage,state,result) VALUES(?,?,'complete',?) ON CONFLICT(task_key,stage) DO NOTHING").run(key, stage, JSON.stringify({ proofPins: pins, reusedOriginal: true }));
        }
        this.event("inventory-import", key, null, { state: r.state, evidencePins: r.evidencePins });
      }
    });
  }
  task(key) {
    return this.query("SELECT * FROM tasks WHERE key=?").get(key);
  }
  inventory(key) {
    const t = this.task(key);
    demand(t, "task_not_imported");
    return JSON.parse(t.inventory);
  }
  stage(key, stage) {
    return this.query("SELECT * FROM stages WHERE task_key=? AND stage=?").get(key, stage);
  }
  claim(key, stage, manifestPin, runDir, planned = false) {
    return this.transaction(() => {
      verifyPin(manifestPin);
      const t = this.task(key);
      demand(t && !t.quarantined, "task_unknown_or_quarantined");
      demand(!t.valid || ["cleanup", "reconcile", "archive"].includes(stage), "valid_task_rerun_forbidden");
      demand(!this.query("SELECT id FROM attempts WHERE task_key=? AND state IN ('planned','intent','running','unknown')").get(key), "unresolved_attempt_prevents_duplicate");
      const old = this.stage(key, stage);
      demand(!old || old.state === "retryable", "stage_already_complete_active_or_held");
      const id = randomUUID2(), dir = runDir(id), queueClass = ["prepare", "qualify"].includes(stage) ? "preparation" : "formal";
      this.query("INSERT INTO attempts(id,task_key,stage,queue_class,state,manifest_pin,run_dir,created_at) VALUES(?,?,?,?,?,?,?,?)").run(id, key, stage, queueClass, planned ? "planned" : "intent", JSON.stringify(manifestPin), dir, new Date().toISOString());
      this.query("INSERT INTO stages(task_key,stage,state,attempt_id) VALUES(?,?,?,?) ON CONFLICT(task_key,stage) DO UPDATE SET state=excluded.state,attempt_id=excluded.attempt_id").run(key, stage, planned ? "planned" : "intent", id);
      this.event(planned ? "planned" : "intent", key, id, { manifestPin, runDir: dir, queue: queueClass });
      return { id, runDir: dir };
    });
  }
  started(id) {
    this.transaction(() => {
      const a = this.attempt(id);
      demand(a?.state === "intent", "only_intent_can_start");
      this.query("UPDATE attempts SET state='running' WHERE id=?").run(id);
      this.query("UPDATE stages SET state='running' WHERE attempt_id=?").run(id);
      this.event("running", a.task_key, id, { runtimeMustWriteExactProcessReceipt: true });
    });
  }
  attempt(id) {
    return this.query("SELECT * FROM attempts WHERE id=?").get(id);
  }
  finish(id, r, spec) {
    for (const p of r.proofPins)
      verifyPin(p);
    demand(r.proofPins.length > 0, "stage_result_requires_evidence");
    demand(r.status !== "valid" || !!r.validResult, "valid_proof_required");
    if (r.validResult) {
      verifyPin(r.validResult.proofPin);
      demand(r.status === "valid", "valid_result_status_required");
    }
    for (const [s, proof] of Object.entries(r.completedStages ?? {})) {
      demand(spec?.bundledStages?.includes(s) && proof.proofPins.length > 0, "undeclared_bundled_stage");
      for (const p of proof.proofPins)
        verifyPin(p);
    }
    return this.transaction(() => {
      const a = this.attempt(id);
      demand(a && ["running", "intent", "unknown"].includes(a.state), "attempt_not_finishable");
      const closed = r.nativeClosed && r.financialClosed, noEffects = spec?.kind === "reuse" || spec?.effect === "read-only";
      let state = r.status === "valid" ? "complete" : r.status === "complete" && (closed || noEffects) ? "complete" : r.status === "retryable" && closed && !r.candidateOrSubmissionPresent ? "retryable" : "unknown";
      if (r.status === "valid" && !closed)
        state = "unknown";
      this.query("UPDATE attempts SET state=?,closed_at=?,result=? WHERE id=?").run(state, closed || noEffects ? new Date().toISOString() : null, JSON.stringify(r), id);
      this.query("UPDATE stages SET state=?,result=? WHERE attempt_id=?").run(state, JSON.stringify(r), id);
      if (state === "complete")
        for (const [stage, proof] of Object.entries(r.completedStages ?? {}))
          this.query("INSERT INTO stages(task_key,stage,state,result) VALUES(?,?,'complete',?) ON CONFLICT(task_key,stage) DO UPDATE SET state='complete',result=excluded.result").run(a.task_key, stage, JSON.stringify({ proofPins: proof.proofPins, verifiedBundledAttempt: id }));
      if (r.status === "valid")
        this.query("UPDATE tasks SET valid=1 WHERE key=?").run(a.task_key);
      if (state === "unknown")
        this.query("UPDATE tasks SET quarantined=1 WHERE key=?").run(a.task_key);
      this.event("stage-result", a.task_key, id, { state, result: r });
      return state;
    });
  }
  quarantine(id, reason) {
    this.transaction(() => {
      const a = this.attempt(id);
      demand(a, "attempt_missing");
      this.query("UPDATE attempts SET state='unknown' WHERE id=?").run(id);
      this.query("UPDATE stages SET state='unknown' WHERE attempt_id=?").run(id);
      this.query("UPDATE tasks SET quarantined=1 WHERE key=?").run(a.task_key);
      this.event("quarantine", a.task_key, id, { reason });
    });
  }
  reconcile(id, r) {
    const a = this.attempt(id);
    demand(a?.state === "unknown", "only_unknown_reconciliation");
    demand(r.nativeClosed && r.financialClosed && r.proofPins.length > 0, "exact_closure_required");
    const s = this.finish(id, r);
    if (s !== "unknown")
      this.transaction(() => {
        this.query("UPDATE tasks SET quarantined=0 WHERE key=?").run(a.task_key);
        this.event("reconciled", a.task_key, id, { state: s });
      });
    return s;
  }
  recoverAfterRestart() {
    this.transaction(() => {
      const rows = this.query("SELECT id FROM attempts WHERE state IN ('intent','running')").all();
      for (const a of rows) {
        this.query("UPDATE attempts SET state='unknown' WHERE id=?").run(a.id);
        const x = this.attempt(a.id);
        this.query("UPDATE stages SET state='unknown' WHERE attempt_id=?").run(a.id);
        this.query("UPDATE tasks SET quarantined=1 WHERE key=?").run(x.task_key);
        this.event("restart-unresolved", x.task_key, a.id, { noAutomaticRespawn: true });
      }
    });
  }
  status() {
    return { tasks: this.query("SELECT key,valid,quarantined FROM tasks ORDER BY key").all(), stages: this.query("SELECT * FROM stages ORDER BY task_key,stage").all(), attempts: this.query("SELECT * FROM attempts ORDER BY created_at").all(), jobs: this.query("SELECT * FROM jobs ORDER BY task_key").all(), queues: this.query("SELECT queue_class,state,COUNT(*) AS count FROM jobs GROUP BY queue_class,state").all(), lastEvent: this.query("SELECT MAX(seq) AS seq FROM events").get(), resourcePool: "original-broker-only", actualSolverCount: null };
  }
  unresolved() {
    return Number(this.query("SELECT COUNT(*) AS n FROM attempts WHERE state IN ('intent','running','unknown')").get().n);
  }
  originalRecovery(key, r) {
    for (const p of r.proofPins)
      verifyPin(p);
    demand(r.proofPins.length > 0 && r.nativeClosed && r.financialClosed && (r.status === "valid" || !r.candidateOrSubmissionPresent) && ["complete", "retryable", "valid"].includes(r.status), "original_result_or_closed_recovery_required");
    if (r.status === "valid") {
      demand(r.validResult, "original_valid_proof_required");
      verifyPin(r.validResult.proofPin);
    }
    this.transaction(() => {
      if (r.status === "valid")
        this.query("UPDATE tasks SET valid=1 WHERE key=?").run(key);
      this.event("original-recovery", key, null, r);
    });
    return r.status;
  }
  enqueue(key, manifestPath, manifestPin, admissionPath, queueClass) {
    verifyPin(manifestPin);
    this.transaction(() => {
      const t = this.task(key);
      demand(t && !t.quarantined, "enqueue_unknown_task");
      const old = this.query("SELECT * FROM jobs WHERE task_key=?").get(key);
      demand(!old || ["closed", "blocked"].includes(old.state), "job_already_exists");
      this.query("INSERT INTO jobs(task_key,manifest_path,manifest_pin,admission_path,queue_class,state,updated_at) VALUES(?,?,?,?,?,'queued',?) ON CONFLICT(task_key) DO UPDATE SET manifest_path=excluded.manifest_path,manifest_pin=excluded.manifest_pin,admission_path=excluded.admission_path,queue_class=excluded.queue_class,state='queued',updated_at=excluded.updated_at").run(key, manifestPath, JSON.stringify(manifestPin), admissionPath, queueClass, new Date().toISOString());
      this.event("job-enqueued", key, null, { manifestPin, queueClass });
    });
  }
  queuedJobs() {
    return this.query("SELECT * FROM jobs WHERE state='queued' ORDER BY CASE queue_class WHEN 'formal' THEN 0 ELSE 1 END,updated_at,task_key").all();
  }
  claimJob(key, maxConcurrent = 16, prepLimit = 4) {
    return this.transaction(() => {
      demand(Number.isInteger(maxConcurrent) && maxConcurrent > 0 && maxConcurrent <= 16 && prepLimit >= 0 && prepLimit <= 4, "dispatcher_bounds");
      const job = this.query("SELECT * FROM jobs WHERE task_key=?").get(key);
      demand(job?.state === "queued", "job_not_queued");
      const active = this.query("SELECT queue_class,COUNT(*) AS n FROM jobs WHERE state='running' GROUP BY queue_class").all(), total = active.reduce((n, x) => n + x.n, 0), prep = active.find((x) => x.queue_class === "preparation")?.n ?? 0;
      demand(total < maxConcurrent, "dispatcher_stage_limit");
      if (job.queue_class === "preparation") {
        demand(prep < Math.min(prepLimit, Math.max(0, maxConcurrent - total)), "preparation_limit");
        demand(!this.query("SELECT task_key FROM jobs WHERE state='queued' AND queue_class='formal'").get(), "formal_ready_has_priority");
      }
      this.query("UPDATE jobs SET state='running',updated_at=? WHERE task_key=?").run(new Date().toISOString(), key);
      this.event("job-claimed", key, null, { queueClass: job.queue_class });
      return job;
    });
  }
  finishJob(key, state, result, queueClass) {
    this.transaction(() => {
      this.query("UPDATE jobs SET state=?,last_result=?,queue_class=COALESCE(?,queue_class),updated_at=? WHERE task_key=?").run(state, JSON.stringify(result), queueClass ?? null, new Date().toISOString(), key);
      this.event("job-result", key, null, { state, result });
    });
  }
  recoverJobsAfterRestart() {
    this.transaction(() => {
      const rows = this.query("SELECT task_key FROM jobs WHERE state='running'").all();
      for (const x of rows) {
        const unresolved = this.query("SELECT id FROM attempts WHERE task_key=? AND state IN ('intent','running','unknown')").get(x.task_key);
        if (!unresolved) {
          this.query("UPDATE jobs SET state='queued',updated_at=? WHERE task_key=?").run(new Date().toISOString(), x.task_key);
          this.event("job-recovered-no-effect", x.task_key, null, { plannedPreserved: true, spawnImpossibleBeforeIntent: true });
          continue;
        }
        this.query("UPDATE jobs SET state='blocked',updated_at=? WHERE task_key=?").run(new Date().toISOString(), x.task_key);
        this.query("UPDATE tasks SET quarantined=1 WHERE key=?").run(x.task_key);
        this.event("job-crash-gap", x.task_key, null, { unknown: true, noAutomaticRespawn: true });
      }
    });
  }
  planned(key, stage) {
    return this.query("SELECT * FROM attempts WHERE task_key=? AND stage=? AND state='planned'").get(key, stage);
  }
  activatePlanned(id) {
    this.transaction(() => {
      const a = this.attempt(id);
      demand(a?.state === "planned", "planned_attempt_required");
      const t = this.task(a.task_key);
      demand(t && !t.quarantined && (!t.valid || ["cleanup", "reconcile", "archive"].includes(a.stage)), "planned_task_not_eligible");
      demand(!this.query("SELECT id FROM attempts WHERE task_key=? AND id!=? AND state IN ('intent','running','unknown')").get(a.task_key, id), "other_unresolved_attempt");
      this.query("UPDATE attempts SET state='intent' WHERE id=?").run(id);
      this.query("UPDATE stages SET state='intent' WHERE attempt_id=?").run(id);
      this.event("planned-activated", a.task_key, id, { sameAttemptAndNonce: true });
    });
  }
  reconcileInventory(newRows, newInventoryPin, key, reviewPin) {
    verifyPin(newInventoryPin);
    verifyPin(reviewPin);
    const review = JSON.parse(readFileSync22(reviewPin.path, "utf8"));
    demand(review.protocol === "universal-inventory-reconciliation-v1" && review.rootReviewed === true && review.taskKey === key && review.nativeClosed === true && review.financialClosed === true && review.exactProcessesAbsent === true && review.historyCoverageComplete === true, "explicit_exact_inventory_review_required");
    demand(Date.parse(review.expiresAtUtc) > Date.now() && review.evidencePins?.length > 0, "fresh_inventory_review_required");
    for (const p of review.evidencePins)
      verifyPin(p);
    verifyPin(review.oldInventoryPin);
    verifyPin(review.newInventoryPin);
    demand(review.newInventoryPin.sha256 === newInventoryPin.sha256 && review.newInventoryPin.bytes === newInventoryPin.bytes && review.newInventoryPin.path === newInventoryPin.path, "review_new_inventory_pin_mismatch");
    const oldDocument = JSON.parse(readFileSync22(review.oldInventoryPin.path, "utf8")), oldRows = Array.isArray(oldDocument) ? oldDocument : oldDocument.tasks;
    demand(Array.isArray(oldRows), "old_inventory_schema");
    const oldMatches = oldRows.filter((x) => this.key(x.bench, x.taskId) === key), matches = newRows.filter((x) => this.key(x.bench, x.taskId) === key);
    demand(oldMatches.length === 1 && matches.length === 1, "review_task_unique");
    const old = oldMatches[0], next = matches[0];
    demand(["recoverable", "never-started"].includes(next.state), "review_must_not_promote_unknown_or_valid");
    for (const p of [...next.evidencePins, ...Object.values(next.successfulStages).flat()])
      verifyPin(p);
    demand(next.evidencePins.length > 0 && old.evidencePins.every((p) => next.evidencePins.some((q) => q.path === p.path && q.bytes === p.bytes && q.sha256 === p.sha256)), "original_inventory_evidence_must_be_retained");
    demand(old.priorRunIds.every((id) => next.priorRunIds.includes(id)) && (next.priorKnownUsd ?? 0) >= (old.priorKnownUsd ?? 0) && (next.priorUnknownUsd ?? 0) >= (old.priorUnknownUsd ?? 0), "original_runs_and_exposure_must_be_retained");
    if (next.state === "never-started")
      demand(review.neverStartedProven === true && old.priorRunIds.length === 0 && (old.priorKnownUsd ?? 0) === 0 && (old.priorUnknownUsd ?? 0) === 0, "unknown_is_not_never_started");
    return this.transaction(() => {
      verifyPin(reviewPin);
      verifyPin(newInventoryPin);
      const task = this.task(key);
      demand(task && !task.valid && task.quarantined, "only_nonvalid_quarantine_reconciliation");
      demand(JSON.stringify(JSON.parse(task.inventory)) === JSON.stringify(old), "old_inventory_not_current_task");
      demand(!this.query("SELECT id FROM attempts WHERE task_key=? AND state IN ('planned','intent','running','unknown')").get(key), "unresolved_attempt_prevents_inventory_reconciliation");
      demand(!this.query("SELECT task_key FROM jobs WHERE task_key=? AND state='running'").get(key), "running_job_prevents_inventory_reconciliation");
      this.query("UPDATE tasks SET inventory=?,quarantined=0 WHERE key=?").run(JSON.stringify(next), key);
      this.event("inventory-reconciled", key, null, { oldInventoryPin: review.oldInventoryPin, newInventoryPin, reviewPin, state: next.state });
      return { taskKey: key, state: next.state, quarantined: false, spawned: false };
    });
  }
}

// scripts/bench-runner/cli.ts
init_bindings();
import { resolve as resolve23 } from "path";
init_admission();
init_manifest();
import { readFileSync as readFileSync25 } from "fs";
async function main(argv = process.argv.slice(2)) {
  const command = argv[0], option = (name) => {
    const i = argv.indexOf("--" + name);
    if (i < 0 || !argv[i + 1])
      throw Error("required --" + name);
    return resolve23(argv[i + 1]);
  };
  if (command === "observe") {
    const { observe: observe2 } = await Promise.resolve().then(() => (init_observer(), exports_observer));
    const optional = (name) => {
      const i = argv.indexOf("--" + name);
      return i < 0 ? undefined : argv[i + 1];
    };
    const result = await observe2({ databasePath: option("db"), snapshotDirectory: option("snapshot-dir"), canonicalPath: optional("canonical"), pythonExecutable: optional("python") });
    console.log(JSON.stringify(result));
    return result;
  }
  const queue = new DurableQueue(option("db"));
  try {
    let result;
    if (command === "status")
      result = queue.status();
    else if (command === "import") {
      const { loadInventory: loadInventory2 } = await Promise.resolve().then(() => (init_inventory(), exports_inventory));
      const tasks = loadInventory2(option("inventory"));
      queue.importInventory(tasks);
      result = { imported: tasks.length, spawned: false };
    } else if (command === "reconcile-inventory") {
      const { loadInventory: loadInventory2 } = await Promise.resolve().then(() => (init_inventory(), exports_inventory));
      const path = option("inventory"), reviewPin = JSON.parse(readFileSync25(option("review"), "utf8"));
      const i = argv.indexOf("--task");
      if (i < 0 || !argv[i + 1])
        throw Error("required --task bench:taskId");
      result = queue.reconcileInventory(loadInventory2(path), pin(path), argv[i + 1], reviewPin);
    } else if (command === "drain")
      result = drainAdmission(option("admission"));
    else if (command === "resume")
      result = resumeAdmission(option("admission"), option("approval"), queue.unresolved());
    else if (command === "recover-state") {
      queue.recoverAfterRestart();
      queue.recoverJobsAfterRestart();
      result = { quarantined: true, noAutomaticRespawn: true };
    } else if (["check", "run-one", "reconcile", "plan", "enqueue", "dispatch"].includes(command)) {
      const { getAdapter: getAdapter3 } = await init_native_stage_adapter().then(() => exports_native_stage_adapter);
      const runner = new Runner(queue, getAdapter3);
      const optional = (name) => {
        const i = argv.indexOf("--" + name);
        return i < 0 ? undefined : argv[i + 1];
      };
      if (command === "check")
        result = runner.check(option("manifest"));
      else if (command === "reconcile")
        result = await runner.reconcile(optional("attempt"), option("manifest"), option("admission"));
      else if (command === "plan")
        result = await runner.plan({ manifestPath: option("manifest"), admissionControlPath: option("admission"), stage: optional("stage") });
      else if (command === "enqueue")
        result = runner.enqueue(option("manifest"), option("admission"));
      else if (command === "dispatch") {
        const stop = new AbortController;
        process.once("SIGINT", () => stop.abort());
        process.once("SIGTERM", () => stop.abort());
        result = await runner.dispatch({ watch: argv.includes("--watch"), signal: stop.signal, maxConcurrentStages: Number(optional("max-concurrent") ?? 16), preparationLimit: Number(optional("prep-limit") ?? 4) });
      } else
        result = await runner.runOne({ manifestPath: option("manifest"), admissionControlPath: option("admission"), dryRun: argv.includes("--dry-run"), checkOnly: argv.includes("--check-only"), stage: optional("stage"), attemptId: optional("attempt") });
    } else
      throw Error("commands: check import status plan enqueue run-one dispatch drain resume reconcile recover-state");
    console.log(JSON.stringify(result));
    return result;
  } finally {
    queue.close();
  }
}
if (import.meta.main)
  main().catch((error) => {
    console.error(JSON.stringify({ error: String(error), newAdmissionsFailClosed: true }));
    process.exitCode = 1;
  });
export {
  prepareContextDraft,
  nativeStageAdapter,
  main,
  loadPreparedContext,
  getAdapter2 as getAdapter,
  Runner,
  DurableQueue
};
