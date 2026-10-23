// @bun
// scripts/repair-2026-10-10/full-f/novaeve_formal_v1/broker/publish-control-v1.ts
import { readFileSync as readFileSync2 } from "fs";
import { join, resolve } from "path";

// scripts/repair-2026-10-10/full-f/shared/atomic-state.ts
import { randomBytes } from "crypto";
import { mkdirSync, openSync, writeFileSync, fsyncSync, closeSync, renameSync, unlinkSync } from "fs";
import { dirname } from "path";
function atomicStateJson(path, value, replace = renameSync, wait = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = path + "." + randomBytes(12).toString("hex") + ".tmp";
  const fd = openSync(temporary, "wx", 384);
  try {
    writeFileSync(fd, JSON.stringify(value, null, 2) + `
`);
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  try {
    for (let attempt = 0;; attempt++) {
      try {
        replace(temporary, path);
        return;
      } catch (error) {
        if (!["EPERM", "EACCES", "EBUSY"].includes(error?.code) || attempt >= 40)
          throw error;
        wait(Math.min(10 + attempt * 2, 50));
      }
    }
  } finally {
    try {
      unlinkSync(temporary);
    } catch (error) {
      if (error?.code !== "ENOENT")
        throw error;
    }
  }
}

// scripts/repair-2026-10-10/full-f/novaeve_formal_v1/broker/remote-disk-gate-v1.ts
import { readFileSync } from "fs";

// scripts/repair-2026-10-10/full-f/shared/actual-physical-disk-floor.next.ts
var GiB = 1024 ** 3;
function evaluateDockerDisk(observation, options) {
  const floor = 5 * GiB, growth = options.plannedGrowthBytes ?? 0, ageLimit = options.maximumAgeMs ?? 30000;
  if (!Number.isFinite(floor) || floor < 5 * GiB || !Number.isFinite(growth) || growth < 0)
    throw Error("invalid_disk_policy");
  const block = (reason) => ({ admissible: false, reason, minimumRequiredBytes: floor, scoreCertificate: false });
  if (!observation)
    return block("physical_disk_measurement_unavailable");
  if (observation.drive.toUpperCase() !== options.expectedDrive.toUpperCase())
    return block("wrong_physical_docker_volume");
  if (observation.driveType !== 3)
    return block("not_a_local_fixed_disk");
  if (!Number.isFinite(observation.freeBytes) || observation.freeBytes < 0)
    return block("invalid_free_space");
  const age = options.nowMs - observation.observedAtMs;
  if (!Number.isFinite(age) || age < 0 || age > ageLimit)
    return block("stale_disk_measurement");
  if (observation.freeBytes < floor)
    return block("actual_disk_below_five_gib_floor");
  return { admissible: true, reason: "actual_local_volume_above_five_gib_floor", freeBytes: observation.freeBytes, minimumRequiredBytes: floor, scoreCertificate: false };
}

// scripts/repair-2026-10-10/full-f/novaeve_formal_v1/broker/remote-disk-gate-v1.ts
function verifyRemoteDisk(path) {
  const d = JSON.parse(readFileSync(path, "utf8"));
  if (!(d.protocol === "novaeve-runtime-disk-v1" && d.dataRoot === "/data/wpx/tgengin/docker" || d.protocol === "novaeve-docker-storage-observation-v1" && d.dockerRootDir === "/data/wpx/tgengin/docker" && d.probeExitCode === 0))
    throw Error("remote_disk_scope_invalid");
  const gate = evaluateDockerDisk({ drive: "E:", driveType: 3, freeBytes: d.freeBytes ?? d.availableBytes, observedAtMs: d.observedAtMs ?? Date.parse(d.observedAtUtc) }, { nowMs: Date.now(), expectedDrive: "E:" });
  if (!gate.admissible)
    throw Error(gate.reason);
  return gate;
}

// scripts/repair-2026-10-10/full-f/novaeve_formal_v1/broker/publish-control-v1.ts
var root = resolve(import.meta.dir, "../../../../..");
var base = join(root, "docs/repair-2026-10-10/full-f-rerun");
if (process.argv[2] !== "--publish")
  throw Error("root operator must explicitly use --publish");
var path = join(base, "control.json");
var c = JSON.parse(readFileSync2(path, "utf8"));
var next = JSON.parse(readFileSync2(join(base, "novaeve-formal-20261013/broker/connection.private.json"), "utf8"));
if (c.broker && c.broker.runId !== next.runId) {
  let old;
  try {
    old = await (await fetch(c.broker.endpoint + "/health", { signal: AbortSignal.timeout(3000) })).json();
  } catch {
    throw Error("old_broker_unreachable_requires_owner_audit");
  }
  if (!old.dispatchPaused)
    throw Error("old_broker_must_be_paused_before_handoff");
  if (old.activeRequests || old.queuedRequests || old.lanes.some((x) => !x.closed) || old.canonicalOwner || old.resourceSlots?.length)
    throw Error("old_broker_owns_unfinished_paid_work");
}
var health = await (await fetch(next.endpoint + "/health", { signal: AbortSignal.timeout(3000) })).json();
if (health.runId !== next.runId || !health.healthy || health.maxInFlight !== 16 || health.targetMax !== 16)
  throw Error("new_broker_not_ready");
if (health.localMock || health.activeRequests || health.queuedRequests || health.canonicalOwner || health.lanes.length || health.resourceSlots?.length || health.providerSlug !== "digitalocean" || health.transportPolicy?.timeoutMs !== 600000)
  throw Error("new_broker_not_clean_real_provider");
verifyRemoteDisk(join(base, "novaeve-formal-20261013/broker/remote-disk.json"));
atomicStateJson(join(base, "novaeve-formal-20261013/broker/control-before.private.json"), c);
atomicStateJson(path, { ...c, broker: next, paidReady: true, updatedAtUtc: new Date().toISOString(), novaeve: { protocol: "novaeve-local-worker-remote-docker-v1", totalConcurrency: 16 }, concurrency: { ...c.concurrency, initialGlobal: 16, targetGlobal: 16, perBenchRequests: 16, heavySlots: 16, perBenchHeavySlots: 16 } });
console.log(JSON.stringify({ published: true, runId: next.runId, total: 16, secretsPrinted: false }));
