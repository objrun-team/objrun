/**
 * The declaration layer: **external callers configure an engine through this one endpoint.**
 *
 * ## Why not ask users to insert rows?
 *
 * The database exposes a full interface: `/exec` can insert rows with `insert into cycle …`. That is for people who know the tables, not ordinary users. **An unrestricted interface hands the schema to the user**, and incorrect writes may produce no error.
 *
 * Worse, **a mode is a graph, while insert operates one row at a time**. When writing the third row, nobody knows that the first row's `next` points to the wrong place. Graph integrity can only be established after all rows exist, by which time they have been written. The result looks like a working engine but has no valid path: a task starts, stops partway through, and stays `claimed` forever without an error.
 *
 * ## Accept and validate a complete declaration; one failure prevents every write
 *
 * This follows `/bench`'s rule that one invalid problem prevents the entire batch from being dispatched. With a partial declaration, configuration faults appear only when a task runs, and look indistinguishable from an uncooperative model.
 *
 * Accept all three together because **they depend on one another**: agent tracks require matching `api` rows, cycle call shapes require compatible handles, and tasks require all three. Separate endpoints would allow a legally accepted "half declaration", precisely what this file prevents.
 *
 * After validation, write in one transaction and create the subtables immediately. Call `POST /tasks` as soon as declaration finishes; no restart is needed.
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import { registrable, type Registry } from "../engine/registry.ts";
import { DIMS, MOMENTS, OPS } from "../engine/trigger.ts";
import type { Servers } from "../mcp/client.ts";
import { inspectServer, pull, type ServerDecl } from "../mcp/register.ts";
import { install, tableNameOf } from "../install/index.ts";
import { MODE_NAMES } from "../llm/index.ts";
import { HOPS_HANDLE, hops } from "../place/index.ts";
import { withSubmit } from "../tree/dfs.ts";

/** Default lifetime when an MCP tool does not specify when to mark it dead. This covers one tool call, not an entire solve. */
export const MCP_EXPECT_MS = 120_000;

/** A location where work can run. */
export interface PlaceDecl {
  /** A hierarchical address: `local` / `wsl` / `ssh://box-7` / `wsl/docker:build-01` … */
  place: string;
  /**
   * **Who forwards tool calls to this location** → `handle.name`.
   *
   * Required when forwarding is enabled (validated below). The built-in handle is `fn:place.hops` (the `wsl` / `ssh` / `docker` command prefixes). An `http://…` handle or an `fn:` handle with a `module` lets that machine supply its own implementation: reaching a location is the handle's responsibility, not the kernel's.
   */
  identity?: string | null;
  /** The runtime to transfer (a local file path). Leave empty for `local`. */
  runtime?: string | null;
  /** Whether to forward tool calls there. Disabled by default. */
  forward?: boolean;
  /** Allowlist: tools that may be forwarded, with their individual policies (`always` / `agent`). */
  tools?: { tool: string; policy: string }[];
  /** Declared availability. **A declaration, not a health probe**; available by default. */
  usable?: boolean;
}

/** One cycle in a mode. */
export interface CycleDecl {
  cycle: string;
  /** The call shape required at this station (`chat` / `duplex` / …). **Empty = no model at this station**. */
  apiMode?: string | null;
  mustCall?: string | null;
  /** Maximum execution units to open in this cycle. Defaults to 1. */
  maxUnits?: number;
  /** Cycles in this mode that normally lead here. **Empty = an entry point**. */
  from?: string[];
  /** Normal successor cycles. **Empty = stop here**. */
  next?: string[];
  /** Inference-function handle name: chooses one candidate from `next`. */
  infer: string;
}

/** A mode = a graph of connected cycles. */
export interface ModeDecl {
  mode: string;
  cycles: CycleDecl[];
  note?: string;
}

/** An agent. */
export interface AgentDecl {
  name: string;
  /** Tracks to attach, each `[key_env, model]`; the corresponding row must exist in `api`. */
  apis: [string, string][];
  /** Execution-unit handle: called when this station does not use a model. */
  unit: string;
  config?: string | null;
  state?: string;
  /**
   * Model parameters **fixed for this agent**. Unspecified parameters fall back to the configuration for the whole run.
   *
   * These belong to the agent because they describe the agent, not the run. An agent that looks up information and reports it clearly does not need reasoning, while the solver it serves should reason as much as possible: one knob cannot control both. In measurements on the same question, `none` took 14.5 seconds and `low` took 113 seconds.
   */
  knobs?: Record<string, unknown>;
}

/**
 * One trigger condition.
 *
 * `dim` identifies the dimension (`agent` / `task` / `cycle` / `chain` / `moment` / `place`), and `key` identifies its property. **`chain`, `moment`, and `place` do not inspect properties; leave it empty**.
 */
export interface TermDecl {
  dim: string;
  key?: string;
  op: string;
  value: string;
}

/**
 * When this item applies. **The outer array contains groups: OR between groups, AND within each group.**
 *
 * Group numbers are derived here from array indexes; clients need not manage them. Otherwise clients would need to know the AND/OR semantics and avoid collisions with existing group numbers.
 *
 * **No conditions = never triggered**, not always triggered. The opposite convention would activate items everywhere when their conditions were accidentally omitted. (System tools with `system: true` are the exception: they ignore conditions.)
 */
export type WhenDecl = TermDecl[][];

/** An externally registered handle. */
export interface HandleDecl {
  name: string;
  /** Time after which a call is considered dead. The kernel marks it dead beyond this limit, **equally for internal and external handles**. */
  expectMs: number;
  /**
   * Where an `fn:` implementation comes from: `path#exportName` (defaults to `default` if the export name is omitted).
   *
   * **With this field, `fn:` can be registered externally**: the module runs in the kernel process, with no IPC per call. A function object cannot be transferred, but its location can. Out-of-process handles do not use this field.
   */
  module?: string | null;
}

/** A tool. `identity` points to a handle: an in-process `fn:` or an external `http://`. */
export interface ToolDecl {
  /** The model-facing name, also referenced by the `workplace` allowlist. */
  name: string;
  identity: string;
  /** The model-facing description. */
  does: string;
  /** The model-facing parameter schema. */
  params: unknown;
  /** The return-value schema, also shown to the model. */
  output: unknown;
  /** A usage convention to append to the system prompt. */
  prompt?: string | null;
  /** Whether it may run concurrently with other tools. */
  concurrent?: boolean;
  /** A system tool: available to all agents from the start, **ignoring `when`**. */
  system?: boolean;
  /**
   * The kind of content it returns → `msg_part.name`. Context compression uses this to decide what can be discarded.
   *
   * `look` can be observed again and becomes stale; `event` cannot be recovered; `receipt` is a bookkeeping line.
   * Omitted = `event`: treating irrecoverable information as recoverable is the one direction of error we cannot afford.
   */
  gives?: string | null;
  access?: string | null;
  usable?: boolean;
  when?: WhenDecl;
}

/**
 * A compression method. **The same shape as a tool**: a name, a handle that performs it, inputs, and outputs.
 *
 * Declared and built-in methods are the same kind of row (`press_how`), so a method requiring a model need not enter the kernel: implement it externally and declare it.
 */
export interface HowDecl {
  /** The name stored in the l1/l2/l3 columns of `msg_part`. */
  name: string;
  identity: string;
  /** Input JSON schema. */
  params: unknown;
  /** Output JSON schema. */
  output: unknown;
  note?: string | null;
}

/** A rule. Attached to a moment, it acts as a hook (`dim: "moment"`). */
export interface RuleDecl {
  identity: string;
  does: string;
  params: unknown;
  /** Declare which tables it changes and how. */
  writes: unknown;
  /** Rows it may modify. Structured matching expressions, not SQL fragments. */
  scope: unknown;
  /** How an external rule accesses the database. **Store only the environment-variable name for a secret.** */
  access?: unknown;
  when?: WhenDecl;
}

/** A skill. Selected by conditions, not chosen by the model. */
export interface SkillDecl {
  identity: string;
  does: string;
  params: unknown;
  /** Static content. Empty = generated dynamically by the handle. */
  body?: string | null;
  role: string;
  usable?: boolean;
  when?: WhenDecl;
}

/**
 * A complete declaration. Any category may be omitted, but omitted items cannot be referenced by other items.
 *
 * **One validation failure prevents every write**: these categories reference one another (tool `identity` requires a handle, trigger owners must exist, agent tracks require matching `api` rows). Inserting them separately could legally produce a "half declaration", with errors appearing only at runtime.
 */
export interface Declare {
  /**
   * MCP server: **a bulk source**, not another registration mechanism.
   *
   * Its shape matches `mcpServers` in `claude_desktop_config.json`: `command` / `args` / `env` start a subprocess, or `url` / `headers` use HTTP. The server reports its tools through `tools/list`, saving individual declarations.
   *
   * **Individual declarations also work**: provide `tools` directly, with `identity` pointing to an `http://` handle. Both paths produce the same database rows.
   *
   * The `tools` section is **our addition**: when to show tools to the model (`when`), when to mark them dead (`expectMs`), and whether everyone receives them (`system`). MCP itself has none of these fields.
   */
  servers?: ServerDecl[];
  handles?: HandleDecl[];
  places?: PlaceDecl[];
  modes?: ModeDecl[];
  agents?: AgentDecl[];
  tools?: ToolDecl[];
  hows?: HowDecl[];
  rules?: RuleDecl[];
  skills?: SkillDecl[];
}

/** What to return after applying the declaration. */
export interface Declared {
  /** Tools reported by each server after connection. */
  servers: Record<string, string[]>;
  handles: string[];
  places: string[];
  modes: string[];
  cycles: number;
  agents: string[];
  tools: string[];
  rules: string[];
  skills: string[];
  /** Subtables created during this application. */
  tables: string[];
  /** Entry cycles for each mode. **With more than one, task submission must specify `cycle`**; report that here. */
  entries: Record<string, string[]>;
}

const POLICIES = ["always", "agent"];

function list(v: unknown, what: string, bad: string[]): string[] {
  if (v === undefined) return [];
  if (!Array.isArray(v) || v.some((x) => typeof x !== "string")) {
    bad.push(`${what} must be a list of cycle names`);
    return [];
  }
  return v as string[];
}

/**
 * Validate a complete declaration. **Return every issue instead of throwing on the first one.**
 *
 * Reporting one at a time forces a user to fix one line, resubmit, and read the next error: ten errors mean ten round trips. The declaration is authored as a whole, so report its problems together.
 */
export function inspect(db: Conn, reg: Registry, d: Declare): string[] {
  const bad: string[] = [];
  const say = (s: string) => bad.push(s);

  // ── MCP server ────────────────────────────────────────────────────────
  //
  // Connectivity requires an actual connection, handled by `apply`. Here, only validate the declaration itself.
  const servers = new Set<string>();
  for (const s of d.servers ?? []) {
    for (const w of inspectServer(s)) say(w);
    if (s.name) {
      if (servers.has(s.name)) say(`server ${s.name}: appears twice in this declaration`);
      servers.add(s.name);
    }
  }

  // ── Externally registered handles. **Validate this section first** ─────
  //
  // Modes, agents, tools, rules, and skills below reference handles. First collect the handles declared here; otherwise the natural pattern of declaring a handle and using it in the same declaration would be rejected.
  //
  // **Only `http://` / `https://` are allowed.** `fn:` handles are real in-process functions that only their process can hold. Writing an `fn:` name into `handle` externally creates an unclaimed handle; the error appears only when a task reaches it.
  const handles = new Set<string>();
  for (const h of d.handles ?? []) {
    const at = `handle ${h.name || "(unnamed)"}`;
    if (!h.name || !h.name.trim()) {
      say(`a handle has no name`);
      continue;
    }
    if (handles.has(h.name)) say(`${at}: appears twice in this declaration`);
    handles.add(h.name);
    if (!registrable(h.name, h.module)) {
      say(
        `${at}: recognised forms are http:// or https:// (another process), ` +
          `and fn: plus module (in-process, implementation on disk, written as path#exportName). ` +
          `a bare fn: name cannot be turned into a function - what cannot cross the wire is the function object, not where it lives`,
      );
    }
    if (!Number.isFinite(h.expectMs) || h.expectMs <= 0) say(`${at}: expectMs must be a positive number`);
  }

  /**
   * Is this handle available: newly declared here, registered in the process, or already recorded in the database?
   *
   * All three count. External handles must be usable for `infer`, `agent.unit`, and tool implementations; that is how external callers extend the engine. Consulting only the in-process registry would break that path.
   */
  const handleThere = (name: string) =>
    handles.has(name) || reg.has(name) || all(db, `select 1 from handle where name = ?`, [name]).length > 0;

  /** The missing-handle message. Explicitly say to declare it alongside the others in handles, so the user knows the next step. */
  const noHandle = (name: string) =>
    `there is no handle named ${name} - in-process fn: handles are registered by code, and http:// ones are given in the handles of this same declaration`;

  // ── Work locations ────────────────────────────────────────────────────
  const places = new Set<string>();
  for (const p of d.places ?? []) {
    const at = `place ${p.place || "(unnamed)"}`;
    if (!p.place || !p.place.trim()) {
      say(`a place has no name`);
      continue;
    }
    if (places.has(p.place)) say(`${at}: appears twice in this declaration`);
    places.add(p.place);
    for (const t of p.tools ?? []) {
      if (!POLICIES.includes(t.policy)) {
        say(`${at}: unrecognised policy for tool ${t.tool} (must be one of ${POLICIES.join(" / ")})`);
      }
    }
    if (p.forward) {
      // **Forwarding requires an explicit forwarding handle.**
      //
      // Previously this was unnecessary because reaching a location was compiled into the kernel: `hops` recognized only `wsl` / `ssh` / `docker`, with hard-coded command construction. A **machine property** such as Docker being installed through snap and only on the login shell's PATH had nowhere to go except changes to those three kernel functions.
      //
      // Locations now use handles just like tools and G nodes. Without a handle, failure would occur only when a task actually forwards a tool call, after the task is already underway.
      const identity = String(p.identity ?? "").trim();
      if (!identity) {
        say(`${at}: it forwards, but no handle was given to carry the calls there - name one in identity`);
      } else if (!handleThere(identity)) {
        say(`${at}: ${noHandle(identity)}`);
      }
      // ── The next two checks apply only to the built-in implementation ─────
      //
      // **Address parsing belongs to the handle.** `fn:place.hops` reads a sequence of hops (`wsl` / `ssh` / `docker`) to build command prefixes. Unknown syntax must fail immediately: guessing could connect somewhere else. Another handle must parse its own address format; `modal:sandbox-7` may be valid there and must not be rejected here.
      if (identity === HOPS_HANDLE) {
        try {
          hops(p.place);
        } catch (e) {
          say(`${at}: ${e instanceof Error ? e.message : String(e)}`);
        }
        // This implementation transfers a runtime. Without a declared source, it would fail on the first call.
        // **Do not ask this of other implementations**: whether and what to transfer also belongs to the handle.
        if (p.place !== "local" && !p.runtime) {
          say(`${at}: ${HOPS_HANDLE} ships a runtime over, but none was given - there is nothing to ship`);
        }
      }
      // Forwarding enabled with an empty allowlist = no tools are forwarded. **Valid, but certainly unintended.**
      if ((p.tools ?? []).length === 0) say(`${at}: forwarding is on but the allow-list is empty - not a single tool would be forwarded`);
    }
  }

  // ── Modes: validate the graph, not the rows ────────────────────────────
  const modes = new Set<string>();
  for (const m of d.modes ?? []) {
    const at = `mode ${m.mode || "(unnamed)"}`;
    if (!m.mode || !m.mode.trim()) {
      say(`a mode has no name`);
      continue;
    }
    if (modes.has(m.mode)) say(`${at}: appears twice in this declaration`);
    modes.add(m.mode);
    // The mode name must form a valid table name (`task_<mode>`); otherwise table installation would fail later.
    try {
      tableNameOf("task_{}", m.mode);
    } catch (e) {
      say(`${at}: ${e instanceof Error ? e.message : String(e)}`);
    }
    if (!Array.isArray(m.cycles) || m.cycles.length === 0) {
      say(`${at}: it has no cycles`);
      continue;
    }
    // Tree mechanisms add a submission station (`withSubmit` in `tree/dfs.ts`). **Validate the completed graph**:
    // validating the original graph would omit that added station from checks such as reachability from an entry point.
    m.cycles = withSubmit(m.cycles as never) as never;

    const names = new Set<string>();
    for (const c of m.cycles) {
      if (!c.cycle || !c.cycle.trim()) {
        say(`${at}: one of its cycles has no name`);
        continue;
      }
      if (names.has(c.cycle)) say(`${at}/${c.cycle}: this cycle name appears twice`);
      names.add(c.cycle);
    }

    for (const c of m.cycles) {
      const cat = `${at}/${c.cycle}`;
      const next = list(c.next, `the next of ${cat}`, bad);
      const from = list(c.from, `the from of ${cat}`, bad);
      // A cycle outside this mode can never be reached, and the kernel says nothing: it simply stops there.
      for (const n of next) if (!names.has(n)) say(`${cat}: next names ${n}, which is not in this mode`);
      for (const f of from) if (!names.has(f)) say(`${cat}: from names ${f}, which is not in this mode`);

      if (c.maxUnits !== undefined && (!Number.isInteger(c.maxUnits) || c.maxUnits < 1)) {
        say(`${cat}: max_units must be a positive integer`);
      }
      // An unregistered inference function fails only when execution reaches this station, halfway through the task.
      if (!c.infer || !c.infer.trim()) say(`${cat}: infer is missing`);
      else if (!handleThere(c.infer)) say(`${cat}: infer is ${c.infer}, but ${noHandle(c.infer)}`);

      const want = (c.apiMode ?? "").trim();
      if (want) {
        if (!MODE_NAMES.has(want)) {
          say(`${cat}: apiMode=${want} is not a known api mode (known: ${[...MODE_NAMES].join(", ")})`);
        } else if (!servedBy(db, want)) {
          say(`${cat}: it needs a ${want} lane, but no row in the api table serves one - every unit of this cycle is stuck`);
        }
      }
    }

    // Entry points have an empty `from`. None = the mode cannot be entered at all.
    const entries = m.cycles.filter((c) => list(c.from, "", []).length === 0).map((c) => c.cycle);
    if (entries.length === 0) say(`${at}: no entry point (every cycle has a non-empty from), so this mode cannot be entered`);

    // Cycles that nothing can reach. **They never execute and produce no error**: dead code remains in the declaration,
    // while the author probably believes it is running.
    const seen = new Set(entries);
    const queue = [...entries];
    while (queue.length) {
      const cur = queue.shift()!;
      const row = m.cycles.find((c) => c.cycle === cur);
      for (const n of list(row?.next, "", [])) {
        if (names.has(n) && !seen.has(n)) {
          seen.add(n);
          queue.push(n);
        }
      }
    }
    for (const c of m.cycles) {
      if (c.cycle && !seen.has(c.cycle)) say(`${at}/${c.cycle}: unreachable from any entry point - this cycle would never be used`);
    }
  }

  // ── Agents ────────────────────────────────────────────────────────────
  const agents = new Set<string>();
  for (const a of d.agents ?? []) {
    const at = `agent ${a.name || "(unnamed)"}`;
    if (!a.name || !a.name.trim()) {
      say(`an agent has no name`);
      continue;
    }
    if (agents.has(a.name)) say(`${at}: appears twice in this declaration`);
    agents.add(a.name);
    try {
      tableNameOf("agent_{}_ctx", a.name);
    } catch (e) {
      say(`${at}: ${e instanceof Error ? e.message : String(e)}`);
    }
    if (!a.unit || !a.unit.trim()) say(`${at}: unit is missing`);
    else if (!handleThere(a.unit)) say(`${at}: unit is ${a.unit}, but ${noHandle(a.unit)}`);

    if (!Array.isArray(a.apis)) {
      say(`${at}: apis must be a list of [key_env, model]`);
      continue;
    }
    for (const pair of a.apis) {
      if (!Array.isArray(pair) || pair.length !== 2) {
        say(`${at}: one entry of apis is not a [key_env, model] pair`);
        continue;
      }
      const [keyEnv, model] = pair;
      if (all(db, `select 1 from api where key_env = ? and model = ?`, [keyEnv, model]).length === 0) {
        say(`${at}: ${keyEnv}/${model} is not registered in the api table - this lane can never be selected`);
      }
    }
  }

  // ── Trigger conditions ────────────────────────────────────────────────
  //
  // The same validation as `check`, moved to **before the write**. Checking afterward leaves the bad condition in the database, where its behavior is never triggering, not raising an error.
  const colsOf = (t: string) => (all(db, `pragma table_info("${t}")`) as { name: string }[]).map((r) => r.name);
  const dimKeys: Record<string, string[]> = {
    agent: colsOf("agent"),
    task: colsOf("task"),
    cycle: colsOf("cycle"),
  };
  const checkWhen = (at: string, when: WhenDecl | undefined) => {
    for (const [i, group] of (when ?? []).entries()) {
      if (!Array.isArray(group) || group.length === 0) {
        say(`${at}: group ${i} is empty - an empty group never matches in full, so writing it changes nothing`);
        continue;
      }
      for (const t of group) {
        const where = `${at} group ${i}`;
        if (!(DIMS as readonly string[]).includes(t.dim)) {
          say(`${where}: unknown dimension ${t.dim} (known: ${DIMS.join(" / ")})`);
          continue;
        }
        if (!(OPS as readonly string[]).includes(t.op)) {
          say(`${where}: unknown operator ${t.op} (known: ${OPS.join(" / ")})`);
          continue;
        }
        if (t.dim === "chain" || t.dim === "moment" || t.dim === "place") {
          if ((t.key ?? "").trim() !== "") say(`${where}: dimension ${t.dim} has no attributes, so key must be empty`);
          if (t.dim === "moment" && !(MOMENTS as readonly string[]).includes(t.value)) {
            say(`${where}: unknown moment ${t.value} (the kernel raises: ${MOMENTS.join(" / ")})`);
          }
        } else if (!(dimKeys[t.dim] ?? []).includes(t.key ?? "")) {
          say(`${where}: dimension ${t.dim} has no attribute ${t.key ?? "(empty)"} (it has: ${(dimKeys[t.dim] ?? []).join(" / ")})`);
        }
        if (t.op === "in") {
          try {
            if (!Array.isArray(JSON.parse(t.value))) say(`${where}: the value for in must be a list, but it is ${t.value}`);
          } catch {
            say(`${where}: the value for in is not readable JSON: ${t.value}`);
          }
        }
        // A keyword containing spaces combines multiple words. The system does not guess whether adjacency or order was intended.
        if (t.op !== "in" && /\s/.test(t.value) && t.dim !== "task") {
          say(`${where}: the value contains a space (${JSON.stringify(t.value)}) - split it into two terms in the same group rather than letting the system guess`);
        }
      }
    }
  };

  // ── Tools ─────────────────────────────────────────────────────────────
  const tools = new Set<string>();
  for (const t of d.tools ?? []) {
    const at = `tool ${t.name || "(unnamed)"}`;
    if (!t.name || !t.name.trim()) {
      say(`a tool has no name`);
      continue;
    }
    if (tools.has(t.name)) say(`${at}: appears twice in this declaration`);
    tools.add(t.name);
    if (!t.identity || !handleThere(t.identity)) {
      say(`${at}: identity is ${t.identity ?? "(empty)"}, but ${noHandle(String(t.identity))}`);
    }
    if (!t.does) say(`${at}: does is missing - that is the description the model reads; empty means the model has no idea what it is for`);
    if (t.params === undefined || t.params === null) say(`${at}: params is missing - that is the argument schema the model reads`);
    if (t.output === undefined || t.output === null) say(`${at}: output is missing - that is the result schema the model reads`);
    checkWhen(at, t.when);
    // A non-system tool with no conditions is available to nobody. **Valid, but certainly unintended.**
    if (!t.system && (t.when ?? []).length === 0) {
      say(`${at}: not a system tool and it has no trigger terms - it would never be attached to any agent`);
    }
  }

  // ── Compression methods ───────────────────────────────────────────────
  const hows = new Set<string>();
  for (const h of d.hows ?? []) {
    const at = `press how ${h.name || "(unnamed)"}`;
    if (!h.name || !h.name.trim()) {
      say(`a way of pressing has no name`);
      continue;
    }
    if (hows.has(h.name)) say(`${at}: appears twice in this declaration`);
    hows.add(h.name);
    if (!h.identity || !handleThere(h.identity)) {
      say(`${at}: identity is ${h.identity ?? "(empty)"}, but ${noHandle(String(h.identity))}`);
    }
    // Both schemas are required. **Without clear inputs and outputs, nobody can validate the compressed result**.
    // Incorrectly compressed context can still be sent, making this one of the hardest errors to diagnose.
    if (h.params === undefined || h.params === null) say(`${at}: params is missing - what the handle is given must be declared`);
    if (h.output === undefined || h.output === null) say(`${at}: output is missing - what the handle answers must be declared`);
  }

  // ── Rules ─────────────────────────────────────────────────────────────
  const rules = new Set<string>();
  for (const r of d.rules ?? []) {
    const at = `rule ${r.identity || "(unnamed)"}`;
    if (!r.identity || !r.identity.trim()) {
      say(`a rule has no identity`);
      continue;
    }
    if (rules.has(r.identity)) say(`${at}: appears twice in this declaration`);
    rules.add(r.identity);
    if (!handleThere(r.identity)) {
      say(`${at}: a rule identity is the handle name, and ${noHandle(r.identity)}`);
    }
    if (r.writes === undefined || r.writes === null) say(`${at}: writes is missing - which tables it touches and how must be declared`);
    if (r.scope === undefined || r.scope === null) say(`${at}: scope is missing - which rows it may touch must be declared`);
    checkWhen(at, r.when);
    if ((r.when ?? []).length === 0) say(`${at}: no trigger terms at all - it would never run`);
  }

  // ── skill ─────────────────────────────────────────────────────────────
  const skills = new Set<string>();
  for (const s of d.skills ?? []) {
    const at = `skill ${s.identity || "(unnamed)"}`;
    if (!s.identity || !s.identity.trim()) {
      say(`a skill has no identity`);
      continue;
    }
    if (skills.has(s.identity)) say(`${at}: appears twice in this declaration`);
    skills.add(s.identity);
    // Empty `body` = dynamically generated, requiring an actual handle to provide it. Static content does not require one.
    if (!s.body && !handleThere(s.identity)) {
      say(`${at}: body is empty (dynamically generated), but ${noHandle(s.identity)} - nobody can produce the content on demand`);
    }
    if (!s.role) say(`${at}: role is missing`);
    checkWhen(at, s.when);
    if ((s.when ?? []).length === 0) say(`${at}: no trigger terms at all - it would never be injected`);
  }

  return bad;
}

/**
 * Apply a complete declaration. **Validate it all first; one failure prevents every write.**
 *
 * Write within one transaction. If an operation fails midway, roll back everything already written; otherwise the declaration would be half written, precisely what this module prevents.
 *
 * Create subtables immediately afterward (`install` is idempotent). Otherwise applying a declaration would still require a restart, breaking the ability to configure an engine entirely over HTTP.
 */
export async function apply(db: Conn, reg: Registry, pool: Servers, d: Declare): Promise<Declared> {
  const bad = inspect(db, reg, d);
  if (bad.length) {
    const e = new Error(`this declaration has ${bad.length} problems; nothing was written`) as Error & {
      statusCode?: number;
      problems?: string[];
    };
    e.statusCode = 400;
    e.problems = bad;
    throw e;
  }

  const before = new Set(tableNames(db));

  // ── Connect to servers and fetch tools **before opening the transaction** ──
  //
  // Connections require waiting; a SQLite transaction must not wait on network I/O. An unreachable server could hold the database lock until timeout. Moreover, a failed connection should be rejected before modifying the database: declaring an unreachable server is an error, just like declaring a nonexistent handle.
  const grew: Record<string, string[]> = {};
  for (const s of d.servers ?? []) {
    run(
      db,
      `insert into mcp_server (name, spec, note) values (?, ?, ?)
       on conflict(name) do update set spec = excluded.spec, note = excluded.note`,
      [
        s.name,
        JSON.stringify({
          ...(s.command ? { command: s.command, args: s.args ?? [], env: s.env ?? {} } : {}),
          ...(s.url ? { url: s.url, headers: s.headers ?? {} } : {}),
        }),
        null,
      ],
    );
    grew[s.name] = await pull(db, pool, { ...s, name: s.name }, s.tools, { expectMs: MCP_EXPECT_MS });
    // The server supplies tools; we supply `when`. Add it here using the same representation as other owners.
    for (const [tool, o] of Object.entries(s.tools ?? {})) {
      if (o.when !== undefined) putWhen(db, "tool", tool, o.when as WhenDecl);
    }
  }

  db.exec("begin");
  try {
    for (const p of d.places ?? []) {
      run(
        db,
        `insert into workplace (place, identity, runtime, forward, tools, usable) values (?, ?, ?, ?, ?, ?)
         on conflict(place) do update set identity = excluded.identity, runtime = excluded.runtime,
           forward = excluded.forward, tools = excluded.tools, usable = excluded.usable`,
        [
          p.place,
          p.identity ?? null,
          p.runtime ?? null,
          p.forward ? 1 : 0,
          JSON.stringify(p.tools ?? []),
          p.usable === false ? 0 : 1,
        ],
      );
    }

    for (const m of d.modes ?? []) {
      run(db, `insert into mode (name, note) values (?, ?) on conflict(name) do update set note = excluded.note`, [
        m.mode,
        m.note ?? null,
      ]);
      // **Replace the entire mode**, not row-by-row upserts. Omitting a cycle should delete it;
      // an upsert would leave an unreachable row in the database: dead code with no error.
      run(db, `delete from cycle where mode = ?`, [m.mode]);
      for (const c of m.cycles) {
        run(
          db,
          `insert into cycle (mode, cycle, api_mode, must_call, max_units, "from", next, infer) values (?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            m.mode,
            c.cycle,
            (c.apiMode ?? "").trim() || null,
            (c.mustCall ?? "").trim() || null,
            c.maxUnits ?? 1,
            JSON.stringify(c.from ?? []),
            JSON.stringify(c.next ?? []),
            c.infer,
          ],
        );
      }
    }

    for (const a of d.agents ?? []) {
      run(
        db,
        `insert into agent (name, config, apis, unit, knobs, state) values (?, ?, ?, ?, ?, ?)
         on conflict(name) do update set config = excluded.config, apis = excluded.apis,
           unit = excluded.unit, knobs = excluded.knobs, state = excluded.state`,
        [
          a.name,
          a.config ?? null,
          JSON.stringify(a.apis),
          a.unit,
          // Omitted means omitted: an empty object and an absent field mean the same thing.
          // There is no need to make callers choose between two forms of absence.
          a.knobs && Object.keys(a.knobs).length ? JSON.stringify(a.knobs) : null,
          a.state ?? "idle",
        ],
      );
    }

    for (const h of d.handles ?? []) {
      run(
        db,
        `insert into handle (name, expect_ms, module) values (?, ?, ?)
         on conflict(name) do update set expect_ms = excluded.expect_ms, module = excluded.module`,
        [h.name, h.expectMs, h.module ?? null],
      );
    }

    for (const h of d.hows ?? []) {
      run(
        db,
        `insert into press_how (name, note, identity, params, output) values (?, ?, ?, ?, ?)
         on conflict(name) do update set note = excluded.note, identity = excluded.identity,
           params = excluded.params, output = excluded.output`,
        [h.name, h.note ?? null, h.identity, JSON.stringify(h.params), JSON.stringify(h.output)],
      );
    }

    for (const t of d.tools ?? []) {
      run(
        db,
        `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable, gives)
         values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         on conflict(name) do update set identity = excluded.identity, does = excluded.does,
           params = excluded.params, output = excluded.output, prompt = excluded.prompt,
           concurrent = excluded.concurrent, system = excluded.system,
           access = excluded.access, usable = excluded.usable, gives = excluded.gives`,
        [
          t.name, t.identity, t.does, JSON.stringify(t.params), JSON.stringify(t.output),
          t.prompt ?? null, t.concurrent ? 1 : 0, t.system ? 1 : 0, t.access ?? null,
          t.usable === false ? 0 : 1, t.gives ?? null,
        ],
      );
      putWhen(db, "tool", t.name, t.when);
    }

    for (const r of d.rules ?? []) {
      run(
        db,
        `insert into rule (identity, does, params, writes, access, scope) values (?, ?, ?, ?, ?, ?)
         on conflict(identity) do update set does = excluded.does, params = excluded.params,
           writes = excluded.writes, access = excluded.access, scope = excluded.scope`,
        [
          r.identity, r.does, JSON.stringify(r.params), JSON.stringify(r.writes),
          r.access === undefined ? null : JSON.stringify(r.access), JSON.stringify(r.scope),
        ],
      );
      putWhen(db, "rule", r.identity, r.when);
    }

    for (const s of d.skills ?? []) {
      run(
        db,
        `insert into skill (identity, does, params, body, role, usable) values (?, ?, ?, ?, ?, ?)
         on conflict(identity) do update set does = excluded.does, params = excluded.params,
           body = excluded.body, role = excluded.role, usable = excluded.usable`,
        [s.identity, s.does, JSON.stringify(s.params), s.body ?? null, s.role, s.usable === false ? 0 : 1],
      );
      putWhen(db, "skill", s.identity, s.when);
    }
    db.exec("commit");
  } catch (e) {
    db.exec("rollback");
    throw e;
  }

  install(db);
  const grown = tableNames(db).filter((t) => !before.has(t));

  const entries: Record<string, string[]> = {};
  for (const m of d.modes ?? []) {
    entries[m.mode] = m.cycles.filter((c) => (c.from ?? []).length === 0).map((c) => c.cycle);
  }

  return {
    servers: grew,
    handles: (d.handles ?? []).map((h) => h.name),
    places: (d.places ?? []).map((p) => p.place),
    modes: (d.modes ?? []).map((m) => m.mode),
    cycles: (d.modes ?? []).reduce((n, m) => n + m.cycles.length, 0),
    agents: (d.agents ?? []).map((a) => a.name),
    tools: (d.tools ?? []).map((t) => t.name),
    rules: (d.rules ?? []).map((r) => r.identity),
    skills: (d.skills ?? []).map((s) => s.identity),
    tables: grown,
    entries,
  };
}

/**
 * **Export the current database declaration unchanged**, in exactly the shape accepted by `apply`, ready to reapply.
 *
 * Exporting an engine's configuration and rebuilding it on another machine then takes two calls, without client-side assembly.
 */
export function dump(db: Conn): Declare {
  const places = (all(db, `select place, identity, runtime, forward, tools, usable from workplace order by place`) as {
    place: string; identity: string | null; runtime: string | null; forward: number; tools: string; usable: number;
  }[]).map((r) => ({
    place: r.place,
    identity: r.identity,
    runtime: r.runtime,
    forward: Boolean(r.forward),
    tools: safeJson(r.tools, []) as { tool: string; policy: string }[],
    usable: Boolean(r.usable),
  }));

  const modes: ModeDecl[] = [];
  for (const m of all(db, `select name, note from mode order by name`) as { name: string; note: string | null }[]) {
    const cycles = all(db, `select cycle, api_mode, must_call, max_units, "from", next, infer from cycle where mode = ? order by cycle`, [
      m.name,
    ]) as { cycle: string; api_mode: string | null; max_units: number; from: string; next: string; infer: string }[];
    // The `mode` table records **call shapes** (chat/duplex); task modes exist only in cycle.
    // Names without cycles are therefore not task modes and are not exported.
    if (cycles.length === 0) continue;
    modes.push({
      mode: m.name,
      ...(m.note ? { note: m.note } : {}),
      cycles: cycles.map((c) => ({
        cycle: c.cycle,
        apiMode: c.api_mode,
        maxUnits: c.max_units,
        from: safeJson(c.from, []) as string[],
        next: safeJson(c.next, []) as string[],
        infer: c.infer,
      })),
    });
  }

  const agents = (all(db, `select name, config, apis, unit, knobs, state from agent order by name`) as {
    name: string; config: string | null; apis: string; unit: string; state: string;
  }[]).map((r) => ({
    name: r.name,
    config: r.config,
    apis: safeJson(r.apis, []) as [string, string][],
    unit: r.unit,
    state: r.state,
  }));

  // Export only **externally registered handles** (`http://`). In-process `fn:` handles come from code;
  // exporting and reapplying them serves no purpose, and importing them on a machine without that code would create an unclaimed handle.
  const handles = (all(db, `select name, expect_ms from handle where name like 'http://%' or name like 'https://%' order by name`) as {
    name: string; expect_ms: number;
  }[]).map((r) => ({ name: r.name, expectMs: r.expect_ms }));

  const tools = (all(db, `select * from tool order by name`) as Record<string, unknown>[]).map((r) => ({
    name: String(r.name),
    identity: String(r.identity),
    does: String(r.does),
    params: safeJson(String(r.params), {}),
    output: safeJson(String(r.output), {}),
    prompt: (r.prompt as string | null) ?? null,
    concurrent: Boolean(r.concurrent),
    system: Boolean(r.system),
    access: (r.access as string | null) ?? null,
    usable: Boolean(r.usable),
    when: whenOf(db, "tool", String(r.name)),
  }));

  const rules = (all(db, `select * from rule order by identity`) as Record<string, unknown>[]).map((r) => ({
    identity: String(r.identity),
    does: String(r.does),
    params: safeJson(String(r.params), {}),
    writes: safeJson(String(r.writes), {}),
    scope: safeJson(String(r.scope), {}),
    access: r.access == null ? null : safeJson(String(r.access), null),
    when: whenOf(db, "rule", String(r.identity)),
  }));

  const skills = (all(db, `select * from skill order by identity`) as Record<string, unknown>[]).map((r) => ({
    identity: String(r.identity),
    does: String(r.does),
    params: safeJson(String(r.params), {}),
    body: (r.body as string | null) ?? null,
    role: String(r.role),
    usable: Boolean(r.usable),
    when: whenOf(db, "skill", String(r.identity)),
  }));

  return { handles, places, modes, agents, tools, rules, skills };
}

/**
 * Replace all trigger groups for an owner.
 *
 * **Replace the groups as a whole, not condition-by-condition upserts.** Omitting a group should delete it; an upsert would leave it in the database, where it would still match. The user narrows the conditions, but the item keeps triggering everywhere without an error.
 *
 * Omitting `when` entirely (`undefined`) leaves existing conditions unchanged; an empty array explicitly clears them.
 * These differ: the first means "not mentioned this time", the second "remove all conditions".
 */
function putWhen(db: Conn, kind: string, owner: string, when: WhenDecl | undefined): void {
  if (when === undefined) return;
  run(db, `delete from trigger where owner_kind = ? and owner = ?`, [kind, owner]);
  for (const [i, group] of when.entries()) {
    for (const t of group) {
      run(
        db,
        `insert into trigger (owner_kind, owner, "group", dim, "key", op, value) values (?, ?, ?, ?, ?, ?, ?)`,
        [kind, owner, i, t.dim, t.key ?? "", t.op, t.value],
      );
    }
  }
}

/** Read an owner's conditions from the database and reconstruct `when` (outer groups, OR between groups). */
function whenOf(db: Conn, kind: string, owner: string): WhenDecl {
  const rows = all(db, `select "group", dim, "key", op, value from trigger where owner_kind = ? and owner = ? order by "group"`, [
    kind,
    owner,
  ]) as { group: number; dim: string; key: string; op: string; value: string }[];
  const by = new Map<number, TermDecl[]>();
  for (const r of rows) {
    const g = Number(r.group);
    by.set(g, [...(by.get(g) ?? []), { dim: r.dim, key: r.key, op: r.op, value: r.value }]);
  }
  return [...by].sort((a, b) => a[0] - b[0]).map(([, terms]) => terms);
}

function safeJson(s: string, fallback: unknown): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return fallback;
  }
}

function tableNames(db: Conn): string[] {
  return (all(db, `select name from sqlite_master where type='table' and name not like 'sqlite_%'`) as {
    name: string;
  }[]).map((r) => r.name);
}

/** Whether any api row supports this call shape. */
function servedBy(db: Conn, want: string): boolean {
  return (all(db, `select modes from api`) as { modes: string }[]).some((r) =>
    String(r.modes ?? "")
      .split(",")
      .map((x) => x.trim())
      .includes(want),
  );
}
