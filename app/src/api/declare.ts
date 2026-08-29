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
import { openPlace } from "../place/index.ts";
import type { Route } from "./spec.ts";

const DECL = "声明";

/** 一份声明里的三样，参数表长一个样 —— 三个口共用，省得写三遍还写歪。 */
const BUNDLE = [
  {
    name: "servers",
    in: "body" as const,
    kind: "array" as const,
    of: "{ name, command?, args?, env?, url?, headers?, tools?: { <工具名>: { when?, expectMs?, system?, usable?, prompt?, concurrent? } } }",
    note:
      "MCP server。**形状跟 claude_desktop_config.json 里那个 mcpServers 一样**：`command`/`args`/`env` 起个子进程，" +
      "或者 `url`/`headers` 走 HTTP。**有哪些工具是它自己用 `tools/list` 报的，你不用一个个写**；" +
      "`tools` 那一项是我们补的（MCP 里没有这几样）。连不上当场拒",
  },
  {
    name: "places",
    in: "body" as const,
    kind: "array" as const,
    of: "{ place, runtime?, forward?, tools?: [{tool, policy: always|agent}], usable? }",
    note: "在哪儿干。`place` 是带层级的地址串：`local` / `wsl:Ubuntu-24.04` / `ssh://box-7` / `wsl/docker:build-01`",
  },
  {
    name: "modes",
    in: "body" as const,
    kind: "array" as const,
    of: "{ mode, note?, cycles: [{ cycle, apiMode?, maxUnits?, from?, next?, infer }] }",
    note: "执行模式。**一个模式是一张图** —— `from`/`next` 指的周期必须都在这个模式里，而且从起点走得到",
  },
  {
    name: "agents",
    in: "body" as const,
    kind: "array" as const,
    of: "{ name, apis: [[key_env, model]], unit, config?, state? }",
    note: "智能体。`apis` 挂哪几条轨，每条得在 api 表里真有那一行",
  },
  {
    name: "handles",
    in: "body" as const,
    kind: "array" as const,
    of: "{ name, expectMs }",
    note: "外面注册进来的句柄。**只能是 `http://` / `https://`** —— `fn:` 是进程内的真函数，往库里写个名字换不出函数来。`expectMs` 是多久算死",
  },
  {
    name: "tools",
    in: "body" as const,
    kind: "array" as const,
    of: "{ name, identity, does, params, output, prompt?, concurrent?, system?, usable?, when? }",
    note: "工具。`identity` 指一个句柄；`does`/`params`/`output` 是**给模型看的**。`system: true` 的所有智能体一上来就有，不看 `when`",
  },
  {
    name: "rules",
    in: "body" as const,
    kind: "array" as const,
    of: "{ identity, does, params, writes, scope, access?, when? }",
    note: "规则。`identity` 就是句柄名。挂在时刻上（`when` 里写 `dim: \"moment\"`）就是钩子 —— **不另开钩子表**",
  },
  {
    name: "skills",
    in: "body" as const,
    kind: "array" as const,
    of: "{ identity, does, params, role, body?, usable?, when? }",
    note: "skill。模型不挑它，是按 `when` 塞进去的。`body` 留空 = 动态生成，那就得真有个同名句柄现给内容",
  },
];

/**
 * `when` 怎么写 —— 这段跟着每个收 `when` 的口一起给出去。
 *
 * 客户端不用知道 `trigger` 表长什么样，更不用自己编组号。
 */
const WHEN_NOTE =
  "什么时候轮到它：`[[条件,条件],[条件]]` —— **外层是组，组间 or；组内 and**。" +
  "一条 = `{dim, key, op, value}`；`dim` 是 agent/task/cycle/chain/moment，" +
  "`chain` 和 `moment` 不看属性（key 留空）；`op` 是 eq/ne/contains/not_contains/prefix/suffix/in。" +
  "**一条都不给 = 永远不触发**，不是「总是触发」—— 反过来定的话，忘了写条件的东西会到处乱开。";

const ALL_OR_NOTHING = {
  code: 400,
  when: "一处不过整份不写。回 `problems`，**把全部问题一次说全** —— 一次说一条的话你得改一行发一次，十处错来回十趟",
};

export function declareRoutes(store: Store, reg: Registry, pool: Servers, onWrite: () => void): Route[] {
  return [
    {
      method: "POST",
      path: "/declare",
      group: DECL,
      does: "灌一整份声明：句柄 / 在哪儿干 / 模式 / 智能体 / 工具 / 规则 / skill",
      why:
        "这几样**互相依赖**：工具的 identity 要有句柄、触发条件的 owner 要真存在、智能体的轨要 api 表有那一行、周期要的调用形状得有句柄接得住。" +
        "拆成几个口的话，客户端可以合法地把系统灌成「一半声明」，而错要等到跑起来那一刻才冒出来。灌完子表现长出来，**不用重启**。\n" +
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
      does: "只验不写：这份声明有没有毛病",
      why: "客户端拿它做**保存前预检** —— 用户在界面上编一份声明，边编边验，不用真写进库。收的东西跟 `/declare` 一模一样。",
      params: BUNDLE,
      returns: {
        ok: false,
        problems: [
          "mode dfs/act：next 指的 done 不在这个模式里",
          "mode dfs/scope：从起点走不到它 —— 这个周期永远不会被用上",
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
      does: "把这台机器现在的声明整份导出来",
      why: "形状跟 `POST /declare` 收的**一模一样，可以直接回灌**。于是「导出配置 / 在另一台上重建」就是两次调用，客户端不用自己拼。",
      returns: { places: [{ place: "local" }], modes: [], agents: [] },
      handler: async () => dump(store.ro),
    },
    {
      method: "GET",
      path: "/modes",
      group: DECL,
      does: "有哪些模式，各自走不走得通",
      why: "`walkable` 和 `agents` 是**这边算的**：后者要把 `agent.apis` × `api.modes` × `cycle.api_mode` 交叉一遍。客户端自己算等于把内核挑轨那段逻辑抄一份 —— 抄错了还不报错。",
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
      does: "一个模式的图长什么样",
      params: [{ name: "mode", in: "path", kind: "string", required: true, note: "模式名" }],
      returns: {
        mode: "dfs",
        entries: ["open"],
        walkable: true,
        problems: [],
        agents: ["solver"],
        cycles: [{ cycle: "open", apiMode: "chat", maxUnits: 1, from: [], next: ["act"], infer: "fn:infer.dfs" }],
      },
      errs: [{ code: 404, when: "没有这个模式" }],
      handler: async (a, _req, reply) => {
        const m = dump(store.ro).modes!.find((x) => x.mode === a.mode);
        if (!m) return reply.code(404).send({ error: `没有这个模式：${String(a.mode)}` });
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
      does: "有哪些智能体，各自挂了哪几条轨",
      why: "`keySet` 查的是环境变量有没有值。**值本身永远不出库、不出接口** —— 客户端要显示「这条轨配好了没」，只能靠这个布尔。",
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
      does: "一个智能体：轨、钥匙配没配、接得住哪些模式、现在在干几件事",
      params: [{ name: "name", in: "path", kind: "string", required: true, note: "智能体名" }],
      errs: [{ code: 404, when: "没有这个智能体" }],
      handler: async (a, _req, reply) => {
        const d = detailOf(store, String(a.name));
        if (!d) return reply.code(404).send({ error: `没有这个智能体：${String(a.name)}` });
        return d;
      },
    },
    {
      method: "GET",
      path: "/places",
      group: DECL,
      does: "有哪些干活的地方",
      returns: { places: [{ place: "local", forward: false, tools: [], usable: true, runtime: null }] },
      handler: async () => ({ places: dump(store.ro).places }),
    },
    {
      method: "POST",
      path: "/places/:place/ping",
      group: DECL,
      does: "现探一下这个地方通不通",
      why: "**现探，不写回库。** `workplace.usable` 是登记不是探活 —— 写回去的话，崩了重启读到的那一列就是过期的谎话。",
      params: [{ name: "place", in: "path", kind: "string", required: true, note: "位置串" }],
      returns: { place: "wsl", alive: true, ms: 812 },
      handler: async (a) => {
        const place = String(a.place);
        const row = all(store.ro, `select runtime from workplace where place = ?`, [place])[0] as
          | { runtime: string | null }
          | undefined;
        const t0 = Date.now();
        try {
          const p = await openPlace(place, row?.runtime ?? undefined);
          const alive = await p.alive();
          p.close();
          return { place, alive, ms: Date.now() - t0 };
        } catch (e) {
          return { place, alive: false, ms: Date.now() - t0, why: e instanceof Error ? e.message : String(e) };
        }
      },
    },
    {
      method: "GET",
      path: "/tools",
      group: DECL,
      does: "注册了哪些工具，各自什么时候会被挂上",
      why: "`when` 是**还原**出来的（库里那张表存的是一行一条、带组号），客户端不用自己按组号分堆。`neverFires` 那一位尤其要紧：不是系统工具又没有条件 = 谁都拿不到它，而这**不报错**。",
      returns: {
        tools: [
          {
            name: "weather", identity: "http://127.0.0.1:9010/weather", system: false, usable: true,
            when: [[{ dim: "task", key: "description", op: "contains", value: "天气" }]],
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
      does: "注册了哪些规则，各自挂在什么时候",
      why: "挂在时刻上（`dim: \"moment\"`）的就是钩子 —— **不另开钩子表**，所以要看钩子也是查这个口。",
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
      does: "注册了哪些 skill",
      why: "`body` 留空的是**动态生成**的 —— 内容由同名句柄在触发那一刻现给。客户端要显示「这条 skill 是写死的还是现生成的」，看的就是这一位。",
      returns: {
        skills: [{ identity: "recap", role: "user", dynamic: false, usable: true, when: [], neverFires: true }],
      },
      handler: async () => ({ skills: listOf(store, "skill", "identity") }),
    },
    {
      method: "POST",
      path: "/install",
      group: DECL,
      does: "照着声明把该有的表建出来。幂等，随时能打",
      why: "`/declare` 已经自己长过一次了，这个口是**兜底**：手工改过库、或者别的路子灌了新模式，打一下让子表跟上。",
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
