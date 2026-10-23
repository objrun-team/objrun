/** Independent, fixed-run financial owner release. Never edits the original registry or certifies scores. */
import { spawn } from 'node:child_process';
import { createReadStream, closeSync, existsSync, fstatSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, readSync, realpathSync, statSync, unlinkSync, writeSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { createGunzip } from 'node:zlib';
import { actualPin, demand, gzipProof, hash, inside, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { assertOriginalAdmissionSources } from './audit-scientific-financial-interruption.ts';

export const FINANCIAL_RUN = 'repair-2026-10-08T18-32-57-118Z';
const ROOT = resolve(import.meta.dir, '../..');
const META = join(ROOT, 'docs/repair-2026-10-08/campaigns', FINANCIAL_RUN);
const STORE = resolve('D:/objrun-experiment-stores/01a119ed-fdf7-7c32-b323-de9bab1290b6/scientific-journal-v2-' + FINANCIAL_RUN);
const SELF = actualPin(import.meta.path);
const REPORT: Pin = { path: join(ROOT, 'docs/repair-2026-10-08/scientific-financial-interruptions', FINANCIAL_RUN + '-audit-v2/audit.json'), bytes: 10661, sha256: '4722f1e9d25ed2f2ed061cf6d37fa89d4c5816625f15809b8309cccfdbcbc4d4' };
const INDEX: Pin = { path: join(dirname(REPORT.path), 'request-evidence.jsonl.gz'), bytes: 6693036, sha256: 'cc1b832b6f59001de8bf3ba4a2d31e7a0dcdeb704f276e1f55bfb4ec9c4f956e' };
const AUDITOR: Pin = { path: join(import.meta.dir, 'audit-scientific-financial-interruption.ts'), bytes: 24818, sha256: '58686eaecd47e1f86c89eef544ad72966afc2abf420b5fccca2706fb9c35d244' };
const FIRST: Pin = { path: join(ROOT, 'docs/repair-2026-10-08/scientific-interruption-' + FINANCIAL_RUN, 'first-pass.json'), bytes: 35517, sha256: '204cc6a0bfa793934b4abdfd78534a57ee606295feffe24a6878c76732652758' };
const LOCK: Pin = { path: join(ROOT, '.phase1-data/owned-paid-campaign.lock.json'), bytes: 432, sha256: '31fa74df0ee0d7c32d1832a4eec3fc2f89e61efe3c4cf54ebe862dd0d488dd53' };
const REGISTRY: Pin = { path: join(META, 'paid-resource-v2-run.json'), bytes: 393, sha256: 'b635eef60fd169d6133c39f5bcfd4f0f50d3d46b00d26723f7f08e6ce8c47d8a' };
const PROOF: Pin = { path: join(import.meta.dir, 'paid-resource-proof-v2.ts'), bytes: 10106, sha256: 'b1bacd465d2a76ca166e8048ac8ee83f152f6b9f21600770b39ec6a9864813fe' };
const SNAPSHOT_SOURCE: Pin = { path: join(import.meta.dir, 'science-worker-db-snapshot-v1.py'), bytes: 20986, sha256: '3d3c408fa18cc76569f841bf3af68366fb68d4adcb167781a7b030dd65573d32' };
const SNAPSHOT_REVIEW: Pin = { path: join(ROOT, 'docs/repair-2026-10-08/science-db-snapshot-native-controls-v1/review.json'), sha256: 'c382728966b8ecae1c2e934dd22404ee40483948e9d6c10f24125003870a574e' };
const SNAPSHOT_RECEIPT: Pin = { path: join(ROOT, 'docs/repair-2026-10-08/science-db-snapshots/root-snapshot-2026-10-09T04-10-v1.json'), bytes: 43523, sha256: '8134c6e96ef8718615da901548f2c0c6ada7076ee15543c4723c555ba2a36220' };
const BUN: Pin = { path: 'C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe', bytes: 114769496, sha256: 'f3b8ec8560eafce3bb0a458ab402c663bd5256ecc5419804df7d5c36b4de98f5' };
const OWNER = { pid: 104376, startedAt: '2026-10-08T18:35:52.317Z', runId: FINANCIAL_RUN, entry: join(import.meta.dir, 'scientific-journal-campaign.ts'), ownerNonce: 'a324165d98aa2edcca6aee98d1ef2099ba6defaac020e4c4', mode: 'carry-science-oom-2026-10-08-v2', policyFaultSha256: 'b56760e02fc14725c7fede86457f6155cb3aa4fdeefa9001b2248282a1cb0357' };
const PID_SET = [104376, 111992, 13948, 102088, 27504];
const WORKER_PORTS = [59388, 59989, 59990, 59991];
const OUTPUT_ROOT = join(ROOT, 'docs/repair-2026-10-08/scientific-financial-releases');
const FIXTURE_ROOT = join(ROOT, '.scratch/financial-release-controls');
const PS = 'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe';
const RELEASE_PROTOCOL = 'financial-interruption-release-v1';
type Actors = Readonly<{ pids: readonly number[]; ports: readonly number[] }>;
type Scope = { home: string; actors: Actors; lockPin: Pin; registryPin: Pin; owner: any; fixture: boolean; financialPin: Pin; identityPin: Pin; validate(): Promise<any>; stable(): void };
type FixtureFault = 'none' | 'nonce-after-probe' | 'ack-path-blocked';
type ProbeMode = 'ordinary' | 'invalid-json' | 'timeout';

function ordinary(path: string, owner: string, directory = false) {
  const p = resolve(path), base = resolve(owner); demand(inside(base, p), 'release_path_outside_owned_root');
  let at = p; while (true) { const st = lstatSync(at); demand(!st.isSymbolicLink() && realpathSync(at).toLowerCase() === at.toLowerCase(), 'release_reparse_path'); if (at === base) break; at = dirname(at); }
  demand(directory ? lstatSync(p).isDirectory() : lstatSync(p).isFile(), 'release_not_ordinary'); return p;
}
function makeHome(parent: string, home: string) {
  const base = resolve(parent), path = resolve(home); demand(path !== base && dirname(path) === base && !existsSync(path), 'fresh_release_home_required');
  if (!existsSync(base)) { ordinary(dirname(base), ROOT, true); mkdirSync(base); }
  ordinary(base, ROOT, true); mkdirSync(path); ordinary(path, base, true); return path;
}
function durable(path: string, value: unknown, owner: string): Pin {
  ordinary(dirname(path), owner, true); const raw = value instanceof Uint8Array ? Buffer.from(value) : Buffer.from(typeof value === 'string' ? value : JSON.stringify(value, null, 2) + '\n'); demand(raw.length <= 512 * 1024, 'release_output_bound');
  const fd = openSync(path, 'wx', 0o600); try { let at = 0; while (at < raw.length) { const n = writeSync(fd, raw, at, raw.length - at, at); demand(n > 0, 'release_short_write'); at += n; } fsyncSync(fd); } finally { closeSync(fd); }
  demand(readFileSync(path).equals(raw), 'release_durable_readback'); return actualPin(path);
}
function expectedOwner(pin: Pin, owner: any) {
  ordinary(pin.path, ROOT); verifyPin(pin); demand(same(jsonPin(pin), owner), 'release_owner_changed');
}
function validateActors(actors: Actors) {
  demand(actors.pids.length === 5 && actors.ports.length === 5 && new Set(actors.pids).size === 5 && new Set(actors.ports).size === 5 && actors.pids.every(n => Number.isSafeInteger(n) && n > 0) && actors.ports.every(n => Number.isSafeInteger(n) && n > 0 && n <= 65535), 'exact_five_actor_identity_required');
}
function psCommand(actors: Actors) {
  validateActors(actors);
  return `$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $rows=@(); foreach($idValue in @(${actors.pids.join(',')})){ try { $p=[System.Diagnostics.Process]::GetProcessById([int]$idValue); $rows+=@{pid=[int]$idValue;state='present';name=$p.ProcessName;startTimeUtc=$p.StartTime.ToUniversalTime().ToString('o')} } catch [System.ArgumentException] { $rows+=@{pid=[int]$idValue;state='absent';name=$null;startTimeUtc=$null} } catch { $rows+=@{pid=[int]$idValue;state='unknown';error=$_.Exception.GetType().FullName} } }; $native=@([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()); $ports=@(); foreach($portValue in @(${actors.ports.join(',')})){ $hits=@($native|Where-Object {$_.Port -eq $portValue}); $ports+=@{port=[int]$portValue;nativeListening=($hits.Count -gt 0);listeners=@($hits|ForEach-Object {@{address=[string]$_.Address;port=[int]$_.Port}})} }; @{protocol='financial-owner-native-query-v1';queryHostPid=$PID;portQuery='IPGlobalProperties.GetActiveTcpListeners';processes=@($rows);ports=@($ports)}|ConvertTo-Json -Depth 7 -Compress;`;
}

/** Native query child is the only process this module can terminate. Target actors are never killed. */
async function nativeProbe(actors: Actors, home: string, fixture: boolean, mode: ProbeMode = 'ordinary') {
  demand(fixture || mode === 'ordinary', 'production_probe_override_forbidden'); validateActors(actors);
  const probe = join(home, 'actor-probe-' + crypto.randomUUID()); mkdirSync(probe); ordinary(probe, home, true);
  const command = mode === 'invalid-json' ? "[Console]::Out.Write('not-json')" : mode === 'timeout' ? "Start-Sleep -Seconds 30" : psCommand(actors);
  const requestPin = durable(join(probe, 'request.json'), { protocol: 'financial-owner-native-request-v1', actors, command, timeoutMs: 10000, hostPid: process.pid, hostBun: actualPin(process.execPath), queryExecutablePin: actualPin(PS), sourcePin: SELF, fixture }, home);
  const startWall = Date.now(), startMono = process.hrtime.bigint(), deadline = startMono + 10000000000n;
  let stdout = Buffer.alloc(0), stderr = Buffer.alloc(0), outputOverflow = false, timeout = false, exitObserved = false, closeObserved = false, killAttempted = false, killReturned: boolean | null = null, status: number | null = null, signal: NodeJS.Signals | null = null, error: string | null = null;
  const env = { ...process.env, PSModulePath: 'C:/Windows/System32/WindowsPowerShell/v1.0/Modules' };
  const child = spawn(PS, ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command], { cwd: ROOT, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let timer: ReturnType<typeof setTimeout> | undefined, grace: ReturnType<typeof setTimeout> | undefined;
  const result = await new Promise<void>(resolveDone => {
    let resolved = false; const done = () => { if (resolved) return; resolved = true; if (timer) clearTimeout(timer); if (grace) clearTimeout(grace); resolveDone(); };
    const terminate = () => { if (!killAttempted && Number.isSafeInteger(child.pid) && child.pid! > 0 && !exitObserved) { killAttempted = true; try { killReturned = child.kill('SIGTERM'); } catch (e) { error = String(e); } } grace ??= setTimeout(done, 5000); };
    const capture = (chunk: Buffer, which: 'stdout' | 'stderr') => { const old = which === 'stdout' ? stdout : stderr; if (old.length + chunk.length > 65536) { outputOverflow = true; terminate(); } const next = Buffer.concat([old, chunk.subarray(0, Math.max(0, 65536 - old.length))]); if (which === 'stdout') stdout = next; else stderr = next; };
    child.stdout?.on('data', chunk => capture(Buffer.from(chunk), 'stdout')); child.stderr?.on('data', chunk => capture(Buffer.from(chunk), 'stderr'));
    child.once('error', e => { error = String(e); }); child.once('exit', (code, sig) => { exitObserved = true; status = code; signal = sig; });
    child.once('close', (code, sig) => { closeObserved = true; status = code; signal = sig; done(); });
    const tick = () => { const remaining = deadline - process.hrtime.bigint(); if (remaining <= 0n) { timeout = true; terminate(); } else timer = setTimeout(tick, Math.max(1, Math.ceil(Number(remaining) / 1000000))); }; tick();
  });
  void result;
  const stdoutPin = durable(join(probe, 'stdout.txt'), stdout, home), stderrPin = durable(join(probe, 'stderr.txt'), stderr, home);
  let parsed: any = null, parseError: string | null = null; try { parsed = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(stdout)); } catch (e) { parseError = String(e); }
  const observation = { protocol: 'financial-owner-native-observation-v1', requestPin, sourcePin: SELF, hostPid: process.pid, childPid: child.pid ?? null, startedAtUtc: new Date(startWall).toISOString(), completedAtUtc: new Date().toISOString(), elapsedMonotonicNs: (process.hrtime.bigint() - startMono).toString(), timeoutMs: 10000, timeout, exitObserved, closeObserved, status, signal, error, outputOverflow, killAttempted, killReturned, stdoutPin, stderrPin, parsed, parseError, fixture };
  const pin = durable(join(probe, 'result.json'), observation, home); return { pin, observation };
}
export function assertNativeOwnerClosure(observation: any, actors: Actors) {
  validateActors(actors); demand(observation?.protocol === 'financial-owner-native-observation-v1' && observation.timeoutMs === 10000 && observation.timeout === false && observation.exitObserved === true && observation.closeObserved === true && observation.status === 0 && observation.signal === null && observation.error === null && observation.outputOverflow === false && observation.parseError === null, 'native_actor_query_unknown');
  const data = observation.parsed; demand(data?.protocol === 'financial-owner-native-query-v1' && data.queryHostPid === observation.childPid && Array.isArray(data.processes) && Array.isArray(data.ports), 'native_actor_query_structure');
  demand(data.portQuery === 'IPGlobalProperties.GetActiveTcpListeners' && BigInt(observation.elapsedMonotonicNs) <= 10000000000n, 'native_actor_query_unknown');
  demand(same(data.processes.map((p: any) => p.pid), actors.pids) && data.processes.every((p: any) => p.state === 'absent' && p.name === null && p.startTimeUtc === null), 'original_actor_present_reused_or_unknown');
  demand(same(data.ports.map((p: any) => p.port), actors.ports) && data.ports.every((p: any) => p.nativeListening === false && Array.isArray(p.listeners) && p.listeners.length === 0), 'original_port_present_reused_or_unknown');
}
function verifyActorEvidence(pin: Pin, actors: Actors, home: string, fixture: boolean) {
  ordinary(pin.path, home); const record = jsonPin(pin); assertNativeOwnerClosure(record, actors);
  demand(record.fixture === fixture && same(record.sourcePin, SELF), 'actor_evidence_source_or_family');
  for (const p of [record.requestPin, record.stdoutPin, record.stderrPin]) { ordinary(p.path, home); verifyPin(p); }
  const request = jsonPin(record.requestPin); demand(request.protocol === 'financial-owner-native-request-v1' && request.fixture === fixture && same(request.sourcePin, SELF) && request.timeoutMs === 10000 && request.command === psCommand(actors) && same(request.actors, actors) && request.hostPid === record.hostPid, 'actor_request_not_exact_native_query');
  demand(resolve(request.queryExecutablePin?.path ?? '') === resolve(PS), 'actor_query_executable_identity'); verifyPin(request.queryExecutablePin); verifyPin(request.hostBun);
  const raw = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(readFileSync(record.stdoutPin.path))); demand(same(raw, record.parsed), 'actor_stdout_parsed_mismatch');
  return record;
}

export function assertFixedFinancialReport(report: any) {
  demand(report?.protocol === 'financial-interruption-v1' && report.runId === FINANCIAL_RUN && report.validated === true && report.financialOnly === true && report.fixtureIntegrityValid === false && report.scoreCertificate === false && report.plannedScoreCompletion === false && report.ownerClosureCertified === false && report.releasePermitted === false, 'fixed_financial_proof_profile');
  demand(report.requests === 23504 && report.actualForwarded === 23503 && report.deniedBeforeForward === 1 && report.rawRequestAndResponseFilesDoubleVerified === 47010 && report.verifiedFallbackCopies === 3 && report.fallbackCopiesChargedAgain === false, 'fixed_financial_request_set');
  demand(report.knownEstimatedNanoCny === '247731051080' && report.knownEstimatedCny === '247.731051080' && report.newUnknownCount === 0 && report.newPendingCount === 0 && report.originalUnknownCarryNanoCny === '8392180000' && report.oldUnknownSettled === false && report.remainingEnvelopeNanoCny === '2268948920', 'financial_unknown_or_amount_changed');
  demand(report.sourceFileCount === 81 && report.currentDependencyFilesVerified === 4100 && same(report.originalAdmissionSourceShape, { intrinsicCount: 3, executedCount: 81, totalCount: 84, exactMultiset: true }) && report.plannedTaskRuns === 1220 && report.recordedTaskRuns === 789 && report.originalClosingArtifactsFabricated === false && report.originalSqliteOpened === false && report.originalRecordsModified === false && report.providerRequestsByAudit === 0 && report.paidLockOperations === 0, 'financial_original_contract_changed');
  demand(same(report.auditSourcePin, AUDITOR) && same(report.compressedRequestEvidence.pin, INDEX) && report.compressedRequestEvidence.rows === 23504 && report.compressedRequestEvidence.lastRowSha256 === '5c270ffe85caa3a8bf31f648aceb160ab14ca699c9398e331ed05b64688498c0' && report.compressedRequestEvidence.concatenatedGzipMembers === true && Array.isArray(report.metadataInputPins) && report.metadataInputPins.length === 11 && Array.isArray(report.inputPins) && report.inputPins.length === 14, 'financial_proof_inputs_changed');
}
async function verifyCompressedEvidence(report: any) {
  verifyPin(INDEX); let carry = Buffer.alloc(0), bytes = 0, rows = 0, chain = AUDITOR.sha256, files = 0, copies = 0, known = 0n, usd = 0;
  const sequences = new Set<number>(); const stream = createReadStream(INDEX.path).pipe(createGunzip());
  for await (const chunk of stream) {
    bytes += chunk.length; demand(bytes <= 96 * 1024 ** 2, 'financial_index_expansion_bound'); carry = Buffer.concat([carry, Buffer.from(chunk)]); let nl: number;
    while ((nl = carry.indexOf(10)) >= 0) {
      const line = carry.subarray(0, nl + 1); demand(line.length <= 65536, 'financial_index_line_bound'); const row = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(line.subarray(0, -1)));
      demand(Buffer.from(JSON.stringify(row) + '\n').equals(line) && row.previousRowSha256 === chain && Number.isSafeInteger(row.requestSeq) && row.requestSeq >= 0 && row.requestSeq < 23504 && !sequences.has(row.requestSeq), 'financial_index_chain_duplicate');
      sequences.add(row.requestSeq); chain = hash(line); rows++;
      const readWire = (descriptor: any, path: string, max: number) => { demand(descriptor && Number.isSafeInteger(descriptor.bytes) && descriptor.bytes > 0 && /^[a-f0-9]{64}$/.test(descriptor.sha256) && /^[a-f0-9]{64}$/.test(descriptor.rawSha256), 'financial_index_wire_pin'); ordinary(path, STORE); const raw = gzipProof({ path, bytes: descriptor.bytes, sha256: descriptor.sha256 }, descriptor.rawSha256, undefined, max); files++; return raw; };
      readWire(row.request, join(STORE, `provider-${row.requestSeq}-request.json.gz`), 4 * 1024 ** 2);
      demand(typeof row.knownEstimatedNanoCny === 'string' && /^\d+$/.test(row.knownEstimatedNanoCny) && Number.isFinite(row.usdUpperBound) && row.usdUpperBound >= 0 && Array.isArray(row.fallbackCopies), 'financial_index_cost');
      known += BigInt(row.knownEstimatedNanoCny); usd += row.usdUpperBound;
      if (row.requestSeq === 23503) demand(row.providerAttempted === false && row.response === null && row.usage === null && row.servedModel === null && row.knownEstimatedNanoCny === '0' && row.usdUpperBound === 0 && row.fallbackCopies.length === 0, 'fixed_denial_zero_not_proven');
      else {
        demand(row.providerAttempted === true && row.response && row.servedModel === 'deepseek-flash' && row.usage, 'financial_forwarded_unknown'); const raw = readWire(row.response, join(STORE, `provider-${row.requestSeq}-response.json.gz`), 64 * 1024 ** 2), data = JSON.parse(raw.toString('utf8')); demand(data.model === row.servedModel && same(data.usage, row.usage), 'financial_index_usage_model_changed');
        for (const copy of row.fallbackCopies) {
          const expectedSeq: Record<number, number> = { 1: 23500, 2: 23502, 3: 23482 }; demand(expectedSeq[copy.receiptIndex] === row.requestSeq && resolve(copy.pin?.path ?? '') === join(STORE, 'journal-failures', `failure-${copy.receiptIndex}-response.json.gz`) && copy.rawSha256 === row.response.rawSha256, 'financial_index_copy_identity');
          ordinary(copy.pin.path, STORE); const copyRaw = gzipProof(copy.pin, copy.rawSha256); demand(copyRaw.equals(raw), 'financial_copy_not_same_response'); copies++; files++;
        }
      }
      carry = carry.subarray(nl + 1);
    }
    demand(carry.length <= 65536, 'financial_index_line_bound');
  }
  demand(carry.length === 0 && rows === 23504 && sequences.size === rows && chain === report.compressedRequestEvidence.lastRowSha256 && files === 47010 && copies === 3 && known.toString() === report.knownEstimatedNanoCny && Math.abs(usd - report.recordedUsageUpperBoundUsd) < 1e-9, 'financial_index_not_complete');
  verifyPin(INDEX); return { rows, files, copies, lastRowSha256: chain, knownEstimatedNanoCny: known.toString(), indexPin: INDEX };
}
function originalContract() {
  verifyPin(SELF); verifyPin(PROOF); verifyPin(AUDITOR); verifyPin(REPORT); verifyPin(FIRST); const report = jsonPin(REPORT); assertFixedFinancialReport(report);
  for (const pin of [...report.metadataInputPins, ...report.inputPins, ...report.observations, report.archivePin]) verifyPin(pin);
  expectedOwner(LOCK, OWNER); verifyPin(REGISTRY); const registry = jsonPin(REGISTRY), admission = jsonPin({ path: join(META, 'paid-resource-admission.json'), bytes: 24186, sha256: 'b6cc55dc4845195056d2227c55935c07fe319e59291e8df40e01b1ddf9d5a878' });
  demand(registry.protocol === 'paid-resource-v2-run' && registry.runId === FINANCIAL_RUN && registry.closedPin === null && registry.released === undefined && same(registry.admissionPin, report.metadataInputPins.find((p: Pin) => resolve(p.path) === join(META, 'paid-resource-admission.json'))) && same(admission.owned, OWNER) && admission.carryNanoCny === '8392180000', 'original_registry_or_admission_changed');
  const first = jsonPin(FIRST); demand(same(first.lock.pin, LOCK) && same(first.lock.record, OWNER) && same(first.registry.pin, REGISTRY), 'original_owner_observation_changed');
  const source = jsonPin(actualPin(join(META, 'source.json'))), manifest = jsonPin(actualPin(join(META, 'manifest.json'))), frozen = jsonPin(actualPin(join(META, 'frozen-source.json'))), sources = [...source.files, ...source.repairFiles].map((p: any) => ({ path: resolve(ROOT, p.path), bytes: p.bytes, sha256: p.sha256 }));
  demand(manifest.campaign === FINANCIAL_RUN && manifest.profile === 'full' && manifest.taskSchedule.length === 1220 && hash(JSON.stringify(manifest.taskSchedule)) === '1ae6590140a51e9c48c656e92e482dd684843f8ae0e1dfc4e8f8ebad0e738bf8' && frozen.campaign === FINANCIAL_RUN && frozen.sourceFiles === 81 && frozen.dependencyFiles.length === 4100, 'fixed_science_scope_changed');
  const recipePin = manifest.paidResourceAdmission.recipePin, recipe = jsonPin(recipePin); assertOriginalAdmissionSources(admission.sourcePins, sources, recipe.executedSourcePins);
  verifyStorageIdentity();
  for (const name of ['summary.json', 'api-ledger.json', 'journal-export.json', 'paid-resource-closure.json', 'final-certificate.json', 'paid-resource-final-certificate.json']) demand(!existsSync(join(META, name)), 'original_closing_state_changed');
  demand(!existsSync(join(STORE, 'currency/cash-close.json')), 'original_cash_close_appeared');
  for (const pin of [...admission.sourcePins, ...sources]) verifyPin(pin); for (const p of frozen.dependencyFiles) verifyPin({ ...p, path: resolve(ROOT, p.path) });
  verifyPin(recipePin); verifyPin(BUN); demand(resolve(process.execPath) === resolve(BUN.path), 'fixed_native_bun_required');
  return { report, sources, dependencies: frozen.dependencyFiles, registry };
}
function verifyStorageIdentity() {
  const layout = jsonPin(actualPin(join(META, 'storage-layout.json')));
  demand(layout.protocol === 'scientific-journal-store-v2' && layout.runId === FINANCIAL_RUN && layout.reuse === 'never' && layout.mode === 'owned-d-new-store' && layout.ownerPid === 104376 && layout.paidLockSha256 === LOCK.sha256 && resolve(layout.physicalStore) === STORE && resolve(layout.logicalStore) === join(ROOT, '.phase1-data/repair', FINANCIAL_RUN) && realpathSync(layout.logicalStore) === STORE && realpathSync(STORE) === STORE, 'original_storage_identity_changed');
  demand(resolve(layout.physicalOwnerReceiptPin.path) === join(STORE, 'storage-owner.json') && layout.physicalOwnerReceiptPin.bytes === 1904 && layout.physicalOwnerReceiptPin.sha256 === '34f6bce8cae2e65853da826c52a52e7974f0d9742b6832616e9b950aa9c63651' && resolve(layout.storageLeasePin.path) === join(ROOT, '.phase1-data/owned-scientific-storage-' + FINANCIAL_RUN + '.lock.json') && layout.storageLeasePin.bytes === 551 && layout.storageLeasePin.sha256 === '327fc9d43b2e61110526d52f87b46f6d93495cdae9388199f85f0d7d2b04c621', 'original_storage_owner_or_lease_pin');
  ordinary(layout.physicalOwnerReceiptPin.path, STORE); verifyPin(layout.physicalOwnerReceiptPin); ordinary(layout.storageLeasePin.path, ROOT); verifyPin(layout.storageLeasePin);
}

const triple = (p: any): Pin => ({ path: resolve(p.path), bytes: p.bytes, sha256: p.sha256 });
/** Pure shape control; production also verifies every real Pin and native file path below. */
export function assertProxySnapshotEnvelope(evidence: any, receipt: any, raw: any) {
  const parent = dirname(STORE), root = resolve(evidence.snapshotRoot ?? '');
  demand(dirname(root) === parent && new RegExp('^scientific-db-snapshot-' + FINANCIAL_RUN + '-[a-f0-9]{32}$').test(basename(root)), 'proxy_snapshot_exact_owned_sibling');
  demand(receipt.protocol === 'science-worker-db-snapshot-v1' && receipt.runId === FINANCIAL_RUN && receipt.fixtureOnly === false && receipt.validated === true && receipt.snapshotComplete === true && receipt.sourceHandlesClosed === true && receipt.originalSqliteOpened === false && receipt.originalBytesUnchanged === true && receipt.sourceDenyWriteAndDelete === true && receipt.sourceShareReadOnly === true && receipt.originalNeverRenamedOrDeleted === true && receipt.allSourceHandlesAcquiredBeforeAnyCopy === true && resolve(receipt.sourceStore) === STORE && resolve(receipt.target) === root && receipt.mode === 'snapshot', 'proxy_snapshot_not_closed_real_copy');
  demand(same(receipt.sourcePin, SNAPSHOT_SOURCE) && receipt.reviewPin?.sha256 === SNAPSHOT_REVIEW.sha256 && resolve(receipt.reviewPin.path) === resolve(SNAPSHOT_REVIEW.path) && Array.isArray(receipt.sourceBefore) && receipt.sourceBefore.length === 12 && same(receipt.sourceBefore, receipt.sourceAfter) && Array.isArray(receipt.rawCopies) && receipt.rawCopies.length === 12 && Array.isArray(receipt.workingCopies) && receipt.workingCopies.length === 12, 'proxy_snapshot_source_or_inventory');
  const source = new Map(receipt.sourceBefore.map((p: any) => [resolve(p.path), p])); demand(source.size === 12, 'proxy_snapshot_duplicate_source');
  const pins: Pin[] = [];
  for (let worker = 0; worker < 4; worker++) for (const name of ['h2h.sqlite', 'h2h.sqlite-wal', 'h2h.sqlite-shm']) {
    const original = join(STORE, `worker-${worker}/data`, name), src: any = source.get(original), path = join(root, `raw/worker-${worker}/data`, name), rows = receipt.rawCopies.filter((p: any) => resolve(p.path) === path);
    demand(src && rows.length === 1 && rows[0].bytes === src.bytes && rows[0].sha256 === src.sha256 && rows[0].FlushFileBuffersReturned === true && rows[0].createNew === true, 'proxy_snapshot_raw_identity'); pins.push(triple(rows[0]));
  }
  const sort = (p: Pin[]) => p.map(x => JSON.stringify(triple(x))).sort();
  demand(Array.isArray(evidence.snapshotPins) && evidence.snapshotPins.length === 12 && Array.isArray(raw.snapshotPins) && raw.snapshotPins.length === 12 && same(sort(evidence.snapshotPins), sort(pins)) && same(sort(raw.snapshotPins), sort(pins)) && raw.immutable === true && raw.walRead === false && same(raw.snapshotReceiptPin, evidence.snapshotReceiptPin) && resolve(raw.snapshotRoot) === root && Array.isArray(raw.rows) && raw.rows.length === 4 && same(raw.rows.map((r: any) => r.worker).sort(), [0, 1, 2, 3]), 'proxy_raw_query_source_set');
  for (const row of raw.rows) {
    const expected = pins.find(p => resolve(p.path) === join(root, `raw/worker-${row.worker}/data/h2h.sqlite`)); demand(expected && same(triple(row.rawDatabasePin), expected), 'proxy_query_not_immutable_raw_main');
  }
  return { snapshotRoot: root, originalPins: [...source.values()].map(triple), rawPins: pins };
}
/** Fifth-port extraction is separately root-reviewed. Its raw query and all snapshot/source Pins must match. */
function proxyIdentity(pin: Pin) {
  verifyPin(pin); ordinary(pin.path, ROOT); const evidence = jsonPin(pin);
  demand(evidence.protocol === 'financial-interruption-proxy-port-identity-v1' && evidence.runId === FINANCIAL_RUN && same(evidence.financialAuditPin, REPORT) && same(evidence.originalLockPin, LOCK) && evidence.hostPid === 104376 && evidence.originalSqliteOpened === false && evidence.modelCalls === 0 && evidence.snapshotOnly === true, 'proxy_port_identity_profile');
  demand(Number.isSafeInteger(evidence.proxyPort) && evidence.proxyPort > 0 && evidence.proxyPort <= 65535 && !WORKER_PORTS.includes(evidence.proxyPort) && evidence.extractorSourcePin && evidence.rawQueryPin && evidence.snapshotReceiptPin, 'proxy_port_provenance_missing');
  demand(same(evidence.snapshotReceiptPin, SNAPSHOT_RECEIPT), 'fixed_actual_snapshot_pin_required');
  for (const p of [evidence.extractorSourcePin, evidence.rawQueryPin, evidence.snapshotReceiptPin, SNAPSHOT_SOURCE, SNAPSHOT_REVIEW]) { ordinary(p.path, ROOT); verifyPin(p); }
  demand(inside(join(ROOT, 'docs/repair-2026-10-08/science-db-snapshots'), evidence.snapshotReceiptPin.path), 'proxy_snapshot_receipt_scope');
  const raw = jsonPin(evidence.rawQueryPin); demand(raw.protocol === 'financial-interruption-readonly-proxy-query-v1' && raw.runId === FINANCIAL_RUN && raw.query === 'SELECT base_url FROM api WHERE model=?' && raw.model === 'deepseek-flash' && same(raw.extractorSourcePin, evidence.extractorSourcePin) && raw.originalSqliteOpened === false, 'proxy_port_raw_query_binding');
  const envelope = assertProxySnapshotEnvelope(evidence, jsonPin(evidence.snapshotReceiptPin), raw);
  for (const p of envelope.originalPins) { ordinary(p.path, STORE); verifyPin(p, undefined, 512 * 1024 ** 2); } for (const p of envelope.rawPins) { ordinary(p.path, envelope.snapshotRoot); verifyPin(p, undefined, 512 * 1024 ** 2); }
  const manifest = jsonPin(actualPin(join(META, 'manifest.json'))), routes = new Set(manifest.taskSchedule.map((t: any) => `/${FINANCIAL_RUN}/${t.benchmark}/${t.arm}/${t.replica}/${t.officialId}/v1`));
  const ports = new Set(raw.rows.map((row: any) => { demand(typeof row.base_url === 'string', 'proxy_port_row'); const url = new URL(row.base_url); demand(url.protocol === 'http:' && url.hostname === '127.0.0.1' && !url.username && !url.password && routes.has(url.pathname) && !url.search && !url.hash && /^\d+$/.test(url.port), 'proxy_port_url_profile'); return Number(url.port); }));
  demand(ports.size === 1 && ports.has(evidence.proxyPort), 'proxy_port_snapshot_disagreement'); return evidence.proxyPort as number;
}
async function productionScope(home: string, identityPin: Pin): Promise<Scope> {
  const actors = { pids: PID_SET, ports: [...WORKER_PORTS, proxyIdentity(identityPin)] }; validateActors(actors);
  return { home, actors, lockPin: LOCK, registryPin: REGISTRY, owner: OWNER, fixture: false, financialPin: REPORT, identityPin,
    async validate() { const state = originalContract(); for (let i = 0; i < 4; i++) { const p = jsonPin(actualPin(join(META, `paid-process-${i}.json`))); demand(p.protocol === 'paid-owned-process-v2' && p.runId === FINANCIAL_RUN && p.ownerNonce === OWNER.ownerNonce && p.worker === i && p.pid === PID_SET[i + 1] && p.base === `http://127.0.0.1:${WORKER_PORTS[i]}/api`, 'worker_identity_changed'); } const raw = await verifyCompressedEvidence(state.report); originalContract(); demand(proxyIdentity(identityPin) === actors.ports[4], 'proxy_identity_changed'); return raw; },
    stable() { verifyPin(SELF); verifyPin(PROOF); verifyPin(AUDITOR); verifyPin(REPORT); verifyPin(INDEX); demand(proxyIdentity(identityPin) === actors.ports[4], 'proxy_identity_changed'); expectedOwner(LOCK, OWNER); verifyPin(REGISTRY); const report = jsonPin(REPORT); for (const p of [...report.metadataInputPins, ...report.inputPins]) verifyPin(p); verifyStorageIdentity(); const source = jsonPin(actualPin(join(META, 'source.json'))); for (const p of [...source.files, ...source.repairFiles]) verifyPin({ ...p, path: resolve(ROOT, p.path) }); }
  };
}
async function inspectScope(scope: Scope, mode: ProbeMode = 'ordinary') {
  const data = await scope.validate(), result = await nativeProbe(scope.actors, scope.home, scope.fixture, mode); assertNativeOwnerClosure(result.observation, scope.actors); verifyActorEvidence(result.pin, scope.actors, scope.home, scope.fixture); scope.stable();
  return durable(join(scope.home, 'inspection.json'), { protocol: RELEASE_PROTOCOL + '-inspection', runId: scope.owner.runId, sourcePin: SELF, financialAuditPin: scope.financialPin, identityPin: scope.identityPin, originalLockPin: scope.lockPin, originalRegistryPin: scope.registryPin, owner: scope.owner, actors: scope.actors, actorObservationPin: result.pin, rawCurrentProof: data, observedAtUtc: new Date().toISOString(), financialOnly: !scope.fixture, scoreCertificate: false, originalRegistryReleased: false, oldUnknownSettled: false, releasePerformed: false, fixture: scope.fixture }, scope.home);
}
async function releaseScope(scope: Scope, inspectionPin: Pin, fault: FixtureFault = 'none') {
  demand(scope.fixture || fault === 'none', 'production_release_fault_override_forbidden');
  ordinary(inspectionPin.path, scope.home); const inspection = jsonPin(inspectionPin); demand(inspection.protocol === RELEASE_PROTOCOL + '-inspection' && inspection.fixture === scope.fixture && same(inspection.sourcePin, SELF) && same(inspection.financialAuditPin, scope.financialPin) && same(inspection.identityPin, scope.identityPin) && same(inspection.originalLockPin, scope.lockPin) && same(inspection.originalRegistryPin, scope.registryPin) && same(inspection.owner, scope.owner) && same(inspection.actors, scope.actors) && inspection.scoreCertificate === false && inspection.releasePerformed === false && inspection.oldUnknownSettled === false, 'release_inspection_binding');
  verifyActorEvidence(inspection.actorObservationPin, scope.actors, scope.home, scope.fixture);
  const data = await scope.validate(), fresh = await nativeProbe(scope.actors, scope.home, scope.fixture); assertNativeOwnerClosure(fresh.observation, scope.actors); verifyActorEvidence(fresh.pin, scope.actors, scope.home, scope.fixture);
  if (fault === 'nonce-after-probe') { const changed = { ...scope.owner, ownerNonce: 'fixture-owner-mutated' }, fd = openSync(scope.lockPin.path, 'w'); try { const b = Buffer.from(JSON.stringify(changed)); writeSync(fd, b); fsyncSync(fd); } finally { closeSync(fd); } }
  scope.stable(); verifyPin(SELF);
  const intent = durable(join(scope.home, 'release-intent.json'), { protocol: RELEASE_PROTOCOL + '-intent', runId: scope.owner.runId, sourcePin: SELF, inspectionPin, financialAuditPin: scope.financialPin, identityPin: scope.identityPin, originalLockPin: scope.lockPin, originalRegistryPin: scope.registryPin, owner: scope.owner, actors: scope.actors, freshActorObservationPin: fresh.pin, rawCurrentProof: data, observedAtUtc: new Date().toISOString(), financialOnly: !scope.fixture, scoreCertificate: false, oldUnknownSettled: false, fixture: scope.fixture }, scope.home);
  scope.stable(); verifyPin(inspectionPin); verifyPin(intent); verifyPin(fresh.pin);
  demand(Date.now() - Date.parse(fresh.observation.completedAtUtc) <= 30000, 'release_actor_probe_expired');
  const descriptor = openSync(scope.lockPin.path, 'r');
  try { const fdStat = fstatSync(descriptor), pathStat = lstatSync(scope.lockPin.path), bytes = Buffer.alloc(fdStat.size); demand(fdStat.size === scope.lockPin.bytes && readSync(descriptor, bytes, 0, bytes.length, 0) === bytes.length && hash(bytes) === scope.lockPin.sha256 && same(JSON.parse(bytes.toString('utf8')), scope.owner) && fdStat.dev === pathStat.dev && fdStat.ino === pathStat.ino && fdStat.mtimeMs === pathStat.mtimeMs && !pathStat.isSymbolicLink(), 'exact_lock_handle_identity_changed'); } finally { closeSync(descriptor); }
  expectedOwner(scope.lockPin, scope.owner); unlinkSync(scope.lockPin.path); demand(!existsSync(scope.lockPin.path), 'exact_original_lock_release_unconfirmed');
  if (fault === 'ack-path-blocked') mkdirSync(join(scope.home, 'release-ack.json'));
  try {
    verifyPin(scope.registryPin); verifyPin(SELF);
    return durable(join(scope.home, 'release-ack.json'), { protocol: RELEASE_PROTOCOL + '-ack', runId: scope.owner.runId, sourcePin: SELF, inspectionPin, releaseIntentPin: intent, financialAuditPin: scope.financialPin, identityPin: scope.identityPin, originalLockPin: scope.lockPin, originalRegistryPin: scope.registryPin, owner: scope.owner, actors: scope.actors, freshActorObservationPin: fresh.pin, observedAtUtc: new Date().toISOString(), exactOriginalLockRemoved: true, originalRegistryReleased: false, financialOnly: !scope.fixture, scoreCertificate: false, plannedScoreCompletion: false, oldUnknownSettled: false, originalUnknownCarryNanoCny: '8392180000', fixture: scope.fixture }, scope.home);
  } catch (e) {
    durable(join(scope.home, 'release-failure.json'), { protocol: RELEASE_PROTOCOL + '-failure', sourcePin: SELF, runId: scope.owner.runId, releaseIntentPin: intent, originalLockPin: scope.lockPin, registryPin: scope.registryPin, error: String(e), exactLockAbsentObserved: !existsSync(scope.lockPin.path), acknowledgementCommitted: false, successorAdmissionPermitted: false, scoreCertificate: false, fixture: scope.fixture }, scope.home); throw e;
  }
}

/** F-only controls cannot target production paths, and always retain fixture labels. */
export async function exerciseFinancialReleaseFixture(input: { directory: string; actors: Actors; probeMode?: ProbeMode; fault?: FixtureFault; mutateAfterInspection?: boolean }) {
  const home = makeHome(FIXTURE_ROOT, input.directory); validateActors(input.actors); const owner = { runId: 'financial-fixture-' + basename(home), pid: input.actors.pids[0], ownerNonce: crypto.randomUUID() };
  const lockPin = durable(join(home, 'owned.lock.json'), owner, home), registryPin = durable(join(home, 'registry.json'), { runId: owner.runId, closedPin: null }, home), financialPin = durable(join(home, 'fixture-financial.json'), { fixture: true, scoreCertificate: false, forwarded: 0, realProvider: false }, home), identityPin = durable(join(home, 'fixture-actors.json'), input.actors, home);
  const stable = () => { ordinary(lockPin.path, home); verifyPin(lockPin); demand(same(jsonPin(lockPin), owner), 'release_owner_changed'); verifyPin(registryPin); verifyPin(financialPin); verifyPin(identityPin); verifyPin(SELF); };
  const scope: Scope = { home, owner, actors: input.actors, lockPin, registryPin, financialPin, identityPin, fixture: true, async validate() { stable(); return { fixture: true, realProvider: false, rawFiles: 0 }; }, stable };
  let inspectionPin: Pin | undefined;
  try { inspectionPin = await inspectScope(scope, input.probeMode ?? 'ordinary');
    if (input.mutateAfterInspection) { const fd = openSync(lockPin.path, 'a'); try { writeSync(fd, '\n'); fsyncSync(fd); } finally { closeSync(fd); } }
    const ackPin = await releaseScope(scope, inspectionPin, input.fault ?? 'none'); return { home, lockPin, registryPin, inspectionPin, ackPin, fixtureWorkflowClosed: true, realProductionRelease: false };
  } catch (error) {
    const failurePin = durable(join(home, 'fixture-result.json'), { error: String(error), inspectionPin: inspectionPin ?? null, originalLockRetained: existsSync(lockPin.path), fixtureWorkflowClosed: false, successorAdmissionPermitted: false, realProductionRelease: false }, home); return { home, lockPin, registryPin, inspectionPin, failurePin, fixtureWorkflowClosed: false, realProductionRelease: false, error: String(error) };
  }
}

if (import.meta.main) {
  const args = process.argv.slice(2), mode = args.shift() ?? 'help', option = (name: string) => { const n = args.indexOf(name); demand(n >= 0 && typeof args[n + 1] === 'string', 'missing_' + name); return args[n + 1]!; };
  let home: string | undefined;
  try {
    demand(option('--source-sha') === SELF.sha256, 'reviewed_release_source_changed');
    if (mode === 'inspect') { const identityPin = { ...actualPin(option('--proxy-proof')), sha256: option('--proxy-proof-sha') }; home = makeHome(OUTPUT_ROOT, option('--output')); const scope = await productionScope(home, identityPin); console.log(JSON.stringify(await inspectScope(scope))); }
    else if (mode === 'release') { const inspectionPin = { ...actualPin(option('--inspection')), sha256: option('--inspection-sha') }; verifyPin(inspectionPin); const inspection = jsonPin(inspectionPin); ordinary(dirname(inspectionPin.path), OUTPUT_ROOT, true); home = dirname(inspectionPin.path); const scope = await productionScope(home, inspection.identityPin); console.log(JSON.stringify(await releaseScope(scope, inspectionPin))); }
    else throw new Error('Explicit inspect or release required. No default lock operation.');
  } catch (error) {
    const failure = { protocol: RELEASE_PROTOCOL + '-attempt-failure', runId: FINANCIAL_RUN, sourcePin: SELF, mode, financialAuditPin: REPORT, originalLockPin: LOCK, originalRegistryPin: REGISTRY, originalLockExists: existsSync(LOCK.path), error: String(error), observedAtUtc: new Date().toISOString(), successorAdmissionPermitted: false, scoreCertificate: false, oldUnknownSettled: false, originalRegistryModified: false };
    if (home) { const failurePin = durable(join(home, 'attempt-failure-' + crypto.randomUUID() + '.json'), failure, home); console.log(JSON.stringify({ failurePin, successorAdmissionPermitted: false })); }
    else console.log(JSON.stringify(failure)); process.exitCode = 1;
  }
}
