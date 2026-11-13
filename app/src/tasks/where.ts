/**
 * Locate an execution-unit instance: **its task and subtable**.
 *
 * Tool handles receive only `{args, place, agent, instance, unit}` (see `runOne` in `tools/unit.ts`).
 * Resolve the task from the database, **never from caller-supplied arguments**. Callers may omit
 * it, and models can alter arguments: accepting a task id would let a model query another task's G.
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import { tableNameOf } from "../install/index.ts";

export interface Where {
  /** Task id. */
  task: string;
  /** The subtable used by this task (`task_<mode>`). */
  sub: string;
}

/** Look up an instance. Return `null` if it was never registered. */
export function whereAmI(db: Conn, instance: string): Where | null {
  for (const m of all(db, `select distinct mode from cycle`) as { mode: string }[]) {
    const sub = tableNameOf("task_{}", m.mode);
    const r = all(db, `select task from "${sub}" where instance = ? limit 1`, [instance])[0] as
      | { task: string }
      | undefined;
    if (r) return { task: r.task, sub };
  }
  return null;
}
