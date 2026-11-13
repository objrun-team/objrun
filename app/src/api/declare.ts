/**
 * Declarations: **these endpoints are the external interface for configuring a machine**.
 *
 * Clients must not configure it through raw SQL. That couples them to table layouts, so schema
 * changes break clients, often silently. More importantly, **a mode is a graph, while INSERT
 * writes one row at a time**. Inserting the third row cannot reveal that the first row's `next`
 * points to the wrong destination.
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

/** Three declaration types share the same parameter structure; reuse it across three endpoints to prevent drift. */
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
 * How to write `when`. Include this explanation with every endpoint accepting `when`.
 *
 * Clients should not need to know the `trigger` schema or invent group numbers.
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
        // This step connects to the server and fetches tools/list, so await it.
        // Connection failures must be reported before touching the database: an unreachable declared server is invalid.
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
        // A non-forwarding place has no connection: it is just the name of where an execution unit runs.
        // Returning alive:false without this explanation would incorrectly make it look broken.
        if (row && !Number(row.forward) && place !== "local") {
          return { place, alive: true, ms: 0, why: "this place does not forward, so there is no connection to probe" };
        }
        // **Probing and forwarding are two operations (`op`) of the same handle.** Separate handles
        // would force custom forwarding implementations to satisfy two contracts for the same concern:
        // forwarding is possible only when the destination is reachable.
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
 * List one type of declaration, reconstruct grouped `when` conditions, and determine
 * **whether it can never trigger**.
 *
 * The kernel defines "no conditions = never triggers"; clients must not independently reinterpret
 * it. Treating it as "always triggers" would report a healthy configuration even though no agent
 * could ever receive the tool.
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
      // System tools ignore conditions, so this issue does not apply to them.
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

/** Agents compatible with a mode must provide a lane for the invocation shape required by every station. */
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

/** A lane as exposed to clients. **No secret value is included**; see below. */
interface Track {
  keyEnv: string;
  model: string;
  handle: string | null;
  modes: string[];
  /** Whether the corresponding `api` row exists. Without it, this lane cannot be selected. */
  registered: boolean;
  /** Whether the environment variable has a value. */
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
      // **Return presence, never the value.** Secrets must not enter databases, logs, or API responses.
      // Presence is enough to show whether a lane is configured. Displaying the secret itself would
      // be a different capability, which this service deliberately does not provide.
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
