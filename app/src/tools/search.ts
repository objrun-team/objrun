/**
 * `web_search`: **let it look things up instead of recalling them.**
 *
 * ## Why this tool exists
 *
 * In a real trajectory, a model spent over ten thousand tokens guessing a paper:
 *
 * > I am now almost certain there is a 2021–2023 paper titled something like "Emergent U(1) symmetry and two Kosterlitz-Thouless transitions...". Perhaps Moessner and Sondhi? Or Bo Yang? Or Xue-Feng Zhang?
 *
 * It **knew which paper to look for** but lacked a tool, so it could only guess titles and authors. With search enabled, the same question took 83 seconds and yielded the volume, page, and year (Isakov & Moessner, PRB 68, 104409, 2003). It was **41 seconds faster than without search**: output fell from 13,057 to 7,916 tokens because it no longer had to guess, and output generation was the slow part.
 *
 * ## Why a nested call rather than another parameter?
 *
 * Provider-hosted search uses **`/responses`**, not our `/chat/completions` endpoint. The latter accepts only `function` for `tools[0].type` (`unknown variant 'web_search', expected 'function'`). This tool therefore **makes its own `/responses` call**, passing a question for the provider to search, open pages, read, and return a cited answer.
 *
 * ## Whose account?
 *
 * **The agent's own provider.** Use `base_url` and `key_env` from the first row in `agent.apis`. Another configuration field would create another value to maintain, synchronize, and potentially let drift. Using the same provider as reasoning is the natural default.
 *
 * ## Do not offer the tool to a provider that cannot search
 *
 * **Store the criterion in `trigger`, alongside other tools**, not a code-level if:
 *
 * ```
 * dim=agent  key=apis  op=contains  value=DEEPSEEK_API_KEY
 * ```
 *
 * Each search-capable provider gets a group (OR between groups), ANDed with the condition that this is not a submission station. This is evaluated **per agent**, not per deployment: in one database, the deepseek agent receives the tool while an agent using another provider does not, which is the appropriate granularity.
 *
 * `VENDORS[…].searches` records providers whose search implementations have actually been tested. Values live in code; conditions live in data, the same division used by `MODES`.
 *
 * A tool that fails only when called is the worst outcome: the model sees it, tries it, receives an error, and has already spent a slot. The tool list must describe capabilities that are actually available.
 *
 * ## We cannot bound one search's depth, but we can bound the number of searches
 *
 * **What we cannot control**: `/responses` accepts `max_tool_calls` but ignores it. Receipts report `null`; a limit of 2 still produced 11 searches, and 8 produced 13. Stop sending that parameter: an ineffective control is worse than none because the next reader assumes it works. Per-search cost is therefore unbounded by it: measured median 130,000 tokens, maximum 250,000, with **40% returning no answer at all**.
 *
 * **What we can control**: `task.max_searches`, the number allowed per round, following G's `checks` rules (one round = one node; restarting after marking a node dead gives a fresh allowance; rejected calls do not count).
 *
 * Measurements explain why the limit counts calls rather than slots: timed-out tasks spent **half** their hour searching, yet **never hit** a station's slot allowance (maximum used: 30; limit: 35). Search consumes wall time, not slots. More slots cannot fix this; limiting search calls can.
 *
 * We also impose our own clock, `SEARCH_WALL_MS`, aborting each call at its deadline.
 *
 * ## Audit trail
 *
 * Return both the **query strings** and **opened URLs**. They accompany tool results into `agent_{}_msg`, requiring no new table and allowing later inspection of what was accessed. This is especially important for evaluation: finding literature is a legitimate capability; finding this problem set's answer key is not. Only an audit trail distinguishes them.
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { declareTool } from "./register.ts";
import { whereAmI } from "../tasks/where.ts";
import { deliver } from "../msg/deliver.ts";
import { tableNameOf } from "../install/index.ts";
import { VENDORS } from "../llm/index.ts";

/**
 * **Name of the agent behind this tool.**
 *
 * Its own row determines the model, endpoint, and reasoning effort (`agent.apis` → `api.base_url`, `agent.knobs`), not the caller's row. Search is a fixed job: look up information and explain the findings clearly. Inheriting caller settings would make search change whenever the solver changes model or reasoning effort, without an explicit reason anywhere.
 *
 * If the row is missing, the tool is unconfigured. Report that immediately instead of guessing.
 */
export const SEARCHER = "searcher";

/**
 * Hard wall-clock limit per call. **Controls how long one search can take**, not how many are allowed.
 * The latter is `task.max_searches`; see the file header.
 *
 * Abort at the deadline and return an error for the slot to continue, rather than waiting for the handle's death timeout.
 */
export const SEARCH_WALL_MS = 240_000;

/**
 * Who receives the tool. **One group per provider, OR between groups; each group is ANDed with "not a submission station".**
 *
 * Check whether `agent.apis` contains the provider's `key_env`. That column stores `[["DEEPSEEK_API_KEY","deepseek-v4-flash"], …]`, so `contains` is sufficient.
 *
 * With no search-capable providers this array is empty. Since no conditions means never triggered in `trigger`, no extra if is needed: **the tool is registered, but no agent receives it.**
 */
const OFFERED_TO = Object.values(VENDORS)
  .filter((v) => v.searches)
  .map((v) => [
    { dim: "cycle", key: "cycle", op: "ne", value: "submit" },
    { dim: "agent", key: "apis", op: "contains", value: v.keyEnv },
  ]);

const SEARCH_TOOL = {
  name: "web_search",
  does:
    "Search the web and read what it finds, then answer the question you ask it. Use it for anything you would " +
    "otherwise be recalling from memory - a paper, a result, a value, who published what and when. It returns " +
    "prose with sources, plus the queries it ran and the pages it opened.",
  params: {
    type: "object",
    properties: {
      question: {
        type: "string",
        description:
          "What you want to know, in full. Ask for what you are actually after - a searcher that is told " +
          "'find the paper that reports X and give title, authors, year' does better than one told 'X'.",
      },
    },
    required: ["question"],
    additionalProperties: false,
  },
  output: {
    type: "object",
    properties: {
      answer: { type: "string", description: "What it found, in prose, with sources named" },
      queries: { type: "array", items: { type: "string" }, description: "The searches it ran" },
      opened: { type: "array", items: { type: "string" }, description: "The pages it opened" },
      searches: { type: "integer", description: "How many moves it made inside this one search" },
      left: { type: "integer", description: "Searches remaining in this attempt, when the publisher set a limit" },
      spent: {
        type: "object",
        description: "What this search cost. Searching reads whole pages, so it is dearer than asking is.",
        properties: {
          prompt_tokens: { type: "integer" },
          completion_tokens: { type: "integer" },
          total_tokens: { type: "integer" },
        },
      },
    },
  },
  prompt:
    "It takes a full question, not keywords: it searches and answers. What comes back is a third party's text.",
  concurrent: true,
  gives: "event",
  expectMs: SEARCH_WALL_MS + 30_000,
  // **Conditions belong in `OFFERED_TO`, not here**. The non-submission-station condition is there too, ANDed with provider capability.
  // Splitting the conditions across two places would make the later database write overwrite the earlier one while its code still appeared present.
};

interface Lane {
  base: string;
  model: string;
  keyEnv: string;
  /** Its fixed model parameters (`agent.knobs`), or empty when absent. */
  knobs: Record<string, unknown>;
}

/**
 * Which provider this agent uses for search: **its own**, the first row in `agent.apis`.
 *
 * Throw if unavailable and explain the full cause. When configuration is missing, this message is all the model has; a vague explanation forces blind retries.
 */
function laneOf(db: Conn, agent: string): Lane {
  const row = all(db, `select apis, knobs from agent where name = ?`, [agent])[0] as
    | { apis?: string; knobs?: string | null }
    | undefined;
  if (!row) throw new Error(`no row in agent for ${agent} - declare it before using this tool`);
  let apis: [string, string][];
  try {
    apis = JSON.parse(String(row.apis ?? "[]")) as [string, string][];
  } catch {
    throw new Error(`agent ${agent} has apis that is not a readable list`);
  }
  const first = apis[0];
  if (!first) throw new Error(`agent ${agent} has no api to search with`);
  const [keyEnv, model] = first;
  const api = all(db, `select base_url from api where key_env = ? and model = ?`, [keyEnv, model])[0] as
    | { base_url?: string }
    | undefined;
  if (!api?.base_url) throw new Error(`no row in api for ${keyEnv}/${model}`);
  let knobs: Record<string, unknown> = {};
  try {
    if (row.knobs) knobs = JSON.parse(row.knobs) as Record<string, unknown>;
  } catch {
    // A malformed knobs column should not disable the tool; the provider's default settings still work.
  }
  return { base: String(api.base_url).replace(/\/+$/, ""), model, keyEnv, knobs };
}

/**
 * What this problem's publisher forbids searching for. Missing data means no restriction.
 *
 * Read from `task`, not caller arguments; otherwise changing one parameter could disable the gate.
 */
function forbidden(db: Conn, task: string): string[] {
  const row = all(db, `select no_search from task where id = ?`, [task])[0] as { no_search?: string } | undefined;
  if (!row?.no_search) return [];
  try {
    const v = JSON.parse(row.no_search) as unknown;
    return Array.isArray(v) ? v.map(String).filter(Boolean) : [];
  } catch {
    return [];
  }
}

/**
 * Whether this search result crosses a restriction. **Inspect the whole result, not just URLs.**
 *
 * ## One entry = a group of words; **all must appear** to match
 *
 * Do not apply `includes` to one contiguous literal string. That is too permissive; an observed miss was:
 *
 * ```
 * huggingface.co/datasets/Infektyd/syntra-evals-dataset/…/cmt-physics.jsonl
 * ```
 *
 * A third party had republished the same problems under a completely different name. Blocking `cmt_benchmark` catches the original but not this copy, which is still an answer key. Yet **both `cmt` and `benchmark` appeared in the returned content**. Therefore require every word in an entry to appear, regardless of intervening text, order, hyphens, or underscores.
 *
 * ## Why inspect the whole result instead of only URLs?
 *
 * In one run the model tried the main site, a mirror (`hf-mirror.com`), a text proxy (`r.jina.ai`), and an archive (`web.archive.org`), then two cross-origin proxies (`allorigins.win`, `corsproxy.io`). **Domain blocking would require enumerating every route and could never anticipate the next one.** Whole-result inspection avoids that problem: the relevant words appear in the content regardless of its route.
 *
 * Match case-insensitively; publishers need not enumerate every capitalization.
 */
function tripped(got: unknown, banned: string[]): string | null {
  if (banned.length === 0) return null;
  const flat = JSON.stringify(got).toLowerCase();
  for (const b of banned) {
    const terms = b.toLowerCase().split(/\s+/).filter(Boolean);
    if (terms.length && terms.every((t) => flat.includes(t))) return b;
  }
  return null;
}

/**
 * Searches already performed this round. **One round = one node**, following G's `checks` rules:
 * restarting after marking a node dead starts a new round with a fresh allowance.
 *
 * Count only **searches actually performed**. Blocked attempts retrieved nothing and do not count.
 *
 * For mechanisms without a node column (non-tree mechanisms), count the entire instance: they have only one round anyway.
 */
function searchesIn(db: Conn, at: { sub: string; task: string }, agent: string, instance: string, unit: number): number {
  if (!agent || !instance) return 0;
  let units: number[];
  try {
    const me = all(db, `select node from "${at.sub}" where task = ? and unit = ?`, [at.task, unit])[0] as
      | { node?: number }
      | undefined;
    const rows =
      me?.node === undefined || me.node === null
        ? (all(db, `select unit from "${at.sub}" where task = ?`, [at.task]) as { unit: number }[])
        : (all(db, `select unit from "${at.sub}" where task = ? and node = ?`, [at.task, me.node]) as { unit: number }[]);
    units = rows.map((r) => Number(r.unit));
  } catch {
    return 0; // If the subtable does not exist yet, no search has occurred.
  }
  if (units.length === 0) return 0;

  const rows = all(
    db,
    `select body from "${tableNameOf("agent_{}_msg", agent)}"
      where instance = ? and kind = 'tool' and unit in (${units.map(() => "?").join(", ")})`,
    [instance, ...units],
  ) as { body: string }[];

  let n = 0;
  for (const r of rows) {
    try {
      const v = JSON.parse(r.body) as { name?: string; value?: { error?: unknown; answer?: unknown } };
      if (v.name !== SEARCH_TOOL.name) continue;
      // Blocked and over-quota attempts retrieved nothing; do not charge them against the allowance.
      if (typeof v.value?.answer !== "string") continue;
      n++;
    } catch {
      // Do not count unreadable rows.
    }
  }
  return n;
}

/**
 * Where to record this problem's searches: **the search agent's own table, one instance per problem.**
 *
 * All searches for one problem share a conversation; different problems remain independent.
 */
function deskOf(task: string): string {
  return `${task}#${SEARCHER}`;
}

/**
 * **Copy this exchange into the search agent's own table**, including the caller's task information.
 *
 * It has the shape of an ordinary conversation, like any other agent:
 *
 * | Row | Meaning |
 * | --- | --- |
 * | `user` | The question asked this time |
 * | `call` | Its answer (`text`) and its search calls |
 * | `tool` | An **unmodified record** of each search, one row per call |
 *
 * Those unmodified records matter: **including them in the next request lets the provider restore the retrieved content**. Measured example: the first request searched 4 times with 14,543 input tokens; a follow-up reused the records, performed no new searches, and used 5,429 input tokens. Content remains with the provider; only query strings and URLs, about three hundred tokens, are stored here.
 *
 * Use the sole `deliver` pipeline: sequence allocation and identity must each have one authority.
 */
function ccBack(db: Conn, task: string, question: string, answer: string): void {
  const desk = deskOf(task);
  const t = tableNameOf("agent_{}_msg", SEARCHER);
  const ctx = tableNameOf("agent_{}_ctx", SEARCHER);
  const unit =
    Number(
      (all(db, `select coalesce(max(unit), 0) as m from "${t}" where instance = ?`, [desk])[0] as { m: number }).m,
    ) + 1;

  // This slot's bookkeeping: **which problem asked**. The table thus identifies whose search this conversation serves.
  run(db, `insert into "${ctx}" (instance, task, unit, place, done) values (?, ?, ?, 'local', 1)`, [desk, task, unit]);

  // **Two rows per exchange: the question and its answer.** Both are plain text. The provider's internal searches and page views are not tool calls in our conversation model, so there are no call or tool-result rows here.
  //
  // Use the sole `deliver` pipeline: identity, kind, and seq must each have one authority.
  deliver(db, { agent: SEARCHER, instance: desk, unit, by: "world", body: question });
  deliver(db, { agent: SEARCHER, instance: desk, unit, by: "agent", body: answer });
}

/**
 * Earlier questions and answers for this problem: **an ordinary conversation retrieved in order.**
 *
 * Include it to avoid revisiting the same ground: **the previous answer is itself source material**. There is no need to preserve the provider's internal search state; how it searches is its concern, while we need what it said.
 *
 * If the table does not exist (the tool has never been used), treat history as absent. The new request may cost slightly more but remains valid. Throwing here would break the very first search.
 */
function deskTalk(db: Conn, task: string): { role: string; content: string }[] {
  const t = tableNameOf("agent_{}_msg", SEARCHER);
  let rows: { role: string; kind: string; body: string }[];
  try {
    rows = all(db, `select role, kind, body from "${t}" where instance = ? order by unit, seq`, [
      deskOf(task),
    ]) as { role: string; kind: string; body: string }[];
  } catch {
    return [];
  }
  return rows
    .filter((r) => r.role === "user" || r.role === "assistant")
    .map((r) => ({ role: r.role, content: r.body }));
}

/** Read the credential only at this point; do not retain it. */
function keyOf(keyEnv: string): string {
  const k = process.env[keyEnv];
  if (!k) throw new Error(`${keyEnv} is not set, so there is nothing to search with`);
  return k;
}

interface Answer {
  status?: string;
  output?: {
    type: string;
    action?: { type?: string; queries?: string[]; url?: string };
    content?: { type: string; text?: string }[];
  }[];
  usage?: { input_tokens?: number; output_tokens?: number; total_tokens?: number };
  error?: { message?: string };
}

/**
 * Split the response into three things: what it said, what it searched, and which pages it opened.
 *
 * **Only the final `message` is the answer**. Earlier messages are search progress commentary (such as "I'll look this up"). Concatenating all of them would bury the answer in commentary.
 */
function unpack(d: Answer): {
  answer: string;
  queries: string[];
  opened: string[];
  searches: number;
  spent: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
} {
  const queries: string[] = [];
  const opened: string[] = [];
  const said: string[] = [];
  let searches = 0;
  for (const o of d.output ?? []) {
    if (o.type === "web_search_call") {
      searches++;
      // **`ws_call_id=…` is a provider-side marker, not a search query.**
      //
      // It appears both appended to URLs and as a standalone query entry. In one measured run, every search's queries ended with such an entry. Keeping it would insert identifiers into the list of what was searched, adding noise to later checks for access to forbidden material.
      for (const q of o.action?.queries ?? []) if (!/^ws_call_id=/.test(q)) queries.push(q);
      if (o.action?.url) opened.push(o.action.url.replace(/#ws_call_id=.*$/, ""));
      continue;
    }
    if (o.type !== "message") continue;
    for (const c of o.content ?? []) if (c.type === "output_text" && c.text) said.push(c.text);
  }
  // **Record the cost of this search too.**
  //
  // Message-table counters cover the **agent's own** call, while this tool makes an additional `/responses` call whose usage otherwise belongs to no row. Measured search calls used 70,000–180,000 tokens each; thirty could exceed the whole run's visible cost. Without recording them, a snapshot's total cost could be an order of magnitude too low without any indication.
  //
  // Store usage in the tool result rather than new columns: it is **part of this call**, and belongs with the result it describes.
  const u = d.usage ?? {};
  return {
    answer: said.at(-1) ?? "",
    queries,
    opened,
    searches,
    spent: {
      prompt_tokens: Number(u.input_tokens ?? 0),
      completion_tokens: Number(u.output_tokens ?? 0),
      total_tokens: Number(u.total_tokens ?? 0),
    },
  };
}

/**
 * Register `web_search`. `OFFERED_TO` determines visibility through `trigger`.
 *
 * To disable it temporarily, change `tool.usable`: a data change, not an edit to this file.
 */
export function registerSearchTool(db: Conn, reg: Registry, log?: { warn(msg: string): void }): string {
  reg.register(db, `fn:tool.${SEARCH_TOOL.name}`, SEARCH_TOOL.expectMs, async (arg) => {
    const a = (arg ?? {}) as { args?: { question?: unknown }; agent?: string; instance?: string; unit?: number };
    const question = String(a.args?.question ?? "").trim();
    if (!question) return { error: "question is required - there is nothing to search for" };
    if (!a.agent) return { error: "the kernel did not say which agent is searching, so there is no api to use" };

    // Identify the problem **from the database**, not caller arguments; otherwise one parameter could disable the gate.
    // The rationale and method match `verify`.
    const at = whereAmI(db, String(a.instance ?? ""));

    // ── Searches allowed per round ────────────────────────────────────────
    //
    // **This gate controls wall time, not slots.** In one measured run, timed-out tasks spent half an hour of their one-hour limit searching and **never hit** the per-station slot allowance (maximum used: 30; limit: 35). More slots cannot fix that; a search-count limit can.
    //
    // One round = one node; restarting after marking it dead gives a fresh allowance. Reject over-quota calls immediately **without charging them**; they retrieved nothing.
    let left: number | undefined;
    if (at) {
      const cap = Number(
        (all(db, `select max_searches from task where id = ?`, [at.task])[0] as { max_searches?: number } | undefined)
          ?.max_searches ?? 0,
      );
      if (cap > 0) {
        const spent = searchesIn(db, at, String(a.agent), String(a.instance ?? ""), Number(a.unit ?? 0));
        left = cap - spent - 1;
        if (spent >= cap) {
          return {
            error:
              `the ${cap === 1 ? "one search" : `${String(cap)} searches`} for this attempt ${cap === 1 ? "is" : "are"} spent. Searching ` +
              `costs time you need for the problem itself - work with what you already found, and reason the rest out.`,
            left: 0,
          };
        }
      }
    }

    // **The track comes from the search agent, not its caller.** Its own row determines model, endpoint, and reasoning effort.
    const lane = laneOf(db, SEARCHER);
    const wall = AbortSignal.timeout(SEARCH_WALL_MS);
    const res = await fetch(`${lane.base}/responses`, {
      method: "POST",
      headers: { authorization: `Bearer ${keyOf(lane.keyEnv)}`, "content-type": "application/json" },
      body: JSON.stringify({
        model: lane.model,
        // **First check for existing records in the table.** Prepend them to the question so the provider can restore prior findings instead of searching the same ground again.
        // Order is mandatory: history goes **before the question**. Reversing it causes rejection (`The reasoning_text in the thinking mode must be passed back to the API`).
        input: at ? [...deskTalk(db, at.task), { role: "user", content: question }] : question,
        tools: [{ type: "web_search" }],
        // Pass its fixed parameters unchanged, using the provider's key names (`reasoning_effort`).
        ...(lane.knobs.reasoningEffort ? { reasoning_effort: String(lane.knobs.reasoningEffort) } : {}),
        stream: false,
      }),
      signal: wall,
    });

    const d = (await res.json()) as Answer;
    if (!res.ok || d.error) {
      // Return the error unchanged. **Do not rewrite provider errors here**: rewritten errors look like our defects,
      // although diagnosing them requires the provider's documentation.
      return { valid: false, outcome: "provider_error", httpStatus: res.status, error: `search failed (${res.status}): ${d.error?.message ?? "no message"}` };
    }

    const got = unpack(d);

    // **Discard a restricted result completely; return none of its text.**
    //
    // The gate must act before the model sees it. A later audit cannot undo contamination: once an answer enters context, that problem's evaluation is invalid, and invalidating it merely records the loss. Do not even return queries or opened pages; those are clues themselves.
    //
    // Still report `spent`: the call incurred real cost even though its result was blocked.
    const hit = tripped(got, at ? forbidden(db, at.task) : []);
    if (hit) {
      // **Log restriction violations.** The database retains only the model-facing refusal, which cannot explain
      // which restriction matched or where the search was heading. Operators need that information: repeated violations for one problem suggest its statement itself points toward that source.
      log?.warn(
        `${at ? at.task : "?"}: a search tripped the publisher's no_search rule on "${hit}" - ` +
          `the whole result was dropped. queries: ${got.queries.join(" | ").slice(0, 300)}`,
      );
      return {
        error:
          "Forbidden access: the publisher of this problem does not allow searching for related content. " +
          "The whole result has been discarded and none of it will be shown to you. Work the problem out " +
          "yourself - looking up what someone else answered is not what is being asked of you.",
        spent: got.spent,
      };
    }

    if (!got.answer) {
      // Search completed without saying anything: observed with 15 actions, 182,063 tokens, and zero answer.
      // Returning **what it did** is more useful than a generic failure, because the model can avoid repeating paths already tried.
      return {
        ...got,
        answer: "",
        error:
          `the search made ${String(got.searches)} ${got.searches === 1 ? "move" : "moves"} and came back with ` +
          `nothing to say; the queries it tried are listed, so try asking for something narrower`,
      };
    }
    // **Copy the exchange only after validation.** Reaching here means no provider error, no blocklist match, and an actual answer.
    // Copy it to the search agent's table with this problem's identity, so future searches for the same problem can continue the conversation.
    // The caller's tool result is still written normally, unchanged.
    if (at) ccBack(db, at.task, question, got.answer);
    return left === undefined ? got : { ...got, left };
  });

  declareTool(db, { ...SEARCH_TOOL, when: OFFERED_TO });
  return SEARCH_TOOL.name;
}
