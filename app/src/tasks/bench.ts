/**
 * Execute a benchmark run.
 *
 * The old protocol had three steps:
 *
 * 1. Construct a `G` for each sample.
 * 2. Solve samples in training mode: **first metric, number with `G=1`**.
 * 3. Distill, then rerun without `G`: **second metric, number resolved**.
 *
 * Here a benchmark run is **a batch of tasks, each with its own G**, identified by `task.run`.
 * Count tasks with `G=1` at completion; no separate scoring system is needed because G already
 * determines state.
 *
 * ## Publish the entire batch or none of it
 *
 * If one task has an invalid G, **reject the whole batch**. Publishing only part would silently
 * change the result denominator without revealing missing tasks. This extends the same atomic
 * rejection principle used for one task.
 *
 * ## No separate benchmark table
 *
 * A run's result is **computed**, not stored: group and count `task` by `run`. A stored copy
 * could silently diverge from the actual task records.
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import type { Sealed } from "../objective/store.ts";
import { publish, type Publish } from "./publish.ts";

export interface Bench {
  /** Run name. Generate one from the timestamp if omitted. */
  run?: string;
  /** Every task in the batch. The outer declaration supplies `run` uniformly. */
  tasks: Publish[];
}

export interface Score {
  run: string;
  total: number;
  /** Number of tasks with `G=1`: **the first metric**. */
  passed: number;
  failed: number;
  running: number;
  /** Tasks that have not started. */
  open: number;
  tasks: { id: string; state: string; result: string | null }[];
}

/**
 * Publish a batch. **Validate every task first; one failure rejects the entire batch.**
 *
 * Attempt publication inside one transaction and roll back if any task throws. Per-task checks
 * (source, G definition, readable, mode/agent/place existence) remain in `publish`, not duplicated here.
 */
export function runBench(db: Conn, b: Bench, sealed: Sealed): { run: string; ids: string[] } {
  // As in `publish`, check for an object before inspecting fields. Empty requests should not fail during property access.
  if (b === null || typeof b !== "object") throw new Error("the request body must be a JSON object");
  if (!Array.isArray(b.tasks) || b.tasks.length === 0) throw new Error("this batch contains no tasks");
  const run = (b.run ?? "").trim() || new Date().toISOString().replace(/[:.]/g, "-");
  if (all(db, `select 1 from task where run = ? limit 1`, [run]).length > 0) {
    throw new Error(`a run named ${run} already exists - pick another name rather than mixing two scorecards`);
  }

  const ids: string[] = [];
  db.exec("begin");
  try {
    for (const t of b.tasks) {
      const r = publish(db, { ...t, run }, sealed);
      ids.push(r.id);
    }
    db.exec("commit");
  } catch (e) {
    db.exec("rollback");
    // `publish` seals G in separate storage that the transaction cannot roll back. Remove this
    // batch's already-sealed definitions manually to avoid orphaned G entries blocking a retry.
    for (const id of ids) sealed.forget(id);
    throw new Error(`the batch was not sent (one bad task rejects the whole batch): ${e instanceof Error ? e.message : String(e)}`);
  }
  return { run, ids };
}

/** A run's results, **computed rather than stored**. */
export function score(db: Conn, run: string): Score {
  const rows = all(db, `select id, state, result from task where run = ? order by id`, [run]) as {
    id: string;
    state: string;
    result: string | null;
  }[];
  const by = (s: string) => rows.filter((r) => r.state === s).length;
  return {
    run,
    total: rows.length,
    passed: by("done"),
    failed: by("failed"),
    running: by("claimed"),
    open: by("open"),
    tasks: rows,
  };
}

/** Available runs. */
export function runs(db: Conn): { run: string; total: number; passed: number }[] {
  return all(
    db,
    `select run, count(*) as total, sum(case when state = 'done' then 1 else 0 end) as passed
       from task where run <> '' group by run order by run`,
  ) as { run: string; total: number; passed: number }[];
}
