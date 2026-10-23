/**
 * 声明 —— **外面把一台机器配起来，只走这几个口。**
 *
 * 客户端不该拿原始 SQL 去配机器：那等于把表结构焊进客户端，表一改它就坏，
 * 而且坏得很安静。更要命的是**模式是一张图，而 insert 是一行一行的** ——
 * 写第三行的时候没人知道第一行的 `next` 指错了地方。
 */

import type { Registry } from "../engine/registry.ts";
import type { Store } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import { apply, dump, inspect, type Declare } from "../declare/index.ts";
import { install } from "../install/index.ts";
import type { Servers } from "../mcp/client.ts";
import { HOPS_HANDLE, type Pong } from "../place/index.ts";
import type { Route } from "./spec.ts";

const DECL = "declare";

/** 一份声明里的三样，参数表长一个样 —— 三个口共用，省得写三遍还写歪。 */
const BUNDLE = [
  {
    name: "servers",
    in: "body" as const,
    kind: "array" as const,
    of: "{ name, command?, args?, env?, url?, headers?, tools?: { <toolName>: { when?, expectMs?, system?, usable?, prompt?, concurrent? } } }",
    note:
      "An MCP server: a bulk source, not another way to register. The shape matches mcpServers in claude_desktop_config.json: " +
      "`command`/`args`/`env` spawns a child process, or `url`/`headers` goes over HTTP. It reports its own tools through `tools/list`, so they need not be written one by one; " +
      "the `tools` field is ours (MCP has no such thing). A server that cannot be reached is rejected outright",
  },
  {
    name: "places",
    in: "body" as const,
    kind: "array" as const,
    of: "{ place, runtime?, forward?, tools?: [{tool, policy: always|agent}], usable? }",
    note: "Where work happens. `place` is a layered address string: `local` / `wsl:Ubuntu-24.04` / `ssh://box-7` / `wsl/docker:build-01`",
  },
  {
    name: "modes",
    in: "body" as const,
    kind: "array" as const,
    of: "{ mode, note?, cycles: [{ cycle, apiMode?, maxUnits?, from?, next?, infer }] }",
    note: "An execution mode. A mode is a graph: every cycle named by `from`/`next` must be in this mode, and reachable from an entry point",
  },
  {
    name: "agents",
    in: "body" as const,
    kind: "array" as const,
    of: "{ name, apis: [[key_env, model]], unit, config?, state? }",
    note: "Agents. `apis` lists the lanes it carries; each must have a real row in the api table",
  },
  {
    name: "handles",
    in: "body" as const,
    kind: "array" as const,
    of: "{ name, expectMs }",
    note: "Out-of-process handles (`http://` / `https://`). `fn:` handles are in-process, shipped with the binary, and cannot be registered from outside. `expectMs` is how long before it counts as dead - the same rule inside and out",
  },
  {
    name: "tools",
    in: "body" as const,
    kind: "array" as const,
    of: "{ name, identity, does, params, output, prompt?, concurrent?, system?, usable?, when? }",
    note: "Tools written one at a time. `identity` points at a handle, in-process `fn:` or out-of-process `http://`. `does`/`params`/`output` are what the model reads. To let a server report its own, use `servers` - the rows that land in the database are the same",
  },
  {
    name: "rules",
    in: "body" as const,
    kind: "array" as const,
    of: "{ identity, does, params, writes, scope, access?, when? }",
    note: "Rules. `identity` is the handle name. One hung on a moment (`dim: \"moment\"` in `when`) is a hook - there is no separate hook table",
  },
  {
    name: "skills",
    in: "body" as const,
    kind: "array" as const,
    of: "{ identity, does, params, role, body?, usable?, when? }",
    note: "Skills. The model does not pick them; they are injected when `when` matches. An empty `body` means dynamically generated, which requires a handle of the same name to produce the content on demand",
  },
];

/**
 * `when` 怎么写 —— 这段跟着每个收 `when` 的口一起给出去。
 *
 * 客户端不用知道 `trigger` 表长什么样，更不用自己编组号。
 */
const WHEN_NOTE =
  "When its turn comes: `[[term,term],[term]]` - the outer level is groups, OR across groups, AND within a group. " +
  "One term = `{dim, key, op, value}`; `dim` is agent/task/cycle/chain/moment, " +
  "`chain` and `moment` have no attributes (leave key empty); `op` is eq/ne/contains/not_contains/prefix/suffix/in. " +
  "No terms at all means never fires, not always fires - defined the other way round, anything whose terms were forgotten would fire everywhere.";

const ALL_OR_NOTHING = {
  code: 400,
  when: "One bad spot rejects the whole declaration. It returns `problems` with every problem at once - reported one at a time, ten mistakes would mean ten round trips",
};

export function declareRoutes(store: Store, reg: Registry, pool: Servers, onWrite: () => void): Route[] {
  return [
    {
      method: "POST",
      path: "/declare",
      group: DECL,
      does: "Load one whole declaration: handles / places / modes / agents / tools / rules / skills",
      why:
        "These depend on each other: a tool identity needs a handle, a trigger owner must really exist, an agent lane needs a row in the api table, and the api mode a cycle asks for needs a handle that serves it. " +
        "Split across several routes, a client could legally leave the system half-declared, with the mistake surfacing only once it runs. Sub-tables are grown as part of loading, so no restart is needed.\n" +
        "      " + WHEN_NOTE,
      params: BUNDLE,
      returns: {
        handles: [],
        places: ["local"],
        modes: ["dfs"],
        cycles: 2,
        agents: ["solver"],
        tools: [],
        rules: [],
        skills: [],
        tables: ["task_dfs", "agent_solver_ctx", "agent_solver_msg"],
        entries: { dfs: ["open"] },
      },
      errs: [ALL_OR_NOTHING],
      handler: async (a, _req, reply) => {
        // 连 server、拉 tools/list 都在这一步里，所以是 await。
        // 连不上就抛 —— 声明一个连不上的 server 是错，得在动库之前说。
        const r = await apply(store.rw, reg, pool, a as Declare);
        onWrite();
        return reply.code(201).send(r);
      },
    },
    {
      method: "POST",
      path: "/declare/inspect",
      group: DECL,
      does: "Validate only, write nothing: is this declaration sound",
      why: "A client uses it as a pre-save check: a person edits a declaration in the UI and validates as they go, without writing to the database. It takes exactly what `/declare` takes.",
      params: BUNDLE,
      returns: {
        ok: false,
        problems: [
          "mode dfs/act: next names done, which is not in this mode",
          "mode dfs/scope: unreachable from any entry point - this cycle would never be used",
        ],
      },
      handler: async (a) => {
        const problems = inspect(store.ro, reg, a as Declare);
        return { ok: problems.length === 0, problems };
      },
    },
    {
      method: "GET",
      path: "/declare",
      group: DECL,
      does: "Export this machine current declaration in full",
      why: "The shape is exactly what `POST /declare` takes, so it can be fed straight back. Export a config and rebuild it on another machine is then two calls, with nothing for the client to assemble.",
      returns: { places: [{ place: "local" }], modes: [], agents: [] },
      handler: async () => dump(store.ro),
    },
    {
      method: "GET",
      path: "/modes",
      group: DECL,
      does: "Which modes exist, and whether each is walkable",
      why: "`walkable` and `agents` are computed here: the latter crosses `agent.apis` with `api.modes` and `cycle.api_mode`. Computing it client-side means copying the kernel lane-selection logic - and a wrong copy raises no error.",
      returns: {
        modes: [{ mode: "dfs", cycles: 2, entries: ["open"], walkable: true, agents: ["solver"], runningTasks: 3 }],
      },
      handler: async () => {
        const d = dump(store.ro);
        return {
          modes: d.modes!.map((m) => ({
            mode: m.mode,
            note: m.note ?? null,
            cycles: m.cycles.length,
            entries: m.cycles.filter((c) => (c.from ?? []).length === 0).map((c) => c.cycle),
            walkable: inspect(store.ro, reg, { modes: [m] }).length === 0,
            agents: agentsFor(store, m.mode),
            runningTasks: Number(
              (all(store.ro, `select count(*) c from task where mode = ? and state not in ('done','failed')`, [
                m.mode,
              ])[0] as { c: number }).c,
            ),
          })),
        };
      },
    },
    {
      method: "GET",
      path: "/modes/:mode",
      group: DECL,
      does: "What the graph of one mode looks like",
      params: [{ name: "mode", in: "path", kind: "string", required: true, note: "Mode name" }],
      returns: {
        mode: "dfs",
        entries: ["open"],
        walkable: true,
        problems: [],
        agents: ["solver"],
        cycles: [{ cycle: "open", apiMode: "chat", maxUnits: 1, from: [], next: ["act"], infer: "fn:infer.dfs" }],
      },
      errs: [{ code: 404, when: "no such mode" }],
      handler: async (a, _req, reply) => {
        const m = dump(store.ro).modes!.find((x) => x.mode === a.mode);
        if (!m) return reply.code(404).send({ error: `no such mode: ${String(a.mode)}` });
        const problems = inspect(store.ro, reg, { modes: [m] });
        return {
          ...m,
          entries: m.cycles.filter((c) => (c.from ?? []).length === 0).map((c) => c.cycle),
          walkable: problems.length === 0,
          problems,
          agents: agentsFor(store, m.mode),
        };
      },
    },
    {
      method: "GET",
      path: "/agents",
      group: DECL,
      does: "Which agents exist, and which lanes each carries",
      why: "`keySet` reports whether the environment variable has a value. The value itself never leaves the database or the API - a client showing whether a lane is configured has only this boolean to go on.",
      returns: {
        agents: [
          {
            name: "solver",
            state: "idle",
            unit: "fn:api.deepseek",
            tracks: [{ keyEnv: "DEEPSEEK_API_KEY", model: "deepseek-chat", modes: ["chat", "tools"], keySet: true }],
            modes: ["dfs"],
            running: 2,
          },
        ],
      },
      handler: async () => ({ agents: dump(store.ro).agents!.map((a) => detailOf(store, a.name)!) }),
    },
    {
      method: "GET",
      path: "/agents/:name",
      group: DECL,
      does: "One agent: its lanes, whether the keys are set, which modes it can serve, how much it is working on now",
      params: [{ name: "name", in: "path", kind: "string", required: true, note: "Agent name" }],
      errs: [{ code: 404, when: "no such agent" }],
      handler: async (a, _req, reply) => {
        const d = detailOf(store, String(a.name));
        if (!d) return reply.code(404).send({ error: `no such agent: ${String(a.name)}` });
        return d;
      },
    },
    {
      method: "GET",
      path: "/places",
      group: DECL,
      does: "Which places work can happen in",
      returns: { places: [{ place: "local", forward: false, tools: [], usable: true, runtime: null }] },
      handler: async () => ({ places: dump(store.ro).places }),
    },
    {
      method: "POST",
      path: "/places/:place/ping",
      group: DECL,
      does: "Probe this place right now",
      why: "Probed on the spot, never written back. `workplace.usable` is a registration, not a liveness reading - written back, that column becomes a stale lie after any crash and restart.",
      params: [{ name: "place", in: "path", kind: "string", required: true, note: "The place string" }],
      returns: { place: "wsl", alive: true, ms: 812 },
      handler: async (a) => {
        const place = String(a.place);
        const row = all(store.ro, `select identity, forward from workplace where place = ?`, [place])[0] as
          | { identity: string | null; forward: number }
          | undefined;
        // 不转发的地方压根没有连接这回事 —— 它只是「这一站在哪儿」的一个名字。
        // 不说清楚的话这儿会回一个 alive:false，看着像坏了。
        if (row && !Number(row.forward) && place !== "local") {
          return { place, alive: true, ms: 0, why: "this place does not forward, so there is no connection to probe" };
        }
        // **探活跟转发是同一条句柄的两个动作**（`op`）。分两条的话，写自定义转发的
        // 人得实现两个契约，而这两件本来就是同一件事的两面：够得着才转得过去。
        const identity = String(row?.identity ?? "").trim() || HOPS_HANDLE;
        const t0 = Date.now();
        try {
          const pong = (await reg.get(identity).call({ place, op: "ping" })) as Pong;
          return { place, alive: Boolean(pong?.alive), ms: Date.now() - t0, ...(pong?.why ? { why: pong.why } : {}) };
        } catch (e) {
          return { place, alive: false, ms: Date.now() - t0, why: e instanceof Error ? e.message : String(e) };
        }
      },
    },
    {
      method: "GET",
      path: "/tools",
      group: DECL,
      does: "Which tools are registered, and when each gets attached",
      why: "`when` is reconstructed here (the table stores one term per row with a group number), so a client need not bucket by group itself. The `neverFires` bit matters most: not a system tool and no terms means nobody ever gets it, and that raises no error.",
      returns: {
        tools: [
          {
            name: "weather", identity: "http://127.0.0.1:9010/weather", system: false, usable: true,
            when: [[{ dim: "task", key: "description", op: "contains", value: "weather" }]],
            neverFires: false,
          },
        ],
      },
      handler: async () => ({ tools: listOf(store, "tool", "name") }),
    },
    {
      method: "GET",
      path: "/rules",
      group: DECL,
      does: "Which rules are registered, and when each is hung",
      why: "A rule hung on a moment (`dim: \"moment\"`) is a hook - there is no separate hook table, so hooks are read through this route too.",
      returns: {
        rules: [
          {
            identity: "http://127.0.0.1:9010/audit",
            when: [[{ dim: "moment", key: "", op: "eq", value: "pre_send" }]],
            neverFires: false,
          },
        ],
      },
      handler: async () => ({ rules: listOf(store, "rule", "identity") }),
    },
    {
      method: "GET",
      path: "/skills",
      group: DECL,
      does: "Which skills are registered",
      why: "An empty `body` means dynamically generated: the handle of the same name produces the content at trigger time. This is the bit a client reads to show whether a skill is fixed or generated.",
      returns: {
        skills: [{ identity: "recap", role: "user", dynamic: false, usable: true, when: [], neverFires: true }],
      },
      handler: async () => ({ skills: listOf(store, "skill", "identity") }),
    },
    {
      method: "POST",
      path: "/install",
      group: DECL,
      does: "Grow the tables the declaration calls for. Idempotent, safe to call any time",
      why: "`/declare` already grows them once; this route is the fallback for when the database was edited by hand, or a new mode arrived some other way, and the sub-tables need to catch up.",
      returns: { create: ["task_dfs"], ok: 12, extra: [] },
      handler: async () => {
        const r = install(store.rw);
        onWrite();
        return { create: r.create, ok: r.ok.length, extra: r.extra };
      },
    },
  ];
}

/**
 * 一类东西的清单，`when` 还原成组的形状，并且算出**它会不会永远不触发**。
 *
 * 「一条条件都没有 = 从不触发」这条语义写在内核里，客户端不该自己再判一遍 ——
 * 判反了（当成「总是触发」）它会告诉用户一切正常，而实际上那个工具谁都拿不到。
 */
function listOf(store: Store, kind: "tool" | "rule" | "skill", idCol: string) {
  const rows = all(store.ro, `select * from "${kind}" order by "${idCol}"`) as Record<string, unknown>[];
  return rows.map((r) => {
    const id = String(r[idCol]);
    const when = whenOfRow(store, kind, id);
    const system = kind === "tool" && Boolean(r.system);
    return {
      ...(kind === "tool" ? { name: id } : { identity: id }),
      identity: String(r.identity ?? id),
      does: r.does ?? null,
      ...(kind === "tool" ? { system, concurrent: Boolean(r.concurrent) } : {}),
      ...(kind === "skill" ? { role: r.role ?? null, dynamic: !r.body } : {}),
      usable: r.usable === undefined ? true : Boolean(r.usable),
      when,
      // 系统工具不看条件，所以它没有这个毛病。
      neverFires: !system && when.length === 0,
    };
  });
}

function whenOfRow(store: Store, kind: string, owner: string) {
  const rows = all(
    store.ro,
    `select "group", dim, "key", op, value from trigger where owner_kind = ? and owner = ? order by "group"`,
    [kind, owner],
  ) as { group: number; dim: string; key: string; op: string; value: string }[];
  const by = new Map<number, { dim: string; key: string; op: string; value: string }[]>();
  for (const r of rows) {
    const g = Number(r.group);
    by.set(g, [...(by.get(g) ?? []), { dim: r.dim, key: r.key, op: r.op, value: r.value }]);
  }
  return [...by].sort((a, b) => a[0] - b[0]).map(([, t]) => t);
}

/** 哪些智能体接得住这个模式：它每一站要的调用形状，这个智能体都得有一条轨。 */
function agentsFor(store: Store, mode: string): string[] {
  const wants = [
    ...new Set(
      (all(store.ro, `select api_mode from cycle where mode = ? and api_mode is not null`, [mode]) as {
        api_mode: string;
      }[])
        .map((r) => String(r.api_mode).trim())
        .filter(Boolean),
    ),
  ];
  return (all(store.ro, `select name from agent order by name`) as { name: string }[])
    .map((r) => r.name)
    .filter((name) => wants.every((w) => tracksOf(store, name).some((t) => t.modes.includes(w))));
}

/** 一条轨在客户端眼里长什么样。**没有密钥这一项** —— 见下。 */
interface Track {
  keyEnv: string;
  model: string;
  handle: string | null;
  modes: string[];
  /** `api` 表里有没有这一行。没有的话这条轨挑不中。 */
  registered: boolean;
  /** 那个环境变量有没有值。 */
  keySet: boolean;
}

function tracksOf(store: Store, name: string): Track[] {
  const row = all(store.ro, `select apis from agent where name = ?`, [name])[0] as { apis: string } | undefined;
  if (!row) return [];
  let apis: [string, string][] = [];
  try {
    apis = JSON.parse(row.apis || "[]") as [string, string][];
  } catch {
    return [];
  }
  return apis.map(([keyEnv, model]) => {
    const r = all(store.ro, `select modes, handle from api where key_env = ? and model = ?`, [keyEnv, model])[0] as
      | { modes: string; handle: string }
      | undefined;
    return {
      keyEnv,
      model,
      handle: r?.handle ?? null,
      modes: String(r?.modes ?? "").split(",").map((x) => x.trim()).filter(Boolean),
      registered: Boolean(r),
      // **只回「在不在」，不回值。** 密钥不进库、不进日志、不进接口 ——
      // 客户端要显示「这条轨配好了没」，够用了；要显示密钥本身，那是另一回事，
      // 而这台机器不提供那回事。
      keySet: Boolean(process.env[keyEnv]),
    };
  });
}

function detailOf(store: Store, name: string) {
  const a = all(store.ro, `select name, config, apis, unit, state from agent where name = ?`, [name])[0] as
    | { name: string; config: string | null; apis: string; unit: string; state: string }
    | undefined;
  if (!a) return null;
  const modes = (all(store.ro, `select distinct mode from cycle order by mode`) as { mode: string }[]).map((r) => r.mode);
  return {
    name: a.name,
    state: a.state,
    config: a.config,
    unit: a.unit,
    tracks: tracksOf(store, name),
    modes: modes.filter((m) => agentsFor(store, m).includes(name)),
  };
}
