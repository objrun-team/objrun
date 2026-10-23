// @bun
// scripts/repair-2026-10-10/full-f/novaeve_formal_v1/broker/pause-old-v1.ts
import { readFileSync } from "fs";
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

// scripts/repair-2026-10-10/full-f/novaeve_formal_v1/broker/pause-old-v1.ts
var root = resolve(import.meta.dir, "../../../../..");
var base = join(root, "docs/repair-2026-10-10/full-f-rerun");
if (process.argv[2] !== "--pause")
  throw Error("use --pause");
var c = JSON.parse(readFileSync(join(base, "control.json"), "utf8"));
var response = await fetch(c.broker.endpoint + "/admin/pause", { method: "POST", headers: { authorization: "Bearer " + c.broker.accessToken }, signal: AbortSignal.timeout(5000) });
if (!response.ok)
  throw Error("old_pause_failed");
var result = await response.json();
var health = await (await fetch(c.broker.endpoint + "/health", { signal: AbortSignal.timeout(5000) })).json();
if (!health.dispatchPaused || health.runId !== c.broker.runId)
  throw Error("old_pause_not_observed");
var proof = { protocol: "novaeve-old-broker-handoff-pause-v1", atUtc: new Date().toISOString(), runId: health.runId, endpoint: c.broker.endpoint, result, activeRequests: health.activeRequests, queuedRequests: health.queuedRequests, unclosedLanes: health.lanes.filter((x) => !x.closed).length, canonicalOwnerPresent: !!health.canonicalOwner, unknownCostsRetained: health.lanes.reduce((n, x) => n + x.unknownCount, 0), modelCalls: 0 };
atomicStateJson(join(base, "novaeve-formal-20261013/broker/old-broker-pause-" + Date.now() + ".json"), proof);
console.log(JSON.stringify(proof));
