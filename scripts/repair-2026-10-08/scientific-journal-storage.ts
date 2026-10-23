import { lstatSync, readFileSync, realpathSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { digest } from "./scientific-journal-plan.ts";
export const SCIENTIFIC_STORE_OWNER_ROOT = "D:/objrun-experiment-stores/01a119ed-fdf7-7c32-b323-de9bab1290b6";
export const SCIENTIFIC_STORE_SETUP_SHA = "108e0c5ab632361785aa6d67185fc75afab64bcfc4627186563c2e20b3b6c2ac";
type Pin = { path: string; bytes?: number; sha256: string };
const samePath = (a: string, b: string) => resolve(a).toLowerCase() === resolve(b).toLowerCase();
function ordinaryAncestors(path: string) {
  let at = resolve(path);
  while (true) {
    const stat = lstatSync(at); if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error("Store ancestor is not ordinary");
    const parent = dirname(at); if (parent === at) break; at = parent;
  }
}
/** Verify only an already-created reviewed D store; this helper does not create or migrate data. */
export function validateScientificStore(root: string, campaign: string, input: Pin) {
  const expectedReceipt = join(root, "docs/repair-2026-10-08/campaigns", campaign, "storage-layout.json");
  if (!samePath(input.path, expectedReceipt) || !/^[a-f0-9]{64}$/.test(input.sha256)) throw new Error("Explicit owned store receipt required");
  const raw = readFileSync(input.path);
  if (digest(raw) !== input.sha256 || (input.bytes !== undefined && input.bytes !== raw.length)) throw new Error("Store receipt changed");
  const layout = JSON.parse(raw.toString("utf8"));
  const physical = join(SCIENTIFIC_STORE_OWNER_ROOT, "scientific-journal-v2-" + campaign), logical = join(root, ".phase1-data/repair", campaign);
  if (layout.protocol !== "scientific-journal-store-v2" || layout.runId !== campaign || layout.mode !== "owned-d-new-store" || layout.junctionVerified !== true || layout.reuse !== "never" || layout.oldStoresMoved !== false || layout.scriptPin?.sha256 !== SCIENTIFIC_STORE_SETUP_SHA || !samePath(layout.allowedOwnerRoot, SCIENTIFIC_STORE_OWNER_ROOT) || !samePath(layout.physicalStore, physical) || !samePath(layout.logicalStore, logical)) throw new Error("Unreviewed store layout");
  ordinaryAncestors(physical); ordinaryAncestors(dirname(logical));
  if (!lstatSync(logical).isSymbolicLink() || !samePath(realpathSync(logical), physical)) throw new Error("Logical store junction changed");
  for (const proof of [layout.physicalOwnerReceiptPin, layout.scriptPin, layout.storageLeasePin] as Pin[]) if (digest(readFileSync(proof.path)) !== proof.sha256) throw new Error("Store ownership proof changed");
  if (digest(readFileSync(join(logical, "storage-owner.json"))) !== layout.physicalOwnerReceiptPin.sha256) throw new Error("Logical owner proof differs");
  return { logicalStore: logical, physicalStore: physical, receipt: input, layout };
}
