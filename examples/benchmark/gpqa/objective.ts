/**
 * G for GPQA Diamond. **Batch launch and resume share one definition.**
 *
 * Two nodes, whose handles are the service addresses:
 *
 * ```
 *   parsed ──→ correct       parsed: can the official regex extract an A–D answer?
 *                            correct: is that letter the correct option (root)?
 * ```
 *
 * The root **must have an incoming edge** (`objective/spec.ts`: otherwise G is constant and publication is rejected). These two nodes are exactly the two steps in the official `run_baseline.py`: `parse_sampled_answer` returning None counts as a refusal and **skips comparison**; otherwise compare `LETTER_TO_INDEX[letter] == correct_index`. We introduce no new criterion, only read the official one in two stages.
 */

/**
 * **How often the box may be queried in one round.**
 *
 * There are four choices, m = 4. From N = (K+1)(c+1)+1, **c ≥ 1 and K ≥ 1 already imply N ≥ 5 ≥ m**: enumeration can reach every one of the 198 tasks, so repeated queries measure answer-space size rather than problem-solving ability. Set this to 1, and K should be 0 too (see “Answer space” in G.md).
 *
 * **Zero cannot be expressed.** `parseObjective` treats 0 as absent and replaces it with the default 5 (`objective/spec.ts`). 1 is the smallest value the kernel can express.
 */
export const CHECKS = Number(process.env.TGENGIN_GPQA_CHECKS ?? 1);

export interface Objective {
  nodes: { name: string; moment: string; domain: string; handle: string }[];
  edges: { src: string; out: number; dst: string }[];
  sink: string;
  checks: number;
}

export function objectiveOf(stand: string, checks = CHECKS): Objective {
  return {
    nodes: [
      { name: "parsed", moment: "task_done", domain: "bool", handle: `${stand}/parsed` },
      { name: "correct", moment: "task_done", domain: "bool", handle: `${stand}/correct` },
    ],
    edges: [{ src: "parsed", out: 0, dst: "correct" }],
    sink: "correct",
    checks,
  };
}
