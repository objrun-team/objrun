/**
 * Start this program.
 *
 * **This layer assembles the parts**: read configuration, start the databases and interfaces, and manage shutdown.
 * Each component below receives resolved inputs without knowing the configuration file's structure.
 *
 * ```
 * bun src/main.ts
 * ```
 */

import pkg from "../package.json" with { type: "json" };
import { aboutRoutes } from "./api/about.ts";
import { benchRoutes } from "./api/bench.ts";
import { declareRoutes } from "./api/declare.ts";
import { mount, mountHelp } from "./api/spec.ts";
import { taskRoutes } from "./api/tasks.ts";
import { Kernel } from "./engine/loop.ts";
import { Registry } from "./engine/registry.ts";
import { readConfig } from "./H2H/config.ts";
import { all, run } from "./H2H/db.ts";
import { build } from "./H2H/server.ts";
import { install, tableNameOf } from "./install/index.ts";
import { registerVendors, seedModes } from "./llm/index.ts";
import { registerDuplex, Sessions } from "./llm/duplex.ts";
import { Servers } from "./mcp/client.ts";
import { attach } from "./mcp/register.ts";
import { mcpServeRoutes } from "./mcp/serve.ts";
import { candidateInput, evaluate } from "./objective/run.ts";
import { finalCandidate } from "./objective/candidate.ts";
import { openSealed } from "./objective/store.ts";
import { deliverVerdict, seedHows, seedKinds, seedParts, seedRoles } from "./msg/deliver.ts";
import { registerPress } from "./msg/press.ts";
import { registerTree } from "./tree/dfs.ts";
import { registerVerifyTool } from "./objective/tool.ts";
import { registerTreeView } from "./tree/view.ts";
import { check } from "./trigger/check.ts";
import { checkData } from "./trigger/data.ts";
import { Places, registerPlace } from "./place/index.ts";
import { registerTools } from "./tools/register.ts";
import { registerSearchTool } from "./tools/search.ts";
import { closePython } from "./tools/python.ts";
import { registerToolUnit } from "./tools/unit.ts";
import { mountUi, UI_PATH } from "./ui/index.ts";

const VERSION = pkg.version;

/** Who is running the final station of this task. */
function lastUnit(
  db: Parameters<typeof all>[0],
  task: string,
): { agent: string; instance: string; unit: number } | undefined {
  const t = all(db, `select mode from task where id = ?`, [task])[0] as { mode?: string } | undefined;
  if (!t?.mode) return undefined;
  const sub = tableNameOf("task_{}", String(t.mode));
  return all(db, `select agent, instance, unit from "${sub}" where task = ? order by unit desc limit 1`, [task])[0] as
    | { agent: string; instance: string; unit: number }
    | undefined;
}

/**
 * Wait for that station to finish writing. **The final verdict must yield to an active call.**
 *
 * Reaching the time limit does not mean the station has returned: it may be running Python or waiting for the model.
 * Both the verdict and the station's result append to the same slot using "current maximum seq plus one", so write order determines message order. If the verdict lands first, a verdict pair separates the previous station's call from its result. The model rejects this shape (`An assistant message with 'tool_calls' must be followed by tool messages responding to each of them`), preventing all subsequent requests on that chain.
 *
 * **Timeout has the lowest priority here**: the call is doing real work; the verdict only finalizes it.
 *
 * Do not wait indefinitely: the station has its own `expect_ms`, after which the kernel marks it dead and closes it. Follow that clock here. The problem has already been graded; writing the verdict a little later changes no result.
 */
async function settled(db: Parameters<typeof all>[0], task: string, unit: number | undefined): Promise<void> {
  if (unit === undefined) return;
  const t = all(db, `select mode from task where id = ?`, [task])[0] as { mode?: string } | undefined;
  if (!t?.mode) return;
  const sub = tableNameOf("task_{}", String(t.mode));
  const CAP_MS = 16 * 60 * 1000; // Slightly longer than the handle's 15 minutes, so it can be marked dead first.
  const t0 = Date.now();
  while (Date.now() - t0 < CAP_MS) {
    const row = all(db, `select done from "${sub}" where task = ? and unit = ?`, [task, unit])[0] as
      | { done?: number }
      | undefined;
    if (!row || Number(row.done) === 1) return;
    await Bun.sleep(500);
  }
}

/**
 * At finalization, **what did this problem actually submit?**
 *
 * Mechanisms with a submission station use only actual submit arguments, including an empty string; without submission, neither verify arguments nor reasoning text count. Modes without a submission station use the last formal prompt.
 * Online finalization and offline grading use the same candidate extraction function.
 */
const lastSaid = finalCandidate;

const cfg = readConfig();

// Wake the kernel after a write endpoint finishes. Leave a placeholder until the kernel exists, then replace it.
// This wiring belongs to the assembly layer: H2H does not know the kernel, and the kernel does not know HTTP.
let wake = () => {};
const app = await build(cfg, { onWrite: () => wake(), public: [UI_PATH] });

// Install tables. Idempotent: skip existing tables with the correct shape; fail immediately on a mismatch without automatically modifying them.
const built = install(app.store.rw);
app.log.info(
  `tables: created ${built.create.length}, already there ${built.ok.length}` +
    (built.extra.length ? `, ${built.extra.length} outside the declaration (untouched)` : ""),
);

// Handle registry + kernel.
//
// **In-process handles are registered here**: only this process can hold the functions.
// Out-of-process handles (starting with http://) need no changes here: insert a handle row in the database, and the kernel synthesizes a caller on its next wake-up.
const registry = new Registry();

// Connection pool for this location-forwarding implementation. **It belongs to this handle**, not to the concept of location.
// Other implementations (an http:// sidecar or a plugin) manage their own connections.
const places = new Places(app.store.ro);

// MCP server pool. Declaring a server defines **a bulk source**: it reports its tools and writes those rows for you.
// Running subprocesses and connections are live resources; like locations, they are not stored in the database. Close them all at shutdown.
const servers = new Servers();

// Install callers for registered MCP tools on every cycle. **A newly registered server is available on the next cycle**, without restarting.
// This must precede kernel startup, or the first cycle will report an unregistered handle.
registry.beforeSync = () => attach(app.store.rw, registry, servers);

// Sealed area for verifier G. **A separate database that H2H never opens**: the main database exposes all interfaces, so storing G there would remove the boundary.
// Enforce the boundary through inaccessibility, not a rule forbidding access.
const sealed = openSealed(cfg.db.sealed);

// When the kernel determines that all execution units of a task are done, run G here and write its verdict to the main database.
// **The kernel does not know G**; it only announces completion.
const kernel = new Kernel(app.store, app.log, registry, {
  onDone(task, expired) {
    if (!sealed.has(task)) return; // A task without G is simply finished when execution ends.
    return (async () => {
      const g = sealed.open(task);
      if (!g) return;
      const row = all(app.store.ro, `select * from task where id = ?`, [task])[0];
      const at = lastUnit(app.store.ro, String(task));
      const said = lastSaid(app.store.ro, String(task));

      // **Without a submission, there is no need to ask G.** Finalizing a task with G requires an explicit "this is my submission"; `verify` is that endpoint.
      // If passed an empty string, the grader only reports "answer not found". The logs then suggest a faulty criterion when there was no submission at all. Keep those cases distinguishable.
      const v = said
        ? await evaluate(g, registry, candidateInput(row ?? {}, said.body))
        : { pass: 0 as const, valid: false, outcome: "no_candidate", why: "nothing submitted - it never reached the hand-in step, so there is nothing to grade", note: "", trace: [] };

      // **Put the verdict back into context as soon as it is available**, following the tree path's rule (`tree/dfs.ts`):
      // every query to G records its verdict at that station as a tool call with a result.
      // Writing only `task.result` informs us, but never tells the model how it was judged.
      // **Timeout yields.** The final verdict must be written at a station that may still be running; reaching the deadline does not mean its call has returned.
      // Both writers use "current maximum seq plus one", so the first write appears first. If the verdict wins, it separates the previous station's call from its result. The model rejects this shape (`An assistant message with 'tool_calls' must be followed by tool messages responding to each of them`). The chain can no longer send requests, leaving a stuck entry in the database.
      //
      // **Timeout has the lowest priority here**: the call is doing real work; the verdict only finalizes it.
      // Wait for the station's writes before writing the verdict. Do not wait indefinitely: the station has its own `expect_ms`, after which it is marked dead and closed. That duration also caps this wait.
      await settled(app.store.ro, String(task), at?.unit);

      if (at) {
        deliverVerdict(app.store.rw, {
          agent: at.agent,
          instance: at.instance,
          unit: at.unit,
          name: "verify",
          input: { task, at: "wrap-up" },
          value: { pass: v.pass, valid: v.valid, outcome: v.outcome, why: v.why, note: v.note },
        });
      }

      // The timeout path also reaches here (`#reap`). **Still issue a verdict**: if a correct answer was submitted before the deadline, the problem was solved even if the tree had no time to finish. The deadline only means it could not stop on its own.
      // For a score of 0, include the timeout in `why`, so the report distinguishes an incorrect answer from exhausted time.
      const why = v.pass === 1 ? v.why : [expired, v.why].filter(Boolean).join("; ");
      run(app.store.rw, `update task set state = ?, result = ? where id = ?`, [
        v.pass === 1 ? "done" : "failed",
        JSON.stringify({ pass: v.pass, valid: v.valid, outcome: v.outcome, why, note: v.note }),
        task,
      ]);
      app.log.info(
        `graded ${task}: ${v.pass} (${said ? said.how : "nothing submitted"}${why ? ", " + why : ""})`,
      );
    })();
  },
});
wake = () => kernel.wake();

// Tree control flow: spawn children / mark dead and open a sibling / backtrack. This is an inference function, not part of the kernel.
// Changing the search strategy means replacing an infer handle without changing the kernel.
app.log.info(`tree: ${registerTree(app.store.rw, registry, sealed).join(", ")}`);

// The two tree introspection tools. **They are not system tools**: dispatch by mode, based on whether this station's inference function uses the tree.
// A single-chain mechanism that follows one path receives neither tool (it already inherits context directly).
app.log.info(`tree introspection: ${registerTreeView(app.store.rw, registry, "fn:infer.dfs").join(", ")}`);
// **A task with G can query G.** Verdicts already enter context every round (also named verify).
// Adding this tool makes that trajectory match its name; see `objective/tool.ts`.
app.log.info(`grading tool: ${registerVerifyTool(app.store.rw, registry, sealed)}`);

// Known message types. **These values are the range of the "who wrote it → kind" inference table.**
// Seed them so both check and people can inspect them, not so callers must fill them in.
app.log.info(`message kinds: ${seedKinds(app.store.rw).join(", ")}`);
app.log.info(`message roles: ${seedRoles(app.store.rw).join(", ")}`);
app.log.info(`message parts: ${seedParts(app.store.rw).join(", ")}`);
// Built-in compression methods. **One handle per method**: each `press_how` row's `identity` refers to one.
// Register them before seeding, because each seed must reference an existing handle name.
app.log.info(`press: ${registerPress(app.store.rw, registry).join(", ")}`);
app.log.info(`ways to press: ${seedHows(app.store.rw).join(", ")}`);

// Basic tools: register functions in the kernel (which can hold them), and write the model-facing descriptions into the tool table.
// Registered functions only **forward** calls, choosing where to run from workplace.
// "How to reach that location" must first be installed as a handle, so tools can forward to it. `workplace.identity` selects the forwarding implementation. This is the built-in implementation (the `wsl` / `ssh` / `docker` command prefixes).
app.log.info(`place: ${registerPlace(app.store.rw, registry, places)}`);
app.log.info(`tools: ${registerTools(app.store.rw, registry).join(", ")}`);

// Search is separate: it does not forward to workplace (it needs network access and credentials, not that machine's filesystem).
// **`trigger` decides who sees it**: only agents whose apis identify a provider that can search receive it.
// If none match, no condition matches and nobody receives the tool: precisely the intended trigger semantics.
app.log.info(`search tool: ${registerSearchTool(app.store.rw, registry, app.log)}`);

// Actually execute the tools requested by the previous model station. **Without this, the tool chain is broken**: requests enter the database but are never executed, with no error.
// The periodic-table station with an empty api_mode uses this handle.
app.log.info(`tool-running unit: ${registerToolUnit(app.store.rw, registry)}`);

// Known call shapes. **These values are the range of the `api.modes` column.** Like message types,
// seed them so both check and people can inspect them, not so callers must fill them in.
app.log.info(`api modes: ${seedModes(app.store.rw).join(", ")}`);

// Model side: one adapter per provider. **This handle is both api.handle and agent.unit**:
// one call is one execution unit. The api rows below are data; changing them requires no code changes.
app.log.info(
  `models: ${registerVendors(
    app.store.rw,
    registry,
    app.log,
    [
      ["deepseek", "deepseek-v4-flash", "chat,tools"],
      ["openrouter", "deepseek/deepseek-v4-flash-0731", "chat,tools"],
      ["openrouter", "deepseek/deepseek-v4.1-flash", "chat,tools"],
      ["deepseek", "deepseek-v4-pro", "chat,tools"],
      ["deepseek", "deepseek-chat", "chat,tools"],
      ["deepseek", "deepseek-reasoner", "chat"],
      ["dashscope", "qwen-max", "chat,tools"],
    ],
    cfg.llm,
  ).join(", ")} | ${cfg.llm.maxTokens} output tokens (up to ${cfg.llm.continueTimes} continuations) | reasoning ${cfg.llm.reasoningEffort}`,
);

// Realtime track. **A separate handle**: it represents a session, not one call; one execution unit corresponds to one exchange in that session.
// Sessions live in this pool (like locations, they are connections, not state, and are not stored in the database). Close them all at shutdown.
const sessions = new Sessions();
const duplexHandles = registerDuplex(app.store.rw, registry, sessions, [
  ["dashscope", "qwen-audio-3.0-realtime-flash"],
]);
app.log.info(`realtime lanes: ${duplexHandles.join(", ")}`);

// Kernel-side endpoints. **Each endpoint's description, parameter schema, and implementation share one declaration**:
// the contract belongs to the interface, not adjacent documentation. Documentation can drift silently, describing one behavior while implementing another. Declaration drift rejects requests incorrectly and is immediately visible.
// The parameter schema also provides **validation**, defining the client's allowed operations.
const kernelRoutes = [
  ...aboutRoutes(cfg.api.prefix, app.store, VERSION, duplexHandles),
  ...declareRoutes(app.store, registry, servers, () => wake()),
  ...taskRoutes(app.store, registry, sealed, () => wake()),
  ...benchRoutes(app.store, registry, sealed, () => wake()),
  // This engine's own MCP server: without it, external callers cannot use the tools implemented by the kernel.
  ...mcpServeRoutes(app.store, registry),
];
mount(app, cfg.api.prefix, kernelRoutes);

// help must **list everything**. Routes are installed in two places (the database layer and here). Omitting a group
// makes clients assume it does not exist and read tables directly, coupling the two sides to the schema.
mountHelp(app, cfg.api.prefix, [...app.routes, ...kernelRoutes]);
app.log.info(`routes: ${app.routes.length + kernelRoutes.length}; GET ${cfg.api.prefix}/help for usage`);

// A human-facing page served by the engine. **It is just another client**: it uses only the endpoints above and never reads tables.
// When the interface adds a state or message type, the page discovers it through /about.
app.log.info(`ui: http://${cfg.server.host}:${cfg.server.port}${mountUi(app, cfg.api.prefix)}`);

// Shutdown: stop accepting requests, then wait for in-flight requests to finish; force shutdown on timeout.
// Without a limit, one hung request could keep the entire process alive indefinitely.
for (const sig of ["SIGINT", "SIGTERM"] as const) {
  process.on(sig, () => {
    const hard = setTimeout(() => process.exit(1), cfg.server.shutdownTimeout).unref();
    app
      .close()
      .then(() => {
        clearTimeout(hard);
        kernel.stop();
        closePython();
        places.closeAll();
        sessions.closeAll();
        servers.closeAll();
        registry.plugins.closeAll();
        sealed.close();
        app.store.close();
        process.exit(0);
      })
      .catch(() => process.exit(1));
  });
}

// Listening beyond localhost, requiring no token, and allowing writes together let anyone on the same network modify the database.
// This combination is particularly easy to enable when connecting Android-like clients, so warn here.
const loopback = /^(127\.|::1$|localhost$)/.test(cfg.server.host);
if (!loopback && !cfg.api.token && cfg.api.allowWrite) {
  app.log.warn(`listening on ${cfg.server.host} with no api.token while api.allowWrite is on - anyone on this network can write to the database`);
}

await app.listen({ host: cfg.server.host, port: cfg.server.port });

// Validate trigger conditions at startup. **Do not block startup**: a malformed condition must not prevent the whole engine from starting.
// But do not stay silent either: silently ineffective conditions are this table's most common failure mode.
const bad = check(app.store.ro);
if (bad.length) {
  app.log.warn(`${bad.length} trigger problems:`);
  for (const b of bad.slice(0, 10)) app.log.warn(`  ${b.owner_kind} ${b.owner} group ${b.group}: ${b.why}`);
}
const badData = checkData(app.store.ro, registry);
if (badData.length) {
  app.log.warn(`${badData.length} data inconsistencies:`);
  for (const b of badData.slice(0, 10)) app.log.warn(`  ${b.what}: ${b.why}`);
}

// Probe the plugin path at startup. **Do not block startup**: a machine without plugins must still start.
// But do not stay silent, or discovery would wait until a task actually invokes a plugin.
const plugBad = await registry.plugins.probe();
if (plugBad) app.log.warn(plugBad);
else app.log.info(`plugin host: ${registry.plugins.host}`);

kernel.start();
app.log.info(`db ${cfg.db.file} | write ${cfg.api.allowWrite ? "on" : "off"} | token ${cfg.api.token ? "required" : "none"}`);
