/**
 * Model adapter layer.
 *
 * **One call is exactly one execution unit**, not necessarily one HTTP request. The kernel supplies everything for that unit (context, attached tools, workplace); the adapter returns the row to store. Message construction, tool declarations, and provider-specific fields remain inside the adapter, unknown to the layer above.
 *
 * ## Use the SDK
 *
 * Use [AI SDK](https://ai-sdk.dev) (`ai` + `@ai-sdk/openai-compatible`) for HTTP, message and tool formats, and retries. Pure JS, no native dependencies, bundleable into one file: both constraints still hold. The handwritten implementation has been removed.
 *
 * ## Separate by mode, not provider
 *
 * `api.modes` (`chat` / `tools` / `vision` / `duplex`) identifies **call shapes**:
 *
 * - `chat`: request-response. **One `generateText` = one execution unit**, implemented in this file.
 * - `duplex`: realtime bidirectional interaction, such as speech. It is a session rather than a single call; one execution unit corresponds to one exchange within a longer-lived session. Implemented in `./duplex.ts` with **exactly the same signature**: the kernel does not know about sessions.
 *
 * An agent may attach both tracks; that is why `agent.apis` is a list.
 *
 * ## Credentials
 *
 * The database stores only the environment-variable **name** (`api.key_env`). Read its value from `process.env` when needed.
 * Credentials never enter the database, logs, or context.
 */

import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import type { FetchFunction } from "@ai-sdk/provider-utils";
import { dynamicTool, generateText, jsonSchema, type ModelMessage } from "ai";

import type { Conn } from "../H2H/db.ts";
import type { Log } from "../engine/loop.ts";
import type { Registry } from "../engine/registry.ts";
import { ROLES as DELIVER_ROLES } from "../msg/deliver.ts";

type Row = Record<string, unknown>;

/**
 * Known providers. **These are seeds; addresses belong in `api.base_url`**. Registration writes the defaults to rows; the table is authoritative afterward. Change an address as data, without code changes or recompilation.
 *
 * `ws` is the provider's realtime endpoint. **Absent means no realtime track**. Do not invent a placeholder: it would register a duplex handle that fails only when called.
 */
/**
 * `searches` means this provider **runs search itself**: its `/responses` endpoint accepts `tools: [{"type": "web_search"}]`, and performs queries and page access on its side.
 *
 * **Values belong in code, like `MODES`**, listing only tested implementations. Merely inserting a row claiming search support cannot teach the implementation; it would silently leave the route unselectable. This field determines **whether to offer** `web_search`: if no supported provider exists, offer none instead of a tool that fails when called.
 */
/**
 * `extra` contains fields required in every request to this provider, merged into the body by the same middleware as `reasoning_effort`.
 * OpenRouter uses it to pin providers and quantization. Without pinning, calls may reach different providers and precisions, so one model name no longer identifies the same model.
 */
export const VENDORS: Record<string, { baseURL: string; keyEnv: string; ws?: string; searches?: boolean; extra?: Record<string, unknown> }> = {
  deepseek: { baseURL: "https://api.deepseek.com/v1", keyEnv: "DEEPSEEK_API_KEY", searches: true },
  // Third-party hosting of open weights. DeepSeek retired V4-Flash on 2026-09-10 and redirected its old name to V4.1,
  // while the paper's 2026-09-01 run used V4-Flash-0731. This is the remaining route to that same model.
  // Pin fp8 (DeepSeek's native precision) and a fixed provider order, with no fallback to other providers.
  openrouter: {
    baseURL: "https://openrouter.ai/api/v1",
    keyEnv: "OPENROUTER_API_KEY",
    // Order follows measured throughput (2026-09-25, 2500 output tokens): BaseTen 447 tok/s, Baidu 227, CoreWeave 180,
    // GMICloud 168; OpenInference only 24 (8 minutes per call, making a one-hour problem limit incomparable).
    // Official DeepSeek delivered about 110 tok/s in the 9-01 run.
    extra: { provider: { order: ["BaseTen", "Baidu", "CoreWeave", "GMICloud"], allow_fallbacks: false, quantizations: ["fp8"] } },
  },
  dashscope: {
    baseURL: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    keyEnv: "DASHSCOPE_API_KEY",
    ws: "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
  },
};

/**
 * **All valid values** of `api.modes`: the available call shapes.
 *
 * **Values are exactly those recognized by the implementation**, following `msg_kind`: code defines what is supported; the `mode` table is **seeded for people and `check` to inspect**, not for arbitrary additions. Otherwise manually inserting `duplx` would make it "valid" despite unsupported behavior, leaving the track silently unselectable while the system continues running.
 */
export const MODES: [string, string][] = [
  ["chat", "One question, one answer. One call = one execution unit"],
  ["tools", "This lane can carry tools"],
  ["vision", "This lane can see images"],
  ["duplex", "Realtime, both directions. Not a call but a session; one execution unit = one turn in it"],
];

/** Names only, for comparison. */
export const MODE_NAMES = new Set(MODES.map(([n]) => n));

/** Seed known call shapes into `mode` idempotently, just like `seedKinds`. */
export function seedModes(db: Conn): string[] {
  for (const [name, note] of MODES) {
    db.run(`insert into mode (name, note) values (?, ?) on conflict(name) do update set note = excluded.note`, [
      name,
      note,
    ]);
  }
  return MODES.map(([n]) => n);
}

/**
 * Modes supported by each handle. **Populate at registration; `checkData` validates against it.**
 *
 * `api` is keyed by `(key_env, model)` and has one `handle` per row, so every listed mode must be supported by that handle. A row declaring `modes = "chat,duplex"` with a chat handle would be selected for duplex but call the chat adapter: **no error, just completely unintended station behavior**. This mapping catches that during validation.
 *
 * Externally registered `http://` handles are absent because their capabilities are unknown; skip them.
 */
export const SERVES = new Map<string, Set<string>>();

/**
 * Number of disconnection retries.
 *
 * **Not merely precautionary**: old-code comments documented frequent transient DeepSeek disconnections (ServerDisconnected / 500). A single attempt would let one transient fault derail the entire solve.
 */
export const RETRIES = 6;

/**
 * Default `api.retry_on` for newly registered rows. **A default, not a rule**: the database value is authoritative and requires no code change.
 *
 * It covers temporary provider failures: rate limits, gateway instability, and connections that never opened.
 * **Exclude all 4xx except 429**: they indicate an invalid request, which retries cannot fix.
 */
export const RETRY_ON = JSON.stringify([408, 409, 425, 429, 500, 502, 503, 504, "network"]);

/** Parse that column into a set. On failure use an empty set: never retrying is safer than indiscriminate retries. */
function retrySet(raw: string): Set<string> {
  try {
    const v = JSON.parse(raw) as unknown;
    return new Set(Array.isArray(v) ? v.map(String) : []);
  } catch {
    return new Set();
  }
}

/**
 * Whether this error is on the retry list.
 *
 * **No status code means no successful connection** (DNS, a dropped connection, read timeout). That is a temporary connectivity failure, distinct from a provider receiving and rejecting an invalid request. Give it its own list entry: `network`.
 */
function listed(e: unknown, on: Set<string>): boolean {
  const code = (e as { statusCode?: number } | null)?.statusCode;
  return on.has(code === undefined ? "network" : String(code));
}

/** Hard deadline for the whole call. The old endpoint hung for 27–31 minutes and required external termination. */
export const HARD_WALL_MS = 900_000;

/** Input passed by the kernel. **Both tracks receive the same shape**; duplex imports this definition. */
export interface Unit {
  agent: Row;
  task: Row;
  cycle: Row;
  chain: string;
  place: string;
  instance: string;
  unit: number;
  /** Track selected by the kernel. **The adapter does not select again**: selection must have one authority. */
  /** Track selected by the kernel. `compress_at` is the token threshold for pre-send compression; empty disables it. */
  api: { key_env: string; model: string; base_url: string; retry_on: string; compress_at?: number | null } | null;
  context: { seq: number; role: string; kind: string; body: string; thought?: string | null }[];
  /**
   * Outbound destination for each role, **read from `msg_role` and supplied by the kernel**.
   *
   * Previously this mapping existed only as a constant here, so a database alone could not reconstruct a model request: the matching code version was also needed to identify message-stream rows.
   */
  sentAs: Record<string, string>;
  /**
   * The tool this station must call. **Empty = the model chooses.**
   *
   * The offered tools define what it **can** call; this column defines what it **must** call. Offering only one tool does not force a call, and at stations such as submission, no call means the required step was not performed.
   */
  mustCall: string | null;
  /**
   * This round's task view. **Facts computed afresh by the kernel each round**, not a context message.
   * Messages follow a single chain and are inaccessible to siblings; every branch receives the view.
   */
  view?: {
    task: Row;
    here: { cycle: string; unit: number; chain: string; next?: string[] };
    tried: { node: number; at: string; status: string | null; done: boolean; mine?: boolean }[];
    /**
     * Remaining allowance. **Facts only**. The declaration layer decides which station and tool to use for submission:
     * stations appear in the transition table; rules belong to skills or the task description.
     */
    budget?: {
      units?: { cycle: string; used: number; cap: number; left: number }[];
      secondsLeft?: number;
      submitted?: boolean;
    };
  };
  tools: Row[];
  rules: string[];
}

/**
 * Effective knobs for this call: **run-wide configuration as the base, overridden by the agent's own settings**.
 *
 * These belong to the agent rather than the run. A lookup-and-report agent needs no reasoning, while its solver should reason as much as possible; one knob cannot control both. In measurements on the same question, `none` took 14.5 seconds and `low` took 113 seconds.
 *
 * Treat unreadable settings as absent: malformed data must not prevent this station from sending a request. Run-wide defaults remain usable.
 */
function knobsOf<T extends Record<string, unknown>>(u: Unit, run: T): T {
  const raw = u.agent.knobs;
  if (typeof raw !== "string" || !raw.trim()) return run;
  try {
    const own = JSON.parse(raw) as Record<string, unknown>;
    return { ...run, ...own };
  } catch {
    return run;
  }
}

/**
 * Add fields to the request body that **this provider adapter does not recognize but the endpoint does**.
 *
 * `providerOptions` does not work here: measured with `@ai-sdk/openai-compatible@3`, it accepted `providerOptions: { deepseek: { reasoning_effort } }` but emitted only `model` and `messages`. The field never reached the wire. **Before this fix, configured reasoning effort had never taken effect**; every run silently used the provider default.
 *
 * The SDK's supported route is the `fetch` hook, documented as request middleware. This remains SDK-managed rather than handwritten HTTP: HTTP, retries, and error classification stay in the SDK; we merge a few fields at the last moment.
 */
function withExtra(extra: Record<string, unknown>): FetchFunction {
  const wrapped = async (input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
    if (init?.body && typeof init.body === "string") {
      init = { ...init, body: JSON.stringify({ ...(JSON.parse(init.body) as object), ...extra }) };
    }
    return await fetch(input, init);
  };
  // The runtime's `fetch` has additional properties (Bun's `preconnect`), and this wrapper must substitute for it.
  // **Forward them unchanged rather than creating a shell**; otherwise paths using them would silently break.
  return Object.assign(wrapped, { preconnect: fetch.preconnect.bind(fetch) });
}

function key(keyEnv: string): string {
  const v = process.env[keyEnv];
  if (!v) throw new Error(`no key in environment variable ${keyEnv} - see .env`);
  return v;
}

/**
 * Whether to send this row to the model. **One definition shared by both tracks.**
 *
 * Exclude kernel bookkeeping about tools offered this round: sending it would read the ledger aloud. System messages use their instructions channels rather than the message stream.
 *
 * **Inspect `role` too, not just `kind = 'inject'`.** `inject` represents two things (see the inference table in `deliver.ts`): kernel bookkeeping is `inject` + `role=system`, while system-injected user-side content is `inject` + `role=user`. **Descriptions of tasks submitted by nonhuman sources use the latter**. Dropping all inject rows would empty the outbound messages for tasks whose `source` is not `user`, yielding "messages must not be empty".
 *
 * Separate chat and duplex copies would recreate the duplication warned about in `deliver.ts`: two copies of a bug, usually only one fixed.
 */
export function sendable(r: { role: string; kind: string }, sentAs: Record<string, string>): boolean {
  return sentAs[r.role] === "messages";
}

/**
 * Known roles. **Values come from `msg_role` rows**, which define each role's outbound destination (`sent_as`); seeds live in `msg/deliver.ts`.
 * An identical mapping formerly in this file was removed. Two copies could drift without error, silently presenting one source under the wrong identity.
 */
/**
 * Convert a database row back into a model message.
 *
 * A `kind = "call"` body's JSON contains text and requested calls; a `kind = "tool"` body contains a tool result. The message table has only one `body` column, so both shapes are stored there. We own both ends and need only a consistent contract; dedicated columns can be added when warranted.
 */
function toMsg(
  r: { role: string; kind: string; body: string; thought?: string | null },
  sentAs: Record<string, string>,
): ModelMessage | null {
  // **Return the reasoning from that turn as well.** Provider documentation requires historical `reasoning_content` when requests include `tools` (it is ignored only without tools). This mechanism includes tools in every request.
  //
  // This does not conflict with keeping reasoning outside `body`: body remains a universally understood replay shape, reasoning has a separate column, and outbound conversion joins them. Preserve it in the database and make it sendable.
  const thought = String(r.thought ?? "");
  // `graded` has the same shape as `call` and is also shown to the model. Only **authorship** differs:
  // `call` is a model request requiring execution; `graded` is a system-recorded external verdict with a result already attached and nothing to execute. Conflating them would rerun a verdict as a pending tool request, yielding two results for one id and making the chain unsendable.
  if (r.kind === "call" || r.kind === "graded") {
    const v = JSON.parse(r.body) as { text?: string; calls?: { id: string; name: string; input: unknown }[] };
    return {
      role: "assistant",
      content: [
        ...(thought ? [{ type: "reasoning" as const, text: thought }] : []),
        ...(v.text ? [{ type: "text" as const, text: v.text }] : []),
        ...(v.calls ?? []).map((c) => ({
          type: "tool-call" as const,
          toolCallId: c.id,
          toolName: c.name,
          input: c.input,
        })),
      ],
    };
  }
  if (r.kind === "tool") {
    const v = JSON.parse(r.body) as { id?: string; name?: string; value?: unknown };
    return {
      role: "tool",
      content: [
        {
          type: "tool-result" as const,
          toolCallId: v.id ?? "",
          toolName: v.name ?? "",
          output: { type: "json" as const, value: v.value as never },
        },
      ],
    };
  }
  if (!sendable(r, sentAs)) return null;
  if (r.role === "assistant") {
    return thought
      ? {
          role: "assistant",
          content: [
            { type: "reasoning" as const, text: thought },
            ...(r.body ? [{ type: "text" as const, text: r.body }] : []),
          ],
        }
      : { role: "assistant", content: r.body };
  }
  return { role: "user", content: r.body };
}

/**
 * Instructions for this request: tool usage conventions plus system entries from context.
 *
 * **Chat resends them per unit**: each unit is a fresh call with no memory of previous instructions. Duplex sessions remember, so send only **when opening the session**. Both construct the same content, so share this implementation.
 *
 * (AI SDK 7 rejects system messages inside messages rather than silently discarding them, which is useful.)
 */
export function instructionsOf(u: Unit): string {
  return [
    ...u.tools.map((t) => String(t.prompt ?? "")),
    // Collect roles routed to instructions: `system` and `skill`.
    // Exclude kernel bookkeeping (`kind: "inject"`), which is our ledger, not model-facing text.
    ...u.context.filter((r) => u.sentAs[r.role] === "instructions" && r.kind !== "inject").map((r) => r.body),
  ]
    .filter(Boolean)
    .join("\n\n");
}

/**
 * Render the kernel-computed task view as text. **The kernel supplies facts; wording is assembled here.**
 *
 * ## Put it in the message stream, not instructions
 *
 * It initially lived in `instructions`, incorrectly: **root-level siblings have no messages** (no ancestors and no speech yet), yielding `messages: []` and `Invalid prompt: messages must not be empty`. Nonempty instructions cannot fix an empty message list.
 *
 * Semantically it belongs in context too. The old repository said the complete context of the current chain is included by default: **context**, not system instructions. The view presents this round's problem, tree position, and other attempts, distinct from tool-usage directions.
 *
 * Include the tree section **only after actual branching**. Single-chain mechanisms already inherit context directly; a one-node tree would only occupy space.
 */
export function viewOf(u: Unit): string {
  const v = u.view;
  if (!v) return "";
  const t = v.task;
  const lines = [
    "## The task",
    `${String(t.description ?? "")}`,
    "",
    `id ${String(t.id)} | domain ${String(t.domain) || "(none)"} | at ${String(t.place)}${
      t.workdir ? `:${String(t.workdir)}` : ""
    }${t.objective ? " | this task is graded by a verification function" : ""}`,
  ];

  // **Which station you are at.** Facts from the transition table: station name and possible successors.
  // "No next station" is the only extra statement, also a fact (empty `next`), establishing whether another station can continue this one's output.
  const next = v.here.next;
  lines.push(
    "",
    "## Where you are",
    `station ${v.here.cycle}#${v.here.unit}` +
      (next === undefined
        ? ""
        : next.length === 0
          ? " - this is the last station: nothing runs after it, so anything you ask for here will not happen"
          : ` - after this comes one of: ${next.join(", ")}`),
  );

  // Report allowance facts only. **Which station and tool perform submission belongs to the declaration layer**:
  // the transition table lists stations, and skills or task descriptions state the rules. The kernel adds no policy wording here.
  const b = v.budget;
  if (b) {
    const units = (b.units ?? []).map((x) => `${x.cycle} ${x.used}/${x.cap}`).join(", ");
    lines.push(
      "",
      "## Budget",
      `units used: ${units || "(none)"}` +
        (b.secondsLeft === undefined ? "" : ` | ${b.secondsLeft}s left`) +
        (b.submitted === undefined ? "" : ` | submitted: ${b.submitted ? "yes" : "not yet"}`),
    );
  }

  // One node means no branching yet: this is a single chain, and the tree section adds nothing.
  if (v.tried.length > 1) {
    lines.push(
      "",
      "## This tree",
      // Describe **nodes**: each is a complete attempt spanning several execution units.
      // `node_load` also accepts node ids. Both must use the same vocabulary, or the model may query row ids instead.
      `You are at ${v.here.chain}. Attempts so far:`,
      ...v.tried.map(
        (n) =>
          `- node ${n.node}${n.mine ? " (this one)" : ""}: ${n.at}` +
          (n.status ? ` - **${n.status}**` : n.done ? " - finished" : " - still running"),
      ),
      "",
      "The ones marked dead were attempts that did not pass. Do not walk them again. " +
        "What they said is not shown by default - fetch one with node_load, by its node number.",
    );
  }
  return lines.join("\n");
}

/**
 * Build outbound messages: **task view first, then sendable context**.
 *
 * The view defines the problem, and context continues from it. It also guarantees a nonempty message stream: root-level siblings have no ancestors and would otherwise produce `messages: []`, rejected by the model.
 *
 * Shared by both tracks (duplex imports it). One criterion must not have two implementations.
 */
/**
 * The outbound message stream: **history first, this round's question last**.
 *
 * The view (task, current progress, remaining budget, tree shape) is **generated afresh for every execution unit**, making it this round's question. Placing it before history has two problems:
 *
 * 1. Newest information occupies the oldest position, buried under dozens of historical messages.
 * 2. **The request can end with an assistant message** if the previous station produced plain text without tools. Some gateways treat that as a continuation prefix and require `reasoning_content`, rejecting its absence with `The reasoning_content in the thinking mode must be passed back to the API.` This stranded an entire problem at submission (cmt-3, submit#14).
 *
 * After tool calls, the final message is a tool result and the shape works. The bug therefore appears only after a station speaks without tools, making it seem random.
 */
export function messagesOf(u: Unit): ModelMessage[] {
  const view = viewOf(u);
  return [
    ...u.context.map((r) => toMsg(r, u.sentAs)).filter((m): m is ModelMessage => m !== null),
    ...(view ? [{ role: "user" as const, content: view }] : []),
  ];
}

/**
 * Register one adapter per provider. **The handle is both `api.handle` and `agent.unit`**:
 * one call is one execution unit, the same operation rather than two layers.
 *
 * The `api` rows in `seed` are **data**, supplying ready-to-use examples that can change without code edits.
 */
export function registerVendors(
  db: Conn,
  reg: Registry,
  log: Log,
  seed: [string, string, string][],
  runKnobs: {
    maxTokens: number;
    retryTimes: number;
    continueTimes: number;
    reasoningEffort: string;
    temperature: number;
    seed: number;
  },
): string[] {
  for (const [vendor, v] of Object.entries(VENDORS)) {
    // Modes this handle supports. **Excludes duplex**, which has its own handle.
    SERVES.set(`fn:api.${vendor}`, new Set(["chat", "tools", "vision"]));
    reg.register(db, `fn:api.${vendor}`, HARD_WALL_MS, async (arg) => {
      const u = arg as unknown as Unit;
      // The kernel already chose this station's track from the cycle table's `api_mode`; use it directly.
      if (!u.api) throw new Error(`fn:api.${vendor} was called, but the kernel did not say which model this station uses`);
      const { model, key_env: keyEnv } = u.api;
      const officialOpenRouter = vendor === "openrouter" && model === "deepseek/deepseek-v4.1-flash";
      const retryOn = retrySet(u.api.retry_on);
      // Effective knobs: run-wide defaults overridden by the agent's settings. **Compute before creating the provider**:
      // reasoning effort enters the body through fetch middleware, attached during provider creation.
      const knobs = knobsOf(u, runKnobs);
      // See provider creation below: stations requiring a specific tool cannot enable reasoning.
      const effort = officialOpenRouter ? "high" : u.mustCall ? "none" : knobs.reasoningEffort;
      // Extra request-body fields: the provider's fixed settings (`VENDORS[…].extra`) plus reasoning effort.
      const extra: Record<string, unknown> = { ...(v.extra ?? {}), ...(effort ? { reasoning_effort: effort } : {}) };
      if (officialOpenRouter) {
        extra.provider = { only: ["digitalocean"], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } };
        extra.reasoning = { enabled: true, effort: "high", exclude: false };
        extra.seed = undefined;
      }
      // **The endpoint comes from the table.** It was once hard-coded in `VENDORS`, then overridden by an environment variable, which was worse: identical databases could behave differently under another environment without any clue in the database or code. A database must remain a kernel-independent snapshot, so such hidden inputs cannot remain.
      //
      // Storing the endpoint also lets tests use a fake endpoint by changing one row, without an environment-variable override.
      // Reasoning effort **uses this path, not `providerOptions`**, which accepts but does not transmit it (see `withExtra`). Treat an empty string as unspecified and let the provider choose its default.
      const provider = createOpenAICompatible({
        name: vendor,
        baseURL: u.api.base_url,
        apiKey: key(keyEnv),
        // **If this station requires a specific tool call, disable reasoning.**
        //
        // This is the endpoint's constraint, not our preference: reasoning mode rejects `tool_choice` with HTTP 400 (`Thinking mode does not support this tool_choice`). Requesting both cannot work.
        //
        // Their purposes are compatible: stations requiring a tool, such as submission, need to send an already computed answer, not reason again.
        ...(Object.keys(extra).length ? { fetch: withExtra(extra) } : {}),
      });

      const instructions = [instructionsOf(u), officialOpenRouter && u.mustCall
        ? `This station requires calling the ${u.mustCall} tool exactly once. A text-only response does not submit the task. Use the available tool.` : ""].filter(Boolean).join("\n\n");
      const messages = messagesOf(u);

      // Tools are **declared, not executed**. Without execute, the SDK only returns call requests.
      // Actual execution belongs to the next execution unit; running tools here would erase that step from the database.
      const tools = Object.fromEntries(
        u.tools.filter(t => !officialOpenRouter || !u.mustCall || t.name === u.mustCall).map((t) => [
          String(t.name),
          dynamicTool({
            description: String(t.does ?? ""),
            inputSchema: jsonSchema(JSON.parse(String(t.params)) as never),
          }),
        ]),
      );

      const wall = new AbortController();
      const timer = setTimeout(() => wall.abort(), HARD_WALL_MS);
      try {
        // ── One call = one execution unit, but **one unit is not one HTTP request** ──
        //
        // Continue unfinished output up to `continueTimes` times.
        //
        // Reasoning models share one output budget between **reasoning and visible text**. A hard cutoff may consume all of it on reasoning and leave no visible answer. Measurements found 12 of 19 responses empty, with three problems receiving no answer at all; the report showed only incorrect answers.
        //
        // **No answer differs from an unfinished answer**: the former should fail; the latter should be allowed to finish. Use `finishReason === "length"`, the model's own truncation signal, rather than guessing.
        //
        // Append existing output as an assistant message so continuation proceeds from that prefix.
        /**
         * Send one request, retrying failures with an additional 5-second delay each time.
         *
         * The SDK's `maxRetries` covers HTTP failures (connection errors, 5xx, 429), but not **an HTTP 200 response it cannot decode** (`Failed to process successful response`). That failure occurs while mapping the body into its own structure, outside the retry path.
         *
         * The kernel deliberately does not retry after such failures (waking it would create a hot loop). The station otherwise waits for `expect_ms`, wasting 15 minutes on a transient fault. This layer must handle it.
         *
         * **Increasing delays** allow transient faults to clear; waiting helps more than immediately retrying.
         */
        const ask = async (msgs: ModelMessage[]) => {
          let boom: unknown;
          for (let n = 0; n <= knobs.retryTimes; n++) {
            if (n > 0) await new Promise((r) => setTimeout(r, 5000 * n));
            try {
              return await generateText({
                model: provider(model),
                messages: msgs,
                ...(instructions ? { instructions } : {}),
                ...(Object.keys(tools).length ? { tools } : {}),
                maxOutputTokens: knobs.maxTokens,
                // **Require this station's designated tool.** Some providers reject it in reasoning mode
                // (DeepSeek V4 returns 400: `Thinking mode does not support this tool_choice`). That is a configuration conflict between the column and reasoning effort. Propagate the error unchanged so it can be fixed by clearing `cycle.must_call` or disabling reasoning.
                ...(u.mustCall && tools[u.mustCall]
                  ? officialOpenRouter ? { toolChoice: "auto" as const } : { toolChoice: { type: "tool" as const, toolName: u.mustCall } }
                  : {}),
                // A benchmark run has to be reproducible: without a fixed temperature
                // there is no telling how much of a score change came from an edit and
                // how much from sampling noise.
                temperature: knobs.temperature,
                seed: knobs.seed,
                maxRetries: RETRIES,
                abortSignal: wall.signal,
              });
            } catch (e) {
              // Stop retrying when the whole-call deadline expires: that is a station timeout, not a transient fault.
              if (wall.signal.aborted) throw e;
              // **Retry only when the allowlist permits it.** Propagate other errors unchanged. A 400 means the request itself is invalid;
              // a hundred retries still yield the same 400. Retrying only wastes time before identical failure: 30 seconds observed with 0+5+10+15 backoff.
              if (!listed(e, retryOn)) throw e;
              boom = e;
            }
          }
          throw boom;
        };

        let text = "";
        let thought = "";
        let calls: { id: string; name: string; input: unknown }[] = [];
        let this_broke = "";
        // **Accumulate usage for the whole call.** Continuation spans multiple `generateText` rounds, each reporting its own usage.
        // Keeping only the final round would record earlier rounds as free.
        const spent = { prompt_tokens: 0, completion_tokens: 0, reasoning_tokens: 0, cached_tokens: 0 };
        for (let round = 0; ; round++) {
          // Append the output already produced so the model continues instead of restarting.
          //
          // **Return the reasoning fragment too.** Reasoning models use the previous round's thought as the next round's premise. Some providers reject visible text alone:
          //   The `reasoning_content` in the thinking mode must be passed back to the API.
          // An entire observed problem stalled at its first continuation this way.
          //
          // ## Test whether anything was produced, not whether anything was spoken
          //
          // The common truncation case is **reasoning with no visible text yet**. `text` is empty; gating on it would resend messages unchanged, **reasking the same question**. Resending handles disconnections (already covered by SDK `maxRetries` for HTTP and outer `retryTimes` with `api.retry_on` for provider retryable errors), not truncation. Truncation means a full budget of tokens was produced but remains unfinished. Discarding it and retracing the same path is **systematically ineffective**: identical input reaches the same reasoning point and limit.
          //
          // Three experiments on one real truncation used the same problem, history, and 160,000-character reasoning trace:
          //
          // | Request strategy | Result |
          // | --- | --- |
          // | Resend without prior output | `length`, all 4,096 tokens spent reasoning, 0 visible characters, 29 seconds; **the new reasoning began verbatim like the discarded trace** |
          // | Include reasoning | `tool_calls`, 7 seconds, only 423 new reasoning tokens, continuing the prior derivation |
          // | Prefix continuation (`/beta` + `prefix`) | 400 `Function call should not be used with prefix`: incompatible with tools |
          //
          // The cost is resending reasoning as input (66,886 input tokens in that experiment).
          // The benefit is avoiding another full output round, and wall time is the bottleneck for these tasks.
          const so_far: ModelMessage[] =
            text || thought
              ? [
                  ...messages,
                  {
                    role: "assistant",
                    content: [
                      ...(thought ? [{ type: "reasoning" as const, text: thought }] : []),
                      ...(text ? [{ type: "text" as const, text }] : []),
                    ],
                  },
                ]
              : messages;
          // **A continuation failure must not lose the whole problem.** The partial output is already part of the answer.
          // Throwing here would leave the station waiting until expect_ms and lose the problem. A truncated answer is better than none, except on the first round when nothing exists yet.
          let out;
          try {
            out = await ask(so_far);
          } catch (e) {
            const accountError = e as { statusCode?: unknown; cause?: { statusCode?: unknown }; lastError?: { statusCode?: unknown } };
            const status = Number(accountError?.statusCode ?? accountError?.cause?.statusCode ?? accountError?.lastError?.statusCode);
            if (round === 0 || [401, 402, 403].includes(status)) throw e;
            this_broke = e instanceof Error ? e.message : String(e);
            break;
          }
          text += out.text;
          // Not every provider fills `reasoningText`; recognition of its `reasoning_content` by openai-compatible depends on the version.
          // Check both locations; if neither supplies it, treat it as absent.
          thought +=
            out.reasoningText ||
            (out.reasoning ?? []).map((r) => ("text" in r ? String(r.text) : "")).join("");
          calls = out.toolCalls.map((c) => ({ id: c.toolCallId, name: c.toolName, input: c.input }));
          // Enforce must_call locally with the official endpoint's supported auto
          // mode. Thinking stays enabled, including at the submission station.
          if (officialOpenRouter && u.mustCall && out.finishReason !== "length" &&
              (calls.length !== 1 || calls[0]?.name !== u.mustCall)) {
            const error = new Error(`The required ${u.mustCall} tool was not called exactly once`);
            error.name = "RequiredToolCallMissing";
            throw error;
          }
          // Accumulate usage by round. **Record missing values as 0; do not guess**. A guessed number looks measured and is worse than no number.
          // A provider that does not report usage leaves that column at 0, visibly.
          spent.prompt_tokens += Number(out.usage?.inputTokens ?? 0);
          spent.completion_tokens += Number(out.usage?.outputTokens ?? 0);
          spent.reasoning_tokens += Number(out.usage?.outputTokenDetails?.reasoningTokens ?? 0);
          spent.cached_tokens += Number(out.usage?.inputTokenDetails?.cacheReadTokens ?? 0);

          // Stop on a tool request: it is a complete action declaration that cannot and should not be continued.
          if (calls.length > 0) break;
          // The model finished, or the continuation limit was reached.
          if (out.finishReason !== "length" || round >= knobs.continueTimes) break;
        }

        if (this_broke) log.warn(`${model} could not continue; handing back what it had said. ${this_broke}`);
        // **Return reasoning alongside the result, but outside `body`.**
        //
        // Previously reasoning was not stored. The original rationale still holds for `body`: it is **the replay representation**, and some gateways reject assistant messages containing reasoning. Preserve the working replay path.
        //
        // That rationale forbids placing reasoning in body, not recording it at all. Give it a separate column while replay continues reading body. Both requirements then hold: cross-unit replay retains the gateway-compatible shape, and the database preserves **what the model actually thought**. Previously this was lost: one call took 174 seconds for only 350 visible tokens, while the snapshot could say nothing about where those two hundred-odd seconds went.
        const said = { thought, ...spent };
        if (calls.length > 0) {
          return { role: "assistant", kind: "call", body: JSON.stringify({ text, calls }), ...said };
        }
        return { role: "assistant", kind: "prompt", body: text, ...said };
      } finally {
        clearTimeout(timer);
      }
    });
  }

  for (const [vendor, model, modes] of seed) {
    if (!VENDORS[vendor]) throw new Error(`unknown vendor: ${vendor}`);
    db.run(
      `insert into api (key_env, model, handle, modes, base_url, retry_on) values (?, ?, ?, ?, ?, ?)
       on conflict(key_env, model) do update set handle = excluded.handle, modes = excluded.modes`,
      [VENDORS[vendor].keyEnv, model, `fn:api.${vendor}`, modes, VENDORS[vendor].baseURL, RETRY_ON],
    );
  }

  return Object.keys(VENDORS).map((v) => `fn:api.${v}`);
}
