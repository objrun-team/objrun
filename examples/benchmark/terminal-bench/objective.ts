/**
 * G for this benchmark. **Batch launch and resume share one definition.**
 *
 * Two nodes, whose handles are the service addresses:
 *
 * ```
 *   ran ──→ passed      ran: official tests/test.sh completed inside the container and wrote a readable reward
 *                       passed: reward == 1 (root)
 * ```
 *
 * The root **must have an incoming edge**; otherwise its value is independent of the candidate, making G constant, and publication rejects it (`objective/spec.ts`).
 *
 * These are exactly the official grader’s two stages: harbor runs `test.sh`, then reads `/logs/verifier/reward.txt` with `_parse_reward_text`. An unreadable reward (missing, empty, nonnumeric) is one failure; a readable 0 is another. We introduce no new criterion, only read the official one in two stages. In deepswe these are called applies → resolved.
 *
 * Unlike deepswe, **the candidate is the container itself, not a patch**. The solver’s submitted string only names this candidate, associating both nodes with one grading run; its content does not affect the decision.
 */

/**
 * **How often the box may be queried in one round.**
 *
 * One grading call runs test.sh inside the live container: install uv, run pytest, taking tens of seconds to minutes, with official limits of 900–12000 seconds. **Each grading call also modifies the container** (test.sh runs apt-get), and hidden tests are visible in the solver’s filesystem for tens of seconds. Set this one step tighter than deepswe’s 6.
 *
 * Allow 4: enough for two cycles of creating a version → verifying → revising from note → verifying again.
 */
export const CHECKS = Number(process.env.TGENGIN_TB_CHECKS ?? 4);

export interface Objective {
  nodes: { name: string; moment: string; domain: string; handle: string }[];
  edges: { src: string; out: number; dst: string }[];
  sink: string;
  checks: number;
}

export function objectiveOf(stand: string, checks = CHECKS): Objective {
  return {
    nodes: [
      { name: "ran", moment: "task_done", domain: "bool", handle: `${stand}/ran` },
      { name: "passed", moment: "task_done", domain: "bool", handle: `${stand}/passed` },
    ],
    edges: [{ src: "ran", out: 0, dst: "passed" }],
    sink: "passed",
    checks,
  };
}
