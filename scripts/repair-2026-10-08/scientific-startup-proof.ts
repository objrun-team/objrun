/** One explicitly reviewed zero-forward startup. No general failed-run or unknown-fee exception. */
import { closeSync, existsSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, readdirSync, realpathSync, unlinkSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { actualPin, demand, same, verifyPin, type Pin } from "./paid-resource-proof-v2.ts";
import { digest, fixedScientificPlan, scientificPrompt, SCIENCE_PORTS } from "./scientific-journal-plan.ts";
import { graderFetch } from "../../app/src/engine/registry.ts";

const ROOT = resolve(import.meta.dir, "../..");
export const ZERO_STARTUP_RUN = "repair-2026-10-08T17-36-10-873Z";
const SNAPSHOT_SHA = "a258544fe3de6826152bcb309fbed8c20c3453ecb08479fc5d92fc8516f93b8b";
const archive = join(ROOT, "docs/repair-2026-10-08/scientific-startup-failures", ZERO_STARTUP_RUN, "root-frozen-v1");
const proofHome = join(ROOT, "docs/repair-2026-10-08/scientific-startup-aborts", ZERO_STARTUP_RUN);
const oldSources = new Map([
  ["scientific-journal-campaign.ts", "458993f378a35c55f65be54c48cbc4d70b277eada87a7d65baf6edcf8eefc493"],
  ["paid-resource-admission-v2.ts", "859844a7f32f88f6fc51b9d0b468620c1ac6222cea9996c7340e3d6f303a9828"],
  ["scientific-journal-admission.ts", "d619371ff2a8763f738a84377bf97d4da20c213654982fd41c7553ed6a2d579d"],
]);
function saved(path: string, raw: Buffer) {
  mkdirSync(dirname(path), { recursive: true }); const fd = openSync(path, "wx", 0o600);
  try { writeFileSync(fd, raw); fsyncSync(fd); } finally { closeSync(fd); }
  demand(readFileSync(path).equals(raw), "startup_proof_readback"); return actualPin(path);
}
function json(path: string) { return JSON.parse(readFileSync(path, "utf8")); }
function save(path: string, value: unknown) { return saved(path, Buffer.from(JSON.stringify(value, null, 2) + "\n")); }
export function exactStartupInventory(path: string, expected: readonly string[]) {
  const names = readdirSync(path).sort(); demand(same(names, [...expected].sort()), "startup_inventory_changed");
  for (const name of names) demand(lstatSync(join(path, name)).isFile() && !lstatSync(join(path, name)).isSymbolicLink(), "startup_nonregular_artifact");
}
export function sameStartupOwner(actual: any, expected: any) {
  demand(actual.pid === expected.pid && actual.runId === expected.runId && actual.ownerNonce === expected.ownerNonce && actual.mode === expected.mode, "startup_lock_owner_changed");
}
export function scientificLiveId(slug: string, row: Record<string, unknown>, fixture = false) {
  if (fixture) { demand(typeof row.id === "string" && row.id.length > 0, "scientific_fixture_id"); return row.id as string; }
  if (slug === "cmt") { demand(Number.isSafeInteger(row.index) && Number(row.index) >= 0 && Number(row.index) < 50, "cmt_official_index"); return `cmt-${row.index}`; }
  demand(typeof row.id === "string" && row.id.length > 0, "scientific_official_id"); return row.id as string;
}
function originalState(requireOriginalLock: boolean) {
  const snapshotPin = { ...actualPin(join(archive, "snapshot.json")), sha256: SNAPSHOT_SHA }; verifyPin(snapshotPin);
  const snapshot = json(snapshotPin.path); demand(snapshot.protocol === "root-unstarted-scientific-admission-failure-snapshot-v1" && snapshot.runId === ZERO_STARTUP_RUN && snapshot.files.length === 15, "startup_snapshot_profile");
  for (const item of snapshot.files) {
    demand(resolve(item.archive).startsWith(archive + "\\"), "startup_archive_path");
    verifyPin({ path: item.archive, bytes: item.bytes, sha256: item.sha256 });
    const name = basename(item.source);
    if (oldSources.has(name)) demand(item.sha256 === oldSources.get(name), "startup_original_source_version");
    else if (name !== "owned-paid-campaign.lock.json" || requireOriginalLock) verifyPin({ path: item.source, bytes: item.bytes, sha256: item.sha256 });
  }
  const get = (name: string) => { const rows = snapshot.files.filter((item: any) => basename(item.source) === name); demand(rows.length === 1, "startup_required_original_missing"); return rows[0]; };
  const home = join(ROOT, "docs/repair-2026-10-08/campaigns", ZERO_STARTUP_RUN);
  const campaignNames = snapshot.files.filter((item: any) => dirname(item.source) === home).map((item: any) => basename(item.source));
  exactStartupInventory(home, campaignNames); demand(campaignNames.length === 9, "startup_metadata_count");
  const failure = json(get("paid-admission-failure.json").archive), phase = json(get("startup-or-closing-failure.json").archive);
  demand(failure.runId === ZERO_STARTUP_RUN && failure.cash === null && phase.campaign === ZERO_STARTUP_RUN && phase.completed === false && phase.modelPhaseEnabled === false && phase.confirmedNoProviderForward === true && phase.error === "Error:Live official book denominator/ID changed", "startup_not_zero_forward_phase");
  demand(same(failure.source.modelPhaseEnabled, phase.modelPhaseEnabled) && failure.source.confirmedNoProviderForward === true, "startup_phase_evidence_disagrees");
  const layout = json(get("storage-layout.json").archive);
  const physical = resolve("D:/objrun-experiment-stores/01a119ed-fdf7-7c32-b323-de9bab1290b6", `scientific-journal-v2-${ZERO_STARTUP_RUN}`);
  demand(layout.runId === ZERO_STARTUP_RUN && resolve(layout.physicalStore) === physical && layout.ownerPid === 110336 && layout.reuse === "never", "startup_store_binding");
  demand(resolve(realpathSync(layout.logicalStore)).toLowerCase() === physical.toLowerCase(), "startup_junction_changed");
  exactStartupInventory(physical, ["storage-owner.json"]); verifyPin(layout.storageLeasePin); verifyPin(layout.physicalOwnerReceiptPin);
  const lockRow = get("owned-paid-campaign.lock.json"), owner = json(lockRow.archive);
  demand(owner.pid === 110336 && owner.runId === ZERO_STARTUP_RUN && owner.mode === "carry-science-oom-2026-10-08-v2", "startup_original_owner");
  if (requireOriginalLock) sameStartupOwner(json(lockRow.source), owner);
  const admission = json(get("paid-resource-admission.json").archive), registry = json(get("paid-resource-v2-run.json").archive);
  demand(same(admission.owned, owner) && registry.closedPin === null && registry.runId === ZERO_STARTUP_RUN, "startup_admission_changed");
  demand(admission.carry.length === 4 && admission.carry.every((row: any) => row.settled === false && row.status === "unknown_original_provider_receipt"), "startup_old_unknowns_changed");
  return { snapshotPin, snapshot, home, physical, lockPin: { path: lockRow.source, bytes: lockRow.bytes, sha256: lockRow.sha256 }, owner };
}
export function assertStartupActorRecord(record: any, expectedSourceSha: string) {
  demand(record.pids?.length === 1 && record.pids[0] === 110336 && record.sourcePin?.sha256 === expectedSourceSha && record.status === 0 && record.error === null && record.timedOut === false && record.ownedChildCloseObserved === true && record.ownedChildExitObserved === true, "startup_actor_query_unknown");
  demand(same(record.observed, [{ pid: 110336, state: "absent" }]) && same(record.parsed, record.observed), "startup_actor_present_or_unknown");
  verifyPin(record.stdoutPin); verifyPin(record.stderrPin);
  demand(record.stdoutPin.truncated === false && record.stderrPin.truncated === false && same(JSON.parse(readFileSync(record.stdoutPin.path, "utf8")), record.observed), "startup_actor_raw_binding");
}
async function actorEvidence() {
  const { observeSpecificUnstartedActor } = await import("./paid-resource-admission-v2.ts");
  const observation = await observeSpecificUnstartedActor(); verifyPin(observation.recordPin);
  assertStartupActorRecord(json(observation.recordPin.path), actualPin(join(import.meta.dir, "paid-resource-admission-v2.ts")).sha256);
  return observation.recordPin;
}
function verifyAudit(pin: Pin, requireLock: boolean) {
  verifyPin(pin); const audit = json(pin.path), state = originalState(requireLock);
  demand(audit.protocol === "scientific-startup-zero-forward-audit-v1" && audit.runId === ZERO_STARTUP_RUN && audit.snapshotPin.sha256 === SNAPSHOT_SHA && same(audit.originalLockPin, state.lockPin) && audit.completed === false && audit.scoreCertified === false && audit.state === "aborted_before_provider", "startup_audit_profile");
  demand(audit.sourceArchives.length === 2 && same(audit.sourceArchives.map((row: any) => basename(row.sourcePath)).sort(), ["paid-resource-admission-v2.ts", "scientific-startup-proof.ts"]), "startup_certifier_sources");
  for (const source of audit.sourceArchives) {
    const name = basename(source.sourcePath);
    demand(resolve(source.sourcePath) === join(import.meta.dir, name) && resolve(source.archivePin.path) === join(proofHome, "sources", name), "startup_certifier_source_path");
    verifyPin(source.archivePin);
  }
  const factory = audit.sourceArchives.find((row: any) => basename(row.sourcePath) === "paid-resource-admission-v2.ts"); demand(factory, "startup_actor_source_missing");
  verifyPin(audit.actorObservationPin); assertStartupActorRecord(json(audit.actorObservationPin.path), factory.archivePin.sha256);
  return { audit, state };
}
/** Writes an independent zero-forward audit only. The original failure, registry, D leaf and lock are untouched. */
export async function auditSpecificStartup() {
  const state = originalState(true), actorObservationPin = await actorEvidence(); originalState(true);
  const sourceArchives = [import.meta.path, join(import.meta.dir, "paid-resource-admission-v2.ts")].map(path => ({ sourcePath: path, archivePin: saved(join(proofHome, "sources", basename(path)), readFileSync(path)) }));
  return save(join(proofHome, "audit.json"), { protocol: "scientific-startup-zero-forward-audit-v1", runId: ZERO_STARTUP_RUN, observedAtUtc: new Date().toISOString(), state: "aborted_before_provider", snapshotPin: state.snapshotPin,
    originalLockPin: state.lockPin, actorObservationPin, sourceArchives, checkedOriginalArtifacts: 15, originalMetadataFiles: 9, physicalFiles: ["storage-owner.json"], modelCalls: 0,
    completed: false, scoreCertified: false, currentFourUnknownLiabilitiesUnchanged: true, newCalls: 0, newKnownFeeUsd: 0, newCashDispatchedCny: "0" });
}
/** Only root's explicit release command reaches this exact owned-lock removal. It never deletes D/data or fabricates score artifacts. */
export async function releaseSpecificStartup(auditPin: Pin) {
  const first = verifyAudit(auditPin, true); for (const source of first.audit.sourceArchives) demand(actualPin(source.sourcePath).sha256 === source.archivePin.sha256, "startup_release_source_changed");
  const freshActorObservationPin = await actorEvidence(); const current = verifyAudit(auditPin, true);
  for (const source of current.audit.sourceArchives) demand(actualPin(source.sourcePath).sha256 === source.archivePin.sha256, "startup_release_source_changed");
  const intent = save(join(proofHome, "release-intent.json"), { protocol: "scientific-startup-zero-forward-release-intent-v1", runId: ZERO_STARTUP_RUN, auditPin, freshActorObservationPin, originalLockPin: current.state.lockPin, observedAtUtc: new Date().toISOString() });
  originalState(true); verifyPin(current.state.lockPin); sameStartupOwner(json(current.state.lockPin.path), current.state.owner);
  for (const source of current.audit.sourceArchives) demand(actualPin(source.sourcePath).sha256 === source.archivePin.sha256, "startup_release_source_changed");
  unlinkSync(current.state.lockPin.path);
  demand(!existsSync(current.state.lockPin.path), "startup_exact_release_not_confirmed");
  return save(join(proofHome, "closure.json"), { protocol: "scientific-startup-zero-forward-closure-v1", runId: ZERO_STARTUP_RUN, auditPin, releaseIntentPin: intent, freshActorObservationPin,
    originalLockPin: current.state.lockPin, exactOriginalLockRemoved: true, observedAtUtc: new Date().toISOString(), completed: false, scoreCertified: false, state: "aborted_before_provider", oldUnknownsSettled: false });
}
/** Historical fixed-run branch: full original/audit/raw/source/intent graph is verified; a bool never skips an unfinished run. */
export function verifySpecificStartupClosure(root: string, runId: string) {
  demand(resolve(root) === ROOT && runId === ZERO_STARTUP_RUN, "startup_fixed_scope");
  const pin = actualPin(join(proofHome, "closure.json")), closure = json(pin.path);
  demand(closure.protocol === "scientific-startup-zero-forward-closure-v1" && closure.runId === ZERO_STARTUP_RUN && closure.exactOriginalLockRemoved === true && closure.completed === false && closure.scoreCertified === false && closure.oldUnknownsSettled === false, "startup_closure_profile");
  const { audit, state } = verifyAudit(closure.auditPin, false); demand(same(closure.originalLockPin, state.lockPin), "startup_closure_lock_binding");
  verifyPin(closure.releaseIntentPin); const intent = json(closure.releaseIntentPin.path);
  demand(intent.protocol === "scientific-startup-zero-forward-release-intent-v1" && intent.runId === ZERO_STARTUP_RUN && same(intent.auditPin, closure.auditPin) && same(intent.originalLockPin, state.lockPin) && same(intent.freshActorObservationPin, closure.freshActorObservationPin), "startup_release_intent_binding");
  verifyPin(closure.freshActorObservationPin); const factory = audit.sourceArchives.find((row: any) => basename(row.sourcePath) === "paid-resource-admission-v2.ts");
  assertStartupActorRecord(json(closure.freshActorObservationPin.path), factory.archivePin.sha256); return pin;
}
export async function verifyLiveScientificBooks() {
  const plan = fixedScientificPlan(ROOT, "repair-2099-01-01T00-00-00-000Z", "full", ["chembench", "aime", "cmt"]), benchmarks = [];
  for (const slug of ["chembench", "aime", "cmt"]) {
    const response = await graderFetch(`http://127.0.0.1:${SCIENCE_PORTS[slug]}/problems?n=${plan.catalogs[slug].length}&seed=0`, { signal: AbortSignal.timeout(10000) }); demand(response.ok, "live_book_http");
    const raw = Buffer.from(await response.arrayBuffer()), rows = JSON.parse(raw.toString("utf8")) as Record<string, unknown>[], byId = new Map(rows.map(row => [scientificLiveId(slug, row), row]));
    demand(rows.length === plan.catalogs[slug].length && byId.size === rows.length, "live_book_denominator");
    const comparisons = plan.catalogs[slug].map(task => { const row = byId.get(task.officialId); demand(row && digest(scientificPrompt(slug, row)) === task.promptSha256, "live_book_prompt_changed"); return { officialId: task.officialId, promptSha256: task.promptSha256 }; });
    benchmarks.push({ benchmark: slug, count: rows.length, rawResponseSha256: digest(raw), comparisons });
  }
  return save(join(ROOT, "docs/repair-2026-10-08", `scientific-live-book-helper-${Date.now()}.json`), { protocol: "scientific-live-book-helper-v1", observedAtUtc: new Date().toISOString(), validated: true, taskCount: 610, modelCalls: 0, scoringRequests: 0, benchmarks, sourcePin: actualPin(import.meta.path) });
}
if (import.meta.main) {
  const mode = process.argv[2];
  if (mode === "audit") console.log(JSON.stringify(await auditSpecificStartup()));
  else if (mode === "release") console.log(JSON.stringify(await releaseSpecificStartup(actualPin(join(proofHome, "audit.json")))));
  else if (mode === "book") console.log(JSON.stringify(await verifyLiveScientificBooks()));
  else throw new Error("Explicit audit, release or book required; no default mutation");
}
