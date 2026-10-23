import { test, expect } from "bun:test";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { createHash } from "node:crypto";
import { assertPidsAbsent, observeOriginalPaidPids, exercisePidProbeFixture } from "../scripts/repair-2026-10-08/paid-resource-admission-v2.ts";

const root = resolve(import.meta.dir, ".."), directory = join(root, "docs/repair-2026-10-08/pid-probe-records");
const original = [50652, 38176, 87440, 96080, 96848];
const sha = (raw: Buffer) => createHash("sha256").update(raw).digest("hex");

test("actual native five-PID probe durably preserves bounded raw streams and execution facts without acquiring a lock", async () => {
  const before = new Set(existsSync(directory) ? readdirSync(directory) : []);
  const lock = join(root, ".phase1-data/owned-paid-campaign.lock.json"), lockBefore = existsSync(lock) ? sha(readFileSync(lock)) : null;
  const observed = await observeOriginalPaidPids();
  const added = readdirSync(directory).filter(name => !before.has(name));
  expect(added).toHaveLength(1);
  const area = join(directory, added[0]), context = JSON.parse(readFileSync(join(area, "context.json"), "utf8"));
  const result = JSON.parse(readFileSync(join(area, "result.json"), "utf8"));
  expect(context.pids).toEqual(original); expect(context.hostPid).toBe(process.pid); expect(context.cwd).toBe(process.cwd());
  expect(context.timeoutMs).toBe(10000); expect(context.maxBufferBytes).toBe(1048576);
  expect(context.sourcePin.sha256).toBe(sha(readFileSync(context.sourcePin.path)));
  expect(result.error).toBeNull(); expect(result.status).toBe(0); expect(result.timedOut).toBe(false);
  expect(result.ownedChildExitObserved).toBe(true); expect(result.ownedChildCloseObserved).toBe(true);
  expect(observed).toEqual(original.map(pid => ({ pid, state: "absent" })));
  expect(() => assertPidsAbsent(original, observed)).not.toThrow();
  expect(result.observed).toEqual(observed); expect(result.modelCalls).toBe(0); expect(result.productionLockAcquiredByProbe).toBe(false);
  expect(result.diagnosticFsyncReturned).toBe(true); expect(result.diagnosticReadbackReturned).toBe(true);
  for (const pin of [result.stdoutPin, result.stderrPin]) {
    const raw = readFileSync(pin.path); expect(raw.length).toBeLessThanOrEqual(1048576);
    expect(statSync(pin.path).size).toBe(pin.bytes); expect(sha(raw)).toBe(pin.sha256);
  }
  if (!result.error && result.status === 0 && !result.parseError) expect(result.parsed).toEqual(observed);
  else expect(observed).toEqual(original.map(pid => ({ pid, state: "query_error" })));
  expect(existsSync(lock) ? sha(readFileSync(lock)) : null).toBe(lockBefore);
  console.log(JSON.stringify({ pidProbeRecord: join(area, "result.json"), hostPid: process.pid, childPid: result.childPid,
    status: result.status, observed, modelCalls: 0, productionLockAcquired: false }));
}, 25000);

for (const scenario of ["timeout", "invalid-json"] as const) test(`actual ${scenario} child closes and the original guard rejects its output`, async () => {
  const base = join(root, ".scratch/paid-pid-probe-fixtures"), before = new Set(existsSync(base) ? readdirSync(base) : []);
  const lock = join(root, ".phase1-data/owned-paid-campaign.lock.json"), lockBefore = existsSync(lock) ? sha(readFileSync(lock)) : null;
  const observed = await exercisePidProbeFixture(scenario), added = readdirSync(base).filter(name => !before.has(name));
  expect(added).toHaveLength(1);
  const file = join(base, added[0], "result.json"), result = JSON.parse(readFileSync(file, "utf8"));
  expect(result.fixtureScenario).toBe(scenario); expect(result.timeoutMs).toBe(10000);
  expect(result.ownedChildExitObserved).toBe(true); expect(result.ownedChildCloseObserved).toBe(true);
  expect(observed).toEqual(original.map(pid => ({ pid, state: "query_error" })));
  expect(() => assertPidsAbsent(original, observed)).toThrow("original_pid_present_or_unknown");
  if (scenario === "timeout") {
    expect(result.timedOut).toBe(true); expect(result.error.code).toBe("ETIMEDOUT");
    expect(result.elapsedMonotonicMs).toBeGreaterThanOrEqual(10000); expect(result.elapsedMonotonicMs).toBeLessThan(15000);
    expect(result.killAttempts.length).toBeGreaterThanOrEqual(1);
    expect(result.killAttempts.every((row: { pid: number }) => row.pid === result.childPid)).toBe(true);
  } else {
    expect(result.status).toBe(0); expect(result.error).toBeNull(); expect(result.timedOut).toBe(false);
    expect(result.parseError).not.toBeNull(); expect(result.killAttempts).toEqual([]);
  }
  for (const pin of [result.stdoutPin, result.stderrPin]) expect(sha(readFileSync(pin.path))).toBe(pin.sha256);
  expect(existsSync(lock) ? sha(readFileSync(lock)) : null).toBe(lockBefore);
  console.log(JSON.stringify({ fixtureScenario: scenario, pidProbeRecord: file, childPid: result.childPid, elapsedMonotonicMs: result.elapsedMonotonicMs,
    ownedChildCloseObserved: result.ownedChildCloseObserved, timedOut: result.timedOut, modelCalls: 0, productionLockAcquired: false }));
}, 25000);

test("the original PID guard still requires the complete unique five-PID absent set", () => {
  const absent = original.map(pid => ({ pid, state: "absent" as const }));
  expect(() => assertPidsAbsent(original, absent)).not.toThrow();
  expect(() => assertPidsAbsent(original, absent.slice(1))).toThrow("original_pid_present_or_unknown");
  expect(() => assertPidsAbsent(original, [absent[0], absent[0], ...absent.slice(2)])).toThrow("original_pid_present_or_unknown");
  expect(() => assertPidsAbsent(original, [{ pid: original[0], state: "present" }, ...absent.slice(1)])).toThrow("original_pid_present_or_unknown");
  expect(() => assertPidsAbsent(original, [{ pid: original[0], state: "query_error" }, ...absent.slice(1)])).toThrow("original_pid_present_or_unknown");
});
