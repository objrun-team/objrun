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
import { deliver, HUMAN_KINDS, HUMAN_MARK } from "../msg/deliver.ts";
import type { Sealed } from "../objective/store.ts";
import { publish, SOURCES, STATES, type Publish } from "../tasks/publish.ts";
import type { Route } from "./spec.ts";

const TASK = "tasks";

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
          return `(cannot be assembled: ${e instanceof Error ? e.message : String(e)})`;
        }
      })(),
    };
  };

  return [
    {
      method: "POST",
      path: "/tasks",
      group: TASK,
      does: "Publish one task",
      why: "Work enters the system through this route and no other. The admission gate (source, grading function, readable) is judged here - insert into the `task` table directly and the gate may as well not exist.",
      params: [
        { name: "id", in: "body", kind: "string", required: true, note: "Task id, unique across the database. A duplicate is rejected outright" },
        { name: "mode", in: "body", kind: "string", required: true, note: "Which execution mode to walk -> `GET /modes`" },
        { name: "agent", in: "body", kind: "string", required: true, note: "Which agent it goes to -> `GET /agents`" },
        { name: "place", in: "body", kind: "string", required: true, note: "Where the work happens -> `GET /places`" },
        { name: "source", in: "body", kind: "string", required: true, only: SOURCES, note: "Who published it. This is an admission criterion, not metadata - only `user` may carry a grading function" },
        { name: "description", in: "body", kind: "string", required: true, note: "The task description in natural language. Transparent to the kernel; how to read it is the agent business" },
        { name: "domain", in: "body", kind: "string", note: "Which kind of problem this is (`physics` / `chem` / `coding` ...). Extensions dispatch on it: a skill / tool / rule states its applicability as a `dim=task, key=domain` term. A different axis from `mode`: `mode` is the reasoning mechanism, this is the field" },
        { name: "cycle", in: "body", kind: "string", note: "Which cycle to start from. Omitted, the one with an empty `from` is taken; required when there is more than one entry point" },
        { name: "instance", in: "body", kind: "string", note: "Which instance. Omitted, one is generated from the task id" },
        { name: "workdir", in: "body", kind: "string", note: "The landing path inside that place. Empty = the cwd on that machine" },
        { name: "run", in: "body", kind: "string", note: "Which run it belongs to (used by bench). Empty = no run" },
        { name: "maxBranches", in: "body", kind: "int", note: "How many branches may be open at once" },
        { name: "maxDeadSiblings", in: "body", kind: "int", note: "How many dead siblings under one parent before backtracking a level to change direction" },
        { name: "solveSeconds", in: "body", kind: "int", note: "Upper bound on solving time for the whole task, in seconds. At the limit the kernel marks it failed" },
        { name: "objective", in: "body", kind: "object", of: "The DAG definition of the grading function", note: "The verification function. Binding happens at publish time and is an admission condition; failing the definition-time checks rejects the whole task" },
        { name: "readable", in: "body", kind: "boolean", note: "Whether the agent may read the definition of the grading function directly. Required whenever one is carried; there is no default" },
      ],
      returns: { id: "t-1", mode: "dfs", cycle: "open", instance: "t-1#1", objective: false },
      errs: [
        { code: 400, when: "this task should not be published at all: duplicate id, unregistered mode or place, a source not allowed to carry a grading function, or one that fails the definition-time checks" },
      ],
      handler: async (a, _req, reply) => {
        // **发布这一路的拒收全是 400。** 「这道题根本别发布」是请求的问题，
        // 不是系统坏了 —— 回 500 的话，客户端会当成服务端故障去重试，
        // 而重试多少次结果都一样。
        let r: unknown;
        try {
          r = publish(store.rw, a as unknown as Publish, sealed);
        } catch (e) {
          return reply.code(400).send({ error: e instanceof Error ? e.message : String(e) });
        }
        wake();
        return reply.code(201).send(r);
      },
    },
    {
      method: "GET",
      path: "/tasks",
      group: TASK,
      does: "List tasks, filtered by state / mode / agent / run / source",
      why: "Progress is included (how many execution units, how many finished). Without it, a client showing a progress bar would have to hit the sub-table once per task.",
      params: [
        { name: "state", in: "query", kind: "string", only: STATES, note: "Only this state" },
        { name: "mode", in: "query", kind: "string", note: "Only this mode" },
        { name: "agent", in: "query", kind: "string", note: "Only what this agent took" },
        { name: "run", in: "query", kind: "string", note: "Only this run" },
        { name: "source", in: "query", kind: "string", only: SOURCES, note: "Only this source" },
        { name: "q", in: "query", kind: "string", note: "Search a substring in the description" },
        { name: "limit", in: "query", kind: "int", def: 50, note: "How many rows" },
        { name: "offset", in: "query", kind: "int", def: 0, note: "Which row to start at" },
        { name: "order", in: "query", kind: "string", only: ["created_at", "id", "state"], def: "created_at", note: "What to order by" },
        { name: "dir", in: "query", kind: "string", only: ["asc", "desc"], def: "desc", note: "Ascending or descending" },
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
      does: "The whole picture of one task: its main row, the grading verdict, and every execution unit",
      why: "The main row, the sub-table, the grading function and the deadlines all come at once. Split across four routes, a client would make four calls while the database moved underneath - assembling a snapshot of four different moments.",
      params: [{ name: "id", in: "path", kind: "string", required: true, note: "Task id" }],
      returns: {
        id: "t-1", state: "claimed",
        objective: { has: true, agentReadable: false, verdict: null },
        solve: { limitSeconds: 900, elapsedMs: 41000, leftMs: 859000, overdue: false },
        units: [{ cycle: "open", unit: 1, phase: "done", chain: "dfs/open#1", deadlineInMs: null }],
      },
      errs: [{ code: 404, when: "no such task" }],
      handler: async (a, _req, reply) => {
        const t = taskOf(store, String(a.id));
        if (!t) return reply.code(404).send({ error: `no such task: ${String(a.id)}` });
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
      does: "The tree of execution units",
      why: "It is built from the `from_cycle`/`from_unit` pointers in the sub-table; assembling it client-side means copying that piece of the kernel. Here the tree comes already nested, ready to draw.",
      params: [{ name: "id", in: "path", kind: "string", required: true, note: "Task id" }],
      returns: {
        roots: [{ cycle: "open", unit: 1, status: null, phase: "done", children: [{ cycle: "act", unit: 2, children: [] }] }],
        orphans: [],
      },
      errs: [{ code: 404, when: "no such task" }],
      handler: async (a, _req, reply) => {
        const t = taskOf(store, String(a.id));
        if (!t) return reply.code(404).send({ error: `no such task: ${String(a.id)}` });
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
      does: "The context of this task: what it saw, what it said, which tools it asked for",
      why: "Messages live in `agent_<name>_msg`, and that table name is grown - assembling it client-side means knowing the renaming rule (illegal characters become underscores). The `body` of `call` and `tool` rows is JSON, and it is unpacked here.",
      params: [
        { name: "id", in: "path", kind: "string", required: true, note: "Task id" },
        { name: "unit", in: "query", kind: "int", note: "Only one execution unit" },
        { name: "kind", in: "query", kind: "string", note: "Only one message kind -> the message kinds in `GET /about`" },
        { name: "limit", in: "query", kind: "int", def: 200, note: "How many rows" },
        { name: "offset", in: "query", kind: "int", def: 0, note: "Which row to start at" },
      ],
      returns: {
        total: 7,
        rows: [
          { unit: 1, seq: 1, role: "user", kind: "user", human: true, at: 1788001988000, body: "…", text: "…" },
          { unit: 1, seq: 3, role: "assistant", kind: "call", body: "…", parsed: { text: "", calls: [] } },
        ],
      },
      errs: [{ code: 404, when: "no such task, or it has no execution units yet" }],
      handler: async (a, _req, reply) => {
        const t = taskOf(store, String(a.id));
        if (!t) return reply.code(404).send({ error: `no such task: ${String(a.id)}` });
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
            // **判据是 `kind`，不是 body 长什么样。**
            //
            // 按前缀判的话，模型只要在回答开头复读一句 `【人】` 就被当成人写的 ——
            // 实测它真的会这么干（上下文里人写的那条就带着这个前缀，它照着学）。
            // `kind` 是投递那一刻推出来的，模型伪造不了。
            const human = HUMAN_KINDS.has(String(m.kind));
            const out: Row = {
              agent: m.agent, instance: m.instance, unit: m.unit, seq: m.seq,
              role: m.role, kind: m.kind, at: Number(m.at), body,
              human,
            };
            // 标记在这儿剥，不让客户端自己截字符串 —— 它一旦硬编码 "【人】"，
            // 这边一改那边就全乱。
            if (human && body.startsWith(HUMAN_MARK)) out.text = body.slice(HUMAN_MARK.length);
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
      does: "Intervene: put a line into the context while it runs",
      why: "`msg_kind` has always had `intervene` (a mark left by a user intervening while it runs), but before this route nothing ever wrote it - that row was an empty slot. Anything from a person is prefixed, and which unit it lands on is computed (the current unfinished one) rather than left to the client to find.",
      params: [
        { name: "id", in: "path", kind: "string", required: true, note: "Task id" },
        { name: "body", in: "body", kind: "string", required: true, note: "What to say" },
        { name: "unit", in: "body", kind: "int", note: "Which execution unit to insert into. Omitted, the current unfinished one" },
      ],
      returns: { task: "t-1", agent: "solver", instance: "t-1#1", unit: 3, seq: 4, kind: "user" },
      errs: [
        { code: 404, when: "no such task" },
        { code: 409, when: "there is no running execution unit to insert into - the task is over, or no unit has been opened yet" },
      ],
      handler: async (a, _req, reply) => {
        const t = taskOf(store, String(a.id));
        if (!t) return reply.code(404).send({ error: `no such task: ${String(a.id)}` });
        if (!has(store, t.sub)) return reply.code(409).send({ error: `${String(a.id)} has no execution units yet` });
        const where = a.unit !== undefined ? `and unit = ?` : `and done = 0`;
        const p = a.unit !== undefined ? [t.id, Number(a.unit)] : [t.id];
        const u = one(store, `select agent, instance, unit from "${t.sub}" where task = ? ${where} order by unit desc`, p);
        if (!u) {
          return reply.code(409).send({
            error:
              a.unit !== undefined
                ? `${String(a.id)} has no execution unit ${String(a.unit)}`
                : `${String(a.id)} has no running execution unit - it is already over (state=${String(t.state)})`,
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
      does: "Why this task is not moving",
      why: "Nobody picks it up and nothing reports it is the most common failure on this machine: the task sits in the database, state stays open, and no one knows why. Everything worth asking is asked here at once: is the mode there, is the place registered, can a lane be selected, is the handle registered, which unit is stuck, how long until it is declared dead. Asking it client-side means copying the kernel lane-selection logic.",
      params: [{ name: "id", in: "path", kind: "string", required: true, note: "Task id" }],
      returns: {
        id: "t-1", state: "open", movable: false,
        problems: ["its mode dfs is not in the cycle table - nobody can pick this task up, and nothing reports it"],
        stuckAt: null,
      },
      errs: [{ code: 404, when: "no such task" }],
      handler: async (a, _req, reply) => {
        const t = taskOf(store, String(a.id));
        if (!t) return reply.code(404).send({ error: `no such task: ${String(a.id)}` });
        const problems: string[] = [];
        const now = Date.now();

        if (all(store.ro, `select 1 from cycle where mode = ?`, [t.mode]).length === 0) {
          problems.push(`its mode ${String(t.mode)} is not in the cycle table - nobody can pick this task up, and nothing reports it`);
        }
        if (all(store.ro, `select 1 from workplace where place = ?`, [t.place]).length === 0) {
          problems.push(`its place ${String(t.place)} is not registered`);
        }
        if (!has(store, t.sub)) problems.push(`the sub-table ${t.sub} has not been grown yet - call POST /install`);

        const units = has(store, t.sub)
          ? (all(store.ro, `select * from "${t.sub}" where task = ? order by unit`, [t.id]) as Row[])
          : [];
        if (units.length === 0 && has(store, t.sub)) {
          problems.push(`no execution units at all - most likely a task row inserted directly, bypassing the publish route`);
        }

        let stuckAt: unknown = null;
        for (const u of units.filter((x) => Number(x.done) === 0)) {
          const info = unitOf(t, u);
          if (!info.handle) {
            problems.push(
              `${String(u.cycle)}#${String(u.unit)}: cannot select a handle for this station - ` +
                `most likely none of the apis of ${String(u.agent)} serves the api mode ${String(t.mode)}/${String(u.cycle)} asks for`,
            );
          } else if (!reg.has(info.handle)) {
            problems.push(`${String(u.cycle)}#${String(u.unit)}: it would call ${info.handle}, but no such handle is registered in this process`);
          }
          if (info.deadlineInMs !== null && info.deadlineInMs < 0) {
            problems.push(
              `${String(u.cycle)}#${String(u.unit)}: over its deadline by ${-info.deadlineInMs}ms - the kernel will declare it dead`,
            );
          }
          stuckAt ??= info;
        }

        const limitMs = Number(t.solve_seconds) * 1000;
        if (String(t.state) !== "done" && String(t.state) !== "failed" && now - Number(t.created_at) > limitMs) {
          problems.push(`the whole task is over solveSeconds=${String(t.solve_seconds)}s - the kernel will mark it failed`);
        }

        // 内核推某一行时炸过的话，它把话落在了那一行的上下文里。**捞出来。**
        // 只留在日志里的话，看日志的人和被卡住的人不是同一个 —— 而客户端手里只有接口。
        for (const u of units) {
          const table = tableNameOf("agent_{}_msg", String(u.agent));
          if (!has(store, table)) continue;
          for (const r of all(
            store.ro,
            `select body from "${table}" where instance = ? and unit = ? and kind = 'inject' and role = 'system'`,
            [u.instance, u.unit],
          ) as { body: string }[]) {
            try {
              const v = JSON.parse(r.body) as { stuck?: string };
              if (v.stuck) problems.push(`${String(u.cycle)}#${String(u.unit)}: the kernel threw while advancing it - ${v.stuck}`);
            } catch {
              // 不是那种记账行，跳过
            }
          }
        }

        return { id: t.id, state: t.state, movable: problems.length === 0, problems, stuckAt };
      },
    },
  ];
}
