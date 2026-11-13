/**
 * Export a run into four CSV files and an explanatory note.
 *
 * ```
 * bun examples/benchmark/deepswe/report.ts [run-name] [output-directory]
 * ```
 *
 * **Try this before starting a run**, using an earlier run name, to confirm that every column is available. Discovering after completion that a required field was never stored forces an hours-long full rerun.
 *
 * Export **existing database data**, without inventing new values: scores are derived by counting records, not stored as scores.
 */

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
const RUN = process.argv[2] ?? "dsw-a";
const OUT = process.argv[3] ?? `data/runs/${RUN}/export`;

async function sql<T>(q: string): Promise<T[]> {
  const r = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sql: q }),
  });
  if (!r.ok) throw new Error(`${r.status} on: ${q.slice(0, 60)}`);
  return ((await r.json()) as { rows: T[] }).rows;
}

/** One CSV row. **Escape commas, quotes, and newlines**; otherwise spreadsheet columns shift silently. */
const cell = (v: unknown) => {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};
const csv = (rows: Record<string, unknown>[]) =>
  rows.length === 0
    ? ""
    : [Object.keys(rows[0]).join(","), ...rows.map((r) => Object.values(r).map(cell).join(","))].join("\n") + "\n";

// ── One row per problem ──
//
// Derive pass from `task.state = 'done'`. The database has, and should have, no stored score column.
//
// **Place comma-bearing free text (`result`) last.** Quote-unaware readers such as `cut -d,` or `awk -F,`, often used for plotting, otherwise silently shift every subsequent column.
const tasks = await sql<Record<string, unknown>>(`
  select
    t.id,
    replace(t.id, '${RUN}/', '')              as task,
    t.state,
    case when t.state = 'done' then 1 else 0 end as pass,
    t.place,
    t.solve_seconds,
    t.created_at,
    (select count(*) from task_solve s where s.task = t.id)                            as stations,
    (select count(*) from task_solve s where s.task = t.id and s.cycle = 'ask')        as asks,
    (select count(*) from task_solve s where s.task = t.id and s.status like 'dead%')  as dead_stations,
    (select count(distinct s.unit) from task_solve s where s.task = t.id and s.status like 'dead%') as attempts_died,
    (select count(*) from agent_bot_msg m where m.instance like t.id || '#%'
       and m.kind = 'tool' and m.body like '%"name":"verify"%')                        as checks,
    (select max(m.at) from agent_bot_msg m where m.instance like t.id || '#%')         as last_at,
    t.result
  from task t where t.run = '${RUN}' order by t.id`);

// ── One row per station ──
const stations = await sql<Record<string, unknown>>(`
  select task, cycle, unit, place, at, status, done
  from task_solve where task like '${RUN}/%' order by task, unit`);

// ── One row per query to G ──
//
// `note` contains grader feedback at its configured level. **Whether it is nonempty after verdict 0 is a key column**: empty feedback makes the chosen information level ineffective.
const verify = await sql<Record<string, unknown>>(`
  select instance, unit, at, body
  from agent_bot_msg
  where instance like '${RUN}/%' and kind = 'tool' and body like '%"name":"verify"%'
  order by instance, unit`);
const checks = verify.map((r) => {
  const v = JSON.parse(String(r.body)) as { value?: { pass?: number; why?: string; note?: string; graded?: string; left?: number; reused?: boolean } };
  const x = v.value ?? {};
  return {
    task: String(r.instance).split("#")[0].slice(RUN.length + 1),
    instance: r.instance,
    unit: r.unit,
    at: r.at,
    pass: x.pass ?? "",
    graded: x.graded ?? "",
    left: x.left ?? "",
    reused: x.reused ? 1 : 0,
    // Keep free text last, for the same reason as above.
    why: x.why ?? "",
    note: x.note ?? "",
  };
});

// ── Call counts for each tool ──
//
// Only this table reveals cases such as glob never being used.
const TOOLS = ["bash", "read", "write", "edit", "glob", "grep", "verify", "submit", "node_load", "task_tree", "web_search", "python_exec"];
const tools: Record<string, unknown>[] = [];
for (const t of tasks) {
  const row: Record<string, unknown> = { task: t.task };
  for (const name of TOOLS) {
    const [{ n }] = await sql<{ n: number }>(
      `select count(*) as n from agent_bot_msg where instance like '${t.id}#%' and kind = 'tool' and body like '%"name":"${name}"%'`,
    );
    row[name] = n;
  }
  tools.push(row);
}

// ── Write output ──
const { mkdirSync, writeFileSync } = await import("node:fs");
mkdirSync(`${OUT}/csv`, { recursive: true });
writeFileSync(`${OUT}/csv/tasks.csv`, csv(tasks));
writeFileSync(`${OUT}/csv/stations.csv`, csv(stations));
writeFileSync(`${OUT}/csv/checks.csv`, csv(checks));
writeFileSync(`${OUT}/csv/tools.csv`, csv(tools));

const passed = tasks.filter((t) => t.pass === 1).length;
const withNote = checks.filter((c) => c.pass === 0 && String(c.note).length > 0).length;
const zeros = checks.filter((c) => c.pass === 0).length;

writeFileSync(
  `${OUT}/FIELDS.md`,
  `# ${RUN}

${passed} / ${tasks.length} solved.

## csv/tasks.csv — one row per task

| Column | Meaning |
| --- | --- |
| \`task\` | Task ID without the run-name prefix |
| \`state\` | \`done\` / \`failed\` / \`claimed\` |
| \`pass\` | 1 = official grader reports success. **Computed by counting**; the database has no score column |
| \`place\` | Its container (\`dsw:<run-name>/<task-id>\`) |
| \`solve_seconds\` | Time limit from official \`task.toml\` \`[agent] timeout_sec\` |
| \`stations\` | Execution-unit count across both cycles |
| \`asks\` | Execution units that call the model, equivalent to model turns |
| \`dead_stations\` | Execution units marked dead |
| \`attempts_died\` | Attempts marked dead (sibling branches opened in the tree) |
| \`checks\` | Proactive queries to G |
| \`result\` | Raw finalization verdict \`{pass, why, note}\` |

## csv/stations.csv — one row per execution unit

\`status\` empty = still running; \`reached\` = reached; \`dead_*\` = marked dead.
\`at\` is the execution unit’s start time in milliseconds; combine with \`done\` to calculate its duration.

## csv/checks.csv — one row per G query

| Column | Meaning |
| --- | --- |
| \`pass\` | Whether this grading call returned 1 or 0 |
| \`graded\` | Graded commit SHA. **Changing one character creates a different candidate** |
| \`left\` | Checks remaining in this round |
| \`reused\` | 1 = submission reused the previous self-check verdict without regrading |
| \`why\` | For a score of 0, this is \`see note\` |
| \`note\` | **Grading-service feedback**, with detail controlled by the service’s \`--level\` |

Of ${zeros} zero scores, ${withNote} include \`note\`.
**If this is not 100%, the feedback-level setting is ineffective for this run.**

## csv/tools.csv — tool-call counts per task

\`web_search\` and \`python_exec\` are disabled for this run; **both columns must be all 0**.
Nonzero values invalidate the run: both official sides use \`no-network\`.
`,
);

console.log(`${RUN}: ${passed} / ${tasks.length} solved`);
console.log(`  csv/tasks.csv     ${tasks.length} rows`);
console.log(`  csv/stations.csv  ${stations.length} rows`);
console.log(`  csv/checks.csv    ${checks.length} rows (${withNote} of ${zeros} zero scores include note)`);
console.log(`  csv/tools.csv     ${tools.length} rows`);
const leaked = tools.reduce((s, r) => s + Number(r.web_search) + Number(r.python_exec), 0);
console.log(`  ${leaked === 0 ? "✓" : "✗"} web_search / python_exec ran ${leaked} times in total`);
console.log(`→ ${OUT}`);
