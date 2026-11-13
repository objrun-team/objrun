/**
 * Build a batch of DeepSWE tasks with G and send it to POST /bench.
 *
 * ```
 * bun examples/benchmark/deepswe/send.ts [count] [run-name] [seed]
 * ```
 *
 * **This script only assembles request bodies.** The README gives complete task and G examples.
 * Statements enter description; **reference solutions and hidden tests do not**. Both remain in the grading service.
 */

import { objectiveOf } from "./objective.ts";

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
/** When api.publisherToken is configured, attaching grading criteria requires this key (X-TGEngin-Publisher). Read it from the environment; if unset, use an empty object to preserve existing behavior. */
const PUBLISHER: Record<string, string> = process.env.TGENGIN_PUBLISHER_TOKEN ? { "x-tgengin-publisher": process.env.TGENGIN_PUBLISHER_TOKEN } : {};
const STAND = process.env.TGENGIN_DSW_STAND ?? "http://127.0.0.1:7902";
const HOW_MANY = Number(process.argv[2] ?? 10);
const RUN = process.argv[3] ?? `dsw-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}`;
const SEED = Number(process.argv[4] ?? process.env.TGENGIN_DSW_SEED ?? 0);
/**
 * **Maximum seconds per problem.** Official task.toml allows 10800 (three hours). Cap it here at 7200 (two hours), using the smaller limit. TGENGIN_DSW_SECONDS overrides this cap.
 *
 * Because the limit is shorter, these scores describe a different experiment from the three-hour leaderboard.
 */
const CAP_SECONDS = Number(process.env.TGENGIN_DSW_SECONDS ?? 7200);
/** K: abandon after this many dead siblings (maxDeadSiblings). Override with TGENGIN_DSW_DEAD; the F-arm setting is 100000 (K=∞). */
const DEAD = Number(process.env.TGENGIN_DSW_DEAD ?? 8);
/** **Arm U** (TGENGIN_DSW_UNAIDED=1, following terminal-bench/send.ts): attach neither G nor readable, but append the same acceptance criteria. The solver knows how it will be graded but cannot query a criterion. At completion, the arm script grades each container's HEAD once through /grade. */
const UNAIDED = process.env.TGENGIN_DSW_UNAIDED === "1";
/** Submit only these comma-separated problem IDs, from TGENGIN_DSW_ONLY. */
const ONLY = (process.env.TGENGIN_DSW_ONLY ?? "").split(",").map((x) => x.trim()).filter(Boolean);

/** Statement exposed by the grader. **Contains neither reference solution nor hidden tests.** */
interface Item {
  id: string;
  language: string;
  title: string;
  instruction: string;
  base_commit: string;
  /** Official task.toml [agent] timeout_sec. **Do not invent another value.** */
  seconds: number;
}

// **Fetch problems from the grader, not disk.** The corpus and reference solutions are installed on the grader side (setup.sh); this sender runs on the engine machine and cannot read that path.
const res0 = await fetch(`${STAND}/problems?n=${HOW_MANY}&seed=${SEED}`);
if (!res0.ok) {
  console.error(`cannot fetch problems from the stand (${STAND}/problems): ${res0.status}`);
  process.exit(1);
}
let items = (await res0.json()) as Item[];
if (ONLY.length) items = items.filter((it) => ONLY.includes(it.id));

// **Resume submission:** with TGENGIN_SKIP_EXISTING=1, skip by name tasks already submitted in this run.
let skip = new Set<string>();
if (process.env.TGENGIN_SKIP_EXISTING === "1") {
  const r = await fetch(`${BASE}/tasks?run=${RUN}&limit=5000`);
  if (r.ok) skip = new Set(((await r.json()) as { rows?: { id: string }[] }).rows?.map((x) => x.id) ?? []);
  console.log(`${RUN}: ${skip.size} already published, skipping them`);
}

const objective = objectiveOf(STAND);
/** Acceptance criteria included in arm-U statements: **remove handle URLs**. Sherlock containers share host loopback, so exposing grader URLs exposes the criterion. The grader also rejects container-origin requests; omission here is the first barrier. */
const criteria = { ...objective, nodes: objective.nodes.map(({ handle: _h, ...n }) => n) };

const tasks = items.filter((it) => !skip.has(`${RUN}/${it.id}`)).map((it) => {
  // Use the smaller of the problem's official time limit and this run's cap.
  const seconds = Math.min(it.seconds, CAP_SECONDS);
  return {
    /** **Include the run name in the id.** task.id is globally unique (tasks/publish.ts rejects duplicates), but DeepSWE problem IDs are unchanged across runs. Bare IDs would permanently occupy those names after one run, preventing another level/seed run without rebuilding the database. The four feedback levels are intended to be four separate runs. */
    id: `${RUN}/${it.id}`,
    mode: "solve",
    agent: "bot",
    // **This address format is ours.** The handle named by workplace.identity parses it; the kernel does not know dsw:. That is the purpose of this column (app/src/place/index.ts).
    //
    // Include the run name so **each run gets a fresh container**. Changing feedback level starts with a clean workspace. Retries within one run deliberately share their container to preserve experience.
    place: `dsw:${RUN}/${it.id}`,
    source: "user",
    domain: "software",
    // Work at the repository root inside the container.
    workdir: "/app",
    /**
     * **Per-problem time limit:** the smaller of official task.toml [agent] timeout_sec (currently 10800 seconds) and CAP_SECONDS (currently 7200).
     *
     * It must exceed an individual call's timeout. Equal deadlines let the task timeout win, preventing stalled-call -> dead-station -> new-node retry.
     */
    solveSeconds: seconds,
    // **Keep time as the only binding constraint.** Provide ample units, branches, and dead-attempt retries so termination means time expired rather than unit budget exhausted.
    maxBranches: 4,
    maxDeadSiblings: DEAD,
    /**
     * **No search.** Official environments are no-network, but our search tool is not forwarded to workplace because it needs network access and credentials, not that filesystem (main.ts). It would expose publicly available GitHub reference solutions searchable by task ID.
     *
     * Give no search allowance and disable the tool in run.sh. These keywords are defense in depth if the tool is accidentally exposed again, blocking the most direct retrieval routes.
     */
    noSearch: ["deepswe solution", "datacurve deep-swe", `${it.id} solution`],
    /** Official statement followed by grading details: the two diff endpoints, required submission, and time limit. */
    description:
      `${it.instruction}\n\n` +
      `## Grading\n\n` +
      `The repository is at /app, checked out at ${it.base_commit}.\n` +
      // At completion, arm U grades container HEAD using the official [[verifier.collect]] command; state that accurately. Arm F grades the submitted SHA.
      (UNAIDED
        ? `What is graded is the diff from ${it.base_commit} to HEAD of /app at the moment you hand in. `
        : `What is graded is the diff from ${it.base_commit} to the commit whose sha is handed in. `) +
      `Changes left uncommitted in the working tree are not in that diff.\n\n` +
      `The wall-clock limit for this task is ${Math.round(seconds / 3600)} hours. ` +
      `Nothing reports how much of it is left.` +
      (UNAIDED ? `\n\n## Acceptance criteria\n${JSON.stringify(criteria, null, 2)}` : ""),
    // When attaching G, explicitly declare whether the agent may read its definition.
    //
    // **Set true.** The solver should know that patches must apply, existing tests must keep passing, and requested behavior must be implemented. This system measures success against a clearly stated target; hiding it measures something else. Arm U has no G and therefore no readable field.
    ...(UNAIDED ? {} : { objective, readable: true }),
  };
});
console.log(`${RUN}: ${tasks.length} tasks, c=${objective.checks}, K=${DEAD}, T<=${CAP_SECONDS}s${UNAIDED ? " (UNAIDED: no objective mounted)" : ""}`);

/**
 * **Validate the exact HTTP request to G before submission.**
 *
 * ```
 * bun examples/benchmark/deepswe/send.ts 10 dsw-l2 0 --dry
 * ```
 *
 * This tests more than grader liveness (/health): it uses **the actual kernel payload shape**:
 *
 * ```json
 * {"node":"applies","moment":"task_done","domain":"bool",
 *  "feed":[], "input":{"task":{…complete row…},"chain":[],"result":{"kind":"prompt","body":"<sha>"}}}
 * ```
 *
 * It detects unreachable handles, task IDs absent from the corpus, out-of-domain responses (a non-bool silently makes G return 0), and roots that do not short-circuit upstream failure. **Finding these after an hours-long run requires starting over.**
 *
 * No container is started here. Since work has not begun, applies should report that the patch cannot be retrieved, proving it recognized the task and reached patch retrieval.
 */
async function dryRun(): Promise<number> {
  console.log(`${RUN}: ${tasks.length} tasks assembled, nothing sent\n`);
  console.log("── One task request (others differ only in id / place / description) ──");
  console.log(JSON.stringify({ ...tasks[0], description: tasks[0].description.slice(0, 160) + " …" }, null, 2));

  console.log("\n── Query G with the kernel’s actual payload shape ──");
  const shape = (node: string, task: (typeof tasks)[number], said: string, feed: unknown[]) => ({
    node,
    moment: "task_done",
    domain: "bool",
    feed,
    input: {
      task: { id: task.id, place: task.place, description: task.description, result: said },
      chain: [],
      result: { kind: "prompt", body: said },
    },
  });

  let bad = 0;
  const ask = async (url: string, body: unknown) => {
    const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json", ...PUBLISHER }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`${r.status}`);
    return (await r.json()) as { value?: unknown; note?: unknown };
  };

  for (const t of tasks) {
    const line: string[] = [];
    let fine = true;
    try {
      // Work has not started, so expect verdict 0 with an explanation that the patch cannot be retrieved.
      const a = await ask(objective.nodes[0].handle, shape("applies", t, "0000000000000000000000000000000000000000", []));
      // **Enforce the domain:** a bool node must return bool; other responses silently map to 0 in G.
      if (typeof a.value !== "boolean") throw new Error(`applies returned ${typeof a.value}, not a bool`);
      if (a.value !== false) throw new Error(`applies said true for a task that has not started`);
      if (!a.note) throw new Error(`applies judged 0 but said nothing (note is empty)`);
      line.push(`applies=false note=${JSON.stringify(a.note).slice(0, 60)}`);

      // After upstream failure, the root **must not grade again**; that would cost tens of seconds to minutes.
      const t0 = Date.now();
      const r = await ask(objective.nodes[1].handle, shape("resolved", t, "0000000000000000000000000000000000000000", [{ from: "applies", out: 0, value: false }]));
      const ms = Date.now() - t0;
      if (typeof r.value !== "boolean") throw new Error(`resolved returned ${typeof r.value}, not a bool`);
      if (r.value !== false) throw new Error(`resolved said true behind a failed upstream`);
      if (ms > 5000) throw new Error(`resolved took ${ms}ms behind a failed upstream - it should short-circuit, not grade`);
      line.push(`resolved=false in ${ms}ms`);
    } catch (e) {
      bad++;
      fine = false;
      line.push(`FAILED: ${e instanceof Error ? e.message : String(e)}`);
    }
    console.log(`  ${fine ? "✓" : "✗"} ${t.id.padEnd(52)} ${line.join("  ")}`);
  }

  // A mismatched problem ID would make every problem score 0 after the entire run.
  console.log("\n── Check whether a mismatched task ID is reported ──");
  const ghost = await ask(objective.nodes[0].handle, shape("applies", { ...tasks[0], id: "no-such-task" }, "x", []));
  const knows = JSON.stringify(ghost.note ?? "").includes("not in the corpus");
  console.log(`  ${knows ? "✓" : "✗"} ${JSON.stringify(ghost)}`);
  if (!knows) bad++;

  console.log(`\n${bad === 0 ? `all ${tasks.length} tasks preflight clean` : `${bad} problems - nothing was sent`}`);
  return bad === 0 ? 0 : 1;
}

if (process.argv.includes("--dry")) process.exit(await dryRun());

/**
 * **Concurrent problems.** 0 submits the full batch immediately.
 *
 * The kernel dispatches all unsent rows as soon as they exist, so only the sender can control concurrency. The number of unfinished database tasks is the number being processed.
 *
 * Submitting all 112 problems means 112 containers and 112 simultaneous calls to one provider. Requests queue rather than fail, consuming **wall-clock** problem budgets. Even ten concurrent tasks already queue grading on this machine (see queued in grader logs).
 *
 * Maintain **N concurrent problems, not fixed batches of N**: replace each completed task immediately rather than waiting for the slowest member of a batch.
 */
const AT_ONCE = Number(process.env.TGENGIN_DSW_AT_ONCE ?? 0);

/** Current unfinished task count for this run: not yet started plus running. */
async function busy(): Promise<number> {
  const r = await fetch(`${BASE}/bench/${RUN}`);
  if (!r.ok) return 0;
  const j = (await r.json()) as { running?: number; open?: number };
  return Number(j.running ?? 0) + Number(j.open ?? 0);
}

if (AT_ONCE > 0) {
  // Submit individually after checking capacity. POST /tasks validates each problem's G, so no criterion is weakened. Atomic batch rejection is lost, however; stop immediately if the first task is rejected.
  console.log(`${RUN}: ${tasks.length} tasks, keeping ${AT_ONCE} of them in flight (seed ${SEED})`);
  let sent = 0;
  let skipped = 0;
  for (const t of tasks) {
    while ((await busy()) >= AT_ONCE) await Bun.sleep(10_000);
    const r = await fetch(`${BASE}/tasks`, {
      method: "POST",
      headers: { "content-type": "application/json", ...PUBLISHER },
      body: JSON.stringify({ ...t, run: RUN }),
    });
    if (!r.ok) {
      const e = (await r.json()) as { error?: string };
      // **An existing name means this task was submitted earlier; skip it.** Resume an interrupted sender with the same run name and recognize prior submissions by name. Other rejections still stop immediately because they indicate a problem with the run.
      if ((e.error ?? "").includes("already exists")) {
        skipped++;
        continue;
      }
      console.error(`${t.id} was refused: ${e.error}`);
      process.exit(1);
    }
    sent++;
    console.log(`  [${String(sent + skipped)}/${tasks.length}] ${t.id.slice(RUN.length + 1)}`);
  }
  console.log(`${RUN}: ${sent} sent${skipped ? `, ${skipped} already there` : ""} (${tasks.length} in the corpus)`);
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
  console.log(`${got.run}: ${got.ids?.length} tasks (seed ${SEED})`);
  for (const it of items) console.log(`  ${it.id}  [${it.language}]`);
}
