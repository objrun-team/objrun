import { test, expect } from "bun:test";
import { mkdirSync, writeFileSync, unlinkSync } from "node:fs";
import { join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { exactStartupInventory, sameStartupOwner, scientificLiveId, assertStartupActorRecord } from "../scripts/benchmark-repair/scientific-startup-proof.ts";

test("actual F file inventories reject missing or additional artifacts", () => {
  const home = join(resolve(import.meta.dir, ".."), ".scratch", "scientific-startup-proof-fixture-" + randomUUID());
  mkdirSync(home); writeFileSync(join(home, "one.json"), "{}\n");
  expect(() => exactStartupInventory(home, ["one.json", "two.json"])).toThrow("startup_inventory_changed");
  writeFileSync(join(home, "two.json"), "{}\n"); expect(() => exactStartupInventory(home, ["one.json", "two.json"])).not.toThrow();
  writeFileSync(join(home, "new-unexpected.json"), "{}\n"); expect(() => exactStartupInventory(home, ["one.json", "two.json"])).toThrow("startup_inventory_changed");
  unlinkSync(join(home, "new-unexpected.json")); expect(() => exactStartupInventory(home, ["one.json", "two.json"])).not.toThrow();
});

test("an unknown actor never qualifies for zero-forward owned release", () => {
  const record = { pids: [110336], sourcePin: { sha256: "fixture-source" }, status: 0, error: null, timedOut: false,
    ownedChildCloseObserved: true, ownedChildExitObserved: true, observed: [{ pid: 110336, state: "query_error" }], parsed: [{ pid: 110336, state: "query_error" }] };
  expect(() => assertStartupActorRecord(record, "fixture-source")).toThrow("startup_actor_present_or_unknown");
  expect(() => assertStartupActorRecord({ ...record, status: null }, "fixture-source")).toThrow("startup_actor_query_unknown");
});

test("a different canonical owner nonce or PID is rejected", () => {
  const original = { pid: 110336, runId: "repair-2026-10-08T17-36-10-873Z", ownerNonce: "private-fixture-original", mode: "carry-science-oom-2026-10-08-v2" };
  expect(() => sameStartupOwner({ ...original }, original)).not.toThrow();
  expect(() => sameStartupOwner({ ...original, ownerNonce: "private-fixture-different" }, original)).toThrow("startup_lock_owner_changed");
  expect(() => sameStartupOwner({ ...original, pid: 110337 }, original)).toThrow("startup_lock_owner_changed");
});

test("official CMT uses exact integer index while controlled synthetic rows preserve id", () => {
  expect(scientificLiveId("cmt", { index: 0 })).toBe("cmt-0"); expect(scientificLiveId("cmt", { index: 49 })).toBe("cmt-49");
  expect(() => scientificLiveId("cmt", { index: "0" })).toThrow("cmt_official_index");
  expect(() => scientificLiveId("cmt", { index: 50 })).toThrow("cmt_official_index");
  expect(scientificLiveId("chembench", { id: "public-native-1" }, true)).toBe("public-native-1");
  expect(scientificLiveId("cmt", { id: "synthetic-cmt-fixture" }, true)).toBe("synthetic-cmt-fixture");
  expect(() => scientificLiveId("cmt", { id: "synthetic-cmt-fixture" })).toThrow("cmt_official_index");
});
