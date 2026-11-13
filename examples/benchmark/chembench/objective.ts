/**
 * ChemBench's G. **Batch submissions and resumed runs share one definition.**
 *
 * Two nodes whose handles are the grader URLs:
 *
 * ```
 *   parsed ──→ correct      parsed: can the official parser extract an answer?
 *                           correct: does the official criterion mark it entirely correct? (root)
 * ```
 *
 * The root **must have an incoming edge**. Otherwise its value is independent of the candidate and G is constant, an invalid objective rejected at publication (`objective/spec.ts`).
 *
 * The nodes are exactly the two stages in the official pipeline (`prompter.BasePrompter._process_single_result`): extract with `prepare_mcq_answer` / `prepare_general_answer`, then use `_calculate_metrics` to compute `all_correct`. We split the official criterion into readable stages without creating a different criterion.
 *
 * The service (`stand.py`) does not use an LLM fallback when parsing fails. That nondeterministic fallback awards credit for answers outside the required format; it is not included. A `parsed` failure note explains the required format.
 */

/**
 * **Maximum queries to this black box per attempt.**
 *
 * A regex and floating-point comparison take milliseconds; the issue is meaning rather than cost. ChemBench has very small answer spaces: of 2542 choice questions, 1013 have two options and 898 have one correct choice among four.
 * A query eliminates one option. **Allow 1**: enough to answer, check, revise from the note, and submit; more queries become enumeration. Even so, four options can be exhausted within (K+1)(c+1)+1 = 7 opportunities. This is a property of the questions, which this setting cannot fix (see the answer-space m section of G.md).
 */
export const CHECKS = Number(process.env.TGENGIN_CHB_CHECKS ?? 1);

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
