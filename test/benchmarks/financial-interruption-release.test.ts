import { afterAll, beforeAll, expect, test } from 'bun:test';
import { spawn, type ChildProcess } from 'node:child_process';
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, writeSync } from 'node:fs';
import { createServer, type Server } from 'node:net';
import { join, resolve } from 'node:path';
import { actualPin, jsonPin, type Pin } from '../../scripts/benchmark-repair/paid-resource-proof-v2.ts';
import { assertFixedFinancialReport, exerciseFinancialReleaseFixture } from '../../scripts/benchmark-repair/financial-interruption-release.ts';

const ROOT = resolve(import.meta.dir, '../..'), PARENT = join(ROOT, '.scratch/financial-release-controls'), ID = crypto.randomUUID();
const children: { child: ChildProcess; pid: number; exit: boolean; close: boolean; stopped: Promise<void> }[] = [];
const servers: Server[] = [], ports: number[] = [], pids: number[] = [];
const results: any[] = [];
const home = (name: string) => join(PARENT, ID + '-' + name);
function save(path: string, value: unknown) { const b = Buffer.from(JSON.stringify(value, null, 2) + '\n'), fd = openSync(path, 'wx'); try { writeSync(fd, b); fsyncSync(fd); } finally { closeSync(fd); } expect(readFileSync(path).equals(b)).toBe(true); return actualPin(path); }
async function stopOwned() { for (const row of children) if (!row.close) row.child.kill('SIGTERM'); await Promise.all(children.map(row => row.stopped)); }
async function stopPorts() { await Promise.all(servers.filter(s => s.listening).map(s => new Promise<void>((yes, no) => s.close(e => e ? no(e) : yes())))); }
async function exercise(name: string, extras: any = {}) { const r = await exerciseFinancialReleaseFixture({ directory: home(name), actors: { pids, ports }, ...extras }); results.push({ name, ...r }); return r; }
beforeAll(async () => {
  if (!existsSync(PARENT)) mkdirSync(PARENT);
  for (let i = 0; i < 5; i++) {
    const child = spawn(process.execPath, ['-e', 'setTimeout(()=>{},60000)'], { cwd: ROOT, windowsHide: true, stdio: 'ignore' }); expect(child.pid).toBeGreaterThan(0);
    let stopped!: () => void; const row = { child, pid: child.pid!, exit: false, close: false, stopped: new Promise<void>(r => { stopped = r; }) }; children.push(row); pids.push(row.pid);
    child.once('exit', () => { row.exit = true; }); child.once('close', () => { row.close = true; stopped(); });
    const server = createServer(); await new Promise<void>((yes, no) => { server.once('error', no); server.listen(0, '127.0.0.1', yes); }); servers.push(server); const address = server.address(); expect(typeof address).toBe('object'); ports.push((address as any).port);
  }
});
afterAll(async () => {
  await stopOwned(); await stopPorts();
  const report = join(PARENT, ID + '-summary'); mkdirSync(report);
  const pin = save(join(report, 'controls.json'), { protocol: 'financial-release-native-controls-v1', sourcePin: actualPin(join(ROOT, 'scripts/benchmark-repair/financial-interruption-release.ts')), testPin: actualPin(import.meta.path), originalProductionLockOperations: 0, actualProviderRequests: 0, scoreCertificate: false, fixtureResults: results, ownedChildren: children.map(r => ({ pid: r.pid, exitObserved: r.exit, closeObserved: r.close })), ownedPorts: ports.map((port, i) => ({ port, closed: !servers[i]!.listening })), observedAtUtc: new Date().toISOString() });
  console.log(JSON.stringify({ controlsPin: pin }));
});

test('actual five owned live PIDs and listeners block fixture release', async () => {
  const r = await exercise('present'); expect(r.fixtureWorkflowClosed).toBe(false); expect(r.error).toContain('original_actor_present_reused_or_unknown'); expect(existsSync(r.lockPin.path)).toBe(true);
}, 30000);
test('after exact child closure an actual listener still blocks release', async () => {
  await stopOwned(); expect(children.every(c => c.exit && c.close)).toBe(true); const r = await exercise('listener'); expect(r.fixtureWorkflowClosed).toBe(false); expect(r.error).toContain('original_port_present_reused_or_unknown'); expect(existsSync(r.lockPin.path)).toBe(true); await stopPorts();
}, 30000);
test('five closed PIDs and ports permit only a temporary fixture lock release', async () => {
  const r = await exercise('closed'); expect(r.fixtureWorkflowClosed).toBe(true); expect(r.realProductionRelease).toBe(false); expect(existsSync(r.lockPin.path)).toBe(false);
  const ack = jsonPin(r.ackPin!); expect(ack.fixture).toBe(true); expect(ack.financialOnly).toBe(false); expect(ack.scoreCertificate).toBe(false); expect(ack.originalRegistryReleased).toBe(false); expect(jsonPin(r.registryPin).closedPin).toBeNull(); expect(ack.oldUnknownSettled).toBe(false);
}, 30000);
test('a current process using a target PID is rejected rather than presumed original closure', async () => {
  const r = await exercise('reused', { actors: { pids: [process.pid, ...pids.slice(1)], ports } }); expect(r.fixtureWorkflowClosed).toBe(false); expect(r.error).toContain('original_actor_present_reused_or_unknown'); expect(existsSync(r.lockPin.path)).toBe(true);
}, 30000);
test('actual invalid-JSON query exit remains unknown and retains lock', async () => {
  const r = await exercise('json', { probeMode: 'invalid-json' }); expect(r.fixtureWorkflowClosed).toBe(false); expect(r.error).toContain('native_actor_query_unknown'); expect(existsSync(r.lockPin.path)).toBe(true);
}, 30000);
test('actual 10-second deadline terminates and closes only the query child', async () => {
  const r = await exercise('timeout', { probeMode: 'timeout' }); expect(r.fixtureWorkflowClosed).toBe(false); expect(r.error).toContain('native_actor_query_unknown'); expect(existsSync(r.lockPin.path)).toBe(true);
  const names = (await import('node:fs')).readdirSync(r.home), queryDir = names.find(n => n.startsWith('actor-probe-'))!; const observation = JSON.parse(readFileSync(join(r.home, queryDir, 'result.json'), 'utf8'));
  expect(observation.timeout).toBe(true); expect(observation.killAttempted).toBe(true); expect(observation.exitObserved).toBe(true); expect(observation.closeObserved).toBe(true); expect(BigInt(observation.elapsedMonotonicNs)).toBeGreaterThanOrEqual(10000000000n); expect(observation.childPid).not.toBe(process.pid);
}, 30000);
test('real nonce mutation after fresh native query refuses removal', async () => {
  const r = await exercise('nonce', { fault: 'nonce-after-probe' }); expect(r.fixtureWorkflowClosed).toBe(false); expect(existsSync(r.lockPin.path)).toBe(true); expect(r.error).toContain('pin_changed'); expect(existsSync(join(r.home, 'release-intent.json'))).toBe(false);
}, 30000);
test('real lock byte mutation between inspection and release refuses removal', async () => {
  const r = await exercise('bytes', { mutateAfterInspection: true }); expect(r.fixtureWorkflowClosed).toBe(false); expect(existsSync(r.lockPin.path)).toBe(true); expect(r.error).toContain('pin_changed');
}, 30000);
test('actual acknowledgement path failure preserves intent and a blocking failure receipt', async () => {
  const r = await exercise('ack', { fault: 'ack-path-blocked' }); expect(r.fixtureWorkflowClosed).toBe(false); expect(existsSync(r.lockPin.path)).toBe(false); expect(existsSync(join(r.home, 'release-intent.json'))).toBe(true); expect(existsSync(join(r.home, 'release-failure.json'))).toBe(true);
  const failure = JSON.parse(readFileSync(join(r.home, 'release-failure.json'), 'utf8')); expect(failure.acknowledgementCommitted).toBe(false); expect(failure.successorAdmissionPermitted).toBe(false); expect(failure.scoreCertificate).toBe(false); expect(jsonPin(r.registryPin).closedPin).toBeNull();
}, 30000);
test('production financial proof rejects unknown, changed carry and incomplete raw-index claims', () => {
  const report = JSON.parse(readFileSync(join(ROOT, 'test/fixtures/repair/scientific-financial-interruptions/repair-2026-10-08T18-32-57-118Z-audit-v2/audit.json'), 'utf8')); expect(() => assertFixedFinancialReport(report)).not.toThrow();
  for (const patch of [{ newUnknownCount: 1 }, { newPendingCount: 1 }, { oldUnknownSettled: true }, { originalUnknownCarryNanoCny: '0' }, { rawRequestAndResponseFilesDoubleVerified: 47007 }, { scoreCertificate: true }]) expect(() => assertFixedFinancialReport({ ...report, ...patch })).toThrow();
});
