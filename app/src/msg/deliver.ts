/**
 * Deliver a message into context: **one write path, one read path, with provenance intact.**
 *
 * ## Why there must be only one entry point
 *
 * The old code had two identical implementations (agent-side and kernel-side); the latter even described them as two copies of the same code. **Two copies duplicate every bug, while fixes usually reach only one.** This file is therefore the sole entry point for the kernel, publishing endpoint, rules, and skills.
 *
 * ## `kind` is **inferred**, not supplied
 *
 * This is the central rule. As the old code put it:
 *
 * > Marking must be **based on facts already known to the system, not on procedural discipline**. If someone must remember to prefix each message, one omission silently breaks the mechanism and cannot be detected afterward.
 *
 * Callers therefore specify **who supplied it** (`by`), from which `kind` is inferred. Previously callers filled in `kind` themselves: another procedural rule, with no error for wrong or missing values and no way afterward to distinguish human writing from rule-injected content.
 *
 * ## Human-authored content must remain identifiable
 *
 * When flattened for the model, all non-assistant content becomes one `user` string. **Human writing and system injection become indistinguishable** unless marked in the database. `HUMAN_MARK` is that marker, defined here once; downstream code reads **the same constant**, not separately written literals.
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import { tableNameOf } from "../install/index.ts";

/** Prefix for human-authored blocks. **Defined once**: downstream code reads it instead of duplicating the literal. */
export const HUMAN_MARK = "[human] ";

/** Sources considered human-provided. **These values directly determine whether to prepend `HUMAN_MARK`.** */
const HUMAN = new Set<By>(["user", "voice"]);

/**
 * Who supplied the message; `kind` is inferred from this.
 *
 * - `user`: written by a person. **Intentional and attributable**; prefix with `HUMAN_MARK` when flattening.
 * - `voice`: **spoken** by a person, transcribed from the realtime track. Equally intentional and attributable, and also prefixed with `HUMAN_MARK`. Record it **separately from `user`**: speech is not typing. Conflating them would silently replay transcribed speech as typed input.
 * - `world`: mechanical, deterministic output (knowledge injected after a rule matches). **No intent or responsibility**.
 * - `skill`: a temporary prompt supplied by a skill.
 * - `tool`: a tool result.
 * - `agent`: the agent's own words. **Outside this pipeline**: they are its trajectory, written directly by the execution unit.
 * - `kernel`: kernel bookkeeping, such as outbound receipts. For human inspection, not sent to the model as content.
 */
export type By = "user" | "voice" | "world" | "skill" | "tool" | "agent" | "kernel";

/** Source → stored `kind` and `role`. **This table is the inference rule itself.** */
const FROM: Record<By, { kind: string; role: string }> = {
  user: { kind: "user", role: "user" },
  voice: { kind: "voice", role: "user" },
  world: { kind: "inject", role: "user" },
  // **A skill has its own identity.**
  //
  // Previously it was stored with `role: "user"`, telling the model that a person was addressing it. In measurements, injected methodology was interpreted as conversation: the model asked for the question's specific options instead of answering. A skill is neither human speech, model speech, nor a tool result; it is a conditionally injected prompt. Give it its own role and let the adapter choose its presentation (see `sendable` / `instructionsOf` in `llm/index.ts`: it enters instructions, not the message stream).
  skill: { kind: "skill", role: "skill" },
  tool: { kind: "tool", role: "tool" },
  agent: { kind: "prompt", role: "assistant" },
  kernel: { kind: "inject", role: "system" },
};

/**
 * Human-provided `kind` values. **Derived from the two tables above, not maintained as another list.**
 *
 * Downstream interface code must use this to identify human input: **never inspect the body's appearance**. A model can imitate a context message's `HUMAN_MARK` prefix at the start of its answer, causing misclassification as human writing (observed in practice). `kind` is inferred at delivery and cannot be forged that way.
 */
export const HUMAN_KINDS = new Set([...HUMAN].map((b) => FROM[b].kind));

export interface Put {
  agent: string;
  instance: string;
  unit: number;
  by: By;
  body: string;
  /** Sources such as `skill` / `tool` must identify which one, so the supplier can be traced afterward. */
  who?: string;
}

/**
 * Everything **besides the words** in a completed model message: its reasoning and the cost of this call.
 *
 * Separating these from `body` is deliberate: `body` is **the replay representation**, and some gateways reject assistant messages containing reasoning. Preserve that working path. Store these fields without sending them back, retaining both a replayable shape and an account of the original reasoning and usage.
 *
 * **Record unreported values as null, not 0.** Missing adapter metrics must visibly mean "not reported". Zero would be indistinguishable from a call that truly consumed no tokens, although those cases differ by an entire call.
 */
export interface Said {
  thought?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  reasoning_tokens?: number;
  cached_tokens?: number;
}

/**
 * Deliver one message and return its sequence number.
 *
 * `role` is inferred too. Models recognize only certain roles, so the message's actual identity needs a separate marker: system-injected content also becomes `user` when flattened, and the message list alone cannot establish whether a person said it.
 */
/**
 * Validate this row's `body` shape. **Check at insertion time.**
 *
 * The former lack of validation had a concrete cost: a stored `call` could contain an entry in `calls` without an `id`, the key used to match tool results. Such a call could never receive a matching result, making the entire context unsendable. Previously this was discovered only at request time.
 *
 * At this point we can validate only the row's internal consistency. Whether someone later answers the call belongs to `answerMissing`.
 */
export function checkBody(kind: string, body: string): void {
  if (kind !== "call" && kind !== "graded" && kind !== "tool") return;
  let v: unknown;
  try {
    v = JSON.parse(body);
  } catch {
    throw new Error(`a ${kind} message must carry JSON in its body, and this one does not parse`);
  }
  if (kind === "call" || kind === "graded") {
    const calls = (v as { calls?: unknown }).calls;
    if (!Array.isArray(calls)) throw new Error("a call message must carry a calls array");
    for (const c of calls as { id?: unknown; name?: unknown }[]) {
      if (typeof c.id !== "string" || c.id === "") throw new Error("every call needs a non-empty id");
      if (typeof c.name !== "string" || c.name === "") throw new Error("every call needs a tool name");
    }
    return;
  }
  const id = (v as { id?: unknown }).id;
  if (typeof id !== "string" || id === "") throw new Error("a tool result needs the id of the call it answers");
}

/**
 * **Complete unanswered calls** in these rows: write a result explaining that each unmatched call never ran. Return the number added.
 *
 * ## Why add results instead of removing calls?
 *
 * An unanswered `call` really happened. **Whether a station executes tools depends on the mechanism**: a following `fn:unit.tools` station runs them; a pure question-answer track does not. System tools are attached unconditionally, so a multi-station question-answer mechanism will eventually request a tool that nobody executes.
 *
 * Without a result, the context cannot be sent: providers require a matching tool result for every tool_call. Previously the call row was **removed** before sending, with two costs:
 *
 * - The call **disappeared** from the model's history. Believing it had never made the call, the model could repeat it.
 * - Stored and transmitted context **differed**. The database could not reconstruct what the model saw.
 *
 * Adding a "not executed" result solves both: the model sees its call and the absence of a result, while the stored context matches what is sent.
 */
/** A message row; pairing validation needs only these columns. */
export interface Pair {
  unit: number;
  seq: number;
  role: string;
  kind: string;
  body: string;
  thought?: string | null;
}

/**
 * **The final pre-send gate: is this message list still valid?**
 *
 * The provider enforces one pairing rule: a call must have its following result, and a result must follow its call. A violation rejects the entire request. Errors identify the missing piece, not who lost it: `Tool result is missing for tool call …` / `Messages with role 'tool' must be a response to a preceding message with 'tool_calls'`.
 *
 * **Remove the small unmatched fragment; do not revert compression.** Compression was selected by the size threshold. Reverting the whole context for an orphaned call trades possible invalidity for certain context overflow. Removing the call costs only that call: its result is already absent, so hiding it loses no additional result.
 *
 * Remove the smallest piece: delete one entry from the row's `calls`, and drop the whole row only when **no calls and no text remain**.
 *
 * Return retained rows and a record of removals. The latter is for logging: any removal means an earlier stage lost a result, and that is the defect to fix.
 */
export function mendPairs(rows: Pair[]): { rows: Pair[]; dropped: string[] } {
  const answered = new Set<string>();
  const asked = new Set<string>();
  for (const r of rows) {
    if (r.kind === "tool") {
      const id = idOf(r.body);
      if (id) answered.add(id);
      continue;
    }
    if (r.kind !== "call" && r.kind !== "graded") continue;
    for (const c of callsOf(r.body)) if (c.id) asked.add(String(c.id));
  }

  const dropped: string[] = [];
  const out: Pair[] = [];
  for (const r of rows) {
    if (r.kind === "tool") {
      const id = idOf(r.body);
      if (id && !asked.has(id)) {
        dropped.push(`result ${id} (nothing asked for it)`);
        continue;
      }
      out.push(r);
      continue;
    }
    if (r.kind !== "call" && r.kind !== "graded") {
      out.push(r);
      continue;
    }
    let v: { text?: unknown; calls?: { id?: unknown }[] };
    try {
      v = JSON.parse(r.body) as typeof v;
    } catch {
      out.push(r);
      continue;
    }
    const calls = v.calls ?? [];
    const keep = calls.filter((c) => c.id && answered.has(String(c.id)));
    if (keep.length === calls.length) {
      out.push(r);
      continue;
    }
    for (const c of calls) if (!keep.includes(c)) dropped.push(`call ${String(c.id)} (no result for it)`);
    const text = typeof v.text === "string" ? v.text : "";
    // No calls and no text remain → the row has no content; drop it entirely.
    if (keep.length === 0 && !text.trim()) continue;
    out.push({ ...r, body: JSON.stringify({ ...v, calls: keep }) });
  }
  return { rows: out, dropped };
}

/** Which call a `kind='tool'` row answers. Unreadable means absent. */
function idOf(body: string): string {
  try {
    return String((JSON.parse(body) as { id?: unknown }).id ?? "");
  } catch {
    return "";
  }
}

/** Calls requested in one row. */
function callsOf(body: string): { id?: unknown }[] {
  try {
    return (JSON.parse(body) as { calls?: { id?: unknown }[] }).calls ?? [];
  } catch {
    return [];
  }
}

export function answerMissing(
  db: Conn,
  agent: string,
  instance: string,
  rows: { unit: number; seq: number; kind: string; body: string }[],
): number {
  const answered = new Set<string>();
  for (const r of rows) {
    if (r.kind !== "tool") continue;
    try {
      const id = (JSON.parse(r.body) as { id?: string }).id;
      if (id) answered.add(id);
    } catch {
      // An unreadable id counts as unanswered. Such rows can no longer enter the database (see checkBody).
    }
  }

  // Which results to add: the slot and call being answered. **Collect first, then mutate**.
  // Each insertion shifts later `seq` values; mutating while iterating would use a stale position for the second insertion.
  const todo: { unit: number; id: string; name: string }[] = [];
  for (const r of rows) {
    // Exclude `graded`: its result is already paired when written, so nothing is waiting.
    if (r.kind !== "call") continue;
    let calls: { id?: string; name?: string }[];
    try {
      calls = (JSON.parse(r.body) as { calls?: { id?: string; name?: string }[] }).calls ?? [];
    } catch {
      continue;
    }
    for (const c of calls) {
      if (!c.id || answered.has(c.id)) continue;
      answered.add(c.id);
      todo.push({ unit: r.unit, id: c.id, name: c.name ?? "" });
    }
  }
  if (todo.length === 0) return 0;

  const t = tableNameOf("agent_{}_msg", agent);
  for (const job of todo) {
    // Look up the row's current position: the previous completion may already have shifted it.
    const host = all(
      db,
      `select seq, body from "${t}" where instance = ? and unit = ? and kind = 'call' order by seq`,
      [instance, job.unit],
    ) as { seq: number; body: string }[];
    const at = host.find((h) => h.body.includes(`"${job.id}"`));
    if (!at) continue;

    // **Insert immediately after the call being answered, not at the end of the slot.** Providers require the assistant message containing tool_calls to be **immediately followed** by its results. An intervening assistant message causes rejection: `An assistant message with 'tool_calls' must be followed by tool messages responding to each of them`. Appending at the end used to place the verdict pair in between, stalling every failed problem at its next station.
    //
    // Make room in two steps because `(instance, unit, seq)` is the primary key: incrementing directly would collide with a row not yet moved. Shift rows far away, insert, then shift them back.
    const pos = Number(at.seq) + 1;
    run(db, `update "${t}" set seq = seq + 1000000 where instance = ? and unit = ? and seq >= ?`, [
      instance,
      job.unit,
      pos,
    ]);
    run(db, `insert into "${t}" (instance, unit, seq, role, kind, body, at) values (?, ?, ?, 'tool', 'tool', ?, ?)`, [
      instance,
      job.unit,
      pos,
      JSON.stringify({
        id: job.id,
        name: job.name,
        value: { ran: false, why: "this station ended before the call was run" },
      }),
      Date.now(),
    ]);
    run(db, `update "${t}" set seq = seq - 999999 where instance = ? and unit = ? and seq >= 1000000`, [
      instance,
      job.unit,
    ]);
  }
  return todo.length;
}

export function deliver(db: Conn, p: Put): number {
  const t = tableNameOf("agent_{}_msg", p.agent);
  const { kind, role } = FROM[p.by];
  if (!kind) throw new Error(`unknown delivery source: ${p.by}`);

  // Prefix human input **here, not in callers**: caller-side marking would depend on procedural discipline.
  // Use `HUMAN` (both written and spoken input), not a particular by value. Otherwise adding a human source without updating this line would silently lose its marker, making it indistinguishable after flattening.
  const body = HUMAN.has(p.by) ? `${HUMAN_MARK}${p.body}` : p.body;
  checkBody(kind, body);

  const got = all(db, `select coalesce(max(seq), 0) as m from "${t}" where instance = ? and unit = ?`, [
    p.instance,
    p.unit,
  ])[0] as { m: number };
  const seq = Number(got.m) + 1;

  run(db, `insert into "${t}" (instance, unit, seq, role, kind, body, at) values (?, ?, ?, ?, ?, ?, ?)`, [
    p.instance,
    p.unit,
    seq,
    role,
    kind,
    body,
    Date.now(),
  ]);
  return seq;
}

/**
 * Deliver an **external verdict** as two rows: a tool call and its result.
 *
 * ## Why this shape?
 *
 * G's verdict previously entered **only logs and `task.result`, never context**. Marking a branch dead and opening a sibling therefore meant **blind retries**: the new branch knew to change direction but not why the previous one failed. The verifier half of verifier-guided search was effectively disconnected.
 *
 * To show the verdict to the model, choose an identity. Three alternatives cause problems:
 *
 * | Treat it as | Why it fails |
 * | --- | --- |
 * | `user` speech | The model interprets a person saying it is wrong and responds or argues. |
 * | `system` instruction | It is **this call's observation**, not an instruction; instructions are resent every round, blending verdicts together. |
 * | The `assistant`'s own words | This makes the model admit the verdict itself, falsifying its trajectory. |
 *
 * **A tool call with a result** fits: an external, specific, verifiable observation, exactly the meaning of a tool result. The kernel already has both row types (`call` / `tool`), and `toMsg` recognizes them without introducing a new model-facing concept.
 *
 * ## Is the `call` half fabricated?
 *
 * We just rejected using `assistant` as falsifying the trajectory, yet this pair's `call` does use `role: assistant`. This is justified only if **`verify` is a real tool**. Otherwise context would claim "I called verify" while a real attempt would fail because verify is absent from the tool table. That would be fabrication. `objective/tool.ts` therefore registers it: tasks with G receive it and the model can call it itself. The trajectory matches the available capability.
 *
 * ## Why in this file?
 *
 * It writes two message rows and must use the sole delivery pipeline. Sequence allocation and `kind` inference must each have one authority. Direct inserts elsewhere would recreate the duplication warned about at the top of this file.
 */
export function deliverVerdict(
  db: Conn,
  p: { agent: string; instance: string; unit: number; name: string; input: unknown; value: unknown },
): number {
  const t = tableNameOf("agent_{}_msg", p.agent);
  const got = all(db, `select coalesce(max(seq), 0) as m from "${t}" where instance = ? and unit = ?`, [
    p.instance,
    p.unit,
  ])[0] as { m: number };
  let seq = Number(got.m);
  // Call ids must match: every tool_call requires a corresponding tool result.
  // An unmatched pair prevents the entire context from being sent (see `dropDangling` in `loop.ts`).
  const id = `g-${p.instance}-${p.unit}-${seq + 1}`;
  const at = Date.now();

  run(db, `insert into "${t}" (instance, unit, seq, role, kind, body, at) values (?, ?, ?, 'assistant', 'graded', ?, ?)`, [
    p.instance,
    p.unit,
    ++seq,
    JSON.stringify({ text: "", calls: [{ id, name: p.name, input: p.input }] }),
    at,
  ]);
  run(db, `insert into "${t}" (instance, unit, seq, role, kind, body, at) values (?, ?, ?, 'tool', 'tool', ?, ?)`, [
    p.instance,
    p.unit,
    ++seq,
    JSON.stringify({ id, name: p.name, value: p.value }),
    at,
  ]);
  return seq;
}

/**
 * Known `role` values: **the role column of the inference table above**, not a separately maintained list.
 *
 * This database column is not limited to the model's four roles: `skill` has its own identity. Adapters decide how to present it (`ROLES` in `llm/index.ts` sends `skill` through instructions, not the message stream). **Recognize an identity in the database first, then decide its presentation**. Reversing this would require two coordinated changes per new identity; an omission would silently present that content as someone else's.
 */
export const ROLES = [...new Set(Object.values(FROM).map((f) => f.role))].sort();
/**
 * Outbound destination for each role, plus a readable description. **This is seed data; `msg_role` is the authoritative home.**
 *
 * | role | Destination |
 * | --- | --- |
 * | `user` `assistant` `tool` | Message stream: the model recognizes these three and receives them unchanged. |
 * | `system` `skill` | `instructions`: guidance for this round, not a conversational turn. |
 *
 * **`skill` has its own role**, without borrowing `user`. Borrowing it tells the model that a person is speaking, although the content is a conditionally injected prompt. In measurements, the model responded by asking for the question's specific options rather than answering. There was no error, only lower scores.
 *
 * **Why attach this to role instead of kind?** One kind can have two roles: world `inject` uses `user`; kernel `inject` uses `system`. One belongs in the message stream, the other in instructions. A lookup by kind would force identical destinations where they must differ.
 */
const SENT_AS: [string, string, string][] = [
  ["user", "messages", "A line in the conversation, from whoever is on the other side"],
  ["assistant", "messages", "What the model itself said, including the tools it asked for"],
  ["tool", "messages", "What a tool answered. It has to be here, matched by id to the call above it"],
  ["system", "instructions", "Part of what this turn is told. Resent every turn, and not a thing anyone said"],
  ["skill", "instructions", "A prompt placed by a skill. Its own role, so it is never taken for a person talking"],
];

/**
 * Seed `msg_role` idempotently, just like `seedKinds`.
 *
 * After seeding, **the table is authoritative**: changing a role's destination to instructions in the database takes effect without code changes. Previously this column existed only as a constant in `llm/index.ts`, invalidating the claim that a database alone reconstructs a model request: the matching code version was also needed to know which rows to include.
 */
export function seedRoles(db: Conn): string[] {
  for (const [name, sentAs, note] of SENT_AS) {
    run(
      db,
      `insert into msg_role (name, sent_as, note) values (?, ?, ?)
       on conflict(name) do update set sent_as = excluded.sent_as, note = excluded.note`,
      [name, sentAs, note],
    );
  }
  return SENT_AS.map(([n]) => n);
}

/** Current database mapping: role → destination. **Ready to use directly, without consulting code.** */
export function sentAsIn(db: Conn): Record<string, string> {
  const rows = all(db, `select name, sent_as from msg_role`) as { name: string; sent_as: string }[];
  return Object.fromEntries(rows.map((r) => [String(r.name), String(r.sent_as)]));
}


/** Known message types: seed data for `msg_kind`. **Values are the range of the inference table above.** */
export const KINDS: [string, string][] = [
  ["user", "Written by a person. Prefixed with " + HUMAN_MARK + " on the way out so it stays distinguishable from system injections"],
  ["voice", "Spoken by a person, transcribed from the realtime lane. Its role is also user; only kind tells speech apart from typing"],
  ["inject", "Injected by the system. Also goes out as role=user; only kind tells it apart"],
  ["skill", "A prompt placed by a skill"],
  ["tool", "A tool result"],
  ["prompt", "What the model itself said"],
  ["call", "The model requesting tools; the calls ride in body. Something still has to run these"],
  [
    "graded",
    "A call the system wrote down after the fact, not one the model asked for - an outside judgement, shaped like a call so the model can read it. Nothing runs these: they arrive with their result already attached",
  ],
  ["intervene", "A mark left by a user intervening while it runs"],
];

/**
 * Available treatments for message parts during compression. **Seed data for `press_how`.**
 *
 * An extensible list: add a row for a new treatment, then use its name in the three `msg_part` columns.
 */
/**
 * Inputs accepted by each treatment. **One shared shape for every method**: built-ins and externally declared methods
 * receive the same data, so changing implementations requires no caller changes.
 */
export const PRESS_IN = {
  type: "object",
  properties: {
    part: { type: "string", description: "Which part of a message this is - a name registered in msg_part" },
    name: { type: "string", description: "The tool this part belongs to, when it belongs to one; empty otherwise" },
    level: { type: "string", description: "Which level is asking: l1, l2 or l3" },
    body: { type: "string", description: "The text of that part, whole" },
    bytes: { type: "integer", description: "How big body is" },
  },
  required: ["part", "level", "body"],
} as const;

/** Outputs from each treatment. **Empty = omit this part**, distinct from returning a note describing what was omitted. */
export const PRESS_OUT = {
  type: "object",
  properties: {
    body: { type: "string", description: "The text that goes out in place of it. Absent or empty means it does not go out at all" },
  },
} as const;

/**
 * Available treatments for message parts during compression. **Seed data for `press_how`.**
 *
 * One row = a name + an implementing handle + two schemas, the same shape as `tool`. Thus **built-ins and methods submitted externally through `/declare` use the same rows**. Declare a new method to change compression; no kernel change is needed.
 *
 * `ask` has no handle: it requires a model, and choosing one is an external concern. Reserve the name and schemas; whoever implements it supplies `identity`.
 */
export const HOWS: [string, string, string | null][] = [
  ["keep", "Goes out as it is", "fn:press.keep"],
  ["drop", "Does not go out at all. What was there is not mentioned either - a line saying something was dropped costs tokens and says nothing the level does not already say", "fn:press.drop"],
  ["cut", "Only the head of it goes out, with a count of what is missing. For anything whose beginning identifies it and whose tail is detail", "fn:press.cut"],
  ["sample", "Some of it goes out - the first and the last of a run of like things, with a count of the ones in between. For a stretch of many small parts where the shape matters more than each one", "fn:press.sample"],
  ["top", "The first lines of it go out, with a count of the lines missing. cut measured in lines rather than bytes - for anything that has lines, since cutting by bytes stops mid-line and half a line reads as confidently as a whole one", "fn:press.top"],
  ["tail", "The last lines of it go out, with a count of the lines before them. For anything whose point is at the end - what a test run came to, the innermost frame of a stack, the line in a build log that actually failed. Keeping the head of those keeps the preamble and drops the part worth reading", "fn:press.tail"],
  ["ask", "A model is given it and answers with a line or two, and that answer goes out instead. The only one that costs a call, and the only one that can say what a stretch amounted to rather than what it contained. Nothing in the binary implements it - declare a handle for it", "ask"],
];

/** Seed known treatments into `press_how` idempotently, **without overwriting externally supplied `identity` values**. */
export function seedHows(db: Conn): string[] {
  for (const [name, note, identity] of HOWS) {
    run(
      db,
      `insert into press_how (name, note, identity, params, output) values (?, ?, ?, ?, ?)
       on conflict(name) do update set note = excluded.note, params = excluded.params, output = excluded.output`,
      [name, note, identity === "ask" ? null : identity, JSON.stringify(PRESS_IN), JSON.stringify(PRESS_OUT)],
    );
  }
  return HOWS.map(([n]) => n);
}

/**
 * Message parts and their treatment at each level. **Seed data for `msg_part`.**
 *
 * ## Identify parts by structure, not tool semantics
 *
 * Use intrinsic message fields: `thought`, `body.text`, `body.calls[]`, `body.name`, `kind`, and `role`. The kernel does not decide whether `bash` or `verify` matters more; that belongs to this table, and this table is data.
 *
 * ## How each part is recognized
 *
 * | Part | Criterion |
 * | --- | --- |
 * | `thought` | Nonempty `thought` column |
 * | `said` | `body` for `kind=prompt`, or `body.text` for `kind=call` |
 * | `call` | `body.calls[]` for `kind=call` |
 * | `look` / `event` / `receipt` / `recall` | `body.value` for `kind=tool`; the tool's `tool.gives` selects the category (empty = `event`) |
 * | `verdict` | `kind=graded`: identified by kind, not by a tool named verify |
 * | `task` | The instance's **first message** (`unit=1, seq=1`). The problem statement is delivered through `user` or `world` according to `source`; its kind matches later human messages, so only position distinguishes it. |
 * | `person` | `kind=user` / `voice`, excluding the first message |
 * | `world` | `kind=inject` **and `role=user`** |
 * | `skill` | `kind=skill` |
 * | `intervene` | `kind=intervene` |
 * | `ledger` | `kind=inject` **and `role=system`** |
 *
 * ## How `look` differs from `event`
 *
 * Not by size: `read` at 9511 B per call is the largest return. The distinction is that **`look` can be retrieved again and becomes stale**. After `edit` changes a file, its retained snapshot no longer describes the current file. An `event` is the opposite: a four-minute test run or a verdict cannot be recovered after discarding it, so even the strongest level retains its beginning.
 *
 * Each tool declares its output category through `tool.gives`: **the tool decides**, and this table contains no tool names.
 *
 * **Both `inject` rows must also inspect role.** The value represents two things (see the inference table above): world injection is `inject`+`user`, entering **the message stream**; kernel bookkeeping is `inject`+`system`, entering instructions. Classifying all inject rows as `ledger` would discard even the problem statement of a task submitted by a nonhuman source.
 *
 * ## The three columns are defaults, not mandates
 *
 * As with `tool.usable`, conflicts update only `note`. The next startup must not overwrite a modified policy. Names must be registered in `press_how`.
 *
 * Currently **no cell uses `ask`**: that method has no implementation (`identity` is empty in `press_how`), so selecting it would fail at that level. Once implemented, it belongs in `l3` for `said` and `call`: those parts cannot reliably be reduced by selecting fragments and instead require a fresh explanation.
 *
 * Measured sizes per run across all 112 problems:
 *
 * | Part | Size per run |
 * | --- | --- |
 * | `thought` | **143 MB**, 70% of the total |
 * | Tool results | 28.8 MB: `bash` alone contributes 24.5 MB (`event`); `read` has the largest per-call return at 9511 B (`look`); `write` returns only 131 B (`receipt`). |
 * | `call` | 7.5 MB, including written content (`write` arguments average 8248 B) |
 * | `said` | 1.7 MB |
 * | `verdict` | 225 KB |
 * | `task` | 240 KB |
 */
export const PARTS: [string, string, string, string, string][] = [
  ["thought", "The reasoning a model produced before it spoke. Its own column, replayed inside every later request", "keep", "sample", "drop"],
  ["said", "What the model itself said, apart from the calls it asked for", "keep", "keep", "keep"],
  ["call", "The tools it asked for, with their arguments - which is where the content it wrote out lives", "keep", "keep", "keep"],
  ["look", "A tool answered with a state that can be looked at again - a file as it was, a listing, a search. It can be had back, and it goes stale: once the same file has been edited, the copy in the context is describing something that is no longer there. Kept by lines rather than bytes: what it holds is lines - a file, a listing, matches - and a byte count stops in the middle of one, which then reads as confidently as a whole one", "keep", "top", "top"],
  ["event", "A tool answered with something that happened and cannot be had back - a test run that took four minutes, a build, a script. Kept by its end rather than its head: a run says what it came to in its last lines, and its first lines are the command echoing back. Something of it survives the last level too, because nothing can produce it a second time", "tail", "sample", "sample"],
  ["receipt", "A tool answered that a change went through. Tens of bytes, and the only index of what this attempt actually changed", "keep", "keep", "keep"],
  ["recall", "A tool answered with this conversation's own context read back - the tree of attempts, another node. Gone at every level: it is a copy of something the store already holds, so keeping it inside a compressed node means carrying another node's summary in the middle of this one. Nothing is lost by dropping it, since asking for it again is one call", "drop", "drop", "drop"],
  ["verdict", "A judgement written down after the fact, not asked for by the model. Recognised by its kind, not by which tool produced it", "keep", "keep", "keep"],
  ["task", "The task as it was handed over - the first message of the instance. Its kind is the same as a person talking, so only its position tells them apart", "keep", "keep", "keep"],
  ["person", "A line from whoever is on the other side, typed or spoken, after the task itself", "keep", "keep", "drop"],
  ["world", "Something the system put into the conversation. Goes out as a user message - inject alone does not say which of the two this is, role does", "cut", "cut", "drop"],
  ["skill", "A prompt a skill placed. Its own role so it is never taken for a person talking; it goes out as instructions rather than in the stream", "keep", "keep", "drop"],
  ["intervene", "A mark left by a person intervening while it runs. Registered since the beginning and still written by nothing - the route that says it writes one delivers it as a plain user line", "drop", "drop", "drop"],
  ["ledger", "The kernel's own note of what was on offer that round. inject as well, but role=system: it goes out as instructions and was never in the message stream", "drop", "drop", "drop"],
];

/** Seed known parts into `msg_part` idempotently, **without overwriting modified policies in the three columns**. */
export function seedParts(db: Conn): string[] {
  for (const [name, note, l1, l2, l3] of PARTS) {
    run(
      db,
      // Set `l4` explicitly to null: it is unconfigured, and **unconfigured must differ from `keep`**.
      // The former means skip this level; the latter means use it without compressing anything.
      `insert into msg_part (name, note, l1, l2, l3, l4) values (?, ?, ?, ?, ?, null)
       on conflict(name) do update set note = excluded.note`,
      [name, note, l1, l2, l3],
    );
  }
  return PARTS.map(([n]) => n);
}

/** Seed known message types into `msg_kind` idempotently. */
export function seedKinds(db: Conn): string[] {
  for (const [name, note] of KINDS) {
    run(db, `insert into msg_kind (name, note) values (?, ?) on conflict(name) do update set note = excluded.note`, [
      name,
      note,
    ]);
  }
  return KINDS.map(([n]) => n);
}
