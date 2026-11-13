/**
 * Check whether rows in a live database **agree with one another**.
 *
 * `check.ts` validates trigger expressions; this module checks **consistency between stored data**.
 * Both make silent failures visible.
 *
 * ## Lessons from the previous implementation
 *
 * Three warnings from its degradation module apply more generally:
 *
 * > A `task_prefix` swallowed by the base class's `**kw` leaves **nobody accepting these tasks,
 * > without an error**.
 *
 * Tasks then remain `open` indefinitely with no obvious cause. Explicitly check whether any
 * agent can accept each task.
 *
 * > Create nodes through the signaling path; direct insertion creates a **signal-free bypass**.
 *
 * Our kernel emits lifecycle moments whenever it advances a row, so directly inserted execution
 * units still trigger hooks when selected. But **inserting `task` directly instead of publishing**
 * bypasses source, G, and readable admission checks. Detect that inconsistency here.
 *
 * > Write `result` only on terminal nodes.
 *
 * Here this means result has content iff state is `done` or `failed`. Writing it mid-task makes
 * it impossible to determine afterward which execution step produced that answer.
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import { tableNameOf } from "../install/index.ts";
import type { Registry } from "../engine/registry.ts";
import { MODE_NAMES, SERVES } from "../llm/index.ts";

export interface Bad {
  what: string;
  why: string;
}

function tables(db: Conn): Set<string> {
  return new Set(
    (all(db, `select name from sqlite_master where type='table'`) as { name: string }[]).map((r) => r.name),
  );
}

/**
 * Check the complete database. Return all problems; an empty list means success.
 *
 * When `reg` is supplied, also check **both handle-registration layers**: database `fn:` rows
 * must have process registrations. Omit that check without `reg`, so diagnostics can run
 * without starting the kernel.
 */
export function checkData(db: Conn, reg?: Registry): Bad[] {
  const out: Bad[] = [];
  const has = tables(db);
  const say = (what: string, why: string) => out.push({ what, why });

  // ── Tasks ──
  for (const t of all(db, `select id, mode, place, state, result from task`) as {
    id: string; mode: string; place: string; state: string; result: string | null;
  }[]) {
    if (all(db, `select 1 from cycle where mode = ?`, [t.mode]).length === 0) {
      say(`task ${t.id}`, `its mode ${t.mode} is not in the cycle table - nobody can pick this task up, and nothing reports it`);
    }
    if (all(db, `select 1 from workplace where place = ?`, [t.place]).length === 0) {
      say(`task ${t.id}`, `its place ${t.place} is not registered`);
    }
    // Write result only at termination; otherwise the execution step that produced the answer becomes ambiguous.
    const done = t.state === "done" || t.state === "failed";
    if (t.result !== null && !done) say(`task ${t.id}`, `state=${t.state} but result is already set - result should only be written at the terminal moment`);
    if (t.result === null && t.state === "failed") say(`task ${t.id}`, `marked failed but has no result - a failure must say why`);

    const sub = tableNameOf("task_{}", t.mode);
    if (!has.has(sub)) {
      say(`task ${t.id}`, `the sub-table ${sub} has not been grown yet - run POST /install once`);
      continue;
    }

    // ── Execution units ──
    const units = all(
      db,
      `select cycle, unit, from_cycle, from_unit, agent, instance, status, done from "${sub}" where task = ?`,
      [t.id],
    ) as {
      cycle: string; unit: number; from_cycle: string | null; from_unit: number | null;
      agent: string; instance: string; status: string | null; done: number;
    }[];
    if (units.length === 0) say(`task ${t.id}`, `no execution units at all - most likely a task row inserted directly, bypassing the publish route`);

    const perCycle = new Map<string, number>();
    for (const u of units) {
      const cyc = all(db, `select max_units from cycle where mode = ? and cycle = ?`, [t.mode, u.cycle])[0] as
        | { max_units: number } | undefined;
      if (!cyc) {
        say(`${sub} ${t.id} ${u.cycle}#${u.unit}`, `cycle ${u.cycle} does not belong to ${t.mode}`);
        continue;
      }
      perCycle.set(u.cycle, (perCycle.get(u.cycle) ?? 0) + 1);

      // The referenced parent row must exist.
      if (u.from_cycle !== null && u.from_unit !== null) {
        if (!units.some((x) => x.cycle === u.from_cycle && x.unit === u.from_unit)) {
          say(`${sub} ${t.id} ${u.cycle}#${u.unit}`, `says it came from ${u.from_cycle}#${u.from_unit}, but that row is missing`);
        }
      }

      // The two sides must agree: the task records its executing agent, and the agent records its task.
      const ctx = tableNameOf("agent_{}_ctx", u.agent);
      if (!has.has(ctx)) {
        say(`${sub} ${t.id} ${u.cycle}#${u.unit}`, `the context table for agent ${u.agent} has not been grown yet`);
        continue;
      }
      const mate = all(db, `select task, done from "${ctx}" where instance = ? and unit = ?`, [u.instance, u.unit])[0] as
        | { task: string; done: number } | undefined;
      if (!mate) {
        say(`${sub} ${t.id} ${u.cycle}#${u.unit}`, `${ctx} has no matching row - the two-sided record does not line up`);
      } else {
        if (mate.task !== t.id) say(`${sub} ${t.id} ${u.cycle}#${u.unit}`, `the other side says it is working on ${mate.task}, not ${t.id}`);
        if (Number(mate.done) !== Number(u.done)) {
          say(`${sub} ${t.id} ${u.cycle}#${u.unit}`, `done disagrees across the two sides: ${u.done} here, ${mate.done} in ${ctx}`);
        }
      }
    }
    for (const [cycle, n] of perCycle) {
      const cap = all(db, `select max_units from cycle where mode = ? and cycle = ?`, [t.mode, cycle])[0] as
        | { max_units: number } | undefined;
      if (cap && n > Number(cap.max_units)) {
        say(`task ${t.id}`, `${cycle} opened ${n} units, over max_units=${cap.max_units}`);
      }
    }
  }

  // ── Can the agent accept the task? ──
  for (const a of all(db, `select name, unit, apis from agent`) as { name: string; unit: string; apis: string }[]) {
    let apis: [string, string][] = [];
    try {
      apis = JSON.parse(a.apis || "[]") as [string, string][];
    } catch {
      say(`agent ${a.name}`, `apis is not a readable list: ${a.apis}`);
    }
    for (const [keyEnv, model] of apis) {
      if (all(db, `select 1 from api where key_env = ? and model = ?`, [keyEnv, model]).length === 0) {
        say(`agent ${a.name}`, `${keyEnv}/${model} in apis is not registered in the api table`);
      }
    }
  }

  // ── Do the API lanes match? ──
  //
  // Three lane problems can silently leave tasks without an executor:
  //
  // 1. A typo in `api.modes`, such as `duplx`, makes the lane unselectable.
  // 2. An unsupported `cycle.api_mode` blocks every unit in that cycle.
  // 3. A row lists `duplex` but references a chat handle: it is **selected, then invokes the wrong
  //    adapter**. This is the worst case because it may run without errors but behave incorrectly.
  //
  // Compare against **what implementations support**, not the contents of the descriptive `mode`
  // table. Otherwise manually inserting `duplx` would make an unsupported value appear valid.
  const modeOK = MODE_NAMES;
  const served = new Map<string, Set<string>>(); // Mode → handles that support it.
  for (const a of all(db, `select key_env, model, handle, modes from api`) as {
    key_env: string; model: string; handle: string; modes: string;
  }[]) {
    const at = `api ${a.key_env}/${a.model}`;
    const modes = String(a.modes ?? "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    if (modes.length === 0) say(at, `modes is empty - nothing will ever select this row`);
    const can = SERVES.get(a.handle);
    for (const m of modes) {
      if (!modeOK.has(m)) {
        say(at, `${m} in modes is not a known api mode (known: ${[...modeOK].join(", ")}) - this lane will never be selected`);
        continue;
      }
      // Supported modes of externally registered handles are unknown here; skip their compatibility check.
      if (can && !can.has(m)) {
        say(at, `modes claims ${m}, but handle=${a.handle} cannot serve it (it serves only ${[...can].join(", ")})`);
      }
      if (!served.has(m)) served.set(m, new Set());
      served.get(m)!.add(a.handle);
    }
  }
  for (const c of all(db, `select mode, cycle, api_mode from cycle where api_mode is not null and trim(api_mode) <> ''`) as {
    mode: string; cycle: string; api_mode: string;
  }[]) {
    const want = String(c.api_mode).trim();
    if (!modeOK.has(want)) {
      say(`cycle ${c.mode}/${c.cycle}`, `api_mode=${want} is not a known api mode (known: ${[...modeOK].join(", ")})`);
    } else if (!served.has(want)) {
      say(`cycle ${c.mode}/${c.cycle}`, `needs a ${want} lane, but no row in the api table serves one - every unit of this cycle is stuck`);
    }
  }

  // ── Two-layer handle validation ──
  //
  // Find `fn:` handles registered in the database but not the process. Without this check,
  // failure appears only when a task reaches that invocation, already halfway through execution.
  if (reg) {
    for (const h of all(db, `select name from handle`) as { name: string }[]) {
      if (h.name.startsWith("fn:") && !reg.has(h.name)) {
        say(`handle ${h.name}`, `registered in the database but never registered in this process`);
      }
    }
  }
  // Also check the reverse: references to handles never registered in the database.
  const known = new Set((all(db, `select name from handle`) as { name: string }[]).map((r) => r.name));
  const refs: [string, string][] = [
    ...(all(db, `select 'api.handle' as at, handle as h from api`) as { at: string; h: string }[]).map(
      (r) => [r.at, r.h] as [string, string],
    ),
    ...(all(db, `select 'agent.unit' as at, unit as h from agent`) as { at: string; h: string }[]).map(
      (r) => [r.at, r.h] as [string, string],
    ),
    ...(all(db, `select 'cycle.infer' as at, infer as h from cycle`) as { at: string; h: string }[]).map(
      (r) => [r.at, r.h] as [string, string],
    ),
  ];
  for (const [at, h] of refs) {
    if (h && !known.has(h)) say(at, `references ${h}, which is not registered in the handle table`);
  }

  return out;
}
