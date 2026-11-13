/**
 * G for SkillsBench 1.1. **Batch launch and resume share one definition.**
 *
 * Two nodes, whose handles are the service addresses:
 *
 * ```
 *   verified ──→ passed      verified: official verifier/test.sh completed and wrote reward.txt
 *                           passed: reward == 1.0 (root)
 * ```
 *
 * The root **must have an incoming edge**; otherwise its value is independent of the candidate, making G constant, and publication rejects it (`objective/spec.ts`).
 *
 * These nodes are exactly the official harness’s two steps: run `test.sh`, then read `/logs/verifier/reward.txt`. A missing file (crash, timeout, OOM) and a written 0 both score 0 on the leaderboard, but convey different information to a solver: the former is usually an environment issue, not an answer issue. We introduce no new criterion, only read the official one in two stages.
 *
 * **The criterion is binary.** The paper defines reward = 1 iff every test_outputs.py assertion passes. Seven tasks’ test.sh scripts write fractional rewards (47/48 = 0.979); leaderboard `mean(reward)` grants partial credit, but this service accepts only 1.0. This matches the paper and is slightly stricter than the leaderboard on those seven tasks. Store the fractional reward in `note` so the leaderboard metric can be calculated afterward.
 */

/**
 * **How often the box may be queried in one round.**
 *
 * One grading call runs pytest (tens of seconds to minutes; the official `verifier.timeout_sec` median is 1800 seconds). This limit concerns meaning, not cost: allow 6, enough for three cycles of creating a version → verifying → revising from note → verifying again, but not exhaustive search. The artifact is a whole file, so enumeration is not practical anyway.
 */
export const CHECKS = Number(process.env.TGENGIN_SKB_CHECKS ?? 6);

export interface Objective {
  nodes: { name: string; moment: string; domain: string; handle: string }[];
  edges: { src: string; out: number; dst: string }[];
  sink: string;
  checks: number;
}

export function objectiveOf(stand: string, checks = CHECKS): Objective {
  return {
    nodes: [
      { name: "verified", moment: "task_done", domain: "bool", handle: `${stand}/verified` },
      { name: "passed", moment: "task_done", domain: "bool", handle: `${stand}/passed` },
    ],
    edges: [{ src: "verified", out: 0, dst: "passed" }],
    sink: "passed",
    checks,
  };
}
