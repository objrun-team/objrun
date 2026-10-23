/**
 * 一次请求带出去的上下文有多大，以及**那一堆消息里哪一段是哪个节点的**。
 *
 * ```
 * bun examples/benchmark/deepswe/context.ts [这一跑叫什么] [某一道题]
 * ```
 *
 * 不给题号就每道题一行（它这辈子最大的那一次）；给了就把那道题按节点摊开。
 *
 * ## 大小从哪儿来：量消息，不读 `prompt_tokens`
 *
 * `prompt_tokens` 那一列记的是**花掉的输入**，不是上下文有多长：一次答复被截断会
 * 接着再问一遍，每一轮各自计费，那一列是几轮之和（表注里写着）。实测过一行 17232
 * 对着一段约 1600 token 的对话。所以这儿的「多大」是**照着内核真会发出去的那份
 * 自己数的**：顺着 `from` 指针把这一站的链走出来，把链上每一行 `body` 的字节加起来。
 *
 * **思考也要算进去。** 它不在 `body` 里（`body` 是那份谁都认得的重放材料），
 * 单独占着 `thought` 那一列 —— 但出站的时候拼进消息里跟着回去：请求带 `tools` 的
 * 时候，历史轮次的 `reasoning_content` 都得回传（`llm/index.ts` 的 `toMsg`），
 * 而这套机制每一次请求都带 `tools`。只数 `body` 的话，量出来会比真的小一多半。
 *
 * 字节不是 token，两者之间没有定数（代码、JSON、中文各不一样）。算过一道题：
 * 4234989 字节对着模型报的 1033906 token，约 4.1 字节一个 token。这儿按 4 估。
 *
 * ## 哪一段是哪个节点的
 *
 * `task_{mode}` 每一行都记着 `node`，而消息行记着 `unit` —— 两边按 `unit` 一对，
 * 每条消息属于哪个节点就是确定的，不用猜。
 *
 * 链是顺着 `from_cycle`/`from_unit` 走出来的，**不是「所有比我小的 unit」**：
 * 这两件事在这套树上现在恰好一样（新节点挂在上一个节点的交卷站上，整棵树是一条
 * 直线），但那是这棵树现在的形状，不是协议。按 `from` 走的话，哪天真长出旁支来，
 * 这个脚本不用改。
 */

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
const RUN = process.argv[2] ?? "dsw-full";
const ONE = process.argv[3] ?? "";

async function sql<T>(q: string): Promise<T[]> {
  const r = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sql: q }),
  });
  if (!r.ok) throw new Error(`${r.status} on: ${q.slice(0, 60)}`);
  return ((await r.json()) as { rows: T[] }).rows;
}

interface Stat {
  unit: number;
  node: number;
  cycle: string;
  from_unit: number | null;
}

const kb = (n: number) => `${(n / 1024).toFixed(0)}k`;

/** 一道题：每个节点收口那一刻，链上有多大、哪个节点占了多少。 */
async function oneTask(task: string): Promise<{ peak: number; nodes: number; line: string[] }> {
  const id = `${RUN}/${task}`;
  const stations = (await sql<Stat>(
    `select unit, node, cycle, from_unit from task_solve where task = '${id}' order by unit`,
  )).map((s) => ({ ...s, unit: Number(s.unit), node: Number(s.node), from_unit: s.from_unit === null ? null : Number(s.from_unit) }));
  if (stations.length === 0) return { peak: 0, nodes: 0, line: [] };

  const bytes = new Map<number, number>();
  const think = new Map<number, number>();
  for (const r of await sql<{ unit: number; n: number; t: number }>(
    `select unit, sum(length(body)) as n, sum(length(coalesce(thought, ''))) as t
       from agent_bot_msg where instance = '${id}#1' group by unit`,
  )) {
    bytes.set(Number(r.unit), Number(r.n) + Number(r.t));
    think.set(Number(r.unit), Number(r.t));
  }

  const by = new Map(stations.map((s) => [s.unit, s]));
  /** 这一站的链，从根到它自己。 */
  const chainOf = (u: number): number[] => {
    const out: number[] = [];
    let cur = by.get(u);
    const seen = new Set<number>();
    while (cur && !seen.has(cur.unit)) {
      seen.add(cur.unit);
      out.push(cur.unit);
      cur = cur.from_unit === null ? undefined : by.get(cur.from_unit);
    }
    return out;
  };

  const nodes = [...new Set(stations.map((s) => s.node))].sort((a, b) => a - b);
  const line: string[] = [];
  let peak = 0;
  for (const n of nodes) {
    const last = Math.max(...stations.filter((s) => s.node === n).map((s) => s.unit));
    const per = new Map<number, number>();
    let total = 0;
    let thought = 0;
    for (const u of chainOf(last)) {
      const b = bytes.get(u) ?? 0;
      total += b;
      thought += think.get(u) ?? 0;
      const nd = by.get(u)!.node;
      per.set(nd, (per.get(nd) ?? 0) + b);
    }
    peak = Math.max(peak, total);
    const split = nodes.filter((x) => per.has(x)).map((x) => `n${String(x)} ${kb(per.get(x) ?? 0)}`).join("  ");
    line.push(
      `  node ${String(n).padStart(2)}  收口在 #${String(last).padEnd(4)}  链上 ${kb(total).padStart(7)}` +
        `  ≈${String(Math.round(total / 4 / 1000)).padStart(4)}k tok  其中思考 ${String(Math.round((thought / total) * 100)).padStart(2)}%   ${split}`,
    );
  }
  return { peak, nodes: nodes.length, line };
}

if (ONE) {
  const r = await oneTask(ONE);
  console.log(`${RUN}/${ONE}  ${r.nodes} 个节点，链上最大 ${kb(r.peak)}\n`);
  console.log(r.line.join("\n"));
  console.log("\n每一行是那个节点收口那一刻链上的样子；后面那串是这一链里各节点各占多少。");
} else {
  const tasks = await sql<{ id: string }>(`select id from task where run = '${RUN}' order by id`);
  console.log(`${RUN}  ${tasks.length} 道\n`);
  console.log("  题".padEnd(50) + "节点  链上最大  ≈token");
  const rows: { task: string; nodes: number; peak: number }[] = [];
  for (const t of tasks) {
    const task = t.id.slice(RUN.length + 1);
    const r = await oneTask(task);
    rows.push({ task, nodes: r.nodes, peak: r.peak });
  }
  for (const r of rows.sort((a, b) => b.peak - a.peak)) {
    console.log(
      `  ${r.task.padEnd(48)}${String(r.nodes).padStart(4)}${kb(r.peak).padStart(10)}${String(Math.round(r.peak / 4 / 1000)).padStart(8)}k`,
    );
  }
}
