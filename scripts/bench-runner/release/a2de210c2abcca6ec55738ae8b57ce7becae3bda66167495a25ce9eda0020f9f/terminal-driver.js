// @bun
// scripts/bench-runner/python-module-binding.ts
import { readFileSync as readFileSync4 } from "fs";
import { dirname as dirname3, resolve as resolve4 } from "path";
import { pathToFileURL as pathToFileURL2 } from "url";

// scripts/bench-runner/manifest.ts
import { openSync, readSync, closeSync, lstatSync, readFileSync, realpathSync } from "fs";
import { createHash } from "crypto";
import { resolve, isAbsolute } from "path";

// scripts/bench-runner/types.ts
var STAGES = ["prepare", "qualify", "solve", "grade", "cleanup", "reconcile", "archive"];

// scripts/bench-runner/manifest.ts
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
var nonnegative = (n) => typeof n === "number" && Number.isFinite(n) && n >= 0;
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

// scripts/bench-runner/runtime.ts
import { readFileSync as readFileSync2, writeFileSync, mkdirSync, openSync as openSync2, closeSync as closeSync2, existsSync, readdirSync } from "fs";
import { resolve as resolve2, join, dirname } from "path";
import { dlopen, FFIType, ptr, toArrayBuffer } from "bun:ffi";
function filePin(path) {
  return pin(path);
}
function checkPin(pin2) {
  verifyPin(pin2);
}
function readPinned(pin2) {
  checkPin(pin2);
  return JSON.parse(readFileSync2(pin2.path, "utf8").replace(/^\uFEFF/, ""));
}
function wxJson(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(value, null, 2) + `
`, { flag: "wx", mode: 384 });
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
  const frozen = JSON.parse(readFileSync2(context.manifestPin.path, "utf8").replace(/^\uFEFF/, ""));
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
    const stat = readFileSync2("/proc/" + pid + "/stat", "utf8");
    const start = stat.slice(stat.lastIndexOf(")") + 2).split(" ")[19];
    const boot = readFileSync2("/proc/sys/kernel/random/boot_id", "utf8").trim();
    return { incarnation: boot + ":" + start, creation: start, kind: "linux-boot-id-start-ticks" };
  }
  throw Error("unsupported_exact_process_identity");
}

// scripts/bench-runner/qualified-driver-interfaces.ts
import { readFileSync as readFileSync3 } from "fs";
import { resolve as resolve3, dirname as dirname2 } from "path";
import { pathToFileURL } from "url";
import { createHash as createHash2 } from "crypto";
var need = (x, s) => {
  if (!x)
    throw Error(s);
};
var same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
var json = (p) => {
  checkPin(p);
  return JSON.parse(readFileSync3(p.path, "utf8"));
};
var at = (x, p) => p.split(".").reduce((v, k) => v && Object.hasOwn(v, k) ? v[k] : undefined, x);
var hash = (s) => createHash2("sha256").update(s).digest("hex");
function assertQualifiedInterfaceReview(m, d, entry) {
  const q = d.qualifiedInterfaces;
  need(q?.protocol === "bench-qualified-driver-interfaces-v1", "qualified_interfaces_protocol");
  const review = json(q.reviewPin);
  need(m.provenance.contractPins.some((p) => same(p, q.reviewPin)), "qualified_interfaces_review_not_bound");
  need(review.protocol === "bench-root-qualified-driver-interface-review-v1" && review.rootReviewed === true && review.taskId === m.taskId && review.bench === m.bench && same(review.qualification, q.qualification) && same(review.stand, q.stand) && same(review.gateway, q.gateway), "qualified_interfaces_root_review");
  need(same(entry.rootReview?.qualifiedInterfacesReviewPin, q.reviewPin), "qualified_interfaces_signed_entry_join");
  return q;
}
var pinSame = (a, b) => a && b && resolve3(a.path) === resolve3(b.path) && a.sha256 === b.sha256 && a.bytes === b.bytes;
function source(m, p) {
  checkPin(p);
  need(m.provenance.sourcePins.some((x) => pinSame(x, p)), "qualified_interface_source_not_bound:" + p.path);
}
function prepareQualifiedStandEvidence(m, d) {
  const q = d.qualifiedInterfaces, s = q.stand;
  need(same(s.campaignPin, d.imports.campaign.pin), "qualified_campaign_exact_import");
  const pins = [s.campaignPin, s.standEntryPin, s.launcherPin, s.pythonPin, s.observedSpawnPin, q.gateway.pin, q.gateway.ownerForwardGuard.pin, ...s.dependencyPins, ...s.dependencyManifestPins];
  for (const p of s.dependencyManifestPins) {
    const v = json(p);
    need(Array.isArray(v.sourcePins) && v.sourcePins.length > 0, "qualified_dependency_inventory");
    pins.push(...v.sourcePins);
  }
  for (const p of pins)
    source(m, p);
  source(m, q.gateway.pin);
  source(m, q.gateway.ownerForwardGuard.pin);
  const contents = readFileSync3(s.campaignPin.path, "utf8");
  need(contents.includes(JSON.stringify(q.gateway.pin.path.replaceAll("\\", "/"))) && contents.includes("providerGateway({...options,"), "qualified_campaign_gateway_callback_spread");
  const expected = "script:" + JSON.stringify(s.standEntryPin.path.replaceAll("\\", "/"));
  need(s.expectedExpression === expected && contents.split(expected).length === 2, "qualified_existing_absolute_stand_expression");
  need(contents.includes(JSON.stringify(s.launcherPin.path.replaceAll("\\", "/"))), "qualified_launcher_import");
  const launcher = readFileSync3(s.launcherPin.path, "utf8");
  need(launcher.includes(JSON.stringify(s.pythonPin.path.replaceAll("\\", "/"))) && launcher.includes("options.script"), "qualified_launcher_python_script");
  need(s.launcherSpawnImport === 'import { spawn } from "node:child_process";' && launcher.split(s.launcherSpawnImport).length === 2, "qualified_unique_spawn_import");
  need(Array.isArray(s.dynamicEdges) && s.dynamicEdges.length > 0, "qualified_dynamic_import_graph_required");
  for (const e of s.dynamicEdges) {
    source(m, e.fromPin);
    source(m, e.toPin);
    need(pins.some((p) => pinSame(p, e.fromPin)) && pins.some((p) => pinSame(p, e.toPin)), "qualified_dynamic_edge_inventory");
    need(typeof e.exactSourceFragment === "string" && e.exactSourceFragment.length > 8 && readFileSync3(e.fromPin.path, "utf8").split(e.exactSourceFragment).length === 2, "qualified_dynamic_edge_exact_fragment");
  }
  const launcherContents = launcher.replace(s.launcherSpawnImport, "import { observedSpawn as spawn } from " + JSON.stringify(s.observedSpawnPin.path.replaceAll("\\", "/")) + ";");
  return { contents, launcherContents, resolveDir: dirname2(s.campaignPin.path), standScriptPath: s.standEntryPin.path, proof: { protocol: "bench-qualified-existing-stand-proof-v1", dependencyPins: pins, dynamicEdges: s.dynamicEdges, originalCampaignPin: s.campaignPin, launcherPin: s.launcherPin, standEntryPin: s.standEntryPin, campaignUnchanged: true, injectedSourceSha256: hash(contents), originalSourceSha256: hash(contents), observedLauncherSourceSha256: hash(launcherContents), rootReviewPin: q.reviewPin, gatewayTransformation: { originalPin: q.gateway.pin, expectedBudgetExpression: q.gateway.expectedBudgetExpression, transformedSha256: hash(gatewayWithBeforeJournal(readFileSync3(q.gateway.pin.path, "utf8"), q.gateway)), awaitedBeforeJournal: true } } };
}
function validateQualifiedQualificationEvidence(m, d) {
  const q = d.qualifiedInterfaces, v = q.qualification;
  need(same(v.readinessPin, d.readinessPin), "qualified_readiness_exact_pin");
  for (const predicate of v.predicates) {
    need(typeof predicate.path === "string" && predicate.path.length > 0, "qualified_predicate_path");
    need(same(at(json(predicate.pin), predicate.path), predicate.equals), "qualified_original_predicate:" + predicate.path);
  }
  need(v.predicates.length > 0, "qualified_original_predicates_required");
  const context = json(v.contextPin), tasks = at(context, v.taskArrayPath);
  need(Array.isArray(tasks), "qualified_task_array");
  const matches = tasks.filter((x) => at(x, v.taskIdField) === m.taskId);
  need(matches.length === 1, "qualified_unique_original_task");
  const task = matches[0], env = at(task, v.environmentField);
  need(at(task, v.agentSecondsField) === m.original.solveSeconds && at(task, v.verifierSecondsField) === m.original.gradeSeconds && env?.cpus === m.original.cpu && env?.memory_mb === m.original.memoryMb, "qualified_original_task_clocks_environment");
  const rawResource = json(v.resourceProofPin), selectors = v.resourceSelectors;
  const resource = selectors ? { taskIds: at(rawResource, selectors.taskIds), memoryMb: at(rawResource, selectors.memoryMb), growthBytes: at(rawResource, selectors.growthBytes), slots: selectors.slots === null ? d.resource.slots : at(rawResource, selectors.slots) } : { ...rawResource, taskIds: [rawResource.taskId] };
  need(Array.isArray(resource.taskIds) && resource.taskIds.length === 1 && resource.taskIds[0] === m.taskId && resource.memoryMb === d.resource.memoryMb && resource.growthBytes === d.resource.growthBytes && resource.slots === 1 && resource.memoryMb >= env.memory_mb && resource.growthBytes >= env.storage_mb * 1024 ** 2, "qualified_aggregate_resource_distinct_from_actor");
  return { contextPin: v.contextPin, actor: env, aggregate: resource, readinessOriginalUnmodified: true };
}
function gatewayWithBeforeJournal(sourceText, g) {
  checkPin(g.pin);
  const a = g.expectedBudgetExpression;
  need(a === "gatewayBudgetDecision(journal,wire,budget.newAttemptMaxSpendUsd)" && sourceText.split(a).length === 2, "qualified_gateway_budget_unique_anchor");
  const admit = "admitted=journal.admit({route,rawRequest:wire});";
  need(sourceText.split(admit).length === 2 && sourceText.indexOf(a) < sourceText.indexOf(admit), "qualified_gateway_before_journal_order");
  return sourceText.replace(a, "gatewayBudgetDecision(journal,wire,Math.min(budget.newAttemptMaxSpendUsd,await options.benchBeforeJournalGuard()))");
}
async function installQualifiedStand(d, prepared, custodyDirectory) {
  const q = d.qualifiedInterfaces, s = q.stand;
  const observer = await import(pathToFileURL(s.observedSpawnPin.path).href);
  observer.configureObservedSpawn(custodyDirectory, prepared.proof.dependencyPins);
  const exact = (p) => new RegExp("^" + p.replaceAll("\\", "/").split("/").map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("[/\\\\]") + "$");
  Bun.plugin({ name: "qualified-existing-stand-" + prepared.proof.injectedSourceSha256, setup(build) {
    build.onLoad({ filter: exact(s.launcherPin.path) }, () => {
      checkPin(s.launcherPin);
      return { contents: prepared.launcherContents, loader: "ts", resolveDir: dirname2(s.launcherPin.path) };
    });
    build.onLoad({ filter: exact(q.gateway.pin.path) }, () => {
      checkPin(q.gateway.pin);
      return { contents: gatewayWithBeforeJournal(readFileSync3(q.gateway.pin.path, "utf8"), q.gateway), loader: "ts", resolveDir: dirname2(q.gateway.pin.path) };
    });
  } });
}
function applyStandardOwnedEnvironment(m, d, lease, pid = process.pid) {
  need(Number.isSafeInteger(pid) && pid > 0 && typeof lease.token === "string" && lease.token.length > 0, "actual_owned_lease_token_required");
  process.env.NOVAEVE_RESOURCE_PARENT_PID = String(pid);
  process.env.NOVAEVE_RESOURCE_LEASE_PID = String(pid);
  process.env.NOVAEVE_RESOURCE_MEMORY_MB = String(d.resource.memoryMb);
  process.env.NOVAEVE_RESOURCE_GROWTH_BYTES = String(d.resource.growthBytes);
  process.env.NOVAEVE_RESOURCE_BENCH = m.bench;
  process.env.NOVAEVE_RESOURCE_TOKEN = lease.token;
  process.env.NOVAEVE_RESOURCE_SLOTS = "1";
}
async function qualifiedCampaignCallbacks(m, d, freshMaximum) {
  if (!d.qualifiedInterfaces)
    return {};
  const q = d.qualifiedInterfaces, g = q.gateway;
  source(m, g.pin);
  source(m, g.ownerForwardGuard.pin);
  const mod = await import(pathToFileURL(g.ownerForwardGuard.pin.path).href), fn = mod[g.ownerForwardGuard.export];
  need(typeof fn === "function", "qualified_owner_forward_export");
  const guarded = async () => {
    const max = await freshMaximum();
    need(Number.isFinite(max) && max > 0, "qualified_current_parent_budget_exhausted");
    await fn();
    return max;
  };
  return { benchBeforeJournalGuard: guarded, ownerForwardGuard: async () => {
    await guarded();
  } };
}
function prepareQualifiedStand(m, d, entry) {
  assertQualifiedInterfaceReview(m, d, entry);
  return prepareQualifiedStandEvidence(m, d);
}
function validateQualifiedQualification(m, d, entry) {
  assertQualifiedInterfaceReview(m, d, entry);
  return validateQualifiedQualificationEvidence(m, d);
}

// scripts/bench-runner/python-module-binding.ts
var need2 = (x, s) => {
  if (!x)
    throw Error(s);
};
var same2 = (a, b) => JSON.stringify(a) === JSON.stringify(b);
var eq = (a, b) => a?.sha256 === b?.sha256 && a?.bytes === b?.bytes && resolve4(a.path) === resolve4(b.path);
function preparePythonModuleBinding(m, d, entry) {
  const q = d.qualifiedInterfaces, b = q?.pythonBindings;
  need2(b?.protocol === "bench-qualified-python-module-binding-contract-v1", "qualified_python_binding_contract");
  const review = readPinned(q.reviewPin);
  need2(review.rootReviewed === true && same2(review.pythonBindings, b) && same2(entry.rootReview?.qualifiedInterfacesReviewPin, q.reviewPin), "qualified_python_binding_root_signature_join");
  const config = readPinned(b.configPin);
  need2(config.protocol === "bench-qualified-python-module-bindings-v1" && eq(config.originalStandEntryPin, q.stand.standEntryPin), "qualified_python_binding_original_stand");
  const pins = [b.bootstrapPin, b.configPin, config.originalStandEntryPin, config.checker.runnerPin, config.checker.reporterPin, ...config.modules.flatMap((x) => [x.sourcePin, x.originalPin].filter(Boolean))];
  for (const p of pins) {
    checkPin(p);
    need2([...m.provenance.sourcePins, ...m.provenance.contractPins].some((x) => eq(x, p)), "qualified_python_binding_pin_not_bound:" + p.path);
  }
  need2(new Set(config.modules.map((x) => x.name)).size === config.modules.length, "qualified_python_unique_module_names");
  need2(config.modules.filter((x) => x.kind === "checker-phase-source-bridge").length === 1, "qualified_python_unique_checker_bridge");
  need2(config.modules.some((x) => x.name === "nodeid_phase_reporter" && eq(x.sourcePin, config.checker.reporterPin)), "qualified_reporter_import_same_uploaded_source");
  for (const module of config.modules.filter((x) => x.kind === "checker-phase-source-bridge")) {
    const text = readFileSync4(module.originalPin.path, "utf8");
    for (const anchor of ["runner=Path(__file__).with_name('checker_runner.py');", "native.upload(runner,checker,'/opt/pipeline-checker/checker_runner.py');", "{'name':name,'missing':request is None,'receipt':capture_receipt}", "assert receipt['closeObserved'] and not receipt.get('timedOut') and receipt['exitCode']==0;"])
      need2(text.split(anchor).length === 2, "qualified_python_checker_bridge_anchor");
  }
  return { contract: b, config, pins };
}
function bindLauncherPythonArgs(contents, contract) {
  need2(contents.includes('const args=["-B","-X","utf8",options.script,'), "qualified_python_exact_original_script_argv");
  const a = "const child=spawn(python,args,";
  need2(contents.split(a).length === 2, "qualified_python_unique_launcher_spawn");
  return contents.replace(a, 'const child=spawn(python,["-B","-X","utf8",' + JSON.stringify(contract.bootstrapPin.path) + ',"--bindings",' + JSON.stringify(contract.configPin.path) + ',"--original-script",options.script,"--",...args.slice(4)],');
}
async function installQualifiedPythonBindings(m, d, entry, prepared, custodyDirectory) {
  const binding = preparePythonModuleBinding(m, d, entry), q = d.qualifiedInterfaces, s = q.stand, observer = await import(pathToFileURL2(s.observedSpawnPin.path).href);
  observer.configureObservedSpawn(custodyDirectory, [...prepared.proof.dependencyPins, ...binding.pins]);
  const launcherContents = bindLauncherPythonArgs(prepared.launcherContents, binding.contract), exact = (p) => new RegExp("^" + p.replaceAll("\\", "/").split("/").map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("[/\\\\]") + "$");
  Bun.plugin({ name: "qualified-python-module-binding-" + binding.contract.configPin.sha256, setup(build) {
    build.onLoad({ filter: exact(s.launcherPin.path) }, () => {
      checkPin(s.launcherPin);
      return { contents: launcherContents, loader: "ts", resolveDir: dirname3(s.launcherPin.path) };
    });
    build.onLoad({ filter: exact(q.gateway.pin.path) }, () => {
      checkPin(q.gateway.pin);
      return { contents: gatewayWithBeforeJournal(readFileSync4(q.gateway.pin.path, "utf8"), q.gateway), loader: "ts", resolveDir: dirname3(q.gateway.pin.path) };
    });
  } });
  return { protocol: "bench-qualified-python-module-binding-proof-v1", configPin: binding.contract.configPin, bootstrapPin: binding.contract.bootstrapPin, sourcePins: binding.pins, originalSourcesUnchanged: true };
}

// scripts/bench-runner/signed-owned-environment.ts
import { readFileSync as readFileSync5 } from "fs";
var need3 = (x, s) => {
  if (!x)
    throw Error(s);
};
var supported = ["NOVAEVE_RESOURCE_PARENT_PID", "NOVAEVE_RESOURCE_LEASE_PID", "NOVAEVE_RESOURCE_MEMORY_MB", "NOVAEVE_RESOURCE_GROWTH_BYTES", "NOVAEVE_RESOURCE_BENCH", "NOVAEVE_RESOURCE_TOKEN", "NOVAEVE_RESOURCE_SLOTS", "NOVAEVE_ROOT_ONLY_DISPATCH"];
function inspectStandardLauncherEnvironment(d) {
  if (!d.qualifiedInterfaces)
    return [];
  const p = d.qualifiedInterfaces.stand.launcherPin;
  checkPin(p);
  const source2 = readFileSync5(p.path, "utf8"), matches = [...source2.matchAll(/for\s*\(const key of (\[[^\]\r\n]+\])\)\s*\{demand\(process\.env\[key\]/g)];
  need3(matches.length === 1, "qualified_unique_required_environment_loop");
  const names = [...matches[0][1].matchAll(/'([A-Z][A-Z0-9_]+)'/g)].map((x) => x[1]);
  need3(names.length > 0 && new Set(names).size === names.length && matches[0][1].replace(/'([A-Z][A-Z0-9_]+)'/g, "").replace(/[\s,\[\]]/g, "") === "", "qualified_literal_required_environment_names");
  need3(names.every((k) => supported.includes(k)), "qualified_unsupported_required_environment");
  return names;
}
function verifyStandardOwnedEnvironment(m, d, lease, dispatch) {
  const keys = inspectStandardLauncherEnvironment(d);
  if (!d.qualifiedInterfaces)
    return { requiredKeys: keys, actualRequiredEnvironmentVerified: true };
  need3(dispatch.protocol === "bench-actual-signed-root-dispatch-v1" && dispatch.actualPid === process.pid, "standard_environment_requires_actual_signed_dispatch");
  need3(typeof lease.token === "string" && lease.token.length > 0 && lease.ownerIncarnation === processIdentity(process.pid).incarnation && lease.memoryMb === d.resource.memoryMb && lease.plannedGrowthBytes === d.resource.growthBytes, "standard_environment_requires_actual_incarnated_lease");
  const values = { NOVAEVE_RESOURCE_PARENT_PID: String(process.pid), NOVAEVE_RESOURCE_LEASE_PID: String(process.pid), NOVAEVE_RESOURCE_MEMORY_MB: String(lease.memoryMb), NOVAEVE_RESOURCE_GROWTH_BYTES: String(lease.plannedGrowthBytes), NOVAEVE_RESOURCE_BENCH: m.bench, NOVAEVE_RESOURCE_TOKEN: lease.token, NOVAEVE_RESOURCE_SLOTS: "1", NOVAEVE_ROOT_ONLY_DISPATCH: "1" };
  for (const key of keys)
    need3(process.env[key] === values[key], "actual_standard_environment_mismatch:" + key);
  return { protocol: "bench-actual-owned-launcher-environment-v1", requiredKeys: keys, actualRequiredEnvironmentVerified: true, actualPid: process.pid, actualOwnerIncarnation: lease.ownerIncarnation, slots: 1, memoryMb: lease.memoryMb, growthBytes: lease.plannedGrowthBytes, secretTokenExcluded: true, signedEntryPin: dispatch.signedEntryPin };
}

// scripts/bench-runner/signed-dispatch-contract.ts
import { join as join3 } from "path";

// scripts/bench-runner/bindings.ts
import { verify } from "crypto";
import { readFileSync as readFileSync6, existsSync as existsSync2 } from "fs";
import { join as join2, resolve as resolve5 } from "path";
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
    OUTPUT: resolve5(s.output.root, s.output.prefix + c.attemptId),
    RECOVERY_ENTRY: join2(c.runDir, "recovery.entry.json"),
    ENTRY_ENVELOPE: join2(c.runDir, "root-entry.signed.json"),
    MANIFEST_PATH: c.manifestPath,
    CONTEXT_PATH: join2(c.runDir, "intent-context.json"),
    MANIFEST: c.manifestPath,
    CONTEXT: join2(c.runDir, "intent-context.json")
  };
  for (const [key, input] of Object.entries(s.inputs))
    values[key] = input.select === "path" ? resolve5(input.pin.path) : input.pin.sha256;
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
function loadPreparedContext(m, c, readOnly = false) {
  checkPin(c.manifestPin);
  const s = specFor(m, c.stage), values = valuesFor(s, c), envelope = JSON.parse(readFileSync6(values.ENTRY_ENVELOPE, "utf8").replace(/^\uFEFF/, ""));
  requireValue(envelope.protocol === "novaeve-root-signed-entry-v4" && envelope.entry && typeof envelope.signature === "string", "root_envelope_required");
  requireValue(verify(null, Buffer.from(JSON.stringify(envelope.entry)), readFileSync6(s.authorityPin.path), Buffer.from(envelope.signature, "base64")), "root_signature_invalid");
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
  if (!existsSync2(values.RECOVERY_ENTRY)) {
    requireValue(!readOnly, "original_plain_entry_missing_custody");
    wxJson(values.RECOVERY_ENTRY, e);
  } else
    requireValue(JSON.stringify(JSON.parse(readFileSync6(values.RECOVERY_ENTRY, "utf8"))) === JSON.stringify(e), "existing_plain_entry_changed");
  return { ...c, bindings: values };
}

// scripts/bench-runner/signed-dispatch-contract.ts
var need4 = (x, s) => {
  if (!x)
    throw Error(s);
};
var same3 = (a, b) => JSON.stringify(a) === JSON.stringify(b);
function applySignedRootDispatch(m, c) {
  const actual = loadPreparedContext(m, c), receipt = readPinned(filePin(join3(c.runDir, "locks-receipt.json")));
  checkPin(receipt.canonicalPin);
  checkPin(receipt.attemptLockPin);
  const lock = readPinned(receipt.attemptLockPin), canonical = readPinned(receipt.canonicalPin), entryPin = filePin(actual.bindings.ENTRY_ENVELOPE);
  need4(lock.taskId === m.taskId && lock.bench === m.bench && lock.attemptId === c.attemptId && same3(lock.manifestPin, c.manifestPin) && same3(lock.signedEntryPin, entryPin), "signed_root_dispatch_actual_attempt_lock");
  need4(canonical.taskId === m.taskId && canonical.bench === m.bench, "signed_root_dispatch_canonical_task");
  process.env.NOVAEVE_ROOT_ONLY_DISPATCH = "1";
  return { protocol: "bench-actual-signed-root-dispatch-v1", manifestPin: c.manifestPin, signedEntryPin: entryPin, canonicalPin: receipt.canonicalPin, attemptLockPin: receipt.attemptLockPin, actualPid: process.pid, environment: { NOVAEVE_ROOT_ONLY_DISPATCH: "1" } };
}
function recordCampaignOutcome(c, result) {
  const summary = readPinned(result.summary);
  need4(summary.runId && same3(summary.financialClose?.cashClose, result.financialClose?.cashClose), "campaign_outcome_summary_financial_join");
  const outcome = { protocol: "bench-qualified-campaign-outcome-v1", taskId: c.taskId, bench: c.bench, attemptId: c.attemptId, runId: summary.runId, summaryPin: result.summary, cashClosePin: result.financialClose?.cashClose ?? null, fatal: summary.fatal ?? null, operationalComplete: summary.operationalComplete === true, segmentComplete: result.segmentComplete === true, formalScoreCertified: summary.formalScoreCertified === true, originalVerdictUnchanged: true };
  wxJson(join3(c.runDir, "driver-campaign-outcome.json"), outcome);
  if (outcome.fatal || !outcome.segmentComplete)
    process.exitCode = 2;
  return outcome;
}

// scripts/bench-runner/saved-candidate-inventory.ts
import { readFileSync as readFileSync14 } from "fs";
import { Database as Database2 } from "bun:sqlite";
import { resolve as resolve13 } from "path";
import { verify as verify3 } from "crypto";

// scripts/bench-runner/original-history.ts
import { existsSync as existsSync7 } from "fs";
import { resolve as resolve12 } from "path";
import { Database } from "bun:sqlite";

// scripts/repair-2026-10-10/full-f/shared/digitalocean-usd-cash.ts
import { closeSync as closeSync7, fsyncSync as fsyncSync4, openSync as openSync7, readFileSync as readFileSync11, readSync as readSync6, statSync as statSync6, writeSync as writeSync4 } from "fs";
import { join as join8, resolve as resolve11 } from "path";

// scripts/repair-2026-10-10/full-f/shared/digitalocean-journal.ts
import { createHash as createHash3, randomBytes } from "crypto";
import { closeSync as closeSync3, existsSync as existsSync3, fstatSync, fsyncSync, lstatSync as lstatSync2, mkdirSync as mkdirSync2, openSync as openSync3, readFileSync as readFileSync7, readSync as readSync2, readdirSync as readdirSync2, realpathSync as realpathSync2, renameSync, statSync as statSync2, writeSync } from "fs";
import { isAbsolute as isAbsolute2, join as join4, relative, resolve as resolve7 } from "path";
import { gunzipSync, gzipSync } from "zlib";

// app/src/H2H/db.ts
function all(db, sql, params) {
  return db.all(sql, params);
}
function run(db, sql, params) {
  return db.run(sql, params);
}

// app/src/engine/plugin.ts
import { statSync } from "fs";
import { resolve as resolve6 } from "path";
import { fileURLToPath, pathToFileURL as pathToFileURL3 } from "url";
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
var HOST = hostPath();
var READY_MS = 1e4;

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
    const hash2 = spec.lastIndexOf("#");
    const path = resolve6(hash2 === -1 ? spec : spec.slice(0, hash2));
    const exp = hash2 === -1 ? "default" : spec.slice(hash2 + 1);
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
      this.#live.set(path, new Live(name, pathToFileURL3(path).href, stamp));
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

// app/src/engine/registry.ts
var IN = /^fn:/;
var OUT = /^https?:\/\//;
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

// scripts/repair-2026-10-08/campaign-contract.ts
var MAX_OUTPUT_TOKENS = 16384;
var PEAK_RATES = Object.freeze({ input: 0.3, cachedInput: 0.006, output: 1.2 });
var object = (value) => value !== null && typeof value === "object" && !Array.isArray(value) ? value : undefined;
var count = (value) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
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

// scripts/repair-2026-10-10/full-f/shared/digitalocean-provider.ts
var BENCHMARK_PROVIDER = Object.freeze({
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

// scripts/repair-2026-10-10/full-f/shared/digitalocean-journal.ts
var CAMPAIGN_JOURNAL_PROTOCOL = "campaign-api-journal-v1";
var OPENROUTER_JOURNAL_PROTOCOL = "campaign-api-journal-openrouter-v1";
var MAX_LINE = 64 * 1024;
var MAX_REQUEST = 4 * 1024 * 1024;
var MAX_RESPONSE = 64 * 1024 * 1024;
var MAX_JOURNAL = 2 * 1024 * 1024 * 1024;
var EPS = 0.000000001;
var WIRE = ["model", "temperature", "seed", "reasoning_effort", "thinking", "reasoning", "provider", "max_tokens", "max_completion_tokens", "tool_choice", "response_format", "stream"];
var hash2 = (data) => createHash3("sha256").update(data).digest("hex");
var json2 = (value) => JSON.stringify(value);
var same4 = (a, b) => json2(a) === json2(b);
var finite = (n) => typeof n === "number" && Number.isFinite(n) && n >= 0;

class CampaignJournalError extends Error {
  code;
  stage;
  constructor(code, stage) {
    super(code + (stage ? ":" + stage : ""));
    this.name = "CampaignJournalError";
    this.code = code;
    this.stage = stage;
  }
}
function demand2(ok, code) {
  if (!ok)
    throw new CampaignJournalError(code);
}
function ordinaryDirectory(path) {
  demand2(isAbsolute2(path), "absolute_directory_required");
  mkdirSync2(path, { recursive: true });
  demand2(lstatSync2(path).isDirectory() && !lstatSync2(path).isSymbolicLink(), "ordinary_directory_required");
  return realpathSync2(path);
}
function regularInStore(path, store) {
  const full = resolve7(path), rel = relative(store, full);
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
  const before = statSync2(path), fd = openSync3(path, "r"), digest = createHash3("sha256"), buffer = Buffer.alloc(64 * 1024);
  let at2 = 0;
  try {
    while (at2 < before.size) {
      const n = readSync2(fd, buffer, 0, Math.min(buffer.length, before.size - at2), at2);
      demand2(n > 0, "hash_short_read");
      digest.update(buffer.subarray(0, n));
      at2 += n;
    }
  } finally {
    closeSync3(fd);
  }
  const after = statSync2(path);
  demand2(before.size === after.size && before.mtimeMs === after.mtimeMs, "hash_file_changed");
  return digest.digest("hex");
}
function rawEvidence(path, expected, compressedExpected, store, parse = true) {
  regularInStore(path, store);
  const before = statSync2(path);
  const zipped = readFileSync7(path);
  demand2(zipped.length <= MAX_RESPONSE + 1024 * 1024, "raw_resource_limit");
  const raw = gunzipSync(zipped, { maxOutputLength: MAX_RESPONSE });
  const after = statSync2(path);
  demand2(before.size === after.size && before.mtimeMs === after.mtimeMs && hash2(zipped) === compressedExpected && hash2(raw) === expected, "raw_digest_changed");
  const data = parse ? JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)) : undefined;
  return { raw, data };
}
function frozenRouting(config) {
  const slug = config.providerSlug ?? "deepseek";
  demand2(config.zeroChargePolicy === undefined || config.zeroChargePolicy === "explicit-rate-rejection-v2", "journal_zero_charge_policy");
  demand2(["deepseek", "relace", "digitalocean"].includes(slug) && (config.providerName === undefined || config.providerName === { relace: "Relace", deepseek: "DeepSeek", digitalocean: "DigitalOcean" }[slug]), "journal_provider_identity");
  const route = { only: [slug], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } };
  demand2(config.providerRouting === undefined || same4(config.providerRouting, route), "journal_provider_route");
  return route;
}
function requestValues(raw, data, config) {
  demand2(data && typeof data === "object" && !Array.isArray(data) && data.model === (config?.model ?? "deepseek-flash") && data.stream !== true, "invalid_frozen_request");
  if (config?.provider)
    demand2(same4(data.provider, frozenRouting(config)) && data.models === undefined && data.route === undefined && data.plugins === undefined, "pinned_provider_routing_required");
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
  demand2(raw.length === c.requestBytes && c.requestedModel === data.model && same4(c.wireParameters, expected.wireParameters) && finite(c.reservationUsd) && Math.abs(c.reservationUsd - expected.reservationUsd) <= EPS, "request_receipt_mismatch");
}
function routingRejection(config, data, status) {
  return !!config.provider && status === 404 && Array.isArray(data?.error?.metadata?.routing_funnel) && typeof data?.error?.metadata?.failed_routing_step === "string" && data.error.metadata.failed_routing_step.startsWith("Filter by ") && !data.usage;
}
function rateRejection(config, data, status) {
  return !!config.provider && config.zeroChargePolicy === "explicit-rate-rejection-v2" && openRouterRateLimitRejection(data, status, config.providerName ?? "DeepSeek");
}
function checkedFinish(c, start, seq, store, config) {
  for (const key of ["route", "startedAt", "requestSha256", "requestedModel", "requestFile", "wireParameters", "requestCompressedSha256", "requestBytes"])
    demand2(same4(c[key], start[key]), "finish_start_mismatch");
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
      demand2(same4(data.usage, c.usage) && (typeof data.model === "string" ? data.model : undefined) === c.servedModel && (typeof data.id === "string" ? data.id : undefined) === c.requestId, "response_receipt_mismatch");
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
  let offset = 0, at2 = 0, carry = Buffer.alloc(0);
  const buffer = Buffer.alloc(16 * 1024);
  while (at2 < length) {
    const n = readSync2(fd, buffer, 0, Math.min(buffer.length, length - at2), at2);
    demand2(n > 0, "journal_short_read");
    at2 += n;
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
  const result = { valid: false, accountingClosed: false, eligibleForScoreCertification: false, errors: [], offsets: new Map, routes: new Map, journalPath: join4(resolve7(directory), "api-events.jsonl"), directory: resolve7(directory) };
  let fd;
  try {
    const store = realpathSync2(directory);
    demand2(store === resolve7(directory), "journal_directory_identity");
    const configBytes = readFileSync7(join4(store, "journal-config.json")), config = JSON.parse(configBytes.toString("utf8"));
    const providerValid = config.provider === "openrouter-deepseek" ? config.protocol === OPENROUTER_JOURNAL_PROTOCOL && config.model === BENCHMARK_PROVIDER.model && config.currency === "USD" : config.provider === undefined && config.protocol === CAMPAIGN_JOURNAL_PROTOCOL && config.model === "deepseek-flash";
    if (config.provider)
      frozenRouting(config);
    demand2(providerValid && Number.isSafeInteger(config.pendingLimit) && config.pendingLimit >= 4 && config.pendingLimit <= 50 && config.maxLineBytes === MAX_LINE && config.maxJournalBytes === MAX_JOURNAL && finite(config.capUsd) && config.capUsd > 0 && finite(config.priorCampaignCostUpperBoundUsd), "journal_config_invalid");
    const configSha = hash2(configBytes), before = statSync2(result.journalPath);
    demand2(before.size <= MAX_JOURNAL && lstatSync2(result.journalPath).isFile() && !lstatSync2(result.journalPath).isSymbolicLink(), "journal_resource_or_identity");
    fd = openSync3(result.journalPath, "r");
    const active = new Map, ids = new Set;
    let accepted = 0, finished = 0, spent = 0, allProviderValid = true;
    let prefix = { bytes: 0, eventCount: 0, lastSha256: configSha };
    for (const { offset, line } of lines(fd, before.size)) {
      const e = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line.subarray(0, -1)));
      demand2(same4(Object.keys(e), ["protocol", "eventSeq", "previousEventSha256", "kind", "requestSeq", "record"]) && Buffer.from(json2(e) + `
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
        result.offsets.set(e.requestSeq, { offset, bytes: line.length, sha256: hash2(line) });
        const route = result.routes.get(e.record.route) ?? [];
        route.push(e.requestSeq);
        result.routes.set(e.record.route, route);
      } else
        throw new CampaignJournalError("unknown_event");
      prefix = { bytes: offset + line.length, eventCount: prefix.eventCount + 1, lastSha256: hash2(line) };
      result.snapshot = financialState(config, configSha, active, accepted, finished, spent, prefix);
    }
    result.snapshot ??= financialState(config, configSha, active, accepted, finished, spent, prefix);
    result.prefix = prefix;
    result.config = config;
    const checkpoint = JSON.parse(readFileSync7(join4(store, "api-state.json"), "utf8"));
    const expected = { ...result.snapshot, ...checkpoint.stopReason ? { stopReason: checkpoint.stopReason } : {} };
    demand2(same4(checkpoint, expected), "checkpoint_prefix_or_accounting");
    const requests = readdirSync2(store).filter((n) => /^provider-\d+-request\.json\.gz$/.test(n));
    const responses = readdirSync2(store).filter((n) => /^provider-\d+-response\.json\.gz$/.test(n));
    demand2(requests.length === accepted && requests.every((n) => Number(n.match(/\d+/)[0]) < accepted), "unindexed_raw_request");
    demand2(responses.every((n) => result.offsets.has(Number(n.match(/\d+/)[0]))), "unindexed_raw_response");
    if (ownedExport)
      demand2(ownedExport.path === join4(store, "api-ledger.json.partial") && statSync2(ownedExport.path).size === ownedExport.bytes && fileHash(ownedExport.path) === ownedExport.sha256, "owned_export_partial_changed");
    demand2(!existsSync3(join4(store, "journal-error.json")) && !readdirSync2(store).some((n) => n.includes(".partial") && join4(store, n) !== ownedExport?.path || n.startsWith("api-state.json.new-")), "unclosed_error_or_partial");
    const after = statSync2(result.journalPath);
    demand2(before.size === after.size && before.mtimeMs === after.mtimeMs && hash2(readFileSync7(join4(store, "journal-config.json"))) === configSha, "journal_changed_during_inspection");
    result.valid = true;
    result.accountingClosed = active.size === 0 && accepted === finished;
    result.eligibleForScoreCertification = result.accountingClosed && allProviderValid && !checkpoint.stopReason && config.priorCampaignCostUpperBoundUsd + spent <= config.capUsd + EPS;
  } catch (e) {
    result.errors.push(e instanceof CampaignJournalError ? e.code : e.code ?? e.name);
  } finally {
    if (fd !== undefined)
      closeSync3(fd);
  }
  return result;
}
function createCampaignJournal(options, hooks = {}) {
  return new CampaignJournal(options, hooks);
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
    this.directory = ordinaryDirectory(resolve7(options.directory));
    this.outputDirectory = ordinaryDirectory(resolve7(options.outputDirectory ?? options.directory));
    demand2(!readdirSync2(this.directory).some((n) => ["api-events.jsonl", "journal-config.json", "api-state.json", "journal-error.json"].includes(n) || /^provider-\d+-/.test(n)), "existing_journal");
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
    this.configSha256 = hash2(configRaw);
    this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configSha256 };
    this.journalPath = join4(this.directory, "api-events.jsonl");
    try {
      this.persistExclusive(join4(this.directory, "journal-config.json"), configRaw, "config", "checkpointBytesWritten");
      this.fd = openSync3(this.journalPath, "wx+");
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
    let at2 = 0;
    while (at2 < raw.length) {
      const op = { kind: "write", stage, path, fd, bytes: raw.length - at2 };
      this.hooks.before?.(op);
      const n = writeSync(fd, raw, at2, raw.length - at2);
      demand2(n > 0, "short_write");
      this.metrics[metric] += n;
      at2 += n;
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
    const fd = openSync3(path, "wx", 384);
    try {
      this.write(fd, path, raw, stage, metric);
      this.sync(fd, path, stage);
    } finally {
      try {
        closeSync3(fd);
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
      this.persistExclusive(join4(this.directory, "journal-error.json"), Buffer.from(json2({ protocol: CAMPAIGN_JOURNAL_PROTOCOL, error: error.code, stage, state: this.state(), ...uncommittedReceipt ? { uncommittedReceipt } : {} }) + `
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
      const checkpoint = readFileSync7(checkpointPath);
      if (checkpoint.length > MAX_LINE || !checkpoint.equals(Buffer.from(json2(this.state()) + `
`)))
        this.poison("checkpoint_changed", "before_append");
    } catch {
      this.poison("checkpoint_changed", "before_append");
    }
    if (existsSync3(join4(this.directory, "journal-error.json")))
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
    const target = join4(this.directory, "api-state.json"), temp = target + ".new-" + randomBytes(8).toString("hex");
    const raw = Buffer.from(json2(this.state()) + `
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
    const raw = Buffer.from(json2(e) + `
`);
    if (raw.length > MAX_LINE || this.prefix.bytes + raw.length > MAX_JOURNAL)
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
    const c = { route: input.route, startedAt: input.startedAt ?? new Date().toISOString(), requestSha256: hash2(raw), requestedModel: String(data.model), requestFile, providerAttempted: false, wireParameters: values.wireParameters, requestCompressedSha256: hash2(zipped), requestBytes: raw.length, reservationUsd: values.reservationUsd };
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
      c.responseSha256 = hash2(raw);
      c.responseCompressedSha256 = hash2(zipped);
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
    demand2(readSync2(fd, line, 0, line.length, offset.offset) === line.length && hash2(line) === offset.sha256, "export_receipt_changed");
    return JSON.parse(line.toString("utf8")).record;
  }
  *closedCalls(route) {
    demand2(this.exported && this.closedProof, "not_exported");
    const proof = this.closedProof;
    demand2(statSync2(this.journalPath).size === proof.prefix.bytes, "exported_journal_changed");
    const fd = openSync3(this.journalPath, "r");
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
      closeSync3(fd);
    }
  }
  exportLegacyLedger() {
    this.writable();
    demand2(this.active.size === 0 && this.accepted === this.finished, "journal_not_closed");
    const proof = inspectCampaignJournal(this.directory);
    if (!proof.valid || !proof.accountingClosed || !same4(proof.prefix, this.prefix) || Math.abs(proof.snapshot.recordedUsageUpperBoundUsd - this.spent) > EPS)
      this.poison("export_integrity", "before_export");
    const target = join4(this.outputDirectory, "api-ledger.json"), temp = target + ".partial";
    demand2(!existsSync3(target) && !existsSync3(temp), "existing_export");
    const fd = openSync3(temp, "wx", 384), journalFd = openSync3(this.journalPath, "r");
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
        closeSync3(fd);
      } catch {}
      closeSync3(journalFd);
    }
    const ownPartial = this.outputDirectory === this.directory ? { path: temp, bytes: statSync2(temp).size, sha256: fileHash(temp) } : undefined;
    const after = inspect(this.directory, ownPartial);
    if (!after.valid || !after.accountingClosed || !same4(after.prefix, proof.prefix))
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
        closeSync3(this.fd);
      } catch {}
      this.closed = true;
    }
  }
}

// scripts/repair-2026-10-08/cny-cash-shadow-v2.ts
import { closeSync as closeSync6, existsSync as existsSync6, fsyncSync as fsyncSync3, openSync as openSync6, readFileSync as readFileSync10, readSync as readSync5, statSync as statSync5, writeFileSync as writeFileSync2, writeSync as writeSync3 } from "fs";
import { join as join7, resolve as resolve10 } from "path";

// scripts/repair-2026-10-08/campaign-journal.ts
import { createHash as createHash4, randomBytes as randomBytes2 } from "crypto";
import { closeSync as closeSync4, existsSync as existsSync4, fstatSync as fstatSync2, fsyncSync as fsyncSync2, lstatSync as lstatSync3, mkdirSync as mkdirSync3, openSync as openSync4, readFileSync as readFileSync8, readSync as readSync3, readdirSync as readdirSync3, realpathSync as realpathSync3, renameSync as renameSync2, statSync as statSync3, writeSync as writeSync2 } from "fs";
import { isAbsolute as isAbsolute3, join as join5, relative as relative2, resolve as resolve8 } from "path";
import { gunzipSync as gunzipSync2, gzipSync as gzipSync2 } from "zlib";

// scripts/repair-2026-10-08/benchmark-provider.ts
var BENCHMARK_PROVIDER2 = Object.freeze({
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

// scripts/repair-2026-10-08/campaign-journal.ts
var CAMPAIGN_JOURNAL_PROTOCOL2 = "campaign-api-journal-v1";
var OPENROUTER_JOURNAL_PROTOCOL2 = "campaign-api-journal-openrouter-v1";
var MAX_LINE2 = 64 * 1024;
var MAX_REQUEST2 = 4 * 1024 * 1024;
var MAX_RESPONSE2 = 64 * 1024 * 1024;
var MAX_JOURNAL2 = 2 * 1024 * 1024 * 1024;
var EPS2 = 0.000000001;
var WIRE2 = ["model", "temperature", "seed", "reasoning_effort", "thinking", "reasoning", "provider", "max_tokens", "max_completion_tokens", "tool_choice", "response_format", "stream"];
var hash3 = (data) => createHash4("sha256").update(data).digest("hex");
var json3 = (value) => JSON.stringify(value);
var same5 = (a, b) => json3(a) === json3(b);
var finite2 = (n) => typeof n === "number" && Number.isFinite(n) && n >= 0;

class CampaignJournalError2 extends Error {
  code;
  stage;
  constructor(code, stage) {
    super(code + (stage ? ":" + stage : ""));
    this.name = "CampaignJournalError";
    this.code = code;
    this.stage = stage;
  }
}
function demand3(ok, code) {
  if (!ok)
    throw new CampaignJournalError2(code);
}
function ordinaryDirectory2(path) {
  demand3(isAbsolute3(path), "absolute_directory_required");
  mkdirSync3(path, { recursive: true });
  demand3(lstatSync3(path).isDirectory() && !lstatSync3(path).isSymbolicLink(), "ordinary_directory_required");
  return realpathSync3(path);
}
function regularInStore2(path, store) {
  const full = resolve8(path), rel = relative2(store, full);
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
  const before = statSync3(path), fd = openSync4(path, "r"), digest = createHash4("sha256"), buffer = Buffer.alloc(64 * 1024);
  let at2 = 0;
  try {
    while (at2 < before.size) {
      const n = readSync3(fd, buffer, 0, Math.min(buffer.length, before.size - at2), at2);
      demand3(n > 0, "hash_short_read");
      digest.update(buffer.subarray(0, n));
      at2 += n;
    }
  } finally {
    closeSync4(fd);
  }
  const after = statSync3(path);
  demand3(before.size === after.size && before.mtimeMs === after.mtimeMs, "hash_file_changed");
  return digest.digest("hex");
}
function rawEvidence2(path, expected, compressedExpected, store, parse = true) {
  regularInStore2(path, store);
  const before = statSync3(path);
  const zipped = readFileSync8(path);
  demand3(zipped.length <= MAX_RESPONSE2 + 1024 * 1024, "raw_resource_limit");
  const raw = gunzipSync2(zipped, { maxOutputLength: MAX_RESPONSE2 });
  const after = statSync3(path);
  demand3(before.size === after.size && before.mtimeMs === after.mtimeMs && hash3(zipped) === compressedExpected && hash3(raw) === expected, "raw_digest_changed");
  const data = parse ? JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)) : undefined;
  return { raw, data };
}
function frozenRouting2(config) {
  const slug = config.providerSlug ?? "deepseek";
  demand3(config.zeroChargePolicy === undefined || config.zeroChargePolicy === "explicit-rate-rejection-v2", "journal_zero_charge_policy");
  demand3(["deepseek", "relace"].includes(slug) && (config.providerName === undefined || config.providerName === (slug === "relace" ? "Relace" : "DeepSeek")), "journal_provider_identity");
  const route = { only: [slug], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } };
  demand3(config.providerRouting === undefined || same5(config.providerRouting, route), "journal_provider_route");
  return route;
}
function requestValues2(raw, data, config) {
  demand3(data && typeof data === "object" && !Array.isArray(data) && data.model === (config?.model ?? "deepseek-flash") && data.stream !== true, "invalid_frozen_request");
  if (config?.provider)
    demand3(same5(data.provider, frozenRouting2(config)) && data.models === undefined && data.route === undefined && data.plugins === undefined, "pinned_provider_routing_required");
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
  demand3(raw.length === c.requestBytes && c.requestedModel === data.model && same5(c.wireParameters, expected.wireParameters) && finite2(c.reservationUsd) && Math.abs(c.reservationUsd - expected.reservationUsd) <= EPS2, "request_receipt_mismatch");
}
function routingRejection2(config, data, status) {
  return !!config.provider && status === 404 && Array.isArray(data?.error?.metadata?.routing_funnel) && typeof data?.error?.metadata?.failed_routing_step === "string" && data.error.metadata.failed_routing_step.startsWith("Filter by ") && !data.usage;
}
function rateRejection2(config, data, status) {
  return !!config.provider && config.zeroChargePolicy === "explicit-rate-rejection-v2" && openRouterRateLimitRejection2(data, status, config.providerName ?? "DeepSeek");
}
function checkedFinish2(c, start, seq, store, config) {
  for (const key of ["route", "startedAt", "requestSha256", "requestedModel", "requestFile", "wireParameters", "requestCompressedSha256", "requestBytes"])
    demand3(same5(c[key], start[key]), "finish_start_mismatch");
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
      demand3(same5(data.usage, c.usage) && (typeof data.model === "string" ? data.model : undefined) === c.servedModel && (typeof data.id === "string" ? data.id : undefined) === c.requestId, "response_receipt_mismatch");
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
  let offset = 0, at2 = 0, carry = Buffer.alloc(0);
  const buffer = Buffer.alloc(16 * 1024);
  while (at2 < length) {
    const n = readSync3(fd, buffer, 0, Math.min(buffer.length, length - at2), at2);
    demand3(n > 0, "journal_short_read");
    at2 += n;
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
  const result = { valid: false, accountingClosed: false, eligibleForScoreCertification: false, errors: [], offsets: new Map, routes: new Map, journalPath: join5(resolve8(directory), "api-events.jsonl"), directory: resolve8(directory) };
  let fd;
  try {
    const store = realpathSync3(directory);
    demand3(store === resolve8(directory), "journal_directory_identity");
    const configBytes = readFileSync8(join5(store, "journal-config.json")), config = JSON.parse(configBytes.toString("utf8"));
    const providerValid = config.provider === "openrouter-deepseek" ? config.protocol === OPENROUTER_JOURNAL_PROTOCOL2 && config.model === BENCHMARK_PROVIDER2.model && config.currency === "USD" : config.provider === undefined && config.protocol === CAMPAIGN_JOURNAL_PROTOCOL2 && config.model === "deepseek-flash";
    if (config.provider)
      frozenRouting2(config);
    demand3(providerValid && config.pendingLimit === 4 && config.maxLineBytes === MAX_LINE2 && config.maxJournalBytes === MAX_JOURNAL2 && finite2(config.capUsd) && config.capUsd > 0 && finite2(config.priorCampaignCostUpperBoundUsd), "journal_config_invalid");
    const configSha = hash3(configBytes), before = statSync3(result.journalPath);
    demand3(before.size <= MAX_JOURNAL2 && lstatSync3(result.journalPath).isFile() && !lstatSync3(result.journalPath).isSymbolicLink(), "journal_resource_or_identity");
    fd = openSync4(result.journalPath, "r");
    const active = new Map, ids = new Set;
    let accepted = 0, finished = 0, spent = 0, allProviderValid = true;
    let prefix = { bytes: 0, eventCount: 0, lastSha256: configSha };
    for (const { offset, line } of lines2(fd, before.size)) {
      const e = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line.subarray(0, -1)));
      demand3(same5(Object.keys(e), ["protocol", "eventSeq", "previousEventSha256", "kind", "requestSeq", "record"]) && Buffer.from(json3(e) + `
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
        result.offsets.set(e.requestSeq, { offset, bytes: line.length, sha256: hash3(line) });
        const route = result.routes.get(e.record.route) ?? [];
        route.push(e.requestSeq);
        result.routes.set(e.record.route, route);
      } else
        throw new CampaignJournalError2("unknown_event");
      prefix = { bytes: offset + line.length, eventCount: prefix.eventCount + 1, lastSha256: hash3(line) };
      result.snapshot = financialState2(config, configSha, active, accepted, finished, spent, prefix);
    }
    result.snapshot ??= financialState2(config, configSha, active, accepted, finished, spent, prefix);
    result.prefix = prefix;
    result.config = config;
    const checkpoint = JSON.parse(readFileSync8(join5(store, "api-state.json"), "utf8"));
    const expected = { ...result.snapshot, ...checkpoint.stopReason ? { stopReason: checkpoint.stopReason } : {} };
    demand3(same5(checkpoint, expected), "checkpoint_prefix_or_accounting");
    const requests = readdirSync3(store).filter((n) => /^provider-\d+-request\.json\.gz$/.test(n));
    const responses = readdirSync3(store).filter((n) => /^provider-\d+-response\.json\.gz$/.test(n));
    demand3(requests.length === accepted && requests.every((n) => Number(n.match(/\d+/)[0]) < accepted), "unindexed_raw_request");
    demand3(responses.every((n) => result.offsets.has(Number(n.match(/\d+/)[0]))), "unindexed_raw_response");
    if (ownedExport)
      demand3(ownedExport.path === join5(store, "api-ledger.json.partial") && statSync3(ownedExport.path).size === ownedExport.bytes && fileHash2(ownedExport.path) === ownedExport.sha256, "owned_export_partial_changed");
    demand3(!existsSync4(join5(store, "journal-error.json")) && !readdirSync3(store).some((n) => n.includes(".partial") && join5(store, n) !== ownedExport?.path || n.startsWith("api-state.json.new-")), "unclosed_error_or_partial");
    const after = statSync3(result.journalPath);
    demand3(before.size === after.size && before.mtimeMs === after.mtimeMs && hash3(readFileSync8(join5(store, "journal-config.json"))) === configSha, "journal_changed_during_inspection");
    result.valid = true;
    result.accountingClosed = active.size === 0 && accepted === finished;
    result.eligibleForScoreCertification = result.accountingClosed && allProviderValid && !checkpoint.stopReason && config.priorCampaignCostUpperBoundUsd + spent <= config.capUsd + EPS2;
  } catch (e) {
    result.errors.push(e instanceof CampaignJournalError2 ? e.code : e.code ?? e.name);
  } finally {
    if (fd !== undefined)
      closeSync4(fd);
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
    this.directory = ordinaryDirectory2(resolve8(options.directory));
    this.outputDirectory = ordinaryDirectory2(resolve8(options.outputDirectory ?? options.directory));
    demand3(!readdirSync3(this.directory).some((n) => ["api-events.jsonl", "journal-config.json", "api-state.json", "journal-error.json"].includes(n) || /^provider-\d+-/.test(n)), "existing_journal");
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
    this.configSha256 = hash3(configRaw);
    this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configSha256 };
    this.journalPath = join5(this.directory, "api-events.jsonl");
    try {
      this.persistExclusive(join5(this.directory, "journal-config.json"), configRaw, "config", "checkpointBytesWritten");
      this.fd = openSync4(this.journalPath, "wx+");
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
    let at2 = 0;
    while (at2 < raw.length) {
      const op = { kind: "write", stage, path, fd, bytes: raw.length - at2 };
      this.hooks.before?.(op);
      const n = writeSync2(fd, raw, at2, raw.length - at2);
      demand3(n > 0, "short_write");
      this.metrics[metric] += n;
      at2 += n;
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
    return financialState2(this.config, this.configSha256, this.active, this.accepted, this.finished, this.spent, this.prefix, this.stopReason);
  }
  snapshot() {
    return { ...this.state(), ...this.poisoned ? { error: this.poisoned.code } : {}, metrics: { ...this.metrics } };
  }
  poison(code, stage, uncommittedReceipt) {
    const error = this.poisoned ?? new CampaignJournalError2(code, stage);
    this.poisoned = error;
    try {
      this.persistExclusive(join5(this.directory, "journal-error.json"), Buffer.from(json3({ protocol: CAMPAIGN_JOURNAL_PROTOCOL2, error: error.code, stage, state: this.state(), ...uncommittedReceipt ? { uncommittedReceipt } : {} }) + `
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
      const checkpoint = readFileSync8(checkpointPath);
      if (checkpoint.length > MAX_LINE2 || !checkpoint.equals(Buffer.from(json3(this.state()) + `
`)))
        this.poison("checkpoint_changed", "before_append");
    } catch {
      this.poison("checkpoint_changed", "before_append");
    }
    if (existsSync4(join5(this.directory, "journal-error.json")))
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
        if (n !== raw.length || hash3(raw) !== this.lastLine.sha256)
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
    const raw = Buffer.from(json3(this.state()) + `
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
    const raw = Buffer.from(json3(e) + `
`);
    if (raw.length > MAX_LINE2 || this.prefix.bytes + raw.length > MAX_JOURNAL2)
      this.poison("journal_resource_limit", `${kind}:${seq}`, receipt);
    this.metrics.maxHotMetadataBytes = Math.max(this.metrics.maxHotMetadataBytes, raw.length);
    const offset = this.prefix.bytes, fsyncBefore = this.metrics.fsyncCallsReturned;
    const commit = () => {
      this.prefix = { bytes: offset + raw.length, eventCount: this.prefix.eventCount + 1, lastSha256: hash3(raw) };
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
    const c = { route: input.route, startedAt: input.startedAt ?? new Date().toISOString(), requestSha256: hash3(raw), requestedModel: String(data.model), requestFile, providerAttempted: false, wireParameters: values.wireParameters, requestCompressedSha256: hash3(zipped), requestBytes: raw.length, reservationUsd: values.reservationUsd };
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
      c.responseSha256 = hash3(raw);
      c.responseCompressedSha256 = hash3(zipped);
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
    demand3(readSync3(fd, line, 0, line.length, offset.offset) === line.length && hash3(line) === offset.sha256, "export_receipt_changed");
    return JSON.parse(line.toString("utf8")).record;
  }
  *closedCalls(route) {
    demand3(this.exported && this.closedProof, "not_exported");
    const proof = this.closedProof;
    demand3(statSync3(this.journalPath).size === proof.prefix.bytes, "exported_journal_changed");
    const fd = openSync4(this.journalPath, "r");
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
      closeSync4(fd);
    }
  }
  exportLegacyLedger() {
    this.writable();
    demand3(this.active.size === 0 && this.accepted === this.finished, "journal_not_closed");
    const proof = inspectCampaignJournal2(this.directory);
    if (!proof.valid || !proof.accountingClosed || !same5(proof.prefix, this.prefix) || Math.abs(proof.snapshot.recordedUsageUpperBoundUsd - this.spent) > EPS2)
      this.poison("export_integrity", "before_export");
    const target = join5(this.outputDirectory, "api-ledger.json"), temp = target + ".partial";
    demand3(!existsSync4(target) && !existsSync4(temp), "existing_export");
    const fd = openSync4(temp, "wx", 384), journalFd = openSync4(this.journalPath, "r");
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
        closeSync4(fd);
      } catch {}
      closeSync4(journalFd);
    }
    const ownPartial = this.outputDirectory === this.directory ? { path: temp, bytes: statSync3(temp).size, sha256: fileHash2(temp) } : undefined;
    const after = inspect2(this.directory, ownPartial);
    if (!after.valid || !after.accountingClosed || !same5(after.prefix, proof.prefix))
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
        closeSync4(this.fd);
      } catch {}
      this.closed = true;
    }
  }
}

// scripts/repair-2026-10-08/paid-resource-proof-v2.ts
import { createHash as createHash5 } from "crypto";
import { closeSync as closeSync5, existsSync as existsSync5, lstatSync as lstatSync4, mkdirSync as mkdirSync4, openSync as openSync5, readFileSync as readFileSync9, readSync as readSync4, realpathSync as realpathSync4, statSync as statSync4 } from "fs";
import { isAbsolute as isAbsolute4, join as join6, relative as relative3, resolve as resolve9 } from "path";
import { gunzipSync as gunzipSync3 } from "zlib";
var REAL_CLOCK = Object.freeze({ wallUnixMs: () => Date.now(), monotonicNs: () => process.hrtime.bigint() });
var JOURNAL_SOURCE_SHA = createHash5("sha256").update(readFileSync9(new URL("./campaign-journal.ts", "file:///F:/git/TgEngin-handoff-2026-10-07/TgEngin/scripts/repair-2026-10-08/paid-resource-proof-v2.ts"))).digest("hex");

class ResourceAdmissionError extends Error {
  code;
  constructor(code) {
    super(code);
    this.code = code;
    this.name = "ResourceAdmissionError";
  }
}
function demand4(value, code) {
  if (!value)
    throw new ResourceAdmissionError(code);
}
var hash4 = (b) => createHash5("sha256").update(b).digest("hex");
var same6 = (a, b) => JSON.stringify(a) === JSON.stringify(b);
function ordinaryDirectory3(path) {
  const p = resolve9(path);
  mkdirSync4(p, { recursive: true });
  demand4(lstatSync4(p).isDirectory() && !lstatSync4(p).isSymbolicLink() && realpathSync4(p) === p, "ordinary_directory_required");
  return p;
}
function fileHash3(path) {
  const before = statSync4(path), fd = openSync5(path, "r"), digest = createHash5("sha256"), buffer = Buffer.alloc(65536);
  let at2 = 0;
  try {
    while (at2 < before.size) {
      const n = readSync4(fd, buffer, 0, Math.min(buffer.length, before.size - at2), at2);
      demand4(n > 0, "hash_short_read");
      digest.update(buffer.subarray(0, n));
      at2 += n;
    }
  } finally {
    closeSync5(fd);
  }
  const after = statSync4(path);
  demand4(before.size === after.size && before.mtimeMs === after.mtimeMs, "file_changed_during_hash");
  return digest.digest("hex");
}
function verifyPin2(pin2, base, maxBytes = 128 * 1024 ** 2) {
  demand4(pin2 && typeof pin2.path === "string" && /^[a-f0-9]{64}$/.test(pin2.sha256), "invalid_pin");
  const path = isAbsolute4(pin2.path) ? resolve9(pin2.path) : resolve9(base ?? ".", pin2.path);
  demand4(lstatSync4(path).isFile() && !lstatSync4(path).isSymbolicLink(), "pin_not_regular");
  const size = statSync4(path).size;
  demand4(size <= maxBytes && (pin2.bytes === undefined || pin2.bytes === size) && fileHash3(path) === pin2.sha256, "pin_changed");
  return path;
}
function actualPin(path) {
  return { path: resolve9(path), bytes: statSync4(path).size, sha256: fileHash3(path) };
}
function jsonPin(pin2, base) {
  return JSON.parse(readFileSync9(verifyPin2(pin2, base), "utf8"));
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
  const path = verifyPin2(pin2, base, 65 * 1024 ** 2), before = statSync4(path), raw = gunzipSync3(readFileSync9(path), { maxOutputLength: maxRaw });
  demand4(hash4(raw) === rawSha && statSync4(path).mtimeMs === before.mtimeMs && statSync4(path).size === before.size, "raw_digest_changed");
  return raw;
}
function validatePrices(pin2, base) {
  const p = jsonPin(pin2, base);
  demand4(p.protocol === "deepseek-cny-pricing-source-snapshot-v1" && p.currency === "CNY" && p.model === "deepseek-flash" && p.modelCalls === 0, "price_profile");
  demand4(p.officialSource === "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/" && same6(p.peak, { uncachedInput: 2, cachedInput: 0.04, output: 8 }) && same6(p.offPeak, { uncachedInput: 1, cachedInput: 0.02, output: 4 }), "price_rates");
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
    demand4(resolve9(this.configPath) === join6(resolve9(directory), "journal-config.json"), "journal_config_path");
    this.config = JSON.parse(readFileSync9(this.configPath, "utf8"));
    demand4(this.config.protocol === "campaign-api-journal-v1" && this.config.pendingLimit === 4 && this.config.model === "deepseek-flash", "journal_config_profile");
    this.configSha = configPin.sha256;
    this.path = join6(resolve9(directory), "api-events.jsonl");
    this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configSha };
    this.checkpoints.set(0, this.prefix);
  }
  consume(target) {
    demand4(integer(target.bytes) && integer(target.eventCount) && /^[a-f0-9]{64}$/.test(target.lastSha256), "invalid_journal_prefix");
    if (target.bytes <= this.prefix.bytes) {
      demand4(same6(this.checkpoints.get(target.bytes), target), "unknown_historical_prefix");
      return;
    }
    demand4(existsSync5(this.path) && statSync4(this.path).size >= target.bytes, "journal_prefix_missing");
    const fd = openSync5(this.path, "r");
    let at2 = this.prefix.bytes, carry = Buffer.alloc(0);
    try {
      while (at2 < target.bytes) {
        const b = Buffer.alloc(Math.min(16384, target.bytes - at2));
        const n = readSync4(fd, b, 0, b.length, at2);
        demand4(n > 0, "journal_short_read");
        at2 += n;
        carry = Buffer.concat([carry, b.subarray(0, n)]);
        let nl;
        while ((nl = carry.indexOf(10)) >= 0) {
          const line = carry.subarray(0, nl + 1);
          demand4(line.length <= 65536, "journal_line_limit");
          const frame = JSON.parse(line.subarray(0, -1).toString("utf8"));
          demand4(Buffer.from(JSON.stringify(frame) + `
`).equals(line) && frame.protocol === "campaign-api-journal-v1" && frame.eventSeq === this.prefix.eventCount && frame.previousEventSha256 === this.prefix.lastSha256 && integer(frame.requestSeq), "journal_chain");
          const offset = this.prefix.bytes, end = offset + line.length, sha = hash4(line);
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
      closeSync5(fd);
    }
    demand4(carry.length === 0 && same6(this.prefix, target), "journal_prefix_mismatch");
  }
  start(seq, prefix) {
    this.consume(prefix);
    const frame = this.starts.get(seq);
    demand4(frame && frame.eventSeq === prefix.eventCount - 1, "not_this_start_prefix");
    return frame.record;
  }
  finish(seq, ref) {
    demand4(integer(ref.finishOffset) && integer(ref.finishEnd) && ref.finishEnd > ref.finishOffset && ref.finishEnd - ref.finishOffset <= 65536, "finish_offset");
    const fd = openSync5(this.path, "r"), line = Buffer.alloc(ref.finishEnd - ref.finishOffset);
    try {
      demand4(readSync4(fd, line, 0, line.length, ref.finishOffset) === line.length, "finish_short_read");
    } finally {
      closeSync5(fd);
    }
    demand4(hash4(line) === ref.finishLineSha256 && line.at(-1) === 10, "finish_digest");
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

// scripts/repair-2026-10-08/cny-cash-shadow-v2.ts
var SELF = actualPin(import.meta.path);
var PROOF_SOURCE = actualPin(join7("F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\repair-2026-10-08", "paid-resource-proof-v2.ts"));

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
`), fd = openSync6(path, "wx", 384);
    try {
      writeFileSync2(fd, raw);
      fsyncSync3(fd);
    } finally {
      closeSync6(fd);
    }
    demand4(readFileSync10(path).equals(raw), "cash_config_readback");
    this.configPin = actualPin(path);
    this.path = join7(directory, "cash-events.jsonl");
    this.fd = openSync6(this.path, "wx+", 384);
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
      const read = Buffer.alloc(raw.length);
      demand4(readSync5(this.fd, read, 0, read.length, offset) === read.length && read.equals(raw) && statSync5(this.path).size === offset + raw.length, "cash_event_readback");
      this.prefix = { bytes: offset + raw.length, eventCount: this.prefix.eventCount + 1, lastSha256: hash4(raw) };
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
      closeSync6(this.fd);
      this.closed = true;
    }
  }
}
function createCnyCashShadow(options) {
  return new CnyCashShadow(options);
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
    this.binding = new JournalBinding(resolve10(options.journal.directory), options.journal.configPin, options.journal.sourcePin);
    demand4(this.binding.config.campaign === options.runId, "cash_journal_run_binding");
    this.config = { protocol: "cny-shadow-config-v2", runId: options.runId, providerKind: options.providerKind, scope: options.admission?.scope ?? "local-mock", ownerNonce: options.admission?.owned.ownerNonce ?? null, admissionPin: options.admission?.proofPin ?? null, envelopeNanoCny: (options.admission?.envelopeNanoCny ?? 0n).toString(), carryNanoCny: (options.admission?.carryNanoCny ?? 0n).toString(), pricesPin: options.prices, journalDirectory: resolve10(options.journal.directory), journalConfigPin: options.journal.configPin, journalSourcePin: options.journal.sourcePin, cashSourcePins: [SELF, PROOF_SOURCE], createdAt: new Date(this.clock.wallUnixMs()).toISOString(), priceTTL: "real-beforeForward24h", moneyUnit: "nanoCNY", invoice: false, foreignExchangeConversion: false };
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
    demand4(Buffer.from(input.rawRequest).equals(raw) && resolve10(input.capturedRequest.path) === resolve10(j.requestFile) && start.requestFile === j.requestFile && start.requestSha256 === j.requestSha256 && start.requestCompressedSha256 === input.capturedRequest.sha256 && start.requestBytes === raw.length && start.route === input.route && start.providerAttempted === false && Math.abs(start.reservationUsd - j.reservationUsd) < 0.000000001, "cash_actual_admission_binding");
    demand4(Math.abs(j.reservationUsd - (v.inputUpper * 0.3 + v.output * 1.2) / 1e6) < 0.000000001, "legacy_usd_reservation_binding");
    const checkpoint = jsonPin(actualPin(join7(this.binding.directory, "api-state.json")));
    demand4(checkpoint.configSha256 === this.binding.configSha && !existsSync6(join7(this.binding.directory, "journal-error.json")), "journal_checkpoint_unacknowledged");
    this.binding.consume(checkpoint.durablePrefix);
    for (const path of [j.requestFile, this.binding.path, join7(this.binding.directory, "api-state.json")]) {
      const fd = openSync6(path, "r+");
      try {
        fsyncSync3(fd);
      } finally {
        closeSync6(fd);
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
    let record, signature, source2, unknown = false;
    if (input.kind === "journal-finish") {
      record = this.binding.finish(s.seq, input.journalRef);
      demand4(record.requestSha256 === s.start.requestSha256 && record.requestFile === s.start.requestFile && record.route === s.route, "cash_finish_start_binding");
      signature = input.journalRef.finishLineSha256;
      source2 = { kind: "journal-finish", journalRef: input.journalRef };
    } else {
      demand4(input.requestSeq === s.seq && input.evidence.files.length > 0, "failed_capture_binding");
      for (const p of input.evidence.files)
        verifyPin2(p);
      this.binding.consume(input.evidence.originalPrefix);
      record = { ...s.start, ...input.evidence };
      signature = hash4(JSON.stringify(input.evidence));
      source2 = { kind: "failed-capture", evidence: input.evidence };
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
        demand4(same6(data2.usage, record.usage) && data2.model === record.servedModel || input.kind === "failed-capture" && same6(data2.usage, input.evidence.usage), "response_usage_binding");
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
      this.writer.append("late-evidence", { id: s.id, requestSeq: s.seq, source: source2, responsePin, rawResponseSha256: rawResponseSha, observedUsage, amountNanoCny: s.amount.toString(), reason: "overlapping_known_finish_retained_once" });
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
    const data = { id: s.id, requestSeq: s.seq, phase, amountNanoCny: amount.toString(), peakReservationNanoCny: s.reservation.toString(), source: source2, signature, responsePin: responsePin ?? null, rawResponseSha256: rawResponseSha ?? null, observedUsage: observedUsage ?? null, observedEstimatedNanoCny: estimate?.toString() ?? null, hostCaptureWallUnixMs: now.wall, hostMonotonicNs: now.mono.toString(), clockFault: now.fault, poisonReason: this.poisonReason ?? null };
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
    const value = { protocol: "cny-shadow-close-v2", runId: this.options.runId, ownerNonce: this.config.ownerNonce, configPin: this.configPin, cashEventsPin: cashEvents, cashPrefix, journalConfigPin: this.options.journal.configPin, journalSourcePin: this.options.journal.sourcePin, journalDirectory: resolve10(this.options.journal.directory), journalPrefix: inspection.prefix ?? this.binding.current(), journalValid: inspection.valid, journalAccountingClosed: inspection.accountingClosed, snapshot, releasePermitted: good, poisonReason: this.poisonReason ?? null, invoice: false, foreignExchangeConversion: false };
    const path = join7(this.directory, "cash-close.json"), fd = openSync6(path, "wx", 384);
    try {
      writeFileSync2(fd, JSON.stringify(value, null, 2) + `
`);
      fsyncSync3(fd);
    } finally {
      closeSync6(fd);
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
  const binding = new JournalBinding(config.journalDirectory, config.journalConfigPin, config.journalSourcePin), raw = readFileSync10(proof.cashEventsPin.path);
  let at2 = 0, seq = 0, last = proof.configPin.sha256;
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
      demand4(start.requestSha256 === d.rawRequestSha256 && start.requestCompressedSha256 === d.requestPin.sha256 && resolve10(start.requestFile) === resolve10(d.requestPin.path) && start.requestBytes === body.length && start.route === d.route && v.inputUpper === d.inputUpper && v.output === d.outputLimit, "cash_start_proof");
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
          demand4(d.responsePin && d.rawResponseSha256 && resolve10(d.responsePin.path) === resolve10(receipt.responseFile) && d.responsePin.sha256 === receipt.responseCompressedSha256 && d.rawResponseSha256 === receipt.responseSha256, "cash_known_response_missing");
          const body = gzipProof(d.responsePin, d.rawResponseSha256), data = JSON.parse(body.toString("utf8"));
          demand4(same6(data.usage, d.observedUsage) && same6(data.usage, receipt.usage) && data.model === receipt.servedModel, "cash_usage_proof");
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
          demand4(same6(data.usage, d.observedUsage), "late_usage_proof");
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
      demand4(same6(data.usage, d.observedUsage), "late_overlap_usage");
    } else
      demand4(e.kind === "poison", "cash_event_kind");
    at2 += line.length;
    seq++;
    last = hash4(line);
  }
  demand4(at2 === raw.length && same6(proof.cashPrefix, { bytes: at2, eventCount: seq, lastSha256: last }), "cash_exact_prefix");
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
  demand4(journal.valid && journal.accountingClosed && journal.snapshot?.acceptedRequestCount === states.size && same6(journal.prefix, proof.journalPrefix) && pendingCount === 0 && unknownCount === 0 && proof.releasePermitted === true, "cash_or_peer_not_closed");
  return { proof, config, states };
}

// scripts/repair-2026-10-10/full-f/shared/digitalocean-usd-cash.ts
function durable(path, value) {
  const raw = Buffer.from(JSON.stringify(value, null, 2) + `
`), fd = openSync7(path, "wx", 384);
  try {
    let at2 = 0;
    while (at2 < raw.length) {
      const count2 = writeSync4(fd, raw, at2, raw.length - at2);
      demand4(count2 > 0, "usd_cash_short_write");
      at2 += count2;
    }
    fsyncSync4(fd);
  } finally {
    closeSync7(fd);
  }
  demand4(readFileSync11(path).equals(raw), "usd_cash_readback");
  return actualPin(path);
}
function validateUsdPrices(pin2, providerSlug = BENCHMARK_PROVIDER.providerSlug) {
  const data = jsonPin(pin2);
  demand4(data.protocol === "openrouter-usd-pricing-source-snapshot-v1" && data.model === BENCHMARK_PROVIDER.model && data.currency === "USD" && data.providerSlug === providerSlug && data.actualOfficialGET === true && data.modelCalls === 0, "openrouter_price_profile");
  demand4(same6(data.reservationRates, BENCHMARK_PROVIDER.peakRates), "openrouter_reservation_rates");
  const raw = jsonPin(data.originalResponsePin);
  demand4(raw.data?.endpoints?.some((row) => row.provider_name === { relace: "Relace", deepseek: "DeepSeek", digitalocean: "DigitalOcean" }[providerSlug] && row.tag === providerSlug && row.model_id === BENCHMARK_PROVIDER.model), "openrouter_price_raw_binding");
  return data;
}
function boundStart(directory, data) {
  const raw = readFileSync11(join8(directory, "api-events.jsonl")), end = data.startPrefix.bytes;
  demand4(Number.isSafeInteger(end) && end > 0 && end <= raw.length && raw[end - 1] === 10, "usd_start_prefix_bounds");
  const begin = raw.lastIndexOf(10, end - 2) + 1, line = raw.subarray(begin, end), event = JSON.parse(line.toString("utf8"));
  demand4(hash4(line) === data.startPrefix.lastSha256 && event.kind === "start" && event.eventSeq + 1 === data.startPrefix.eventCount && event.requestSeq === data.ticket.requestSeq && event.record.route === data.ticket.route && same6(data.requestPin, actualPin(event.record.requestFile)) && data.requestSha256 === event.record.requestSha256, "usd_start_journal_binding");
  gzipProof(data.requestPin, data.requestSha256, undefined, 4 * 1024 ** 2);
  return event.record;
}
function createBenchmarkCash(options, provider) {
  if (!provider)
    return createCnyCashShadow(options);
  return new UsdCash(options);
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
    this.fd = openSync7(join8(this.directory, "cash-events.jsonl"), "wx+", 384);
    fsyncSync4(this.fd);
    try {
      admission?.registerCash(this.configPin);
    } catch (error) {
      closeSync7(this.fd);
      throw error;
    }
  }
  append(kind, data) {
    const event = { protocol: "openrouter-usd-cash-event-v1", index: this.events.length, previousSha256: this.previousHash, kind, data };
    const raw = Buffer.from(JSON.stringify(event) + `
`);
    demand4(raw.length <= 65536 && this.bytes + raw.length <= 256 * 1024 ** 2, "usd_cash_event_limit");
    let at2 = 0;
    while (at2 < raw.length) {
      const count2 = writeSync4(this.fd, raw, at2, raw.length - at2, this.bytes + at2);
      demand4(count2 > 0, "usd_cash_short_write");
      at2 += count2;
    }
    fsyncSync4(this.fd);
    const readback = Buffer.alloc(raw.length);
    demand4(readSync6(this.fd, readback, 0, raw.length, this.bytes) === raw.length && readback.equals(raw) && statSync6(join8(this.directory, "cash-events.jsonl")).size === this.bytes + raw.length, "usd_cash_event_readback");
    this.bytes += raw.length;
    this.previousHash = hash4(raw);
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
    demand4(inspected.valid && Buffer.from(input.rawRequest).equals(raw) && resolve11(input.capturedRequest.path) === resolve11(j.requestFile) && j.requestSeq === this.states.size, "usd_actual_request_binding");
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
    const signature = hash4(JSON.stringify(finish));
    if (state.signature) {
      demand4(state.signature === signature, "usd_duplicate_finish_changed");
      return this.snapshot();
    }
    let phase, amount, receipt;
    if (finish.kind === "journal-finish") {
      const ref = finish.journalRef;
      const bytes = readFileSync11(join8(this.options.journal.directory, "api-events.jsonl"));
      const line = bytes.subarray(ref.finishOffset, ref.finishEnd);
      demand4(hash4(line) === ref.finishLineSha256, "usd_finish_line_changed");
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
    closeSync7(this.fd);
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
  const config = jsonPin(proof.configPin), eventsRaw = readFileSync11(verifyPin2(proof.cashEventsPin));
  const journalConfig = jsonPin(config.journal.configPin);
  validateUsdPrices(config.pricesPin, journalConfig.providerSlug ?? "deepseek");
  verifyPin2(config.sourcePin);
  verifyPin2(config.journal.sourcePin);
  demand4(config.currency === "USD" && config.protocol === "openrouter-usd-cash-config-v1" && Number.isFinite(config.capUsd) && config.capUsd > 0 && resolve11(config.journal.directory) === resolve11(proof.journalDirectory) && journalConfig.currency === "USD" && journalConfig.provider === BENCHMARK_PROVIDER.kind && journalConfig.campaign === config.runId && journalConfig.priorCampaignCostUpperBoundUsd === 0 && journalConfig.capUsd <= config.capUsd, "usd_close_config");
  const journal = inspectCampaignJournal(proof.journalDirectory);
  demand4(journal.valid && journal.accountingClosed && same6(journal.prefix, proof.journalPrefix), "usd_close_journal");
  demand4(eventsRaw.length <= 256 * 1024 ** 2 && (eventsRaw.length === 0 || eventsRaw.at(-1) === 10), "usd_cash_complete_events");
  let previous = proof.configPin.sha256, seq = 0, starts = 0, known = 0, unknown = 0, unknownCount = 0;
  const active = new Map;
  for (const text of eventsRaw.toString("utf8").trimEnd().split(`
`).filter(Boolean)) {
    const event = JSON.parse(text);
    demand4(JSON.stringify(event) === text && Buffer.byteLength(text) <= 65536 && event.index === seq++ && event.previousSha256 === previous && event.protocol === "openrouter-usd-cash-event-v1", "usd_cash_chain");
    previous = hash4(text + `
`);
    const { data } = event;
    if (event.kind === "start") {
      const ticket = data.ticket, start = boundStart(proof.journalDirectory, data);
      demand4(ticket.requestSeq === starts++ && ticket.currency === "USD" && ticket.reservationUsd === (config.providerKind === "local-mock" ? 0 : start.reservationUsd), "usd_start_reservation");
      const pending = [...active.values()].reduce((sum, row) => sum + (row.dispatchAllowed ? row.reservationUsd : 0), 0);
      demand4(ticket.dispatchAllowed === known + unknown + pending + ticket.reservationUsd <= config.capUsd + 0.000000001, "usd_start_budget_replay");
      active.set(ticket.requestSeq, ticket);
    } else {
      demand4(event.kind === "finish" && same6(active.get(data.ticket.requestSeq), data.ticket) && data.signature === hash4(JSON.stringify(data.finish)) && Number.isFinite(data.amountUsd) && data.amountUsd >= 0, "usd_cash_finish_without_start");
      if (data.finish.kind === "journal-finish") {
        const ref = data.finish.journalRef, raw = readFileSync11(join8(proof.journalDirectory, "api-events.jsonl")).subarray(ref.finishOffset, ref.finishEnd);
        const offset = journal.offsets.get(data.ticket.requestSeq);
        demand4(offset && offset.offset === ref.finishOffset && offset.offset + offset.bytes === ref.finishEnd && offset.sha256 === ref.finishLineSha256 && hash4(raw) === ref.finishLineSha256, "usd_cash_raw_finish");
        const source2 = JSON.parse(raw.toString("utf8"));
        demand4(source2.kind === "finish" && source2.requestSeq === data.ticket.requestSeq && source2.record.route === data.ticket.route && data.phase === (source2.record.costBasis === "reservation" ? "unknown" : "known") && data.costBasis === source2.record.costBasis && data.generationId === (source2.record.requestId ?? null) && data.providerName === (source2.record.providerName ?? null) && data.servedModel === (source2.record.servedModel ?? null) && (config.providerKind === "local-mock" ? data.amountUsd === 0 : source2.record.usdUpperBound === data.amountUsd), "usd_cash_amount_binding");
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

// scripts/bench-runner/pre-native-history.ts
import { verify as verify2 } from "crypto";
import { readFileSync as readFileSync12 } from "fs";
function inspectPreNativeHistory(m, budget, seen) {
  let knownUsd = 0, unknownUsd = 0, calls = 0;
  const need5 = (x, s) => {
    if (!x)
      throw Error(s);
  };
  for (const h of m.adapterConfig.preNativeRecoveryHistory ?? []) {
    const envelope = readPinned(h.reviewEnvelopePin), r = envelope.review, authority = m.adapterConfig.bindingSpec?.authorityPin;
    checkPin(authority);
    need5(envelope.protocol === "bench-root-signed-pre-native-reconciliation-v1" && r?.protocol === "bench-pre-native-reconciliation-v1" && verify2(null, Buffer.from(JSON.stringify(r)), readFileSync12(authority.path), Buffer.from(envelope.signature, "base64")), "pre_native_root_signature");
    need5(r.taskId === m.taskId && r.bench === m.bench && r.attemptId === h.attemptId && r.runId === h.runId && r.cashClosePin.sha256 === h.cashClosePin.sha256 && r.closureAuditPin.sha256 === h.closureAuditPin.sha256, "pre_native_history_identity");
    const audit = readPinned(h.closureAuditPin), context = readPinned(r.contextPin), process2 = readPinned(r.processReceiptPin);
    checkPin(r.manifestPin);
    need5(context.attemptId === h.attemptId && context.manifestPin.sha256 === r.manifestPin.sha256 && process2.attemptId === h.attemptId && process2.manifestPin.sha256 === r.manifestPin.sha256, "pre_native_actual_context");
    need5(audit.taskId === m.taskId && audit.bench === m.bench && audit.attemptId === h.attemptId && audit.runId === h.runId && audit.nativeCommandCount === 0 && audit.actorsEverCreated === false && audit.candidateOrSubmissionPresent === false && audit.resourceReleased === true && audit.brokerLaneClosed === true, "pre_native_zero_custody");
    need5(audit.evidencePins?.length > 0, "pre_native_raw_evidence");
    for (const p of audit.evidencePins)
      checkPin(p);
    for (const p of r.permanentLockPins)
      checkPin(p);
    need5(audit.exactPidAbsence?.some((x) => x.pid === process2.pid && x.incarnation === process2.incarnation), "pre_native_incarnation_closure");
    const cash = verifyBenchmarkCashClosure(h.cashClosePin), j = inspectCampaignJournal(cash.proof.journalDirectory), s = cash.proof.snapshot;
    need5(!seen.has(cash.config.runId) && cash.config.runId === h.runId && budget.cashClosePins.some((p) => p.path === h.cashClosePin.path && p.sha256 === h.cashClosePin.sha256), "pre_native_cash_chain");
    seen.add(h.runId);
    need5(j.valid && j.accountingClosed && j.snapshot?.acceptedRequestCount === 0 && j.snapshot?.finishedRequestCount === 0 && s.pendingCount === 0 && s.billedUsd === 0 && s.unknownReservationUsd === 0 && cash.config.capUsd <= m.original.taskCapUsd, "pre_native_actual_zero_cash");
    knownUsd += s.billedUsd;
    unknownUsd += s.unknownReservationUsd;
    calls += j.snapshot.acceptedRequestCount;
  }
  return { knownUsd, unknownUsd, calls };
}

// scripts/bench-runner/original-history.ts
import { createHash as createHash6 } from "crypto";
var need5 = (x, message) => {
  if (!x)
    throw Error(message);
};
var same7 = (a, b) => a?.path === b?.path && a?.sha256 === b?.sha256 && a?.bytes === b?.bytes;
function checkedPin(m, p) {
  checkPin(p);
  need5([...m.provenance.sourcePins, ...m.provenance.contractPins, ...m.history.priorRunPins].some((x) => same7(x, p)), "original_history_pin_not_manifest_bound:" + p.path);
}
function streams(m, p) {
  checkedPin(m, p);
  const c = readPinned(p);
  need5(c.exitObserved === true && c.closeObserved === true, "original_process_close_unproven");
  for (const s of [c.stdout, c.stderr])
    checkPin(s);
  return c;
}
function finalHandIn(database, id) {
  const task = database.query("select id,run,mode,result,created_at,solve_seconds from task where id=?").get(id);
  need5(task, "original_main_task_missing");
  if (task.result !== null)
    return { task, resultPresent: true, submitPresent: false, submits: [] };
  need5(/^[A-Za-z0-9_]+$/.test(task.mode), "original_mode_identifier");
  const deadline = Number(task.created_at) + Number(task.solve_seconds) * 1000;
  need5(Number.isFinite(deadline) && task.solve_seconds > 0, "original_task_clock");
  const units = database.query('select agent,instance,unit from "task_' + task.mode + '" where task=?').all(id);
  const submits = [];
  for (const u of units) {
    need5(/^[A-Za-z0-9_]+$/.test(u.agent), "original_agent_identifier");
    for (const row of database.query('select seq,at,body from "agent_' + u.agent + `_msg" where instance=? and unit=? and kind='call' and at<=?`).all(u.instance, u.unit, deadline)) {
      let payload;
      try {
        payload = JSON.parse(row.body);
      } catch {
        throw Error("original_call_payload_unparseable");
      }
      for (const call of payload.calls ?? [])
        if (call.name === "submit")
          submits.push({ agent: u.agent, instance: u.instance, unit: u.unit, seq: row.seq, at: row.at, callId: call.id, answerSha256: createHash6("sha256").update(typeof call.input?.answer === "string" ? call.input.answer : "").digest("hex") });
    }
  }
  const station = database.query("select count(*) n from cycle where mode=? and cycle='submit'").get(task.mode);
  need5(station.n > 0, "original_final_candidate_policy_requires_adapter_recovery");
  return { task, resultPresent: false, submitPresent: submits.length > 0, submits };
}
function auditOriginalHistory(m, c) {
  need5(c?.protocol === "bench-original-history-v1" && c.taskId === m.taskId && c.bench === m.bench, "original_history_identity");
  need5(c.attempts.length > 0 && c.attempts.length + (m.adapterConfig.preNativeRecoveryHistory ?? []).length === c.cashClosePins.length, "original_history_complete_cash_attempts");
  need5(m.history.validResultPins.length === 0, "valid_wrong_must_never_repeat");
  checkedPin(m, c.reviewPin);
  const review = readPinned(c.reviewPin);
  need5(review.protocol === "bench-original-history-review-v1" && review.taskId === m.taskId && review.bench === m.bench, "original_history_review_identity");
  need5(JSON.stringify(review.cashClosePins) === JSON.stringify(c.cashClosePins) && JSON.stringify(review.attemptRunIds) === JSON.stringify(c.attempts.map((x) => x.runId)), "original_history_review_coverage");
  checkedPin(m, c.originalTaskCashConfigPin);
  const original = readPinned(c.originalTaskCashConfigPin);
  need5(original.capUsd === m.original.taskCapUsd, "original_task_cap_config");
  let knownUsd = 0, unknownUsd = 0, calls = 0, resultPresent = false, submitPresent = false;
  const seen = new Set, actorCids = [], nativeRows = [], mainObservations = [];
  for (const a of c.attempts) {
    need5(c.cashClosePins.some((p) => same7(p, a.cashClosePin)), "original_cash_coverage");
    checkedPin(m, a.cashClosePin);
    const cash = verifyBenchmarkCashClosure(a.cashClosePin), journal = inspectCampaignJournal(cash.proof.journalDirectory), s = cash.proof.snapshot;
    need5(!seen.has(a.runId) && cash.config.runId === a.runId, "original_history_unique_actual_run");
    seen.add(a.runId);
    need5(cash.config.capUsd <= m.original.taskCapUsd + 0.000000001 && journal.valid && journal.accountingClosed && s.pendingCount === 0 && s.pendingReservationUsd === 0, "original_history_cash_not_closed");
    knownUsd += s.billedUsd;
    unknownUsd += s.unknownReservationUsd;
    calls += journal.snapshot.acceptedRequestCount;
    checkedPin(m, a.summaryPin);
    const summary = readPinned(a.summaryPin);
    need5(summary.runId === a.runId, "original_summary_run");
    if (summary.taskPins?.length)
      resultPresent = true;
    checkedPin(m, a.processPin);
    const process2 = readPinned(a.processPin);
    need5(process2.runId === a.runId, "original_process_run");
    streams(m, a.standClosePin);
    for (const p of a.engineClosePins)
      streams(m, p);
    need5(a.ownedLedgerPins.length > 0 && a.closureProofPins.length > 0, "original_native_custody_required");
    for (const p of [...a.ownedLedgerPins, ...a.closureProofPins])
      checkedPin(m, p);
    const custody = review.attemptClosures?.find((x) => x.runId === a.runId);
    need5(custody && custody.brokerLaneClosed === true && custody.resourceReleased === true && custody.originalProcessesClosed === true && JSON.stringify(custody.proofPins) === JSON.stringify(a.closureProofPins), "original_custody_review_coverage");
    const ledger = a.ownedLedgerPins.find((p) => p.path.endsWith(".sqlite"));
    need5(ledger, "original_native_ledger_required");
    for (const suffix of ["-wal", "-shm"])
      if (existsSync7(ledger.path + suffix))
        need5(a.ownedLedgerPins.some((p) => resolve12(p.path) === resolve12(ledger.path + suffix)), "original_native_sidecar_unpinned");
    const db = new Database(ledger.path, { readonly: true });
    let actors = 0, commands = 0;
    const runActorCids = [];
    try {
      for (const row of db.query("select cid,closed from actor").all()) {
        need5(row.closed === 1 && /^[a-f0-9]{64}$/.test(row.cid), "original_actor_custody_open");
        actorCids.push(row.cid);
        runActorCids.push(row.cid);
        actors++;
      }
      for (const row of db.query("select json from command").all()) {
        const command = JSON.parse(row.json);
        need5(command.closeObserved === true && Number.isInteger(command.exitCode) && !command.captureFaults?.length, "original_command_capture_open");
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
        if (existsSync7(d.pin.path + suffix))
          need5(d.sidecarPins.some((p) => resolve12(p.path) === resolve12(d.pin.path + suffix)), "original_main_db_sidecar_unpinned");
      const db2 = new Database(d.pin.path, { readonly: true });
      try {
        const f = finalHandIn(db2, d.mainTaskId);
        need5(f.task.run === a.runId, "original_main_run");
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
      need5(grade.taskId === m.taskId, "original_grade_task_identity");
      if (grade.result)
        resultPresent = true;
    }
  }
  const preNative = inspectPreNativeHistory(m, { cashClosePins: c.cashClosePins }, seen);
  knownUsd += preNative.knownUsd;
  unknownUsd += preNative.unknownUsd;
  calls += preNative.calls;
  need5(seen.size === c.cashClosePins.length && Math.abs(knownUsd - m.original.priorKnownUsd) < 0.000000001 && Math.abs(unknownUsd - m.original.priorUnknownUsd) < 0.000000001, "original_all_cash_exposure_preserved");
  need5(c.canonicalLocks.length > 0, "real_historical_canonical_required");
  for (const l of c.canonicalLocks) {
    checkedPin(m, l.pin);
    checkedPin(m, l.entryPin);
    const lock = readPinned(l.pin), entry = readPinned(l.entryPin);
    need5(lock.taskId === m.taskId && lock.bench === m.bench && lock.nonce === l.nonce && same7(lock.entryPin, l.entryPin), "real_canonical_nonce_entry_join");
    const e = entry.entry ?? entry;
    need5(e.taskId === m.taskId && e.nonce === l.nonce, "historical_entry_identity");
  }
  need5(JSON.stringify(review.canonicalLockPins) === JSON.stringify(c.canonicalLocks.map((x) => x.pin)), "review_canonical_coverage");
  for (const p of c.preservedSnapshotPins)
    checkedPin(m, p);
  let resolvedSubmits = 0, dispositionApproved = false;
  const resolutionProofPins = [];
  if (c.originalResultDispositionPin) {
    checkedPin(m, c.originalResultDispositionPin);
    const disposition = readPinned(c.originalResultDispositionPin);
    need5(disposition.protocol === "bench-original-result-disposition-v1" && disposition.taskId === m.taskId && disposition.bench === m.bench, "original_disposition_identity");
    for (const resolution of disposition.resolutions ?? []) {
      checkedPin(m, resolution.proofPin);
      const proof = readPinned(resolution.proofPin);
      need5(proof.protocol === "bench-original-result-recovery-readonly-review-v1" && proof.taskId === m.taskId && proof.bench === m.bench && proof.runId === resolution.runId, "original_disposition_proof_identity");
      need5(proof.validResultRecoverableFromExistingGrade === false && proof.originalGrade?.standGradeRows === 0 && proof.originalGrade?.gradeJsonFiles?.length === 0 && proof.originalGrade?.taskResult === null && proof.originalCandidate?.existed === true && proof.originalCandidate?.ownedLedgerClosed === true && proof.originalCandidate?.filesystemSnapshotOrCapsulePresentInRun === false && proof.originalSubmit?.ran === false && proof.originalSubmit?.exactOriginalToolReason === "this station ended before the call was run", "original_disposition_not_unexecuted_destroyed_candidate");
      const observation = mainObservations.find((x) => x.runId === resolution.runId && x.mainTaskId === resolution.mainTaskId);
      need5(observation && !observation.resultPresent, "original_disposition_main_identity");
      checkPin(proof.originalSubmit.extractPin);
      const extract = readPinned(proof.originalSubmit.extractPin), call = extract.assistantSubmit, tool = extract.matchingToolResponse;
      need5(nativeRows.some((x) => x.runId === resolution.runId && x.actorCids.includes(proof.originalCandidate.cid)), "original_disposition_destroyed_candidate_identity");
      need5(extract.task?.id === observation.mainTaskId && extract.task?.run === observation.runId && extract.databasePins?.some((p) => same7(p, observation.databasePin)), "original_submit_extract_database_join");
      const agent = observation.submits.find((s) => s.callId === proof.originalSubmit.callId)?.agent;
      need5(typeof agent === "string" && /^[A-Za-z0-9_]+$/.test(agent), "original_disposition_agent_identity");
      const db = new Database(observation.databasePin.path, { readonly: true });
      try {
        for (const row of [call, tool]) {
          const actual = db.query('select body,at,kind from "agent_' + agent + '_msg" where instance=? and unit=? and seq=?').get(row.instance, row.unit, row.seq);
          need5(actual && actual.body === row.body && actual.at === row.at && actual.kind === row.kind, "original_submit_extract_actual_row_mismatch");
        }
      } finally {
        db.close();
      }
      const response = JSON.parse(tool.body);
      need5(response.id === proof.originalSubmit.callId && response.name === "submit" && response.value?.ran === false && response.value?.why === proof.originalSubmit.exactOriginalToolReason, "original_submit_tool_not_unexecuted");
      const matches = observation.submits.filter((s) => s.callId === response.id && s.instance === call.instance && s.unit === call.unit && s.seq === call.seq && s.answerSha256 === proof.originalSubmit.answerSha256);
      need5(matches.length === 1, "original_submit_resolution_not_exact");
      need5(!resolutionProofPins.some((p) => same7(p, resolution.proofPin)), "duplicate_original_submit_resolution");
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
  need5(!actual.resultPresent && !actual.unresolvedSubmitPresent, "original_result_requires_adapter_recovery");
  need5(actual.rootDispositionApproved, "original_result_disposition_requires_root_review");
  return { ...actual, candidateOrSubmissionPresent: false, historicalSubmitPresent: actual.submitPresent, legacyIdentityPreserved: false };
}

// scripts/bench-runner/saved-candidate-inventory.ts
var need6 = (x, s) => {
  if (!x)
    throw Error(s);
};
var same8 = (a, b) => !!a && !!b && resolve13(a.path) === resolve13(b.path) && a.bytes === b.bytes && a.sha256 === b.sha256;
function bound(m, p, parse = true) {
  checkPin(p);
  need6([...m.provenance.sourcePins, ...m.provenance.contractPins, ...m.history.priorRunPins].some((x) => same8(x, p)), "saved_candidate_pin_not_manifest_bound");
  return parse ? readPinned(p) : p;
}
var artifactKeys = ["candidateArtifactPin", "capsulePin", "partialGradePin", "originalPid1FramePin", "rawCtrfPin", "originalContractPin", "closureProofPin", "frameRecoveryProofPin"];
function priorGradeUnrecoverable(f) {
  return f.originalValidatorRejected === true || f.originalGradeValid === false && f.originalGraderResultAbsent === true && f.originalTestsReached === false;
}
function samePinSet(a, b) {
  return a.length === b.length && new Set(a.map((x) => resolve13(x.path) + ":" + x.sha256 + ":" + x.bytes)).size === a.length && a.every((x) => b.some((y) => same8(x, y)));
}
function detectOriginalCandidates(c) {
  const detected = [];
  for (const a of c.attempts ?? []) {
    for (const p of a.candidateCustodyPins ?? [])
      checkPin(p);
    for (const p of a.gradePins ?? []) {
      const g = readPinned(p);
      if (g.candidateArtifactPin) {
        checkPin(g.candidateArtifactPin);
        detected.push(g.candidateArtifactPin);
      } else
        need6(!g.candidateArtifactCapture && !g.capsulePath, "original_saved_candidate_artifact_identity_missing");
    }
  }
  return [...new Map(detected.map((p) => [resolve13(p.path) + ":" + p.sha256, p])).values()];
}
function verifySavedCandidateDisposition(m, actual) {
  const config = m.adapterConfig.savedCandidateDisposition;
  need6(config?.protocol === "bench-saved-candidate-disposition-contract-v1", "saved_candidate_disposition_required");
  const envelope = bound(m, config.envelopePin);
  need6(envelope.protocol === "bench-root-signed-saved-candidate-disposition-v1" && typeof envelope.signature === "string", "saved_candidate_signed_envelope");
  const p = envelope.disposition;
  need6(p?.protocol === "bench-saved-candidate-disposition-v1" && p.taskId === m.taskId && p.bench === m.bench, "saved_candidate_identity");
  need6(!m.history.validResultPins.length && !actual.resultPresent && !actual.unresolvedSubmitPresent, "saved_candidate_original_valid_or_submit_requires_recovery");
  need6(Date.parse(p.expiresAtUtc) > Date.now(), "saved_candidate_disposition_expired");
  const old = bound(m, p.predecessorManifestPin), authority = old.adapterConfig?.bindingSpec?.authorityPin;
  checkPin(authority);
  need6(same8(authority, m.adapterConfig.bindingSpec?.authorityPin) && same8(authority, p.authorityPin), "saved_candidate_same_original_authority_required");
  need6(verify3(null, Buffer.from(JSON.stringify(p)), readFileSync14(authority.path), Buffer.from(envelope.signature, "base64")), "saved_candidate_signature_invalid");
  need6(old.taskId === m.taskId && old.bench === m.bench, "saved_candidate_predecessor_identity");
  const lock = bound(m, p.oldAttemptLockPin), originalEnvelope = bound(m, lock.signedEntryPin);
  need6(lock.attemptId === p.attemptId && lock.taskId === m.taskId && lock.bench === m.bench && same8(lock.manifestPin, p.predecessorManifestPin), "saved_candidate_old_attempt_lock_join");
  need6(originalEnvelope.protocol === "novaeve-root-signed-entry-v4" && verify3(null, Buffer.from(JSON.stringify(originalEnvelope.entry)), readFileSync14(authority.path), Buffer.from(originalEnvelope.signature, "base64")), "saved_candidate_original_entry_signature");
  const e = originalEnvelope.entry;
  need6(e.nonce === p.attemptId && e.taskId === m.taskId && e.bench === m.bench && same8(e.rootRuntimeBinding?.manifestPin, p.predecessorManifestPin), "saved_candidate_original_signed_identity");
  bound(m, p.aggregateBudgetPin);
  need6(same8(p.aggregateBudgetPin, m.adapterConfig.terminalDriver?.aggregateBudgetPin), "saved_candidate_aggregate_budget_join");
  const history = m.adapterConfig.originalHistory;
  need6(history && JSON.stringify(p.canonicalLockPins) === JSON.stringify(history.canonicalLocks.map((x) => x.pin)), "saved_candidate_canonical_coverage");
  for (const item of history.canonicalLocks) {
    const l = bound(m, item.pin), env = bound(m, item.entryPin);
    need6(same8(l.entryPin, item.entryPin) && l.nonce === item.nonce && env.protocol === "novaeve-root-signed-entry-v4" && env.entry.taskId === m.taskId && env.entry.bench === m.bench && env.entry.nonce === l.nonce && verify3(null, Buffer.from(JSON.stringify(env.entry)), readFileSync14(authority.path), Buffer.from(env.signature, "base64")), "saved_candidate_canonical_original_signature");
  }
  const attempt = history.attempts.find((a) => a.runId === p.runId);
  need6(attempt && attempt.mainDatabases.some((d) => same8(d.pin, p.mainDatabasePin) && d.mainTaskId === p.mainTaskId), "saved_candidate_actual_attempt_database");
  const database = new Database2(p.mainDatabasePin.path, { readonly: true });
  try {
    const row = database.query("select id,run,state,result from task where id=?").get(p.mainTaskId);
    need6(row?.run === p.runId && row.state === "claimed" && row.result === null, "saved_candidate_actual_main_state");
  } finally {
    database.close();
  }
  const observation = actual.mainObservations.find((x) => x.runId === p.runId && x.mainTaskId === p.mainTaskId && same8(x.databasePin, p.mainDatabasePin));
  need6(observation && !observation.resultPresent && !observation.submitPresent && observation.submits.length === 0, "saved_candidate_actual_main_no_final_result");
  need6(JSON.stringify(p.cashClosePins) === JSON.stringify(history.cashClosePins) && p.fees.knownUsd === actual.knownUsd && p.fees.unknownUsd === actual.unknownUsd && p.fees.calls === actual.calls, "saved_candidate_complete_fee_coverage");
  need6(p.originalContract.taskCapUsd === old.original.taskCapUsd && p.originalContract.solveSeconds === old.original.solveSeconds && p.originalContract.gradeSeconds === old.original.gradeSeconds && p.originalContract.providerSeconds === old.original.providerSeconds, "saved_candidate_original_contract_join");
  for (const k of ["taskCapUsd", "solveSeconds", "gradeSeconds", "providerSeconds", "cpu", "memoryMb", "model", "provider", "reasoning", "toolSeconds"])
    need6(m.original[k] === old.original[k], "saved_candidate_contract_cannot_expand:" + k);
  need6(p.decisions?.originalFormalResultUnrecoverable === true && p.decisions.originalCandidateCompletelyPreserved === true && p.decisions.allowNewAttempt === true && p.decisions.promoteOriginalValid === false && p.decisions.regradeOriginal === false && p.decisions.restoreCandidateIntoFreshWorkspace === false, "saved_candidate_explicit_narrow_decision");
  const facts = bound(m, p.factsPin);
  need6(facts.taskId === m.taskId && facts.bench === m.bench && facts.attemptId === p.attemptId && facts.runId === p.runId && facts.originalCandidateOrSubmissionPresent === true && facts.originalAssistantSubmitCount === 0 && facts.originalMainTask?.id === p.mainTaskId && facts.originalMainTask?.state === "claimed" && facts.originalMainTask?.result === null && facts.originalValidatorResult?.valid === false, "saved_candidate_original_rejection_facts");
  need6(Array.isArray(config.candidateEvidencePins) && config.candidateEvidencePins.length === artifactKeys.length, "saved_candidate_complete_artifacts");
  for (const k of artifactKeys) {
    const pin2 = p[k];
    bound(m, pin2, false);
    need6(same8(pin2, facts[k]) && config.candidateEvidencePins.some((x) => same8(x, pin2)), "saved_candidate_evidence_join:" + k);
  }
  need6(attempt.closureProofPins.some((x) => same8(x, p.closureProofPin)), "saved_candidate_closure_not_actual_history");
  const candidates = [{ runId: p.runId, candidateArtifactPin: p.candidateArtifactPin, capsulePin: p.capsulePin, partialGradePin: p.partialGradePin, closureProofPin: p.closureProofPin, mainDatabasePin: p.mainDatabasePin, mainTaskId: p.mainTaskId }, ...p.priorPreservedCandidates ?? []];
  need6(Array.isArray(p.priorPreservedCandidates) && new Set(candidates.map((x) => x.runId)).size === candidates.length, "saved_candidate_unique_complete_runs");
  for (const item of candidates) {
    const a = history.attempts.find((a2) => a2.runId === item.runId);
    need6(a && a.gradePins.some((x) => same8(x, item.partialGradePin)) && a.closureProofPins.some((x) => same8(x, item.closureProofPin)) && a.mainDatabases.some((x) => same8(x.pin, item.mainDatabasePin) && x.mainTaskId === item.mainTaskId), "saved_candidate_prior_actual_history_join");
    const grade = bound(m, item.partialGradePin);
    need6(same8(grade.candidateArtifactPin, item.candidateArtifactPin) && !grade.result, "saved_candidate_actual_grade_candidate_join");
    for (const k of ["candidateArtifactPin", "capsulePin", "closureProofPin", "mainDatabasePin"])
      bound(m, item[k], false);
    const observation2 = actual.mainObservations.find((x) => x.runId === item.runId && x.mainTaskId === item.mainTaskId && same8(x.databasePin, item.mainDatabasePin));
    need6(observation2 && !observation2.resultPresent && !actual.unresolvedSubmitPresent, "saved_candidate_prior_original_no_executed_result_or_submit");
    const db = new Database2(item.mainDatabasePin.path, { readonly: true });
    try {
      const row = db.query("select id,run,state,result from task where id=?").get(item.mainTaskId);
      need6(row?.run === item.runId && row.state === "claimed" && row.result === null, "saved_candidate_prior_actual_main_state");
    } finally {
      db.close();
    }
    if (item.runId !== p.runId) {
      const f = bound(m, item.factsPin);
      need6(f.taskId === m.taskId && f.bench === m.bench && f.runId === item.runId && f.candidatePresent === true && f.originalFormalResultUnrecoverable === true && f.candidateCompletelyPreserved === true && priorGradeUnrecoverable(f) && f.originalAssistantSubmitCount === observation2.submits.length && (observation2.submits.length === 0 || f.originalSubmitExecuted === false) && f.originalMainTask?.id === item.mainTaskId && f.originalMainTask.state === "claimed" && f.originalMainTask.result === null, "saved_candidate_prior_root_facts");
      for (const k of ["candidateArtifactPin", "capsulePin", "partialGradePin", "closureProofPin", "mainDatabasePin"])
        need6(same8(f[k], item[k]), "saved_candidate_prior_fact_pin_join");
    }
  }
  const detected = detectOriginalCandidates(history), inventory = p.candidateInventoryPins;
  need6(Array.isArray(inventory) && samePinSet(inventory, detected) && samePinSet(inventory, candidates.map((x) => x.candidateArtifactPin)), "saved_candidate_signed_complete_inventory");
  const unresolved = m.adapterConfig.unresolvedOriginalCandidatePins;
  need6(Array.isArray(unresolved) && samePinSet(unresolved, candidates.flatMap((x) => [x.candidateArtifactPin, x.capsulePin])), "saved_candidate_unresolved_inventory_coverage");
  return { protocol: "bench-verified-saved-candidate-disposition-v1", envelopePin: config.envelopePin, predecessorManifestPin: p.predecessorManifestPin, attemptId: p.attemptId, runId: p.runId, candidateOrSubmissionPresent: true, newAttemptPermitted: true, originalValidPromoted: false, candidateRestored: false };
}
function inspectDispositionHistory(m, c) {
  const candidates = m.adapterConfig.unresolvedOriginalCandidatePins;
  const detected = detectOriginalCandidates(c);
  need6(!(c.attempts ?? []).some((a) => a.candidateCustodyPins?.length) || !!candidates?.length, "original_saved_candidate_custody_requires_disposition_inventory");
  need6(detected.every((p) => candidates?.some((x) => same8(x, p))), "original_saved_candidate_requires_explicit_disposition_inventory");
  if (!candidates?.length) {
    need6(!m.adapterConfig.savedCandidateDisposition, "saved_candidate_inventory_required");
    return inspectOriginalHistory(m, c);
  }
  for (const p of candidates)
    checkPin(p);
  const actual = auditOriginalHistory(m, c), savedCandidateDisposition = verifySavedCandidateDisposition(m, actual);
  need6(actual.rootDispositionApproved, "original_history_root_review_required");
  return { ...actual, candidateOrSubmissionPresent: true, savedCandidateDisposition };
}

// scripts/bench-runner/campaign-stand-adapter.ts
import { readFileSync as readFileSync15, existsSync as existsSync8, readdirSync as readdirSync4 } from "fs";
import { dirname as dirname6, resolve as resolve14, join as join9 } from "path";
import { createHash as createHash7 } from "crypto";
import { pathToFileURL as pathToFileURL4 } from "url";
var digest = (s) => createHash7("sha256").update(s).digest("hex");
function requireTrue(x, message) {
  if (!x)
    throw Error(message);
}
function prepareStandInjection(m, s) {
  requireTrue(s?.protocol === "bench-qualified-stand-injection-v1", "stand_injection_protocol");
  const pins = [s.campaignPin, s.standEntryPin, s.launcherPin, s.pythonPin, s.observedSpawnPin, ...s.dependencyPins, ...s.dependencyManifestPins, ...Object.values(s.pythonModules)];
  for (const pkg of Object.values(s.pythonPackages)) {
    const actual = [];
    const walk = (dir) => {
      for (const e of readdirSync4(dir, { withFileTypes: true })) {
        const p = join9(dir, e.name);
        if (e.isDirectory() && e.name !== "__pycache__")
          walk(p);
        else if (e.isFile() && /\.(py|pyd|dll)$/.test(e.name))
          actual.push(resolve14(p));
      }
    };
    walk(pkg.directory);
    requireTrue(actual.length > 0 && actual.length === pkg.pins.length && actual.every((p) => pkg.pins.some((x) => resolve14(x.path) === p)), "python_package_complete_pin_inventory");
    pins.push(...pkg.pins);
  }
  for (const p of s.dependencyManifestPins) {
    checkPin(p);
    const data = JSON.parse(readFileSync15(p.path, "utf8"));
    requireTrue(Array.isArray(data.sourcePins) && data.sourcePins.length > 0, "qualified_dependency_manifest_empty");
    pins.push(...data.sourcePins);
  }
  for (const p of pins) {
    checkPin(p);
    requireTrue(m.provenance.sourcePins.some((x) => x.path === p.path && x.sha256 === p.sha256 && x.bytes === p.bytes), "stand_dependency_not_manifest_bound:" + p.path);
  }
  const source2 = readFileSync15(s.campaignPin.path, "utf8");
  requireTrue(/^script:join\(import\.meta\.dir,"[^"\r\n]+\.py"\)$/.test(s.expectedExpression), "only_reviewed_stand_expression_permitted");
  requireTrue(source2.split(s.expectedExpression).length === 2, "stand_expression_must_match_exactly_once");
  const launcher = readFileSync15(s.launcherPin.path, "utf8");
  requireTrue(source2.includes(JSON.stringify(s.launcherPin.path.replaceAll("\\", "/"))) && launcher.includes(JSON.stringify(s.pythonPin.path.replaceAll("\\", "/"))), "actual_launcher_python_binding");
  requireTrue(launcher.includes("options.script"), "launcher_script_parameter_missing");
  requireTrue(s.launcherSpawnImport === 'import { spawn } from "node:child_process";' && launcher.split(s.launcherSpawnImport).length === 2, "only_unique_original_spawn_import_permitted");
  const launcherContents = launcher.replace(s.launcherSpawnImport, "import { observedSpawn as spawn } from " + JSON.stringify(s.observedSpawnPin.path.replaceAll("\\", "/")) + ";");
  const localPaths = new Set(Object.values(s.pythonModules).map((p) => resolve14(p.path)));
  requireTrue(localPaths.has(resolve14(s.standEntryPin.path)), "python_entry_not_in_dependency_graph");
  const imports = [];
  for (const p of Object.values(s.pythonModules)) {
    const code = readFileSync15(p.path, "utf8");
    const names = [...code.matchAll(/^\s*from\s+([A-Za-z_][\w.]*)\s+import\s/gm)].map((x) => x[1].split(".")[0]);
    for (const line of code.matchAll(/^\s*import\s+([^\r\n#]+)/gm))
      for (const item of line[1].split(","))
        names.push(item.trim().split(/\s+as\s+/)[0].split(".")[0]);
    for (const name of names) {
      const local = join9(dirname6(p.path), name + ".py");
      if (existsSync8(local))
        requireTrue(resolve14(s.pythonModules[name]?.path ?? "") === resolve14(local), "local_python_import_not_exact:" + name);
      requireTrue(s.pythonModules[name] || s.pythonPackages[name] || s.standardLibraryModules.includes(name), "unbound_python_import:" + name);
      imports.push({ path: p.path, module: name });
    }
  }
  const contents = source2.replace(s.expectedExpression, "script:options.standScriptPath");
  new Bun.Transpiler({ loader: "ts" }).transformSync(contents);
  new Bun.Transpiler({ loader: "ts" }).transformSync(launcherContents);
  return {
    contents,
    launcherContents,
    resolveDir: dirname6(s.campaignPin.path),
    standScriptPath: s.standEntryPin.path,
    proof: {
      protocol: "bench-qualified-stand-injection-proof-v1",
      originalCampaignPin: s.campaignPin,
      standEntryPin: s.standEntryPin,
      launcherPin: s.launcherPin,
      pythonPin: s.pythonPin,
      dependencyPins: pins,
      imports,
      originalSourceSha256: digest(source2),
      injectedSourceSha256: digest(contents),
      launcherSourceSha256: digest(launcher),
      observedLauncherSourceSha256: digest(launcherContents),
      replacement: { from: s.expectedExpression, to: "script:options.standScriptPath", count: 1 },
      launcherReplacement: { from: s.launcherSpawnImport, to: "pinned observedSpawn import", count: 1 },
      originalSourceUnchanged: true
    }
  };
}
async function installStandInjection(s, prepared, custodyDirectory) {
  const exact = resolve14(s.campaignPin.path), launcher = resolve14(s.launcherPin.path);
  checkPin(s.observedSpawnPin);
  const observer = await import(pathToFileURL4(s.observedSpawnPin.path).href);
  observer.configureObservedSpawn(custodyDirectory, prepared.proof.dependencyPins);
  const exactFilter = (path) => new RegExp("^" + path.replaceAll("\\", "/").split("/").map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("[/\\\\]") + "$");
  Bun.plugin({ name: "qualified-stand-injection-" + prepared.proof.injectedSourceSha256, setup(build) {
    build.onLoad({ filter: exactFilter(exact) }, (args) => {
      requireTrue(resolve14(args.path) === exact, "campaign_exact_module_identity");
      checkPin(s.campaignPin);
      return { contents: prepared.contents, loader: "ts", resolveDir: prepared.resolveDir };
    });
    build.onLoad({ filter: exactFilter(launcher) }, (args) => {
      requireTrue(resolve14(args.path) === launcher, "launcher_exact_module_identity");
      checkPin(s.launcherPin);
      return { contents: prepared.launcherContents, loader: "ts", resolveDir: dirname6(s.launcherPin.path) };
    });
  } });
}
// scripts/bench-runner/terminal-driver.ts
import { readFileSync as readFileSync17, existsSync as existsSync10, mkdirSync as mkdirSync5 } from "fs";
import { resolve as resolve15, join as join10, relative as relative4, isAbsolute as isAbsolute5 } from "path";
import { pathToFileURL as pathToFileURL5 } from "url";
import { Database as Database3 } from "bun:sqlite";

// scripts/bench-runner/admission.ts
import { readFileSync as readFileSync16, writeFileSync as writeFileSync3, renameSync as renameSync3, existsSync as existsSync9, openSync as openSync8, closeSync as closeSync8, unlinkSync } from "fs";
function readAdmission(path) {
  demand(existsSync9(path), "admission_control_missing_closed");
  const x = JSON.parse(readFileSync16(path, "utf8"));
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

// scripts/bench-runner/terminal-driver.ts
function demand5(x, message) {
  if (!x)
    throw Error(message);
}
function codePath(m, path) {
  const rel = relative4(resolve15(m.root), resolve15(path));
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
async function importsFor(d) {
  const result = {};
  for (const [name, b] of Object.entries(d.imports)) {
    checkPin(b.pin);
    const module = await import(pathToFileURL5(b.pin.path).href);
    demand5(b.export in module, "pinned_export_missing:" + name);
    result[name] = module[b.export];
  }
  return result;
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
    return inspectDispositionHistory(m, m.adapterConfig.originalHistory);
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
function nativeClosed(output, d) {
  const close = join10(output, d.native.standCloseRelative), ledger = join10(output, d.native.ledgerRelative);
  if (!existsSync10(close) && !existsSync10(ledger))
    return !existsSync10(join10(output, "stand-process"));
  if (!existsSync10(close) || !existsSync10(ledger))
    return false;
  const c = JSON.parse(readFileSync17(close, "utf8"));
  if (c.exitObserved !== true || c.closeObserved !== true)
    return false;
  const db = new Database3(ledger, { readonly: true });
  try {
    return db.query("select count(*) as n from actor where closed<>1").get().n === 0 && db.query("select json from command").all().every((row) => {
      const c2 = JSON.parse(row.json);
      return c2.closeObserved === true && Number.isInteger(c2.exitCode) && !c2.captureFaults?.length;
    });
  } finally {
    db.close();
  }
}
async function preflightTerminalDriver(m, initial) {
  assertContext(m, initial);
  const c = loadPreparedContext(m, initial), d = validateTerminalDriverData(m), entry = JSON.parse(readFileSync17(c.bindings.RECOVERY_ENTRY, "utf8"));
  demand5((m.adapterConfig.originalHistory ? entry.rootReview?.originalHistoryApproved === true && entry.rootReview?.originalHistoryReviewPin?.sha256 === m.adapterConfig.originalHistory.reviewPin?.sha256 : entry.rootReview?.legacyNullIdentityApproved === true) && entry.rootReview?.closureReviewPin?.sha256 === d.closureReviewPin.sha256 && entry.rootReview?.aggregateBudgetPin?.sha256 === d.aggregateBudgetPin.sha256, "root_reviewed_legacy_data_required");
  if (m.adapterConfig.savedCandidateDisposition)
    demand5(entry.rootReview?.savedCandidateDispositionPin?.sha256 === m.adapterConfig.savedCandidateDisposition.envelopePin.sha256 && entry.rootReview?.savedCandidateDispositionPin?.bytes === m.adapterConfig.savedCandidateDisposition.envelopePin.bytes && entry.rootReview?.savedCandidateDispositionPin?.path === m.adapterConfig.savedCandidateDisposition.envelopePin.path, "saved_candidate_successor_root_signature_join");
  inspectStandardLauncherEnvironment(d);
  const history = inspectLegacyHistory(m, d);
  demand5(history.remainingUsd > 0, "original_task_budget_exhausted");
  if (!d.qualifiedInterfaces && (d.standInjection.campaignPin.sha256 !== d.imports.campaign.pin.sha256 || d.standInjection.campaignPin.path !== d.imports.campaign.pin.path))
    throw Error("injected_campaign_must_equal_reviewed_import");
  const prepared = d.qualifiedInterfaces ? prepareQualifiedStand(m, d, entry) : prepareStandInjection(m, d.standInjection);
  if (d.qualifiedInterfaces?.pythonBindings) {
    const earlyBinding = preparePythonModuleBinding(m, d, entry);
    bindLauncherPythonArgs(prepared.launcherContents, earlyBinding.contract);
  }
  const proofPath = join10(c.runDir, "stand-injection-proof.json");
  if (existsSync10(proofPath)) {
    if (JSON.stringify(JSON.parse(readFileSync17(proofPath, "utf8"))) !== JSON.stringify(prepared.proof))
      throw Error("injection_proof_changed");
  } else {
    wxJson(proofPath, prepared.proof);
    wxJson(join10(c.runDir, "stand-injected-sources.json"), { campaign: prepared.contents, launcher: prepared.launcherContents });
  }
  if (d.qualifiedInterfaces?.pythonBindings) {
    const pythonBindingProof = await installQualifiedPythonBindings(m, d, entry, prepared, join10(c.runDir, "native-spawn-custody"));
    const pythonProofPath = join10(c.runDir, "python-module-binding-proof.json");
    if (!existsSync10(pythonProofPath))
      wxJson(pythonProofPath, pythonBindingProof);
  } else if (d.qualifiedInterfaces)
    await installQualifiedStand(d, prepared, join10(c.runDir, "native-spawn-custody"));
  else
    await installStandInjection(d.standInjection, prepared, join10(c.runDir, "native-spawn-custody"));
  const api = await importsFor(d), ready = readPinned(d.readinessPin);
  if (d.qualifiedInterfaces)
    validateQualifiedQualification(m, d, entry);
  else {
    demand5(ready.nativeReady === true && ready.publishAllowed === true && ready.readyTaskIds?.length === 1 && ready.readyTaskIds[0] === m.taskId && ready.actualPrivateImportsValidated === true && ready.allOwnedBuildersClosed === true, "original_qualification_required");
    const original = readPinned(ready.contextManifest), task = original.tasks?.find((x) => x.taskId === m.taskId);
    demand5(task?.agentSeconds === m.original.solveSeconds && task?.verifierSeconds === m.original.gradeSeconds && ready.officialEnvironment?.cpus === m.original.cpu && ready.officialEnvironment?.memory_mb === m.original.memoryMb && ready.officialEnvironment?.storage_mb * 1048576 === d.resource.growthBytes, "original_task_time_cpu_memory_growth_contract");
  }
  demand5(api.provider.model === m.original.model && api.provider.providerSlug === m.original.provider && m.original.reasoning === "high" && m.original.providerSeconds === 600, "original_model_provider_reasoning_timeout");
  const { activation, connection } = await api.activated(d.activationPin.path), output = resolve15(c.bindings[d.outputBinding]);
  await inspectLegacyActorAbsence(d, history.actorCids);
  demand5(!existsSync10(output), "fresh_output_already_exists");
  const projection = readPinned(d.assetProjectionPin);
  for (const asset of m.provenance.sourcePins.filter((p) => !codePath(m, p.path))) {
    checkPin(asset);
    demand5(projection.assets?.some((p) => p.path === asset.path && p.sha256 === asset.sha256 && p.bytes === asset.bytes), "external_asset_projection_missing");
  }
  demand5(codePath(m, d.assetProjectionPin.path), "asset_carrier_must_be_in_code_root");
  const sourcePins = [...m.provenance.sourcePins.filter((p) => codePath(m, p.path)), d.assetProjectionPin, ...m.provenance.contractPins.filter((p) => codePath(m, p.path)), filePin(c.manifestPath)];
  demand5(codePath(m, c.manifestPath), "manifest_carrier_must_be_in_code_root");
  const freshParent = await api.freshHistory(api.historyContract());
  return { m, c, d, entry, history, api, ready, activation, connection, output, sourcePins, freshParent };
}
async function runTerminalDriver(m, initial) {
  const { c, d, history, api, activation, connection, output, sourcePins } = await preflightTerminalDriver(m, initial);
  assertAdmission(c.admissionControlPath, m.bench + ":" + m.taskId, c.stage, true);
  const locks = readPinned(filePin(join10(c.runDir, "locks-receipt.json")));
  checkPin(locks.canonicalPin);
  checkPin(locks.attemptLockPin);
  const lock = readPinned(locks.attemptLockPin);
  demand5(lock.attemptId === c.attemptId && lock.taskId === m.taskId && lock.bench === m.bench && lock.manifestPin.sha256 === c.manifestPin.sha256 && lock.signedEntryPin.sha256 === filePin(c.bindings.ENTRY_ENVELOPE).sha256, "actual_permanent_attempt_lock_join");
  const rootDispatch = applySignedRootDispatch(m, c);
  wxJson(join10(c.runDir, "signed-root-dispatch-proof.json"), rootDispatch);
  const lease = await api.resource(connection, { planPin: d.readinessPin, originalPeakMemoryMb: d.resource.memoryMb, originalPlannedGrowthBytes: d.resource.growthBytes });
  let lane, runId, campaignEntered = false, financialClosed = false;
  try {
    mkdirSync5(output, { recursive: false });
    runId = api.formalRunId(connection.runId);
    process.env.DOCKER_HOST = activation.dockerHost;
    process.env.NOVAEVE_ACTIVATION_PATH = d.activationPin.path;
    process.env.NOVAEVE_BROKER_CONTROL_PATH = activation.brokerControlPath;
    process.env.NOVAEVE_LEASE_PID = String(process.pid);
    if (d.qualifiedInterfaces) {
      applyStandardOwnedEnvironment(m, d, lease);
      const actualOwnedEnvironment = verifyStandardOwnedEnvironment(m, d, lease, rootDispatch);
      wxJson(join10(c.runDir, "actual-owned-launcher-environment.json"), actualOwnedEnvironment);
    }
    const host = api.hostGuard(d.hostCapacityPolicy, output), owned = api.ownedGuard(connection, lease), guard = () => {
      host();
      owned();
    };
    guard();
    await api.freshHistory(api.historyContract());
    lane = await api.acquireAdmission({ ownedResource: { pid: process.pid, token: lease.token }, root: m.root, output, runId, slug: m.bench, sourcePins, connection });
    const fresh = await api.freshHistory(api.historyContract(), lane.proofPin), maximum = Math.min(history.remainingUsd, lane.capUsd, fresh.maximumAdditionalSpendUsd);
    demand5(maximum > 0, "actual_parent_and_original_task_budget_exhausted");
    const processPath = join10(output, "process.json");
    wxJson(processPath, { pid: process.pid, incarnation: processIdentity(process.pid).incarnation, runId, taskId: m.taskId, bench: m.bench, output });
    await lane.registerOwnedProcess(filePin(processPath));
    wxJson(join10(output, "universal-original-budget-binding.json"), { protocol: "bench-real-lane-original-budget-v1", manifestPin: c.manifestPin, aggregateBudgetPin: d.aggregateBudgetPin, actualLanePin: lane.proofPin, originalTaskCapUsd: m.original.taskCapUsd, ...history, maximumNewSpendUsd: maximum, oldRootIdentityWasNull: !m.adapterConfig.originalHistory });
    const freshMaximumNewSpendUsd = async () => {
      guard();
      const h = await api.freshHistory(api.historyContract(), lane.proofPin);
      return Math.min(history.remainingUsd, lane.capUsd, h.maximumAdditionalSpendUsd);
    };
    const qualifiedCallbacks = await qualifiedCampaignCallbacks(m, d, freshMaximumNewSpendUsd);
    campaignEntered = true;
    const result = await api.campaign(api.formalExecuteOptions({
      task: m.taskId,
      runId,
      output,
      sourcePins,
      prices: lane.prices,
      provider: api.provider,
      admission: lane,
      transport: async (raw) => {
        guard();
        return lane.transport(raw);
      },
      ...qualifiedCallbacks,
      freshMaximumNewSpendUsd,
      recoveryParentMaximumNewSpendUsd: maximum,
      standScriptPath: (d.qualifiedInterfaces?.stand ?? d.standInjection).standEntryPin.path,
      recoveryBudgetProofPin: d.aggregateBudgetPin,
      hostCapacityGuard: guard,
      recoveryAgentSeconds: m.original.solveSeconds,
      readinessPath: d.readinessPin.path
    }));
    recordCampaignOutcome(c, result);
    demand5(result.financialClose?.cashClose, "original_cash_close_missing");
    const closed = api.inspectClosedCash(m.root, result.financialClose.cashClose, activation.brokerControlPath);
    demand5(closed.accountingClosed, "original_cash_journal_not_closed");
    await lane.finishLightweight({ cashPin: result.financialClose.cashClose, summaryPin: result.summary });
    financialClosed = true;
  } catch (error) {
    const fault = { message: String(error), campaignEntered, runId: runId ?? null, laneCreated: !!lane, atUtc: new Date().toISOString() };
    wxJson(join10(c.runDir, "driver-failure.json"), fault);
    if (lane && runId)
      try {
        const existingCash = join10(output, "cash/cash-close.json"), existingSummary = join10(output, "summary.json");
        if (existsSync10(existingCash) && existsSync10(existingSummary) && nativeClosed(output, d)) {
          const cashPin = filePin(existingCash), verified = verifyBenchmarkCashClosure(cashPin), journal = inspectCampaignJournal(verified.proof.journalDirectory);
          demand5(verified.config.runId === runId && journal.valid && journal.accountingClosed && verified.proof.snapshot.pendingCount === 0, "original_failure_cash_not_closed");
          await lane.finishLightweight({ cashPin, summaryPin: filePin(existingSummary) });
          financialClosed = true;
        } else if (!campaignEntered && !existsSync10(join10(output, "provider")) && !existsSync10(join10(output, "cash")) && !existsSync10(join10(output, "stand-process"))) {
          const healthResponse = await fetch(connection.endpoint + "/health", { signal: AbortSignal.timeout(5000) }), health = await healthResponse.json();
          const actual = health.lanes?.find((x) => x.runId === runId);
          demand5(healthResponse.ok && health.healthy === true && actual && !actual.closed && actual.dispatched === 0 && actual.active === 0, "pre_native_lane_not_proven_zero");
          const directory = join10(output, "provider"), journal = createCampaignJournal({ directory, campaign: runId, capUsd: lane.capUsd, priorCampaignCostUpperBoundUsd: 0, provider: api.provider });
          const cash = createBenchmarkCash({
            directory: join10(output, "cash"),
            runId,
            providerKind: "real-provider",
            admission: lane,
            prices: lane.prices,
            journal: { directory, configPin: filePin(join10(directory, "journal-config.json")), sourcePin: filePin(resolve15("F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\bench-runner", "../repair-2026-10-10/full-f/shared/digitalocean-journal.ts")) },
            unknownCostPolicy: "record_and_continue"
          }, api.provider);
          journal.exportLegacyLedger();
          const cashClose = cash.close();
          journal.close();
          const inspection = inspectCampaignJournal(directory);
          demand5(inspection.valid && inspection.accountingClosed && inspection.snapshot?.acceptedRequestCount === 0, "actual_zero_journal_not_closed");
          wxJson(existingSummary, { protocol: "bench-pre-native-denial-original-zero-cash-v1", runId, executingTaskIds: [m.taskId], taskPins: [], formalScoreCertified: false, modelCalls: 0, fatal: "pre_native_denial", fault, financialClose: { cashClose }, actorEverCreated: false });
          await lane.finishLightweight({ cashPin: cashClose, summaryPin: filePin(existingSummary) });
          financialClosed = true;
        }
      } catch (closureError) {
        wxJson(join10(c.runDir, "failure-custody-unresolved.json"), { originalFault: fault, closureError: String(closureError), financialClosed: false, resourceReleaseForbidden: true });
      }
    throw error;
  } finally {
    if (nativeClosed(output, d) && (!lane || financialClosed)) {
      await lease.release();
      wxJson(join10(c.runDir, "driver-resource-release.json"), { pid: process.pid, incarnation: processIdentity(process.pid).incarnation, resourceReleased: true, originalPool: true, financialClosed: lane ? financialClosed : null });
    } else
      wxJson(join10(c.runDir, "native-custody-held.json"), { pid: process.pid, resourceReleaseForbidden: true, reason: "original_native_closure_unproven" });
  }
}
if (import.meta.main) {
  if (!["--run", "--preflight"].includes(process.argv[2]) || !process.argv[3] || !process.argv[4])
    throw Error("explicit_root_authorized_run_or_preflight_manifest_context_required");
  const m = loadManifest(process.argv[3]), c = JSON.parse(readFileSync17(process.argv[4], "utf8"));
  if (process.argv[2] === "--preflight") {
    const p = await preflightTerminalDriver(m, c);
    console.log(JSON.stringify({ verified: true, taskId: m.taskId, bench: m.bench, originalCalls: p.history.calls, priorKnownUsd: p.history.knownUsd, priorUnknownUsd: p.history.unknownUsd, remainingTaskCapUsd: p.history.remainingUsd, oldActorsCurrently404: p.history.actorCids.length, resourceAcquisitions: 0, laneClaims: 0, modelCalls: 0, newGrades: 0, newOracles: 0 }));
  } else
    await runTerminalDriver(m, c);
}
export {
  validateTerminalDriverData,
  runTerminalDriver,
  prepareStandInjection,
  preflightTerminalDriver,
  installStandInjection,
  inspectLegacyHistory,
  inspectLegacyActorAbsence
};
