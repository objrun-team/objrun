/**
 * Execution-chain strings, compared by trigger conditions with `dim=chain`.
 *
 * # This is a protocol, not an implementation detail
 *
 * Changing the format makes every `dim=chain` condition **silently stop matching**.
 * Keep formatting in this one function. A format change is a protocol change and requires
 * migrating existing database conditions too.
 *
 * ## Format
 *
 * Starting at the task's root node, follow `from_cycle` / `from_unit` to the current execution
 * unit. Format each segment as `mode/cycle#unit` and join segments with ` > `.
 *
 * ```
 * dfs/open#1 > dfs/scope#1 > dfs/act#2
 * ```
 *
 * Segments run **from the root to the current unit**, never backward, so comparisons such
 * as `prefix` have the intended meaning.
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";

export interface Unit {
  task: string;
  cycle: string;
  unit: number;
  from_cycle: string | null;
  from_unit: number | null;
}

const SEP = " > ";

function seg(mode: string, u: { cycle: string; unit: number }): string {
  return `${mode}/${u.cycle}#${u.unit}`;
}

/**
 * Construct the chain string for the current row.
 *
 * Follow `from` pointers until there is no predecessor. **Fail immediately on a cycle**:
 * returning to the same execution unit indicates corrupt data; silently continuing would hang.
 */
export function chainOf(db: Conn, sub: string, mode: string, at: Unit): string {
  const segs: string[] = [seg(mode, at)];
  const seen = new Set<string>([`${at.cycle}#${at.unit}`]);
  let cur = at;

  while (cur.from_cycle !== null && cur.from_unit !== null) {
    const key = `${cur.from_cycle}#${cur.from_unit}`;
    if (seen.has(key)) throw new Error(`chain for ${at.task} in ${sub} is cyclic, at ${key}`);
    seen.add(key);
    const rows = all(
      db,
      `select task, cycle, unit, from_cycle, from_unit from "${sub}"
        where task = ? and cycle = ? and unit = ?`,
      [cur.task, cur.from_cycle, cur.from_unit],
    ) as unknown as Unit[];
    if (rows.length === 0) {
      throw new Error(`${sub} ${at.task} ${seg(mode, cur)} says it came from ${key}, but that row is missing`);
    }
    cur = rows[0];
    segs.unshift(seg(mode, cur));
  }
  return segs.join(SEP);
}
