/**
 * 把一趟的东西导出来：四张 csv + 一份说明。
 *
 * ```
 * bun examples/benchmark/deepswe/report.ts [这一跑叫什么] [导到哪儿]
 * ```
 *
 * **在开跑之前就该跑一遍**（拿上一趟的名字），确认每一栏都取得出来。跑完才发现少一栏
 * 的话，那一栏的数据不在库里，就是整趟重来 —— 而全集一趟要好几个钟头。
 *
 * 导的是**库里已经有的东西**，一个数都不新算：分数是数出来的，不是存下来的。
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

/** csv 一行。**逗号、引号、换行都得转义** —— 不转的话表格那边错一列，而且不报错。 */
const cell = (v: unknown) => {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};
const csv = (rows: Record<string, unknown>[]) =>
  rows.length === 0
    ? ""
    : [Object.keys(rows[0]).join(","), ...rows.map((r) => Object.values(r).map(cell).join(","))].join("\n") + "\n";

// ── 一道题一行 ──────────────────────────────────────────────────────────────
//
// `pass` 是**数出来的**：`task.state = 'done'`。库里没有「分数」这一栏，也不该有。
//
// **带逗号的自由文本（`result`）排在最后一栏。** 排中间的话，`cut -d,` / `awk -F,`
// 这类不认引号的工具会从那一栏开始整行错位 —— 而且不报错，只是后面每一栏都读错。
// 拿去画图的人多半就是这么读的。
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

// ── 一站一行 ────────────────────────────────────────────────────────────────
const stations = await sql<Record<string, unknown>>(`
  select task, cycle, unit, place, at, status, done
  from task_solve where task like '${RUN}/%' order by task, unit`);

// ── 每次问 G 一行 ───────────────────────────────────────────────────────────
//
// `note` 那一栏是判卷台说的话（分级由它那边定）。**判 0 的时候有没有内容，
// 是这一跑最要紧的一列** —— 空的话这一跑的级别设了等于没设。
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
    // 自由文本排最后，理由同上。
    why: x.why ?? "",
    note: x.note ?? "",
  };
});

// ── 每件工具跑了几次 ────────────────────────────────────────────────────────
//
// `glob` 一次没人用这种事只有这张表看得出来。
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

// ── 落盘 ────────────────────────────────────────────────────────────────────
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

## csv/tasks.csv — 一道题一行

| 栏 | 是什么 |
| --- | --- |
| \`task\` | 题号（去掉跑名前缀） |
| \`state\` | \`done\` / \`failed\` / \`claimed\` |
| \`pass\` | 1 = 官方判据说做成了。**数出来的**，库里没有「分数」这一栏 |
| \`place\` | 它的容器（\`dsw:<跑名>/<题号>\`） |
| \`solve_seconds\` | 时限，取自官方 \`task.toml\` 的 \`[agent] timeout_sec\` |
| \`stations\` | 走了多少站（两个周期加起来） |
| \`asks\` | 其中多少站是问模型 —— 相当于模型轮次 |
| \`dead_stations\` | 判死了几站 |
| \`attempts_died\` | 判死了几次尝试（树上开了几次兄弟） |
| \`checks\` | 它自己问了几次 G |
| \`result\` | 收尾判决的原文 \`{pass, why, note}\` |

## csv/stations.csv — 一站一行

\`status\` 空 = 还在跑；\`reached\` = 走到了；\`dead_*\` = 被判死。
\`at\` 是这一站开始的毫秒时刻，配 \`done\` 能算出每一站花了多久。

## csv/checks.csv — 每次问 G 一行

| 栏 | 是什么 |
| --- | --- |
| \`pass\` | 这一次判 1 还是 0 |
| \`graded\` | 判的是哪个提交（sha）。**改一个字符就是另一份候选** |
| \`left\` | 这一轮还剩几次额度 |
| \`reused\` | 1 = 交卷那次没重判，用的是它自己验过的那次判决 |
| \`why\` | 判 0 的时候是 \`see note\` |
| \`note\` | **判卷台说的话**，详略由台子的 \`--level\` 定 |

判 0 的 ${zeros} 次里，${withNote} 次带着 \`note\`。
**这个比例要是不到十成，这一趟的级别设了等于没设。**

## csv/tools.csv — 每道题每件工具跑了几次

\`web_search\` 和 \`python_exec\` 这一跑是关掉的，**这两列必须全是 0**。
不是 0 的话这一趟不作数：官方那套两侧都是 \`no-network\`。
`,
);

console.log(`${RUN}: ${passed} / ${tasks.length} solved`);
console.log(`  csv/tasks.csv     ${tasks.length} 行`);
console.log(`  csv/stations.csv  ${stations.length} 行`);
console.log(`  csv/checks.csv    ${checks.length} 行（判 0 的 ${zeros} 次里 ${withNote} 次带 note）`);
console.log(`  csv/tools.csv     ${tools.length} 行`);
const leaked = tools.reduce((s, r) => s + Number(r.web_search) + Number(r.python_exec), 0);
console.log(`  ${leaked === 0 ? "✓" : "✗"} web_search / python_exec 一共跑了 ${leaked} 次`);
console.log(`→ ${OUT}`);
