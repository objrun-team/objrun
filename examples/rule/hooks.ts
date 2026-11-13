/**
 * Two rules in one file. **Attaching a rule to a moment makes it a hook.**
 *
 * | Export | Moment | Action |
 * | --- | --- | --- |
 * | `audit` | `pre_send` | Record which rail this execution unit will send to |
 * | `archive` | `task_done` | Append a line to `done.log` when the task finishes |
 *
 * Both handles reference the same file, so they share a Worker and module state. `archive` can read the count maintained by `audit`, providing the audit count in the archived line.
 */

import { appendFile } from "node:fs/promises";
import { join } from "node:path";

const LOG = process.env.TGENGIN_RULE_LOG ?? join(process.cwd(), "examples", "rule", "done.log");

/** Audit count for this run. Stored in this Worker’s memory, not in the database. */
let audited = 0;

interface At {
  moment?: string;
  place?: string;
  task?: { id?: string; source?: string; description?: string; result?: string | null };
  cycle?: { cycle?: string; api_mode?: string | null };
  chain?: string;
  unit?: number;
}

export async function audit(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  audited++;
  console.log(
    `[hooks] ${a.moment} | ${a.task?.id} station ${a.unit} | lane=${a.cycle?.api_mode ?? "(no model)"} | chain=${a.chain}`,
  );
  return { audited };
}

export async function archive(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  const line = JSON.stringify({
    at: new Date().toISOString(),
    task: a.task?.id,
    source: a.task?.source,
    audited,
    result: (a.task?.result ?? "").slice(0, 60),
  });
  await appendFile(LOG, line + "\n", "utf8");
  console.log(`[hooks] ${a.moment} | archiving ${a.task?.id} -> ${LOG}`);
  return { archived: a.task?.id };
}
