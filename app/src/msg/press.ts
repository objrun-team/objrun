/**
 * Compress a node into three versions, and provide the built-in compression methods.
 *
 * ## When to compress
 *
 * **When a node closes** (its station reaches a terminal state). Do not compress a node still producing output: its messages are in use, and the next station may continue the exchange. Thus **the current node always retains the original text**; only closed ancestors are compressed.
 *
 * Store the results (`press` + `press_l1/l2/l3`, referenced by `task_{mode}.press`) instead of computing them when sending a request. On-demand computation could compress the same slot differently for every request; failures cannot be reproduced if context changes underneath the model.
 *
 * ## Who decides
 *
 * Split a message using only **its intrinsic structure** (`thought`, `body.text`, `body.calls[]`, `kind`, `role`). A tool's own `tool.gives` declares its return category. Look up each part's treatment at each level in `msg_part`; the `press_how.identity` handle performs it.
 *
 * This file therefore contains **no tool names and no judgments about relative importance**: those belong in the tables.
 *
 * ## Built-in methods
 *
 * `keep` / `drop` / `cut` / `sample` are pure functions shipped with the binary. `ask` (having a model rewrite a passage) is not here: it needs a model, and choosing that model is an external concern. Declare a handle for it.
 */

import { createHash } from "node:crypto";

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { tableNameOf } from "../install/index.ts";

/** One compression request. */
export interface Press {
  part: string;
  name?: string;
  level: string;
  body: string;
  bytes?: number;
}

/** Bytes to retain with `cut`. */
export const CUT_BYTES = 2_000;
/** Leading and trailing lines to retain with `sample`. */
export const SAMPLE_HEAD = 3;
export const SAMPLE_TAIL = 3;
/** Lines retained by `top` and `tail`. About one screen: a stack trace or a test result is typically this size. */
export const TOP_LINES = 20;
export const TAIL_LINES = 20;

/**
 * Level column names, **ordered from lightest to strongest compression**. Move through this order when selecting a level.
 *
 * There are four columns, but **only the first three are configured**: `l4` remains empty in `msg_part` (see `readyLevels`). Neither write nor send an unconfigured level. Reserve the column now because the next compression method (having a model replace a passage with a sentence) is declared externally against a running database. Adding a column then would require a migration.
 */
export const LEVELS = ["l1", "l2", "l3", "l4"] as const;
export type Level = (typeof LEVELS)[number];

/**
 * Levels that are **fully configured**: every `msg_part` row specifies how that level handles it.
 *
 * The criterion is **every row**, not merely some rows. Partial configuration would give some parts a policy and leave others unspecified, with multiple plausible interpretations and no error.
 *
 * Return an empty list when there are no rows (the table is not seeded): nothing is configured, rather than all four levels being ready.
 */
export function readyLevels(db: Conn): Level[] {
  const rows = all(db, `select ${LEVELS.map((l) => `"${l}"`).join(", ")} from msg_part`) as Record<string, string | null>[];
  if (rows.length === 0) return [];
  return LEVELS.filter((l) => rows.every((r) => String(r[l] ?? "").trim() !== ""));
}

const say = (v: unknown): string => (typeof v === "string" ? v : String(v ?? ""));
const B = (s: string) => Buffer.byteLength(s, "utf8");
const id = (s: string) => createHash("sha256").update(s).digest("hex").slice(0, 32);

/**
 * Keep the beginning and append a note describing how much remains.
 *
 * The note costs a few dozen bytes, but **without it the model cannot know the text is truncated** and will reason from the fragment. Such failures are especially hard to diagnose because the input appears complete.
 */
export function cut(body: string, keep = CUT_BYTES): string {
  const size = B(body);
  if (size <= keep) return body;
  return `${Buffer.from(body, "utf8").subarray(0, keep).toString("utf8")}\n... (${size - keep} more bytes)`;
}

/**
 * Keep the first few lines and append a note with the remaining line count.
 *
 * This is `cut` measured differently: `cut` counts bytes; `top` counts lines. **Preserve line-oriented content by line**. A byte cut may leave half a line that looks just as authoritative as a complete one.
 */
export function top(body: string, keep = TOP_LINES): string {
  const lines = body.split("\n");
  // Do not truncate just one extra line: saving one line would cost one line to announce the saving.
  if (lines.length <= keep + 1) return body;
  return [...lines.slice(0, keep), `... (${lines.length - keep} more lines)`].join("\n");
}

/**
 * Keep the last few lines and prepend a note with the omitted line count.
 *
 * The opposite of `top`, for content whose **conclusion comes last**: the final test-run lines, the last stack frame, or the actual failure in a build log. Keeping the beginning would retain the setup and discard exactly the part needed.
 */
export function tail(body: string, keep = TAIL_LINES): string {
  const lines = body.split("\n");
  if (lines.length <= keep + 1) return body;
  return [`... (${lines.length - keep} earlier lines)`, ...lines.slice(-keep)].join("\n");
}

/** Leading lines + trailing lines, with an omitted count in between. Sample lines, not bytes: half a line is meaningless. */
export function sample(body: string, head = SAMPLE_HEAD, foot = SAMPLE_TAIL): string {
  const lines = body.split("\n");
  if (lines.length <= head + foot + 1) return body;
  return [...lines.slice(0, head), `... (${lines.length - head - foot} more lines)`, ...lines.slice(-foot)].join("\n");
}

/** Register the built-in methods. **Return the registered handle names.** */
export function registerPress(db: Conn, reg: Registry): string[] {
  const names: string[] = [];
  const one = (name: string, f: (p: Press) => { body?: string }) => {
    const handle = `fn:press.${name}`;
    reg.register(db, handle, 10_000, async (arg) => f((arg ?? {}) as Press));
    names.push(handle);
  };
  one("keep", (p) => ({ body: say(p.body) }));
  // **Return an object without body, not an empty string.** They look alike in the database, but readers distinguish
  // an absent part from a present part with empty content.
  one("drop", () => ({}));
  one("cut", (p) => ({ body: cut(say(p.body)) }));
  one("sample", (p) => ({ body: sample(say(p.body)) }));
  one("top", (p) => ({ body: top(say(p.body)) }));
  one("tail", (p) => ({ body: tail(say(p.body)) }));
  return names;
}

// ── Split ─────────────────────────────────────────────────────────────

/** One part of a split message. */
export interface Piece {
  part: string;
  /** The tool this part belongs to; empty if it belongs to none. */
  name: string;
  body: string;
}

interface Row {
  unit: number;
  seq: number;
  role: string;
  kind: string;
  body: string;
  thought: string | null;
}

/**
 * Split a message into parts. **Structure is the sole criterion**; see the file header.
 *
 * `gives` maps tool names to return categories. The caller reads it once from `tool` and passes it in: querying for each split row would mean hundreds of queries per node.
 */
export function piecesOf(r: Row, first: boolean, gives: Map<string, string>): Piece[] {
  const out: Piece[] = [];
  if (r.thought) out.push({ part: "thought", name: "", body: r.thought });

  if (r.kind === "call" || r.kind === "graded") {
    let v: { text?: unknown; calls?: { name?: unknown; input?: unknown }[] };
    try {
      v = JSON.parse(r.body) as typeof v;
    } catch {
      return out;
    }
    const text = say(v.text).trim();
    if (text) out.push({ part: "said", name: "", body: text });
    for (const c of v.calls ?? []) {
      // `graded` is a verdict recorded afterward by the system: identify it by kind, not the tool name.
      out.push({
        part: r.kind === "graded" ? "verdict" : "call",
        name: say(c.name),
        body: `${say(c.name)} ${JSON.stringify(c.input ?? {})}`,
      });
    }
    return out;
  }

  if (r.kind === "tool") {
    let v: { name?: unknown; value?: unknown };
    try {
      v = JSON.parse(r.body) as typeof v;
    } catch {
      return out;
    }
    const name = say(v.name);
    // The tool declares its own return category. **Unspecified = `event`**:
    // treating irrecoverable information as recoverable is the one direction of error we cannot afford.
    out.push({ part: gives.get(name) || "event", name, body: JSON.stringify(v.value ?? null) });
    return out;
  }

  if (r.kind === "prompt") {
    if (r.body.trim()) out.push({ part: "said", name: "", body: r.body });
    return out;
  }
  // `inject` covers two cases: world injection uses role=user and enters the message stream; kernel bookkeeping uses role=system and enters instructions.
  // **Inspect role as well.**
  if (r.kind === "inject") {
    out.push({ part: r.role === "system" ? "ledger" : "world", name: "", body: r.body });
    return out;
  }
  if (r.kind === "user" || r.kind === "voice") {
    // The problem statement shares a kind with human messages; position distinguishes them: the first instance message is the problem statement.
    out.push({ part: first ? "task" : "person", name: "", body: r.body });
    return out;
  }
  if (r.kind === "skill" || r.kind === "intervene") {
    out.push({ part: r.kind, name: "", body: r.body });
    return out;
  }
  out.push({ part: "person", name: "", body: r.body });
  return out;
}

// ── Compress ──────────────────────────────────────────────────────────

interface Policy {
  /** Part name → compression method at each level. An unconfigured level is an empty string. */
  part: Map<string, Record<Level, string>>;
  /** Configured levels. **Only these levels are written and sent.** */
  ready: Level[];
  /** Compression-method name → implementing handle. Omit methods with no implementation. */
  how: Map<string, string>;
  /** Tool name → return category. */
  gives: Map<string, string>;
}

/** Read the three tables once. **Once per node, not once per part.** */
export function policyOf(db: Conn): Policy {
  const part = new Map<string, Record<Level, string>>();
  for (const r of all(db, `select name, ${LEVELS.join(", ")} from msg_part`) as Record<string, string | null>[]) {
    const at = {} as Record<Level, string>;
    for (const l of LEVELS) at[l] = String(r[l] ?? "");
    part.set(String(r.name), at);
  }
  const how = new Map<string, string>();
  for (const r of all(db, `select name, identity from press_how where identity is not null and identity <> ''`) as {
    name: string;
    identity: string;
  }[]) {
    how.set(String(r.name), String(r.identity));
  }
  const gives = new Map<string, string>();
  for (const r of all(db, `select name, gives from tool where gives is not null and gives <> ''`) as {
    name: string;
    gives: string;
  }[]) {
    gives.set(String(r.name), String(r.gives));
  }
  return { part, ready: readyLevels(db), how, gives };
}

/**
 * Compress one slot into a passage.
 *
 * Prefix each part with a marker so tool results remain distinguishable from model text when combined.
 * Return an empty string if no parts remain: omit that slot entirely at this level.
 */
export async function pressUnit(reg: Registry, pieces: Piece[], level: Level, p: Policy): Promise<string> {
  const out: string[] = [];
  for (const one of pieces) {
    const how = p.part.get(one.part)?.[level] ?? "keep";
    // Empty = this level is not configured in `msg_part`. Reaching it is a caller error (check `ready` first).
    // Falling back to keep would place original text in a supposedly compressed level.
    if (!how) throw new Error(`msg_part says nothing about ${one.part} at ${level}`);
    const handle = p.how.get(how);
    // **Fail immediately for an unimplemented method.** Silently falling back to keep would send content unchanged
    // when compression was promised, with the only symptom being an unexpectedly large context.
    if (!handle) throw new Error(`msg_part says ${one.part} is ${how} at ${level}, but no handle implements ${how}`);
    const back = (await reg.get(handle).call({
      part: one.part,
      name: one.name,
      level,
      body: one.body,
      bytes: B(one.body),
    })) as { body?: unknown };
    const body = say(back?.body);
    if (!body) continue;
    out.push(one.name ? `[${one.part} ${one.name}] ${body}` : `[${one.part}] ${body}`);
  }
  return out.join("\n");
}

/**
 * Compress every slot in a node into three versions and store them. **Return the number of compressed slots.**
 *
 * Skip slots already compressed: a node closes only once, but reinstallation or replay may reach here again.
 */
export async function pressNode(
  db: Conn,
  reg: Registry,
  at: { sub: string; task: string; node: number; agent: string; instance: string },
): Promise<number> {
  const units = (all(db, `select unit, press from "${at.sub}" where task = ? and node = ? order by unit`, [
    at.task,
    at.node,
  ]) as { unit: number; press: string | null }[]).filter((u) => !u.press);
  if (units.length === 0) return 0;

  const t = tableNameOf("agent_{}_msg", at.agent);
  const holes = units.map(() => "?").join(", ");
  const rows = all(
    db,
    `select unit, seq, role, kind, body, thought from "${t}" where instance = ? and unit in (${holes}) order by unit, seq`,
    [at.instance, ...units.map((u) => u.unit)],
  ) as unknown as Row[];

  const p = policyOf(db);
  const byUnit = new Map<number, Row[]>();
  for (const r of rows) byUnit.set(Number(r.unit), [...(byUnit.get(Number(r.unit)) ?? []), r]);

  let done = 0;
  for (const u of units) {
    const mine = byUnit.get(Number(u.unit)) ?? [];
    if (mine.length === 0) continue;
    const pieces = mine.flatMap((r) => piecesOf(r, Number(r.unit) === 1 && Number(r.seq) === 1, p.gives));

    const at3: Record<string, string> = {};
    for (const level of p.ready) {
      const body = await pressUnit(reg, pieces, level, p);
      // **One passage per row, with a content-derived id**: two slots compressing to identical text share a row automatically,
      // so several slots can naturally be represented by one passage.
      const rid = id(body);
      run(db, `insert into "press_${level}" (id, body, bytes) values (?, ?, ?) on conflict(id) do nothing`, [
        rid,
        body,
        B(body),
      ]);
      at3[level] = rid;
    }
    // Derive the id from **all** levels, including empty ones. When `l4` gains content, two previously identical slots
    // may need separate rows; the id will change automatically.
    const pid = id(LEVELS.map((l) => at3[l] ?? "").join(" "));
    const cols = LEVELS.filter((l) => at3[l]);
    run(
      db,
      `insert into press (id, ${cols.join(", ")}) values (${["?", ...cols.map(() => "?")].join(", ")}) on conflict(id) do nothing`,
      [pid, ...cols.map((l) => at3[l])],
    );
    run(db, `update "${at.sub}" set press = ? where task = ? and unit = ?`, [pid, at.task, u.unit]);
    done++;
  }
  return done;
}

/** A message row; only these columns are needed. */
export interface Line {
unit: number;
seq: number;
role: string;
kind: string;
body: string;
thought: string | null;
}

/**
 * Replace **closed nodes** with their compressed versions. Leave the current node untouched: its messages are still in use.
 *
 * Replace by **node**, not slot: a call and its result occupy adjacent slots. Replacing only one would leave an orphaned result, causing the model to reject the entire context.
 *
 * Send original text for uncompressed nodes (empty `press`). Compression occurs at closure; its failure must not also prevent this request from being sent.
 *
 * **Request dispatch and later reconstruction share this function** (`engine/loop.ts` and `scripts/request.ts`). Separate implementations would make reconstruction measure the script rather than the actual request.
 */
export function swapClosed(
db: Conn,
at: { sub: string; task: string; unit: number },
rows: Line[],
line: number[],
level: Level,
): Line[] {
  const nodes = all(
    db,
    `select unit, node, status from "${at.sub}" where task = ? and unit in (${line.map(() => "?").join(", ")})`,
    [at.task, ...line],
  ) as unknown as { unit: number; node: number; status: string | null }[];
  const here = nodes.find((n) => Number(n.unit) === at.unit)?.node;
  const closed = new Set(
    nodes.filter((n) => Number(n.node) !== Number(here)).map((n) => Number(n.node)),
  );
  if (closed.size === 0) return rows;

  const nodeOf = new Map(nodes.map((n) => [Number(n.unit), Number(n.node)]));
  const swap = line.filter((u) => closed.has(nodeOf.get(u) ?? -1));
  const bodies = bodiesAt(db, at.sub, at.task, swap, level);

  const out: Line[] = [];
  for (const r of rows) {
    const u = Number(r.unit);
    if (!closed.has(nodeOf.get(u) ?? -1)) {
      out.push(r);
      continue;
    }
    // This slot belongs to a compressed node: replace its own rows with the compressed passage.
    // **Emit each passage only once**; sharing across slots is common, and `bodiesAt` already deduplicates them.
    const body = bodies.get(u);
    if (body === undefined) {
      // Uncompressed: this slot is absent from `bodiesAt`, so send its original text.
      if (!bodies.size) out.push(r);
      continue;
    }
    if (out.some((x) => Number(x.unit) === u)) continue;
    // If compression produces an empty string (every part was dropped at this level), omit the entire slot.
    // An empty message wastes an entry; some providers reject empty content with only a generic message-list error.
    if (!body.trim()) continue;
    out.push({ unit: u, seq: 1, role: "user", kind: "user", body, thought: null } as unknown as Line);
  }
  return out;
}

/**
 * Bodies for these slots at a given level. **Emit each row only once**: multiple slots commonly reference one passage.
 * Repeating it for every slot would add back all the content saved.
 */
export function bodiesAt(db: Conn, sub: string, task: string, units: number[], level: Level): Map<number, string> {
  if (units.length === 0) return new Map();
  const holes = units.map(() => "?").join(", ");
  const rows = all(
    db,
    `select s.unit as unit, l.body as body, s.press as press
       from "${sub}" s join press p on p.id = s.press join "press_${level}" l on l.id = p."${level}"
      where s.task = ? and s.unit in (${holes})`,
    [task, ...units],
  ) as { unit: number; body: string; press: string }[];
  const seen = new Set<string>();
  const out = new Map<number, string>();
  for (const r of rows.sort((a, b) => Number(a.unit) - Number(b.unit))) {
    const key = String(r.body);
    if (seen.has(key)) continue;
    seen.add(key);
    out.set(Number(r.unit), String(r.body));
  }
  return out;
}
