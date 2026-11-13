/**
 * Build a batch of G-bearing tasks from `cmt_data.jsonl` and submit it to `POST /bench`.
 *
 * ```
 * bun examples/benchmark/cmt/send.ts [count] [run-name]
 * ```
 *
 * Issuing 50 curl commands in documentation is impractical. **This script only assembles request bodies**; the README includes complete examples of a task and G.
 *
 * Put the statement in `description`, **never `solution`**: the agent side must not see the answer.
 */

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
/** When api.publisherToken is configured, attaching grading criteria requires this key (X-TGEngin-Publisher). Read it from the environment; if unset, use an empty object to preserve existing behavior. */
const PUBLISHER: Record<string, string> = process.env.TGENGIN_PUBLISHER_TOKEN ? { "x-tgengin-publisher": process.env.TGENGIN_PUBLISHER_TOKEN } : {};
const GRADER = process.env.TGENGIN_CMT_GRADER ?? "http://127.0.0.1:7901";
const HOW_MANY = Number(process.argv[2] ?? 0);
const RUN = process.argv[3] ?? `cmt-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}`;

/** Problem statement exposed by the grader. **No `solution`**; that field remains inside the grading process. */
interface Item {
  index: number;
  prompt: string;
  parameters: string;
  functions: string;
  type: string;
}

// **Fetch problems from the grader, not disk.**
//
// The corpus and answers are installed on the grader side (setup.sh). This script runs on the engine machine and cannot read that path, as intended: a solver with read/glob/bash would find a local corpus immediately, and an observed run had already reached it.
//
// Fetch through HTTP: `/problems` returns statements and no `solution` content.
const res0 = await fetch(`${GRADER}/problems${HOW_MANY > 0 ? `?n=${HOW_MANY}` : ""}`);
if (!res0.ok) {
  console.error(`cannot fetch problems from the grader (${GRADER}/problems): ${res0.status}`);
  process.exit(1);
}
let items = (await res0.json()) as Item[];

// **Submit only named problems; empty means all.**
//
// Use this to reproduce the unfinished problems from an earlier run: their corpus indexes may be scattered, so selecting the first N is insufficient.
// **Remove empty entries before converting to numbers.** Otherwise `"".split(",")` is `[""]`, `Number("")` is `0`, and 0 is a valid problem index. An empty selection then becomes only problem 0; this caused a real unintended submission.
const ONLY = (process.env.TGENGIN_CMT_ONLY ?? "")
  .split(",")
  .map((x) => x.trim())
  .filter((x) => x !== "")
  .map((x) => Number(x))
  .filter((n) => Number.isInteger(n) && n >= 0);
if (ONLY.length) {
  items = items.filter((it) => ONLY.includes(it.index));
  if (items.length !== ONLY.length) {
    console.error(`asked for ${String(ONLY.length)} problems, the grader has ${String(items.length)} of them`);
    process.exit(1);
  }
}

/**
 * Per-problem G has two nodes, with **grader URLs as handles**:
 *
 * ```
 *   parsed ──→ equiv       parsed: was an answer supplied in \boxed{}?
 *                          equiv: is it equivalent to GT? (root)
 * ```
 *
 * The root **must have an incoming edge**; without one it is candidate-independent, making G constant and invalid at publication. These nodes are the original benchmark's own `parse`/`equiv` results.
 */
const objective = {
  nodes: [
    { name: "parsed", moment: "task_done", domain: "bool", handle: `${GRADER}/parsed` },
    { name: "equiv", moment: "task_done", domain: "bool", handle: `${GRADER}/equiv` },
  ],
  edges: [{ src: "parsed", out: 0, dst: "equiv" }],
  sink: "equiv",
  // **Black-box queries per attempt.** Match this to the work budget: with 20 work units, 10 queries comfortably allow repeated compute/check/revise-from-why/check cycles.
  //
  // The existence of a limit matters most. Otherwise enumerating answers is the easiest strategy: one observed problem tried 77 permutations without reasoning. That measures answer-space size rather than solving ability.
  checks: Number(process.env.TGENGIN_CMT_CHECKS ?? 10),
};

/**
 * **Arm U: no G attached.** The unaided arm preregistered in report 1 §6 uses the same problems, solver, and descriptions, but no verification function. Submission ends the task without verdicts or retries, giving pass@1.
 *
 * Descriptions must be **byte-identical** (Appendix A, B3). With `readable: true`, publication appends `## Acceptance criteria` and G JSON. Publication does not do that for tasks without G, so this sender appends the same text itself. After completion, `grade-unaided.ts` submits the saved answer to the grader.
 */
const UNAIDED = process.env.TGENGIN_CMT_UNAIDED === "1";
/** Provider key and model. Defaults match the baseline; override here when arm U uses the 0731 model through OpenRouter. */
const BOT_APIS = process.env.TGENGIN_CMT_BOT_APIS;

const tasks = items.map((it) => ({
  id: `cmt-${it.index}`,
  mode: "solve",
  agent: "bot",
  place: "local",
  source: "user",
  // Problem category. **Extensions dispatch on this**, independently of `mode` (the reasoning mechanism).
  // Keep the value flat; express tighter conditions across dimensions in `when` instead of encoding a hierarchy in it.
  domain: "physics",
  // **Per-problem time limit.** Override through the environment; default is one hour.
  //
  // It must exceed one call's timeout, not equal it. The model handle has `expect_ms` of 15 minutes; simultaneous deadlines let the task timeout win, preventing the stalled-call -> dead-station -> new-node retry path. One transient delay would end the whole task.
  //
  // Even one hour was insufficient in observed slow problems: reaching station 7 used only 4 of 12 budget units before time expired. They never reached submission, so not even a wrong answer was handed in.
  solveSeconds: Number(process.env.TGENGIN_CMT_SECONDS ?? 3600),
  // **Let time be the only binding constraint.** Provide enough units, branches, and retries that termination means time expired rather than work units exhausted. The first exhausted budget determines what the score measures, and we intend to measure the former.
  maxBranches: 4,
  maxDeadSiblings: Number(process.env.TGENGIN_CMT_K ?? 8),
  /**
   * **Searches allowed per round.** Here a round is one station; restarting after a dead attempt gets a fresh allowance. Blocked or over-limit searches do not count.
   *
   * This value was measured, not guessed. In the previous run (same medium reasoning, same one-hour limit, **this field unset**), time was distributed as follows:
   *
   * | Activity | Share |
   * | --- | --- |
   * | Model calls | 60% (462 × 107 s) |
   * | **Waiting for search** | **39%** (230 × 138 s) |
   * | Other tools | 1% (198 × 5 s) |
   *
   * Mean searches per problem were 16, maximum 34: **23 minutes of an hour went to waiting for search**. No problem hit its work-unit cap; wall time was binding. Search cost more time than a reasoning call (138 s versus 107 s), so each avoided search directly permits another reasoning call.
   *
   * Allow 5: enough to find a paper, follow a reference, and look up a definition, but not repeatedly browse one direction.
   */
  maxSearches: 5,
  /**
   * **Do not retrieve this benchmark's own answer set.**
   *
   * Finding a paper containing the relevant physics, understanding it, and deriving an answer is legitimate solving. Retrieving **the benchmark answer book** instead measures how easy the dataset is to scrape.
   *
   * This happened in practice: of 834 pages opened in 15 minutes, **143 were dataset pages**, reached systematically:
   *
   * ```
   * huggingface.co/datasets/…/resolve/main/cmt_data.jsonl    Primary host
   * hf-mirror.com/…/raw/main/cmt_data.jsonl                  Mirror when the primary fails
   * r.jina.ai/https://…/cmt_data.jsonl                       Text proxy when the mirror fails
   * web.archive.org/web/…/rows?…&offset=1&length=1            Archive as the next fallback
   * ```
   *
   * Queries explicitly included `cmt_benchmark row 1 answer` and `"cmt_benchmark" "answer": "$\Delta"`; the model even reverse-searched the original answer text. It succeeded, leaving "The web search found the reference answer" in the trace.
   *
   * **Domain blocking is insufficient**: every fallback needs its own entry, and future ones cannot all be enumerated.
   *
   * ## Match separate words, with more than one rule
   *
   * The joined token `cmt_benchmark` misses copies such as `Infektyd/syntra-evals-dataset/…/cmt-physics.jsonl`, encountered in that same run under a different name.
   * Each entry is therefore **a group of words that must all appear** (`tripped` in `tools/search.ts`), irrespective of separators, hyphens/underscores, or order.
   *
   * Why not just `"cmt benchmark"`? Testing the 168 real searches gave:
   *
   * | Rule | Misses | False positives |
   * | --- | --- | --- |
   * | `cmt benchmark` | **5** | 0 |
   * | `cmt` | 0 | **1** |
   * | The three rules below | **0** | **0** |
   *
   * The five misses fetched raw JSONL directly: results contained cmt but not benchmark. Using cmt alone blocked legitimate literature. The three rules cover distinct phrasings at little cost; omitting one leaves that hole open.
   */
  noSearch: ["cmt benchmark", "cmt dataset", "cmt jsonl"],
  description:
    `${it.prompt}\n\n` +
    (it.parameters ? `Symbols: ${it.parameters}\n` : "") +
    (it.functions ? `Functions: ${it.functions}\n` : "") +
    `\nPut the final answer inside \\boxed{}.` +
    (UNAIDED ? `\n\n## Acceptance criteria\n${JSON.stringify(objective, null, 2)}` : ""),
  ...(UNAIDED ? {} : { objective }),
  // When attaching G, explicitly declare whether the agent may read its definition.
  //
  // **Set true.** Hide only GT, not acceptance criteria. The solver should know that its answer belongs in \boxed{} and must be readable by the official parser. In the hidden-criteria run, two of five problems failed with parsed=False because the format was unknown, not because the problems were unsolvable.
  ...(UNAIDED ? {} : { readable: true }),
}));
if (UNAIDED) console.log(`${RUN}: UNAIDED arm - no objective mounted, descriptions carry the same acceptance text`);
void BOT_APIS;

/**
 * **Concurrent problems.** 0 preserves the old behavior of submitting the whole batch without a cap.
 *
 * The kernel dispatches every unsent row immediately. Concurrency must therefore be controlled by the sender: unfinished tasks in the database correspond to active tasks on the machine.
 *
 * Submitting 50 problems creates 50 concurrent calls to one provider, which queues rather than rejects them. At concurrency 20, observed median call time reached 1.5 minutes with a ten-minute tail. **Latency increased without a throughput increase**, exhausting per-task wall-time budgets.
 *
 * Maintain **20 concurrent problems, not batches of 20**: replace each completed task immediately instead of letting the slowest task hold up a whole batch.
 */
const AT_ONCE = Number(process.env.TGENGIN_CMT_AT_ONCE ?? 0);

/** Current unfinished task count for this run: not yet started plus running. */
async function busy(): Promise<number> {
  const r = await fetch(`${BASE}/bench/${RUN}`);
  if (!r.ok) return 0;
  const j = (await r.json()) as { running?: number; open?: number };
  return Number(j.running ?? 0) + Number(j.open ?? 0);
}

if (AT_ONCE > 0) {
  // Submit tasks individually after checking for a free slot. Admission through `POST /tasks` validates each problem and rejects its invalid G, so splitting a batch weakens no rule.
  console.log(`${RUN}: ${tasks.length} tasks, keeping ${AT_ONCE} of them in flight`);
  let sent = 0;
  for (const t of tasks) {
    while ((await busy()) >= AT_ONCE) await Bun.sleep(5000);
    const r = await fetch(`${BASE}/tasks`, {
      method: "POST",
      headers: { "content-type": "application/json", ...PUBLISHER },
      body: JSON.stringify({ ...t, run: RUN }),
    });
    if (!r.ok) {
      const e = (await r.json()) as { error?: string };
      console.error(`${t.id} was refused: ${e.error}`);
      process.exit(1);
    }
    sent++;
    if (sent % 5 === 0 || sent === tasks.length) console.log(`  sent ${sent}/${tasks.length}`);
  }
  console.log(`${RUN}: all ${tasks.length} sent`);
} else {
  const res = await fetch(`${BASE}/bench`, {
    method: "POST",
    headers: { "content-type": "application/json", ...PUBLISHER },
    body: JSON.stringify({ run: RUN, tasks }),
  });
  const got = (await res.json()) as { run?: string; ids?: string[]; error?: string };
  if (!res.ok) {
    console.error(`the whole batch was not sent: ${got.error}`);
    process.exit(1);
  }
  console.log(`${got.run}: ${got.ids?.length} tasks`);
}
