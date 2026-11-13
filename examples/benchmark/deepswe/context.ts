/**
 * Measure the outgoing context size and identify **which messages belong to each node**.
 *
 * ```
 * bun examples/benchmark/deepswe/context.ts [run-name] [problem-id]
 * ```
 *
 * Without a problem ID, print one row per problem for its largest lifetime context; with one, break that problem down by node.
 *
 * ## Measure messages, not `prompt_tokens`
 *
 * `prompt_tokens` records **billed input**, not context length. Truncated responses trigger continuation calls, each billed separately, and the column sums them (as documented in the schema). An observed row recorded 17232 tokens for a conversation of about 1600 tokens.
 * Measure the exact context the kernel would send instead: follow the station's `from` chain and sum each row's body bytes.
 *
 * **Include reasoning.** It occupies `thought`, not `body` (the universally replayable message payload), but is reattached to outgoing messages. When a request includes tools, previous `reasoning_content` must be returned (`toMsg` in `llm/index.ts`), and every request in this mechanism includes tools. Counting body alone underestimates size by more than half.
 *
 * Bytes and tokens have no fixed ratio across code, JSON, and Chinese. One measured problem had 4,234,989 bytes and 1,033,906 provider-reported tokens, about 4.1 bytes/token. Estimate with 4 here.
 *
 * ## Attribute context to nodes
 *
 * Each `task_{mode}` row records node, while message rows record unit. Joining by unit identifies ownership exactly.
 * Follow `from_cycle`/`from_unit`, **not all smaller unit numbers**. They happen to coincide in the current linear tree because each new node attaches to the previous submission station, but that is a topology rather than a protocol guarantee. Following from pointers also works if branches are later added.
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

/** For one problem, measure total chain size and each node's share when every node closes. */
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
  /** This station's chain, from the root through the station itself. */
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
      `  node ${String(n).padStart(2)}  Finalized at #${String(last).padEnd(4)}  chain ${kb(total).padStart(7)}` +
        `  ≈${String(Math.round(total / 4 / 1000)).padStart(4)}k tok  reasoning ${String(Math.round((thought / total) * 100)).padStart(2)}%   ${split}`,
    );
  }
  return { peak, nodes: nodes.length, line };
}

if (ONE) {
  const r = await oneTask(ONE);
  console.log(`${RUN}/${ONE}  ${r.nodes} nodes, peak chain size ${kb(r.peak)}\n`);
  console.log(r.line.join("\n"));
  console.log("\nEach row shows the chain when that node finalized; the suffix breaks down each node’s contribution.");
} else {
  const tasks = await sql<{ id: string }>(`select id from task where run = '${RUN}' order by id`);
  console.log(`${RUN}  ${tasks.length} tasks\n`);
  console.log("  Task".padEnd(50) + "Nodes  Peak chain  ≈tokens");
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
