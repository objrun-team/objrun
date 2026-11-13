/**
 * Watch a run while it is in progress.
 *
 * ```
 * bun examples/benchmark/deepswe/watch.ts [run-name] [--loop 60]
 * ```
 *
 * **Spotting problems early requires more than a scorecard**: the first score takes hours, by which time it may be too late to fix anything. Show each task’s execution-unit count, time since its last message, number of grading calls, and grading feedback.
 *
 * Several silent failure modes are immediately visible here:
 *
 * | Observation | Likely cause |
 * | --- | --- |
 * | Every task’s `station` stays at 1 and `idle` keeps increasing | The model rail is unavailable (key, quota, network) |
 * | Stations increase, but there is no `verify` | It does not know to submit a SHA, or is not progressing toward submission |
 * | There are `verify` calls, but `patch` is always 0 bytes | It edits files without committing; the collection hook finds nothing |
 * | Every grading failure is in `collect` | The submission is not a commit hash |
 * | One task’s `station` count races upward while others stand still | That task is stuck in a loop, consuming quota |
 */

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
const RUN = process.argv[2] ?? "dsw-l2";
const LOOP = Number((process.argv.find((a) => a.startsWith("--loop")) ?? "").split("=")[1] ?? 0) ||
  (process.argv.includes("--loop") ? 60 : 0);

async function sql<T>(q: string): Promise<T[]> {
  const r = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sql: q }),
  });
  if (!r.ok) throw new Error(`${q.slice(0, 40)}: ${r.status}`);
  return ((await r.json()) as { rows: T[] }).rows;
}

const ago = (ms: number) => (ms < 0 ? "?" : ms < 60_000 ? `${Math.round(ms / 1000)}s` : `${Math.round(ms / 60_000)}m`);

async function once(): Promise<void> {
  const now = Date.now();

  const tasks = await sql<{ id: string; state: string; result: string | null; created_at: number }>(
    `select id, state, result, created_at from task where run = '${RUN}' order by id`,
  );
  if (tasks.length === 0) {
    console.log(`${RUN}: no tasks`);
    return;
  }

  // Execution-unit count: one row per station in the child table.
  const units = await sql<{ task: string; n: number; dead: number }>(
    `select task, count(*) as n, sum(case when status like 'dead%' then 1 else 0 end) as dead
     from task_solve where task like '${RUN}/%' group by task`,
  );
  // Time of the last message: prolonged silence indicates a stall.
  const last = await sql<{ instance: string; at: number; n: number }>(
    `select instance, max(at) as at, count(*) as n from agent_bot_msg
     where instance like '${RUN}/%' group by instance`,
  );
  // How many times it has queried G itself.
  const checks = await sql<{ instance: string; n: number }>(
    `select instance, count(*) as n from agent_bot_msg
     where instance like '${RUN}/%' and kind = 'tool' and body like '%"verify"%' group by instance`,
  );

  const u = new Map(units.map((r) => [r.task, r]));
  const l = new Map(last.map((r) => [r.instance.split("#")[0], r]));
  const c = new Map<string, number>();
  for (const r of checks) c.set(r.instance.split("#")[0], (c.get(r.instance.split("#")[0]) ?? 0) + r.n);

  const done = tasks.filter((t) => t.state === "done").length;
  const failed = tasks.filter((t) => t.state === "failed").length;
  console.log(
    `\n${new Date().toTimeString().slice(0, 8)}  ${RUN}  ` +
      `${done} passed / ${failed} dead / ${tasks.length - done - failed} running`,
  );
  console.log("  " + "Task".padEnd(46) + "State    Units Dead Checks Idle Start");
  for (const t of tasks) {
    const short = t.id.slice(RUN.length + 1);
    const uu = u.get(t.id);
    const ll = l.get(t.id);
    const verdict = t.result ? (JSON.parse(t.result) as { pass?: number; note?: string }) : null;
    const tail = verdict ? `  ${verdict.pass === 1 ? "PASS" : "FAIL"} ${String(verdict.note ?? "").slice(0, 60)}` : "";
    console.log(
      `  ${short.padEnd(46)}${t.state.padEnd(9)}` +
        `${String(uu?.n ?? 0).padStart(3)}${String(uu?.dead ?? 0).padStart(5)}` +
        `${String(c.get(t.id) ?? 0).padStart(4)}` +
        `${(ll ? ago(now - ll.at) : "-").padStart(6)}` +
        `${ago(now - t.created_at).padStart(7)}${tail}`,
    );
  }

  // Before any call lands, every value above is 0; this cannot distinguish “not started” from “rail unavailable”.
  const sent = await sql<{ n: number; kind: string }>(
    `select kind, count(*) as n from agent_bot_msg where instance like '${RUN}/%' group by kind`,
  );
  console.log("  Messages: " + (sent.map((r) => `${r.kind} ${r.n}`).join("  ") || "none"));
}

if (LOOP > 0) {
  for (;;) {
    try {
      await once();
    } catch (e) {
      console.log(`  Cannot inspect: ${e instanceof Error ? e.message : String(e)}`);
    }
    await Bun.sleep(LOOP * 1000);
  }
} else {
  await once();
}
