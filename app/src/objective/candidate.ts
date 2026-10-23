import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import { tableNameOf } from "../install/index.ts";
import { SUBMIT } from "../tree/dfs.ts";

/** A single final-candidate policy shared by live and offline grading. */
export function finalCandidate(db: Conn, task: string): { body: string; how: string } | undefined {
  const row = all(db, "select mode,created_at,solve_seconds from task where id = ?", [task])[0];
  if (!row?.mode) return undefined;
  const limit = Number(row.solve_seconds);
  const deadline = Number.isFinite(limit) && limit > 0 ? Number(row.created_at) + limit * 1000 : Number.MAX_SAFE_INTEGER;
  const sub = tableNameOf("task_{}", String(row.mode));
  const units = all(db, `select agent,instance,unit from "${sub}" where task = ? order by unit desc`, [task]);
  for (const unit of units) {
    const messages = tableNameOf("agent_{}_msg", String(unit.agent));
    const calls = all(db, `select body from "${messages}" where instance = ? and unit = ? and kind = 'call' and at <= ? order by seq desc`, [unit.instance, unit.unit, deadline]);
    for (const call of calls) {
      try {
        const payload = JSON.parse(String(call.body)) as { calls?: { name?: string; input?: { answer?: unknown } }[] };
        for (const item of [...(payload.calls ?? [])].reverse()) {
          if (item.name === SUBMIT) return { body: typeof item.input?.answer === "string" ? item.input.answer : "", how: "submitted" };
        }
      } catch { /* malformed stored messages do not supply a candidate */ }
    }
  }
  // A mode with a hand-in station cannot turn an unsubmitted thought or verify argument into delivery.
  if (all(db, "select 1 from cycle where mode = ? and cycle = ? limit 1", [row.mode, SUBMIT]).length) return undefined;
  for (const unit of units) {
    const messages = tableNameOf("agent_{}_msg", String(unit.agent));
    const prompts = all(db, `select body from "${messages}" where instance = ? and unit = ? and kind = 'prompt' and at <= ? order by seq desc`, [unit.instance, unit.unit, deadline]);
    const said = prompts.find(message => String(message.body ?? "").trim());
    if (said) return { body: String(said.body), how: "last words" };
  }
  return undefined;
}
