/**
 * G for this benchmark. **Batch submissions and resumed runs share one definition.**
 *
 * ```
 *   applies ──→ resolved      applies: does the submitted patch apply?
 *                             resolved: does the official criterion report success? (root)
 * ```
 *
 * Handles are grader URLs. The root **must have an incoming edge**; otherwise it is candidate-independent, making G constant and invalid at publication (`objective/spec.ts`).
 *
 * These are the official grader's stages: an inapplicable patch sets `apply_failed=1` and **skips tests**; an applicable patch runs both existing and added tests. We split the official criterion into stages without replacing it.
 *
 * This definition has its own file because send.ts starts runs and resume.ts continues timed-out tasks. Duplicate definitions could silently drift, making the runs solve different problems. It cannot be recovered from the ordinary database row because G is sealed outside API access (`tasks/publish.ts`).
 */

/**
 * **Queries to this black box per attempt.** Observed grading times were 3–97 seconds across one problem in each of five languages, far below the official 1800-second limit. **The query count concerns meaning rather than cost**: it determines whether success reflects reasoning or trial and error.
 *
 * Allow 6, enough for three implement/check/revise-from-note/check cycles.
 */
export const CHECKS = Number(process.env.TGENGIN_DSW_CHECKS ?? 6);

export interface Objective {
  nodes: { name: string; moment: string; domain: string; handle: string }[];
  edges: { src: string; out: number; dst: string }[];
  sink: string;
  checks: number;
}

export function objectiveOf(stand: string, checks = CHECKS): Objective {
  return {
    nodes: [
      { name: "applies", moment: "task_done", domain: "bool", handle: `${stand}/applies` },
      { name: "resolved", moment: "task_done", domain: "bool", handle: `${stand}/resolved` },
    ],
    edges: [{ src: "applies", out: 0, dst: "resolved" }],
    sink: "resolved",
    checks,
  };
}
