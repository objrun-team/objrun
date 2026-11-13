/**
 * `verify`: **let the model query G itself**.
 *
 * ## Why this must be an actual tool
 *
 * After a node is marked dead, `deliverVerdict` in `msg/deliver.ts` injects its verdict as a
 * tool call and result named `verify`. Originally no such tool was registered: context said
 * "I called verify" in an assistant row, but an actual call failed because verify was absent
 * from the tool table. **An apparent tool that cannot be called fabricates the model's trajectory.**
 * Registering it makes the recorded interaction real.
 *
 * ## Exposing the objective is not leaking the answer
 *
 * Only **ground truth** must remain hidden. Knowing acceptance criteria and whether a candidate
 * meets them is part of doing the task. Hiding this can cause unnoticed formatting failures:
 * in one observed set, two of five tasks failed at `parsed=False` because their formats did
 * not satisfy the official parser, rather than because the model could not solve them.
 *
 * Return `{pass, why}`: **whether the candidate passed and why it failed**. Do not return
 * per-node `trace` or the dataset answer; the grader never exposes `solution`.
 *
 * ## Limits are a budget concern, not a secrecy mechanism
 *
 * Unlimited checks would become best-of-N with a perfect oracle, but this is a **budget** issue.
 * `max_branches` / `max_dead_siblings` / `solve_seconds` provide the relevant bounds.
 * Hiding the grader cannot meaningfully enforce a limit when verdicts already arrive every round.
 *
 * ## Availability depends on whether the task has G
 *
 * Do not restrict by mode, unlike the two `task_tree` tools whose meaning depends on a tree.
 * **A task with G should be able to query G**, including in a linear mode. Use the shared
 * `trigger` table, with `task.objective = 'sealed'`.
 */

import type { Conn } from "../H2H/db.ts";
import { CANDIDATE } from "./store.ts";
import { SUBMIT } from "../tree/dfs.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { whereAmI } from "../tasks/where.ts";
import { tableNameOf } from "../install/index.ts";
import { declareTool } from "../tools/register.ts";
import { candidateInput, evaluate } from "./run.ts";
import type { Sealed } from "./store.ts";

const VERIFY_TOOL = {
  name: "verify",
  does:
    "Check one candidate answer against the bar for this task. Says whether it meets the bar and, when it does " +
    "not, what is wrong with it. It does not return the correct answer.",
  params: CANDIDATE,
  output: {
    type: "object",
    properties: {
      pass: { type: "integer", description: "1 = meets the bar, 0 = does not" },
      valid: { type: "boolean", description: "Whether the grader completed successfully. An unavailable grader is not an incorrect answer." },
      outcome: { type: "string", description: "passed, rejected, or grader_error" },
      why: { type: "string", description: "What is wrong with it. Empty when it passed." },
      note: { type: "string", description: "Whatever the bar itself had to add about this answer. Empty when it passed, and empty when the bar has nothing to add." },
      graded: { type: "string", description: "The exact text this verdict is about. If it passed, hand in this text unchanged." },
      left: { type: "integer", description: "How many checks remain in this attempt" },
    },
  },
  prompt:
    "The number of checks per attempt is fixed before the attempt starts; every completed grading decision spends one, pass or fail. Grader errors do not spend a check. " +
    "`left` says how many remain. A verdict applies to the exact text echoed back in `graded` and to nothing else.",
  expectMs: 120_000,
};

/** Register `verify`. `sealed` stores G definitions outside the reach of the fully exposed main database API. */
export function registerVerifyTool(db: Conn, reg: Registry, sealed: Sealed): string {
  reg.register(db, `fn:tool.${VERIFY_TOOL.name}`, VERIFY_TOOL.expectMs, async (arg) => {
    const a = (arg ?? {}) as { args?: { answer?: unknown }; instance?: string; agent?: string; unit?: number };
    const answer = String(a.args?.answer ?? "");
    if (!answer.trim()) return { error: "answer is required - an empty one cannot be graded" };

    // Resolve the task **from the database**, not caller arguments. Otherwise a model could change
    // one parameter and use another task's G to query its own candidate.
    const at = whereAmI(db, String(a.instance));
    if (!at) return { error: `cannot tell which task ${String(a.instance)} belongs to` };
    if (!sealed.has(at.task)) return { error: `${at.task} has no grading function, nothing to check against` };

    const g = sealed.open(at.task)!;
    const task = all(db, `select * from task where id = ?`, [at.task])[0] as Record<string, unknown> | undefined;

    // ── Per-attempt verification allowance ──
    //
    // **Without a limit, enumerating the answer space is the easiest strategy.** An observed
    // multiple-choice task tried 77 combinations (`b;a` / `c;d` / `b;c;d` / `b;a;c;d` …) without
    // reasoning. That measures answer-space size rather than problem-solving ability.
    //
    // An **execution-unit limit cannot prevent this**: a single request can contain many tool calls,
    // so twenty checks in one unit cost the same unit budget as one. Count queries to G instead.
    //
    // The **publisher** chooses the limit (`task.max_checks`). A round is one node; a retry starts
    // a new attempt with a fresh allowance. **Final submission is excluded** because the kernel
    // requests it and records `graded`, rather than an agent-initiated `call`.
    // **The allowance belongs to G, not the task**: otherwise another publisher could assign
    // 100 checks to the same G and bypass the intended boundary.
    const here = numberOf(sealed.checksOf(at.task), 5);
    const spent = checksIn(db, {
      sub: at.sub,
      task: at.task,
      agent: String(a.agent ?? ""),
      instance: String(a.instance ?? ""),
      unit: Number(a.unit ?? 0),
    });
    if (spent >= here) {
      return {
        error:
          `the ${String(here)} checks for this attempt are spent. A check is for finding the mistake in your ` +
          `reasoning, not for trying answers one after another - work out what the last verdict told you, and ` +
          `hand in what you get. What you hand in is graded either way.`,
        left: 0,
      };
    }

    // Use the same input structure as `tree/dfs.ts`. The same G and handles must receive the same
    // input regardless of who requested the check.
    const v = await evaluate(g, reg, candidateInput(task ?? {}, answer));
    if (!v.valid) return { valid: false, outcome: "grader_error", error: v.why || "the grader did not complete", graded: answer, left: here - spent };
    // **Identify the graded candidate in the receipt.** A bare 1 becomes ambiguous after several
    // iterations. A model once verified an equiv=True answer, then submitted a different one;
    // its `{pass:1, why:""}` record did not identify which candidate had passed.
    //
    // Continue withholding per-node `trace`, which is for internal diagnostics.
    return { pass: v.pass, valid: v.valid, outcome: v.outcome, why: v.why, note: v.note, graded: answer, left: here - spent - 1 };
  });
  // **Use the same persistence path.** This previously duplicated an upsert and two trigger
  // inserts from `register.ts`, and had already drifted: one updated `concurrent`, the other did
  // not. Both paths now call `declareTool`.
  declareTool(db, {
    ...VERIFY_TOOL,
    concurrent: false,
    // **Verdicts cannot simply be recovered.** Rechecking G costs 3–97 seconds, measured on one
    // problem in each of five languages, and consumes this attempt's allowance. During context
    // compression, treat it like a test run that took four minutes.
    gives: "event",
    // Two conditions in one group mean AND: **the task has G and this is not the submission station**.
    //
    // The first permits any task with G to query it, including linear modes.
    //
    // The second matters because only action stations execute tools (`api_mode` empty, using
    // `agent.unit`). Submission is a model station followed by another model station, so tool
    // calls requested there have no executor. They remain pending until completion repair writes
    // a failure result. In practice, a model called `submit` there and received a failure message.
    // Submission itself does not require tool execution; the submitted candidate is its text.
    when: [
      [
        { dim: "task", key: "objective", op: "eq", value: "sealed" },
        { dim: "cycle", key: "cycle", op: "ne", value: SUBMIT },
      ],
    ],
  });
  return VERIFY_TOOL.name;
}

function numberOf(v: unknown, fallback: number): number {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

/**
 * Number of verification checks **consumed** in this attempt. **One attempt is one node.**
 *
 * Count **received verdicts**, not requested calls:
 *
 * - Multiple calls can share one message row. Counting requests would let the first call see
 *   five requests already present and reject all five, despite no checks having been used.
 * - Blocked checks **must not consume allowance**, since they reveal nothing about a candidate.
 *
 * Tool results are recorded individually, making verdict counts correct naturally: early
 * calls receive verdicts; later ones observe the exhausted allowance. Blocked calls produce
 * no verdict and consume nothing.
 *
 * **Exclude final submission**, which the kernel requests with a `g-` id and records as a
 * `graded` pair, rather than an agent-requested verification.
 *
 * Modes without a node column count the entire instance, because they have only one attempt.
 */
function checksIn(db: Conn, at: { sub: string; task: string; agent: string; instance: string; unit: number }): number {
  const sub = at.sub;
  if (!at.agent || !at.instance) return 0;

  let units: number[] = [];
  try {
    const me = all(db, `select node from "${sub}" where task = ? and unit = ?`, [at.task, at.unit])[0] as
      | { node?: number }
      | undefined;
    const rows =
      me?.node === undefined || me.node === null
        ? (all(db, `select unit from "${sub}" where task = ?`, [at.task]) as { unit: number }[])
        : (all(db, `select unit from "${sub}" where task = ? and node = ?`, [at.task, me.node]) as { unit: number }[]);
    units = rows.map((r) => Number(r.unit));
  } catch {
    return 0; // If the table has not been created, no checks have been used.
  }
  if (units.length === 0) return 0;

  const t = tableNameOf("agent_{}_msg", at.agent);
  const rows = all(
    db,
    `select body from "${t}" where instance = ? and kind = 'tool' and unit in (${units.map(() => "?").join(", ")})`,
    [at.instance, ...units],
  ) as { body: string }[];

  let n = 0;
  for (const r of rows) {
    try {
      const v = JSON.parse(r.body) as { id?: string; name?: string; value?: { pass?: unknown; valid?: unknown; outcome?: unknown } };
      if (v.name !== VERIFY_TOOL.name) continue;
      if (String(v.id ?? "").startsWith("g-")) continue; // Final submission check.
      if (v.value?.valid === false || v.value?.outcome === "grader_error") continue;
      if (v.value?.pass !== 0 && v.value?.pass !== 1) continue;
      n++;
    } catch {
      // Do not count unreadable rows.
    }
  }
  return n;
}
