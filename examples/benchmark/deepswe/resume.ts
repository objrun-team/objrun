/**
 * Resume **timed-out** problems using their previous workspaces.
 *
 * ```
 * bun examples/benchmark/deepswe/resume.ts [original-run] [new-run-name] [additional-seconds]
 * bun examples/benchmark/deepswe/resume.ts dsw-full dsw-full-r2 7200 --dry
 * ```
 *
 * ## What is resumed?
 *
 * **Do not reset the working container**; resetting the grading container is a separate concern. Previous files, branches, and commits remain in /app. The new task points to the **same container** with a new id, since task.id is globally unique and duplicates are rejected by tasks/publish.ts.
 *
 * Carry over the **workspace, not the context**. New tasks start with empty messages. Previous conversations and trees remain in agent_bot_msg/task_solve but are not attached; they caused the context overflow. The solver can inspect its existing commits with git log.
 *
 * ## Read the statement from the database
 *
 * The task row stores description, readable, workdir, no_search, and both limits. Copy them unchanged, **changing only the id and time limit**. Reconstructing them independently creates duplicate definitions that could silently make resumed tasks differ.
 *
 * G cannot be copied from the ordinary row, which contains only sealed because its definition is in the sealed store (tasks/publish.ts). Reload the shared objective.ts definition also used by send.ts.
 */

import { objectiveOf } from "./objective.ts";

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
/** When api.publisherToken is configured, attaching grading criteria requires this key (X-TGEngin-Publisher). Read it from the environment; if unset, use an empty object to preserve existing behavior. */
const PUBLISHER: Record<string, string> = process.env.TGENGIN_PUBLISHER_TOKEN ? { "x-tgengin-publisher": process.env.TGENGIN_PUBLISHER_TOKEN } : {};
const STAND = process.env.TGENGIN_DSW_STAND ?? "http://127.0.0.1:7902";
const FROM = process.argv[2] ?? "dsw-full";
const RUN = process.argv[3] ?? `${FROM}-r2`;
const SECONDS = Number(process.argv[4] ?? 7200);
/** Concurrent problems; 0 submits all immediately. Uses the same environment variable as send.ts. */
const AT_ONCE = Number(process.env.TGENGIN_DSW_AT_ONCE ?? 0);

interface Row {
  id: string;
  place: string;
  mode: string;
  source: string;
  domain: string;
  workdir: string;
  description: string;
  readable: number;
  max_branches: number;
  max_dead_siblings: number;
  max_searches: number | null;
  no_search: string;
  result: string;
}

async function sql<T>(q: string): Promise<T[]> {
  const r = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: { "content-type": "application/json", ...PUBLISHER },
    body: JSON.stringify({ sql: q }),
  });
  if (!r.ok) throw new Error(`${r.status} on: ${q.slice(0, 60)}`);
  return ((await r.json()) as { rows: T[] }).rows;
}

// **Select only timed-out problems.** Verdict 0 can also mean an inapplicable patch, missing behavior, or broken existing tests; another two hours may yield the same answer. A time-limited task differs because it was still making progress.
const rows = await sql<Row>(`
  select id, place, mode, source, domain, workdir, description, readable,
         max_branches, max_dead_siblings, max_searches, no_search, result
  from task
  where run = '${FROM}' and state = 'failed' and result like '%over solve_seconds%'
  order by id`);

if (rows.length === 0) {
  console.log(`${FROM}: no tasks were marked dead by timeout`);
  process.exit(0);
}

/** Where the previous run stopped: the grader's last note, used to assess whether another two hours are worthwhile. */
const near = (result: string): string => {
  const note = (JSON.parse(result) as { note?: string }).note ?? "";
  const m = /"new_behaviours":"([^"]+)"/.exec(note);
  return m ? m[1] : "nothing gradable";
};

const tasks = rows.map((r) => {
  const task = r.id.slice(FROM.length + 1);
  return {
    // New id, **same place**: the container contains the previous run's work.
    id: `${RUN}/${task}`,
    place: r.place,
    mode: r.mode,
    agent: "bot",
    source: r.source,
    domain: r.domain,
    workdir: r.workdir,
    // Keep the original statement and append a notice that **this workspace is not empty**. Otherwise the solver may start over; this allowance is for continuing work, not restarting it.
    description:
      `${r.description}\n\n` +
      `## Where this starts\n\n` +
      `/app carries the work of an earlier attempt at this same task: its branch and its commits are there, ` +
      `and \`git log\` reads them. Nothing else from that attempt is here.\n` +
      `That attempt ran out of its wall-clock limit with ${near(r.result)} of the new behaviours passing.`,
    objective: objectiveOf(STAND),
    readable: r.readable === 1,
    maxBranches: r.max_branches,
    maxDeadSiblings: r.max_dead_siblings,
    ...(r.max_searches === null ? {} : { maxSearches: r.max_searches }),
    noSearch: JSON.parse(r.no_search) as string[],
    // The only other changed number: additional time.
    solveSeconds: SECONDS,
  };
});

if (process.argv.includes("--dry")) {
  console.log(`${FROM} → ${RUN}: ${tasks.length} timed-out tasks, each given another ${SECONDS} seconds\n`);
  for (const [i, r] of rows.entries()) {
    console.log(`  ${r.id.slice(FROM.length + 1).padEnd(50)} ${near(r.result).padEnd(16)} → ${tasks[i].id}`);
  }
  console.log(`\nPlace is unchanged (same container); statement, G, and limits are copied unchanged from the database row.`);
  process.exit(0);
}

/** Current unfinished problem count for this run. */
async function busy(): Promise<number> {
  const r = await fetch(`${BASE}/bench/${RUN}`);
  if (!r.ok) return 0;
  const j = (await r.json()) as { running?: number; open?: number };
  return Number(j.running ?? 0) + Number(j.open ?? 0);
}

console.log(`${FROM} → ${RUN}: ${tasks.length} tasks, ${SECONDS} seconds each${AT_ONCE > 0 ? `, ${AT_ONCE} concurrent` : ""}`);
let sent = 0;
for (const t of tasks) {
  if (AT_ONCE > 0) while ((await busy()) >= AT_ONCE) await Bun.sleep(10_000);
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
  console.log(`  [${sent}/${tasks.length}] ${t.id.slice(RUN.length + 1)}`);
}
console.log(`${RUN}: all ${tasks.length} sent`);
