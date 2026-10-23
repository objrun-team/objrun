import { randomBytes } from "node:crypto";
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export function requireNoUnfinishedCampaign(root: string) {
  const directory = join(root, "docs/repair-2026-10-08/campaigns");
  if (!existsSync(directory)) return;
  for (const name of readdirSync(directory)) {
    const path = join(directory, name), summary = join(path, "summary.json");
    const ledger = join(path, "api-ledger.json");
    if (existsSync(ledger)) {
      const receipt = JSON.parse(readFileSync(ledger, "utf8"));
      if (Number(receipt.reservedUpperBoundUsd ?? 0) > 1e-9 || Object.values(receipt.pending ?? {}).some(value => Number(value) > 0)) throw new Error("Unreconciled provider calls block paid startup: " + name);
    }
    if (!existsSync(summary)) {
      if (["manifest.json", "source.json", "api-ledger.json"].some(file => existsSync(join(path, file)))) throw new Error("Unfinished legacy campaign blocks paid startup: " + name);
      continue;
    }
    const value = JSON.parse(readFileSync(summary, "utf8"));
    if (value.completed !== true && !value.fatal) throw new Error("Unfinished campaign blocks paid startup: " + name);
  }
}

/** One atomic lock shared by every new paid entry; never reclaim an unknown/stale lock. */
export function acquirePaidCampaignLock(input: { root: string; runId: string; entry: string }) {
  requireNoUnfinishedCampaign(input.root);
  const directory = join(input.root, ".phase1-data"); mkdirSync(directory, { recursive: true });
  const path = join(directory, "owned-paid-campaign.lock.json");
  const owned = { pid: process.pid, startedAt: new Date().toISOString(), runId: input.runId, entry: input.entry, ownerNonce: randomBytes(24).toString("hex") };
  let fd: number;
  try { fd = openSync(path, "wx", 0o600); }
  catch { throw new Error("Existing or inaccessible paid lock blocks startup; preserve it for audit: " + path); }
  try { writeFileSync(fd, JSON.stringify(owned, null, 2) + "\n"); fsyncSync(fd); }
  finally { closeSync(fd); }
  let released = false;
  const release = () => {
    if (released) return;
    const actual = JSON.parse(readFileSync(path, "utf8"));
    if (actual.ownerNonce !== owned.ownerNonce || actual.pid !== owned.pid || actual.runId !== owned.runId || actual.startedAt !== owned.startedAt) throw new Error("Refusing to release a paid lock whose ownership changed: " + path);
    unlinkSync(path); released = true;
  };
  try { requireNoUnfinishedCampaign(input.root); } catch (error) { release(); throw error; }
  return { path, owned, release };
}
