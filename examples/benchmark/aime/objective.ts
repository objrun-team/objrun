/**
 * G for this benchmark. **Batch submission and resumed runs share this one definition.**
 *
 * Two nodes; their handles are the grader URLs:
 *
 * ```
 *   parsed ──→ correct       parsed: can the submission be parsed as an integer in 0–999?
 *                            correct: does it equal the official answer? (root)
 * ```
 *
 * The root **must have an incoming edge**. Otherwise it is independent of the candidate and G is constant, which is an invalid objective rejected at publication (`objective/spec.ts`).
 *
 * These nodes are exactly the two parts of AIME's own rule: the answer must be an integer in 0–999 (the answer sheet accepts three digits), and then it must match. We split the official criterion into two readable stages rather than defining a different one.
 */

/**
 * **Maximum queries to this black box per attempt.**
 *
 * Grading takes milliseconds, so the issue is meaning rather than cost. The answer space has m = 1000 elements. Binary feedback rules out only one number per query; c queries plus final submission give blind guessing a success rate of (c+1)/1000. With 10 queries this is 1.1%, while allowing two or three computed candidates to be tried.
 *
 * The full budget N = (K+1)(c+1)+1 = 100 < 1000, so no problem is enumeration-reachable (see G.md).
 */
export const CHECKS = Number(process.env.TGENGIN_AIME_CHECKS ?? 10);

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
