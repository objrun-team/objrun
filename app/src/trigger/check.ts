/**
 * Two tools for trigger conditions: **validate without running the system**, and **explain why a match failed**.
 *
 * The old implementation warned:
 *
 * > A typical mistake **silently has no effect**, even when the system is exercised.
 *
 * Invalid conditions can leave a rule permanently inactive while everything else runs normally.
 * These tools are prerequisites for using the trigger table, not optional debugging conveniences.
 *
 * ## check: validate every condition without starting the engine
 *
 * Unknown dimensions or comparisons, missing references, non-list `in` values, and keywords
 * containing spaces are **detectable during loading**. Do not defer them until execution.
 *
 * ## explain: identify each failing condition
 *
 * The two common causes occur before candidate evaluation: **the keyword is absent from the
 * text**, or **the dimension has no such property**. Show the actual retrieved value instead
 * of merely saying that the condition did not match.
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import { compare, DIMS, MOMENTS, OPS, pick, type Facts } from "../engine/trigger.ts";

export interface Term {
  owner_kind: string;
  owner: string;
  group: number;
  dim: string;
  key: string;
  op: string;
  value: string;
}

export interface Problem {
  owner_kind: string;
  owner: string;
  group: number;
  why: string;
}

/** Table to consult for the existence of each owner type. */
const OWNER_TABLE: Record<string, { table: string; col: string }> = {
  rule: { table: "rule", col: "identity" },
  tool: { table: "tool", col: "name" },
  skill: { table: "skill", col: "identity" },
};

/** Properties available on a dimension: the corresponding table columns. */
function keysOf(db: Conn, dim: string): string[] {
  const table = dim === "cycle" ? "cycle" : dim === "task" ? "task" : dim === "agent" ? "agent" : "";
  if (!table) return [];
  return (all(db, `pragma table_info("${table}")`) as { name: string }[]).map((r) => r.name);
}

/**
 * Validate every trigger condition **without running the system**.
 *
 * Return a list of problems; an empty list means all checks passed.
 */
export function check(db: Conn): Problem[] {
  const out: Problem[] = [];
  const terms = all(db, `select owner_kind, owner, "group", dim, "key", op, value from trigger`) as unknown as Term[];
  const keys = new Map(DIMS.map((d) => [d as string, keysOf(db, d)]));

  const say = (t: Term, why: string) =>
    out.push({ owner_kind: t.owner_kind, owner: t.owner, group: Number(t.group), why });

  for (const t of terms) {
    // Unknown dimensions or comparisons never trigger, and a one-character typo can be difficult to notice.
    if (!(DIMS as readonly string[]).includes(t.dim)) {
      say(t, `unknown dimension ${t.dim} (known: ${DIMS.join(" / ")})`);
      continue;
    }
    if (!(OPS as readonly string[]).includes(t.op)) {
      say(t, `unknown operator ${t.op} (known: ${OPS.join(" / ")})`);
      continue;
    }

    // `chain` / `moment` / `place` have no property key. Other dimensions require a real column in their table.
    if (t.dim === "chain" || t.dim === "moment" || t.dim === "place") {
      if (t.key.trim() !== "") say(t, `dimension ${t.dim} has no attributes, so key must be empty, but it says ${t.key}`);
      if (t.dim === "moment" && !(MOMENTS as readonly string[]).includes(t.value)) {
        say(t, `unknown moment ${t.value} (the kernel raises: ${MOMENTS.join(" / ")})`);
      }
    } else {
      const ks = keys.get(t.dim) ?? [];
      if (!ks.includes(t.key)) {
        say(t, `dimension ${t.dim} has no attribute ${t.key} (it has: ${ks.join(" / ")})`);
      }
    }

    // An `in` value must decode as a list.
    if (t.op === "in") {
      try {
        if (!Array.isArray(JSON.parse(t.value))) say(t, `the value for in must be a list, but it is ${t.value}`);
      } catch {
        say(t, `the value for in is not readable JSON: ${t.value}`);
      }
    }

    // Keywords cannot contain spaces: **spaces imply several words combined into one condition**.
    // Do not guess whether adjacency or order was intended; use separate conditions in one group.
    if (t.op !== "in" && /\s/.test(t.value) && t.dim !== "task") {
      say(t, `the value contains a space: ${JSON.stringify(t.value)} - split it into two terms in the same group rather than letting the system guess`);
    }

    // Whether the referenced owner exists.
    const at = OWNER_TABLE[t.owner_kind];
    if (!at) {
      say(t, `unknown owner_kind ${t.owner_kind} (known: ${Object.keys(OWNER_TABLE).join(" / ")})`);
    } else if (all(db, `select 1 from "${at.table}" where "${at.col}" = ?`, [t.owner]).length === 0) {
      say(t, `no row in ${at.table} for ${t.owner} - nothing will ever use this term`);
    }
  }

  // An owner with no conditions never triggers. **This is not inherently invalid**; system tools
  // use tool.system. Still report it because missing conditions are often accidental.
  for (const [kind, at] of Object.entries(OWNER_TABLE)) {
    const owners = (all(db, `select "${at.col}" as id from "${at.table}"`) as { id: string }[]).map((r) => r.id);
    for (const id of owners) {
      if (terms.some((t) => t.owner_kind === kind && t.owner === id)) continue;
      if (kind === "tool") {
        const sys = all(db, `select system from tool where name = ?`, [id])[0] as { system: number } | undefined;
        if (sys && Number(sys.system)) continue; // System tools legitimately ignore trigger conditions.
      }
      out.push({ owner_kind: kind, owner: id, group: 0, why: "no trigger terms at all - it will never be attached to anything" });
    }
  }

  return out;
}

/** Whether one condition matches these facts. */
export interface Told {
  group: number;
  dim: string;
  key: string;
  op: string;
  value: string;
  /** **The actual retrieved value**, where the common causes of a failed match become visible. */
  got: string;
  hit: boolean;
  error?: string;
}

/**
 * Explain a failed match.
 *
 * Show each condition **with its actual input value**. A bare mismatch would make users guess
 * whether they misspelled a keyword or the keyword was absent from the text.
 */
export function explain(db: Conn, kind: string, owner: string, f: Facts): { fired: boolean; groups: Told[][] } {
  const terms = all(
    db,
    `select owner_kind, owner, "group", dim, "key", op, value from trigger where owner_kind = ? and owner = ? order by "group"`,
    [kind, owner],
  ) as unknown as Term[];

  const byGroup = new Map<number, Term[]>();
  for (const t of terms) {
    const g = Number(t.group);
    byGroup.set(g, [...(byGroup.get(g) ?? []), t]);
  }

  const groups: Told[][] = [];
  let fired = false;
  for (const [g, ts] of [...byGroup].sort((a, b) => a[0] - b[0])) {
    const told: Told[] = ts.map((t) => {
      try {
        const got = pick(f, t.dim, t.key);
        return { group: g, dim: t.dim, key: t.key, op: t.op, value: t.value, got, hit: compare(t.op, got, t.value) };
      } catch (e) {
        return {
          group: g,
          dim: t.dim,
          key: t.key,
          op: t.op,
          value: t.value,
          got: "",
          hit: false,
          error: e instanceof Error ? e.message : String(e),
        };
      }
    });
    groups.push(told);
    if (told.length && told.every((x) => x.hit)) fired = true;
  }
  return { fired, groups };
}

// Reuse `fire`'s value-extraction and comparison functions directly. Separate implementations
// would drift, making explain misrepresent actual behavior, which is worse than no explanation.
