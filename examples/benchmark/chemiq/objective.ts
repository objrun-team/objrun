/**
 * ChemIQ's G. **Batch submissions and resumed runs share one definition.**
 *
 * Two nodes whose handles are the grader URLs:
 *
 * ```
 *   parsed ──→ correct      parsed: can official AnswerParser extract an answer?
 *                           correct: does official AnswerVerifier.check_answer accept it? (root)
 * ```
 *
 * The root **must have an incoming edge**; otherwise it is independent of the candidate and G is constant, so publication rejects it (`objective/spec.ts`).
 *
 * These are the two steps in official `analysis.ipynb`: `parser.parse(uuid, raw)` followed by `verifier.check_answer(uuid, parsed)`. Upstream represents failed extraction as False and rejects it. We expose the official steps separately rather than inventing another criterion.
 *
 * Grading returns bool and statements request short answers, so this G is as small as CMT's.
 */

/** **Maximum queries per attempt.** There are 226 integer questions (carbon counts 3–27, ring counts 1–6, shortest paths 3–20). With enough queries, success measures the small answer space rather than counting ability. Allow 3: enough to answer, check, revise from the note, and check again, but not enumerate 1–27. See the budget section in G.md. */
export const CHECKS = Number(process.env.TGENGIN_CHEMIQ_CHECKS ?? 3);

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
