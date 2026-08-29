/**
 * 任务 —— 客户端用得最多的一组。
 *
 * ## 这一组的标准
 *
 * 客户端要显示的每一样，这儿得直接给出来。凡是要它「自己算一下」的，都是这边欠的：
 *
 * - **树长什么样**：依据是子表里的 `from_cycle`/`from_unit` 指针，客户端拼一遍
 *   等于把内核那段抄一份
 * - **链路串**：拼法是协议（`chain.ts`），客户端另拼一份的话，哪天拼法改了
 *   它那边的条件就**静默失效**
 * - **还有多久判死**：`now - at > expect_ms`，而 `expect_ms` 挂在这一站真正要调的
 *   那个句柄上 —— 客户端要自己算，得先把「这一站调哪个句柄」那段挑轨逻辑抄一遍
 * - **为什么不动**：见 `/tasks/:id/why`
 *
 * ## 干预
 *
 * `msg_kind` 里一直有 `intervene`（「用户看着它执行时施加的干预标记」），但在这个
 * 口之前**没有任何一处写它** —— 那一行是个空位。客户端要能在它跑的时候插一句话，
 * 这就是那个口。
 */

import type { Store } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import { chainOf } from "../engine/chain.ts";
import type { Registry } from "../engine/registry.ts";
import { tableNameOf } from "../install/index.ts";
import { deliver, HUMAN_MARK } from "../msg/deliver.ts";
import type { Sealed } from "../objective/store.ts";
import { publish, SOURCES, STATES, type Publish } from "../tasks/publish.ts";
import type { Route } from "./spec.ts";

const TASK = "任务";

type Row = Record<string, unknown>;

function one(store: Store, sql: string, p: unknown[] = []): Row | null {
  const r = all(store.ro, sql, p);
  return r.length ? r[0] : null;
}

/** 主表那一行 + 它的子表叫什么。找不到回 null。 */
function taskOf(store: Store, id: string): (Row & { sub: string }) | null {
  const t = one(store, `select * from task where id = ?`, [id]);
  if (!t) return null;
  return { ...t, sub: tableNameOf("task_{}", String(t.mode)) };
}

function has(store: Store, table: string): boolean {
  return all(store.ro, `select 1 from sqlite_master where type='table' and name = ?`, [table]).length > 0;
}

/** 这一行这一站要调哪个句柄 —— 跟内核挑的是同一套依据。 */
function handleOf(store: Store, mode: string, cycle: string, agent: string): string | null {
  const a = one(store, `select unit, apis from agent where name = ?`, [agent]);
  if (!a) return null;
  const c = one(store, `select api_mode from cycle where mode = ? and cycle = ?`, [mode, cycle]);
  const want = String(c?.api_mode ?? "").trim();
  if (!want) return String(a.unit);
  let apis: [string, string][] = [];
  try {
    apis = JSON.parse(String(a.apis ?? "[]")) as [string, string][];
  } catch {
    return null;
  }
  for (const [keyEnv, model] of apis) {
    const row = one(store, `select handle, modes from api where key_env = ? and model = ?`, [keyEnv, model]);
    if (!row) continue;
    if (String(row.modes ?? "").split(",").map((x) => x.trim()).includes(want)) return String(row.handle);
  }
  return null;
}

export function taskRoutes(store: Store, reg: Registry, sealed: Sealed, wake: () => void): Route[] {
  /** 一个执行单元在客户端眼里的样子。**该算的都算好。** */
  const unitOf = (t: Row & { sub: string }, u: Row) => {
    const handle = handleOf(store, String(t.mode), String(u.cycle), String(u.agent));
    const expect = handle && reg.has(handle) ? reg.get(handle).expectMs : null;
    const at = Number(u.at);
    const msg = tableNameOf("agent_{}_msg", String(u.agent));
    const sentOut = has(store, msg)
      ? Number(
          (one(store, `select count(*) c from "${msg}" where instance = ? and unit = ? and kind = 'inject'`, [
            u.instance,
            u.unit,
          ])! as { c: number }).c,
        ) > 0
      : false;
    return {
      cycle: u.cycle,
      unit: u.unit,
      from: u.from_cycle === null ? null : { cycle: u.from_cycle, unit: u.from_unit },
      agent: u.agent,
      instance: u.instance,
      place: u.place,
      at,
      done: Number(u.done) === 1,
      status: u.status ?? null,
      // 三档是**算**出来的，不是存着的 —— 内核也是这么判的，这儿给同一个答案。
      phase: Number(u.done) === 1 ? "done" : sentOut ? "running" : "pending",
      handle: handle,
      expectMs: expect,
      deadlineInMs: expect === null || Number(u.done) === 1 ? null : at + expect - Date.now(),
      chain: (() => {
        try {
          return chainOf(store.ro, t.sub, String(t.mode), u as never);
        } catch (e) {
          // 链路拼不出来（数据坏了）不该让整个任务查不了 —— 把话带上就行。
          return `（拼不出来：${e instanceof Error ? e.message : String(e)}）`;
        }
      })(),
    };
  };

  return [
    {
      method: "POST",
      path: "/tasks",
      group: TASK,
      does: "发一个任务",
      why: "**外面往系统里放活，只走这一个口。** 准入闸（来源、G、readable）判在这儿 —— 绕过它直接往 `task` 表插行，那道闸就等于没有。",
      params: [
        { name: "id", in: "body", kind: "string", required: true, note: "任务 id，全库唯一。重了当场拒" },
        { name: "mode", in: "body", kind: "string", required: true, note: "走哪种执行模式 → `GET /modes`" },
        { name: "agent", in: "body", kind: "string", required: true, note: "交给哪个智能体 → `GET /agents`" },
        { name: "place", in: "body", kind: "string", required: true, note: "在哪儿干 → `GET /places`" },
        { name: "source", in: "body", kind: "string", required: true, only: SOURCES, note: "谁发的。**这是准入判据不是元数据** —— 只有 `user` 能带 G" },
        { name: "description", in: "body", kind: "string", required: true, note: "自然语言的任务描述。内核透明，怎么解读是智能体的事" },
        { name: "cycle", in: "body", kind: "string", note: "从哪个周期起步。不给就取 `from` 为空的那一个；**起点不止一个时必须给**" },
        { name: "instance", in: "body", kind: "string", note: "哪个实例。不给按任务 id 生一个" },
        { name: "workdir", in: "body", kind: "string", note: "那个场所里的落脚路径。空 = 那台机器上的 cwd" },
        { name: "run", in: "body", kind: "string", note: "属于哪一跑（bench 用）。空 = 不属于任何一跑" },
        { name: "maxBranches", in: "body", kind: "int", note: "同时最多开几条分支" },
        { name: "maxDeadSiblings", in: "body", kind: "int", note: "同一个父底下判死几个兄弟就回退到更上层换方向" },
        { name: "solveSeconds", in: "body", kind: "int", note: "整道题的求解时长上限，秒。到点内核判 failed" },
        { name: "objective", in: "body", kind: "object", of: "G 的 DAG 定义", note: "验证函数 G。**绑定发生在发布这一刻，是准入条件**；过不了定义期检测就拒收整个任务" },
        { name: "readable", in: "body", kind: "boolean", note: "智能体能不能直接读到 G 的定义。**带 G 就必须显式给，没有默认值**" },
      ],
      returns: { id: "t-1", mode: "dfs", cycle: "open", instance: "t-1#1", objective: false },
      errs: [
        { code: 400, when: "**这道题根本别发布**：id 重了、模式/地方没登记、来源不许带 G、G 过不了定义期检测" },
      ],
      handler: async (a, _req, reply) => {
        const r = publish(store.rw, a as unknown as Publish, sealed);
        wake();
        return reply.code(201).send(r);
      },
    },
    {
      method: "GET",
      path: "/tasks",
      group: TASK,
      does: "列任务，可按状态 / 模式 / 智能体 / 一跑 / 来源筛",
      why: "**带上进度**（几个执行单元、干完几个）。客户端要显示一条进度条，否则得对每个任务再打一次子表。",
      params: [
        { name: "state", in: "query", kind: "string", only: STATES, note: "只看这个状态的" },
        { name: "mode", in: "query", kind: "string", note: "只看这个模式的" },
        { name: "agent", in: "query", kind: "string", note: "只看这个智能体接的" },
        { name: "run", in: "query", kind: "string", note: "只看这一跑的" },
        { name: "source", in: "query", kind: "string", only: SOURCES, note: "只看这个来源的" },
        { name: "q", in: "query", kind: "string", note: "描述里搜一段字" },
        { name: "limit", in: "query", kind: "int", def: 50, note: "要几条" },
        { name: "offset", in: "query", kind: "int", def: 0, note: "从第几条开始" },
        { name: "order", in: "query", kind: "string", only: ["created_at", "id", "state"], def: "created_at", note: "按什么排" },
        { name: "dir", in: "query", kind: "string", only: ["asc", "desc"], def: "desc", note: "升还是降" },
      ],
      returns: {
        total: 42,
        limit: 50,
        offset: 0,
        rows: [
          {
            id: "t-1", mode: "dfs", agent: "solver", place: "local", state: "claimed",
            source: "user", run: "", created_at: 1788001988000, hasObjective: true,
            progress: { units: 5, done: 3 }, solveSeconds: 900, elapsedMs: 41000,
          },
        ],
      },
      handler: async (a) => {
        const where: string[] = [];
        const p: unknown[] = [];
        const eq = (col: string, v: unknown) => {
          if (v !== undefined) {
            where.push(`${col} = ?`);
            p.push(v);
          }
        };
        eq("state", a.state);
        eq("mode", a.mode);
        eq("run", a.run);
        eq("source", a.source);
        if (a.q !== undefined) {
          where.push(`description like ?`);
          p.push(`%${String(a.q)}%`);
        }
        const w = where.length ? ` where ${where.join(" and ")}` : "";
        const total = Number((all(store.ro, `select count(*) c from task${w}`, p)[0] as { c: number }).c);
        const rows = all(
          store.ro,
          `select * from task${w} order by "${String(a.order)}" ${String(a.dir)} limit ? offset ?`,
          [...p, Number(a.limit), Number(a.offset)],
        );
        const now = Date.now();
        const out = rows
          .map((t) => {
            const sub = tableNameOf("task_{}", String(t.mode));
            const g = has(store, sub)
              ? (one(store, `select count(*) n, coalesce(sum(done),0) d from "${sub}" where task = ?`, [t.id]) as {
                  n: number; d: number;
                })
              : { n: 0, d: 0 };
            const agents = has(store, sub)
              ? (all(store.ro, `select distinct agent from "${sub}" where task = ?`, [t.id]) as { agent: string }[]).map(
                  (r) => r.agent,
                )
              : [];
            return {
              id: t.id, mode: t.mode, place: t.place, state: t.state, source: t.source,
              run: t.run, description: t.description, created_at: Number(t.created_at),
              agents,
              hasObjective: Boolean(t.objective),
              progress: { units: Number(g.n), done: Number(g.d) },
              solveSeconds: Number(t.solve_seconds),
              elapsedMs: now - Number(t.created_at),
            };
          })
          .filter((r) => a.agent === undefined || r.agents.includes(String(a.agent)));
        return { total, limit: Number(a.limit), offset: Number(a.offset), rows: out };
      },
    },
    {
      method: "GET",
      path: "/tasks/:id",
      group: TASK,
      does: "一个任务的全貌：主表那行 + G 的判决 + 每个执行单元",
      why: "把主表、subTable、G、时限**一次给全**。分成四个口的话客户端要打四次，而且中间库还会变 —— 拼出来的是四个时刻的快照。",
      params: [{ name: "id", in: "path", kind: "string", required: true, note: "任务 id" }],
      returns: {
        id: "t-1", state: "claimed",
        objective: { has: true, agentReadable: false, verdict: null },
        solve: { limitSeconds: 900, elapsedMs: 41000, leftMs: 859000, overdue: false },
        units: [{ cycle: "open", unit: 1, phase: "done", chain: "dfs/open#1", deadlineInMs: null }],
      },
      errs: [{ code: 404, when: "没有这个任务" }],
      handler: async (a, _req, reply) => {
        const t = taskOf(store, String(a.id));
        if (!t) return reply.code(404).send({ error: `没有这个任务：${String(a.id)}` });
        const units = has(store, t.sub)
          ? all(store.ro, `select * from "${t.sub}" where task = ? order by unit`, [t.id])
          : [];
        const now = Date.now();
        const limitMs = Number(t.solve_seconds) * 1000;
        let verdict: unknown = null;
        try {
          verdict = t.result ? JSON.parse(String(t.result)) : null;
        } catch {
          verdict = t.result;
        }
        return {
          ...t,
          sub: undefined,
          subTable: t.sub,
          objective: {
            has: Boolean(t.objective),
            // **只说有没有、读不读得到，不给定义** —— G 存在封存区，主库够不着。
            agentReadable: Number(t.readable ?? 0) === 1,
            verdict,
          },
          solve: {
            limitSeconds: Number(t.solve_seconds),
            elapsedMs: now - Number(t.created_at),
            leftMs: Number(t.created_at) + limitMs - now,
            overdue: now - Number(t.created_at) > limitMs,
          },
          units: units.map((u) => unitOf(t, u)),
        };
      },
    },
    {
      method: "GET",
      path: "/tasks/:id/tree",
      group: TASK,
      does: "执行单元的树",
      why: "**依据是子表里的 `from_cycle`/`from_unit` 指针**，客户端拼一遍等于把内核那段抄一份。这儿直接给嵌好的树，画就是了。",
      params: [{ name: "id", in: "path", kind: "string", required: true, note: "任务 id" }],
      returns: {
        roots: [{ cycle: "open", unit: 1, status: null, phase: "done", children: [{ cycle: "act", unit: 2, children: [] }] }],
        orphans: [],
      },
      errs: [{ code: 404, when: "没有这个任务" }],
      handler: async (a, _req, reply) => {
        const t = taskOf(store, String(a.id));
        if (!t) return reply.code(404).send({ error: `没有这个任务：${String(a.id)}` });
        if (!has(store, t.sub)) return { roots: [], orphans: [] };
        const rows = all(store.ro, `select * from "${t.sub}" where task = ? order by unit`, [t.id]);
        const key = (c: unknown, u: unknown) => `${String(c)}#${String(u)}`;
        const nodes = new Map(rows.map((r) => [key(r.cycle, r.unit), { ...unitOf(t, r), children: [] as unknown[] }]));
        const roots: unknown[] = [];
        const orphans: unknown[] = [];
        for (const r of rows) {
          const me = nodes.get(key(r.cycle, r.unit))!;
          if (r.from_cycle === null || r.from_unit === null) {
            roots.push(me);
            continue;
          }
          const parent = nodes.get(key(r.from_cycle, r.from_unit));
          // 父指的那一行不在 —— 数据坏了。**单列出来**，不要静静挂到根上：
          // 挂上去的话树看着是完整的，而它其实断了。
          if (parent) parent.children.push(me);
          else orphans.push(me);
        }
        return { roots, orphans };
      },
    },
    {
      method: "GET",
      path: "/tasks/:id/messages",
      group: TASK,
      does: "这个任务的上下文：它看见了什么、说了什么、请求了哪个工具",
      why: "消息存在 `agent_<名字>_msg` 里，**表名是长出来的** —— 客户端要自己拼表名就得知道那条改名规则（非法字符换下划线）。而且 `call`/`tool` 那两种的 `body` 是 JSON，这儿替它解开。",
      params: [
        { name: "id", in: "path", kind: "string", required: true, note: "任务 id" },
        { name: "unit", in: "query", kind: "int", note: "只看某一个执行单元的" },
        { name: "kind", in: "query", kind: "string", note: "只看某一种消息 → `GET /about` 的「消息类型」" },
        { name: "limit", in: "query", kind: "int", def: 200, note: "要几条" },
        { name: "offset", in: "query", kind: "int", def: 0, note: "从第几条开始" },
      ],
      returns: {
        total: 7,
        rows: [
          { unit: 1, seq: 1, role: "user", kind: "user", human: true, at: 1788001988000, body: "…", text: "…" },
          { unit: 1, seq: 3, role: "assistant", kind: "call", body: "…", parsed: { text: "", calls: [] } },
        ],
      },
      errs: [{ code: 404, when: "没有这个任务，或者它一个执行单元都还没有" }],
      handler: async (a, _req, reply) => {
        const t = taskOf(store, String(a.id));
        if (!t) return reply.code(404).send({ error: `没有这个任务：${String(a.id)}` });
        if (!has(store, t.sub)) return { total: 0, rows: [] };
        const pairs = all(store.ro, `select distinct agent, instance from "${t.sub}" where task = ?`, [t.id]) as {
          agent: string; instance: string;
        }[];
        const rows: Row[] = [];
        for (const { agent, instance } of pairs) {
          const table = tableNameOf("agent_{}_msg", agent);
          if (!has(store, table)) continue;
          const w: string[] = [`instance = ?`];
          const p: unknown[] = [instance];
          if (a.unit !== undefined) {
            w.push(`unit = ?`);
            p.push(Number(a.unit));
          }
          if (a.kind !== undefined) {
            w.push(`kind = ?`);
            p.push(String(a.kind));
          }
          for (const m of all(store.ro, `select * from "${table}" where ${w.join(" and ")} order by unit, seq`, p)) {
            rows.push({ agent, ...m });
          }
        }
        rows.sort((x, y) => Number(x.unit) - Number(y.unit) || Number(x.seq) - Number(y.seq));
        const page = rows.slice(Number(a.offset), Number(a.offset) + Number(a.limit));
        return {
          total: rows.length,
          limit: Number(a.limit),
          offset: Number(a.offset),
          rows: page.map((m) => {
            const body = String(m.body ?? "");
            const human = body.startsWith(HUMAN_MARK);
            const out: Row = {
              agent: m.agent, instance: m.instance, unit: m.unit, seq: m.seq,
              role: m.role, kind: m.kind, at: Number(m.at), body,
              human: human,
            };
            // 标记在这儿剥，不让客户端自己截字符串 —— 它一旦硬编码 "【人】"，
            // 这边一改那边就全乱。
            if (human) out.text = body.slice(HUMAN_MARK.length);
            if (m.kind === "call" || m.kind === "tool" || m.kind === "inject") {
              try {
                out.parsed = JSON.parse(body);
              } catch {
                // 解不开就算了，`body` 原样还在，不是丢了
              }
            }
            return out;
          }),
        };
      },
    },
    {
      method: "POST",
      path: "/tasks/:id/messages",
      group: TASK,
      does: "干预：在它跑的时候往上下文里插一句话",
      why: "`msg_kind` 里一直有 `intervene`（「用户看着它执行时施加的干预标记」），**但在这个口之前没有任何一处写它** —— 那一行是个空位。人给的东西缀 `【人】`，落在哪个单元上是**算**出来的（当前那个没干完的），不用客户端自己找。",
      params: [
        { name: "id", in: "path", kind: "string", required: true, note: "任务 id" },
        { name: "body", in: "body", kind: "string", required: true, note: "要说的话" },
        { name: "unit", in: "body", kind: "int", note: "插进哪个执行单元。不给就插进当前那个没干完的" },
      ],
      returns: { task: "t-1", agent: "solver", instance: "t-1#1", unit: 3, seq: 4, kind: "user" },
      errs: [
        { code: 404, when: "没有这个任务" },
        { code: 409, when: "没有正在跑的执行单元可以插 —— 任务已经完了，或者一个单元都还没开" },
      ],
      handler: async (a, _req, reply) => {
        const t = taskOf(store, String(a.id));
        if (!t) return reply.code(404).send({ error: `没有这个任务：${String(a.id)}` });
        if (!has(store, t.sub)) return reply.code(409).send({ error: `${String(a.id)} 一个执行单元都还没有` });
        const where = a.unit !== undefined ? `and unit = ?` : `and done = 0`;
        const p = a.unit !== undefined ? [t.id, Number(a.unit)] : [t.id];
        const u = one(store, `select agent, instance, unit from "${t.sub}" where task = ? ${where} order by unit desc`, p);
        if (!u) {
          return reply.code(409).send({
            error:
              a.unit !== undefined
                ? `${String(a.id)} 没有第 ${String(a.unit)} 个执行单元`
                : `${String(a.id)} 没有正在跑的执行单元 —— 它已经完了（state=${String(t.state)}）`,
          });
        }
        const seq = deliver(store.rw, {
          agent: String(u.agent),
          instance: String(u.instance),
          unit: Number(u.unit),
          by: "user",
          body: String(a.body),
        });
        wake();
        return { task: t.id, agent: u.agent, instance: u.instance, unit: u.unit, seq, kind: "user" };
      },
    },
    {
      method: "GET",
      path: "/tasks/:id/why",
      group: TASK,
      does: "这个任务为什么不动",
      why: "**「谁都不接而且不报错」是这台机器最常见的一种故障** —— 任务躺在库里，状态永远是 open，没人知道为什么。该问的这儿一次问完：模式在不在、地方登没登记、轨挑不挑得中、句柄注册没、卡在哪个单元、还有多久判死。客户端自己问一遍，就得把内核挑轨那段逻辑抄一份。",
      params: [{ name: "id", in: "path", kind: "string", required: true, note: "任务 id" }],
      returns: {
        id: "t-1", state: "open", movable: false,
        problems: ["走的模式 dfs 在任务周期表里没有 —— 这个任务谁都接不了，而且不会报错"],
        stuckAt: null,
      },
      errs: [{ code: 404, when: "没有这个任务" }],
      handler: async (a, _req, reply) => {
        const t = taskOf(store, String(a.id));
        if (!t) return reply.code(404).send({ error: `没有这个任务：${String(a.id)}` });
        const problems: string[] = [];
        const now = Date.now();

        if (all(store.ro, `select 1 from cycle where mode = ?`, [t.mode]).length === 0) {
          problems.push(`走的模式 ${String(t.mode)} 在任务周期表里没有 —— 这个任务谁都接不了，而且不会报错`);
        }
        if (all(store.ro, `select 1 from workplace where place = ?`, [t.place]).length === 0) {
          problems.push(`干活的地方 ${String(t.place)} 没登记`);
        }
        if (!has(store, t.sub)) problems.push(`subTable ${t.sub} 还没长出来 —— 打一下 POST /install`);

        const units = has(store, t.sub)
          ? (all(store.ro, `select * from "${t.sub}" where task = ? order by unit`, [t.id]) as Row[])
          : [];
        if (units.length === 0 && has(store, t.sub)) {
          problems.push(`一个执行单元都没有 —— 多半是绕过发布口直接插的 task 行`);
        }

        let stuckAt: unknown = null;
        for (const u of units.filter((x) => Number(x.done) === 0)) {
          const info = unitOf(t, u);
          if (!info.handle) {
            problems.push(
              `${String(u.cycle)}#${String(u.unit)}：挑不出这一站该调的句柄 —— ` +
                `多半是 ${String(u.agent)} 的 apis 里没有一条支持 ${String(t.mode)}/${String(u.cycle)} 要的调用形状`,
            );
          } else if (!reg.has(info.handle)) {
            problems.push(`${String(u.cycle)}#${String(u.unit)}：要调 ${info.handle}，但进程里没有这个句柄`);
          }
          if (info.deadlineInMs !== null && info.deadlineInMs < 0) {
            problems.push(
              `${String(u.cycle)}#${String(u.unit)}：已经超过时限 ${-info.deadlineInMs}ms —— 内核会判死它`,
            );
          }
          stuckAt ??= info;
        }

        const limitMs = Number(t.solve_seconds) * 1000;
        if (String(t.state) !== "done" && String(t.state) !== "failed" && now - Number(t.created_at) > limitMs) {
          problems.push(`整道题超过 solve_seconds=${String(t.solve_seconds)}s 了 —— 内核会判 failed`);
        }

        return { id: t.id, state: t.state, movable: problems.length === 0, problems, stuckAt };
      },
    },
  ];
}
