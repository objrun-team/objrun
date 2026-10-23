/** Filter-only fresh-campaign result mapping (post-command executeFor branch).
 *
 * The shared runner cb1264e7 must stay byte-identical for the other tasks. The current
 * source tree no longer reproduces it (financial-policy-source.ts drifted from
 * sha 55b3022c…/9766B to d28044a9…/14131B), so this transform is applied to the pinned
 * cb1264e7 bundle. That keeps the diff to this one post-command segment and avoids
 * silently importing a newer financial transform. A future full source rebuild can use
 * the same anchors once the financial transform is pinned back.
 */
export const FRESH_RESULT_FUNCTION = `async function freshCampaignResult(bench, m, c, custody) {
  const output = expand("{{bindings.OUTPUT}}", c);
  const outcomePath = join12(c.runDir, "driver-campaign-outcome.json");
  requireTrue(existsSync12(outcomePath), "driver_campaign_outcome_required");
  const outcome = JSON.parse(readFileSync19(outcomePath, "utf8"));
  requireTrue(outcome.protocol === "bench-qualified-campaign-outcome-v1" && outcome.taskId === m.taskId && outcome.bench === bench && outcome.attemptId === c.attemptId, "driver_campaign_outcome_identity");
  requireTrue(outcome.segmentComplete === true && !outcome.fatal && outcome.originalVerdictUnchanged === true, "driver_campaign_segment_not_complete");
  const summary = readPinned(outcome.summaryPin);
  requireTrue(summary.runId === outcome.runId && summary.segmentComplete === true && !summary.fatal, "fresh_summary_not_complete");
  requireTrue(JSON.stringify(summary.financialClose?.cashClose) === JSON.stringify(outcome.cashClosePin), "fresh_summary_cash_join");
  financeClosed(outcome.cashClosePin, outcome.runId, m.original.taskCapUsd);
  const nativePath = join12(output, "provider-native-close.json");
  requireTrue(existsSync12(nativePath), "fresh_provider_native_close_required");
  const native = JSON.parse(readFileSync19(nativePath, "utf8"));
  requireTrue(native.protocol === "tb12-provider-native-close-v1" && native.runId === outcome.runId && native.serverClosed === true && native.pendingCount === 0 && native.tokenExcluded === true, "fresh_provider_native_close_not_proven");
  requireTrue(summary.standClose, "fresh_stand_close_required");
  const stand = readPinned(summary.standClose);
  requireTrue(stand.exitObserved === true && stand.closeObserved === true && Number.isInteger(stand.exitCode), "fresh_stand_close_not_proven");
  const engines = summary.engineClosures ?? [];
  requireTrue(engines.length > 0, "fresh_engine_closures_required");
  for (const p of engines) {
    const e = readPinned(p);
    requireTrue(e.exitObserved === true && e.closeObserved === true, "fresh_engine_close_not_proven");
  }
  const taskPins = summary.taskPins ?? [];
  requireTrue(taskPins.length === 1, "fresh_single_task_result_required");
  const task = readPinned(taskPins[0]);
  requireTrue((task.officialId ?? task.taskId) === m.taskId && task.generationValid === true && task.acceptance?.valid === true && typeof task.acceptance.passed === "boolean", "fresh_generation_and_acceptance_required");
  const proofPins = [filePin(outcomePath), outcome.summaryPin, outcome.cashClosePin, filePin(nativePath), summary.standClose, ...engines, ...taskPins, ...custody];
  for (const p of proofPins) checkPin(p);
  const candidateOrSubmissionPresent = task.acceptance.outcome !== "budget_exhausted";
  if (task.acceptance.passed === true)
    return { status: "valid", proofPins, nativeClosed: true, financialClosed: true, candidateOrSubmissionPresent, validResult: { passed: true, outcome: "passed", proofPin: taskPins[0] }, reason: "fresh_campaign_verified_native_and_cash_closed" };
  return { status: "complete", proofPins, nativeClosed: true, financialClosed: true, candidateOrSubmissionPresent, reason: "fresh_campaign_valid_but_not_passed" };
}
`;

export function applyFilterFreshResultToBundle(source: string): string {
  let s = source;
  const once = (a: string, b: string, tag: string) => {
    if (s.split(a).length !== 2) throw Error("filter_fresh_result_anchor_not_unique:" + tag);
    s = s.replace(a, b);
  };
  // 1) Only the non-empty original-results mapping may enter recoverFor.
  once(
    'if (Array.isArray(m.adapterConfig.originalResultsPaths)) {',
    'if (Array.isArray(m.adapterConfig.originalResultsPaths) && m.adapterConfig.originalResultsPaths.length > 0) {',
    'guard_recover'
  );
  // 2) Absent/empty mapping: map the fresh qualified campaign instead of failing mapping.
  once(
    '  const config = m.adapterConfig.driverResult;',
    '  if (!Array.isArray(m.adapterConfig.originalResultsPaths) || m.adapterConfig.originalResultsPaths.length === 0)\n' +
      '    return await freshCampaignResult(bench, m, c, custody);\n' +
      '  const config = m.adapterConfig.driverResult;',
    'insert_branch'
  );
  // 3) Inject the mapper next to recoverFor.
  once(
    'async function recoverFor(bench, m, c) {',
    FRESH_RESULT_FUNCTION + 'async function recoverFor(bench, m, c) {',
    'insert_function'
  );
  return s;
}
