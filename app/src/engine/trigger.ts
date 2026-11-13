/**
 * Determine which owner should trigger at a given time.
 *
 * Conditions live in `trigger`, one condition per row: **AND within a group, OR between groups**.
 * This layer performs comparisons without knowing any specific rule, tool, or cycle names.
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";

/** Facts available to comparisons. `chain` is the formatted execution-chain string. */
export interface Facts {
  agent: Record<string, unknown>;
  task: Record<string, unknown>;
  cycle: Record<string, unknown>;
  chain: string;
  /**
   * The workspace of **this execution unit**, not the task's original workspace.
   *
   * They initially match, but workspace assignments propagate row by row (see station creation
   * in `loop.ts`). After branching, two units of the same task can run in different places.
   * Tool availability must use the current unit's place; using `task.place` would select incorrectly.
   */
  place: string;
  /** The current lifecycle moment; see `MOMENTS`. Conditions not evaluated at a moment do not use it. */
  moment?: string;
}

interface Term {
  owner_kind: string;
  owner: string;
  group: number;
  dim: string;
  key: string;
  op: string;
  value: string;
}

/**
 * Supported comparisons. **This set is authoritative**; do not maintain another registration table.
 *
 * A separate list can drift from implementation, for example after renaming `contains` on only
 * one side. The valid values are exactly those supported by this switch, so validation checks
 * this implementation directly.
 */
export const OPS = ["eq", "ne", "contains", "not_contains", "prefix", "suffix", "in"] as const;

/** Supported dimensions, likewise without a separate registration table. */
export const DIMS = ["agent", "task", "cycle", "chain", "moment", "place"] as const;

/**
 * Lifecycle moments announced by the kernel. **Hooks attach to these points** through a rule
 * and a `dim=moment` condition, without a separate hooks table.
 *
 * The old implementation used `cards/<id>/hooks/<event_type>/*.py`, one directory per moment.
 * Here the moment is **a data value**, and `trigger` determines what attaches to it.
 */
export const MOMENTS = ["unit_start", "pre_send", "post_send", "task_done"] as const;

/** Supported comparisons. A typo must not silently fail to match; reject unknown names immediately. */
export function compare(op: string, got: string, want: string): boolean {
  switch (op) {
    case "eq":
      return got === want;
    case "ne":
      return got !== want;
    case "contains":
      return got.includes(want);
    case "not_contains":
      // Negation: a present value prevents a match. The old code used a separate absent field;
      // here it is a comparison operator, removing a field and allowing AND with other conditions.
      return !got.includes(want);
    case "prefix":
      return got.startsWith(want);
    case "suffix":
      return got.endsWith(want);
    case "in":
      return (JSON.parse(want) as unknown[]).map(String).includes(got);
    default:
      throw new Error(`unknown operator: ${op}`);
  }
}

export function pick(f: Facts, dim: string, key: string): string {
  switch (dim) {
    case "chain":
      return f.chain;
    case "place":
      return f.place;
    case "moment":
      return f.moment ?? "";
    case "agent":
    case "task":
    case "cycle": {
      const row = f[dim];
      if (!(key in row)) throw new Error(`dimension ${dim} has no attribute ${key}`);
      return String(row[key] ?? "");
    }
    default:
      throw new Error(`unknown dimension: ${dim}`);
  }
}

/**
 * Owners that should trigger now.
 *
 * An owner matches when **any group** matches (OR between groups); **every condition** in that
 * group must match (AND within groups). No conditions means never, not always. The opposite
 * interpretation would activate declarations everywhere when their conditions were omitted.
 */
export function fire(db: Conn, kind: string, f: Facts): string[] {
  const terms = all(
    db,
    `select owner_kind, owner, "group", dim, "key", op, value from trigger where owner_kind = ?`,
    [kind],
  ) as unknown as Term[];

  const byOwnerGroup = new Map<string, Term[]>();
  for (const t of terms) {
    const k = `${t.owner}\u0000${t.group}`;
    const arr = byOwnerGroup.get(k);
    if (arr) arr.push(t);
    else byOwnerGroup.set(k, [t]);
  }

  const hit = new Set<string>();
  for (const [k, group] of byOwnerGroup) {
    const owner = k.slice(0, k.indexOf("\u0000"));
    if (hit.has(owner)) continue;
    if (group.every((t) => compare(t.op, pick(f, t.dim, t.key), t.value))) hit.add(owner);
  }
  return [...hit].sort();
}
