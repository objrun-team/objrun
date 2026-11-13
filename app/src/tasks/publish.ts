/**
 * Publish a task.
 *
 * **This is the sole operation admitting external tasks into the system.** Enforce admission
 * here rather than relying on each caller. The old implementation emphasized source-based
 * authorization: a caller merely happening to omit a parameter is not the same as being unable
 * to provide it. A signature change or new derivation path would otherwise bypass the guard.
 *
 * One invocation creates everything required:
 *
 * 1. A `task` row containing immutable identity and mutable state.
 * 2. Its initial execution unit in `task_<mode>`.
 * 3. The corresponding `agent_<name>_ctx` row, linked consistently with that unit.
 * 4. The task description as the first `agent_<name>_msg` row.
 *
 * **Create all of it or leave no rows.** Partial creation could leave a task that exists in the
 * database but never advances, without reporting any error.
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import { install, tableNameOf } from "../install/index.ts";
import { deliver } from "../msg/deliver.ts";
import { parseObjective, validate } from "../objective/spec.ts";
import type { Sealed } from "../objective/store.ts";

/** Who publishes the task. **This determines admission permissions**, which differ by source. */
export const SOURCES = ["user", "agent", "world", "eacn"] as const;
export type Source = (typeof SOURCES)[number];

/** The minimal four task states. Add blocked / cancelled / paused only when needed, rather than assuming them now. */
export const STATES = ["open", "claimed", "done", "failed"] as const;

export interface Publish {
  id: string;
  /** Execution mode: the first column of the task-cycle table. */
  mode: string;
  /** Initial cycle within the mode. If omitted, select the cycle with an empty `from` list. */
  cycle?: string;
  /** Agent assigned to the task. */
  agent: string;
  /** Instance name; derive it from the task id if omitted. */
  instance?: string;
  /** Execution location, referencing `workplace.place`. */
  place: string;
  /** Working path within that location. */
  workdir?: string;
  source: Source;
  description: string;
  /**
   * Problem domain (`physics` / `chem` / `coding` …). **Extensions dispatch on this field.**
   *
   * This differs from `mode`, which identifies the reasoning mechanism (cot / tot / tree).
   * A skill for physics tasks uses `dim=task, key=domain`; it remains applicable across machines,
   * runs, and individual tasks as long as the domain is physics.
   */
  domain?: string;
  /** Benchmark run this task belongs to; empty means no run. */
  run?: string;
  maxBranches?: number;
  /** Number of dead siblings under one parent before backing up to a higher level to try another direction. */
  maxDeadSiblings?: number;
  solveSeconds?: number;
  /**
   * **Content the publisher forbids searching for.** A match discards the entire search result.
   *
   * Match the string anywhere in returned content, not only URLs. In one observed run, the model
   * searched a dataset by name, switching from the main site to mirrors, text proxies, and archives,
   * with queries explicitly asking for "row 1 answer". Domain-only blocking would miss those routes.
   *
   * Enforce this **before the model sees the result**. Once an answer enters its context, the task
   * is already contaminated; invalidating it afterward only records the damage.
   */
  noSearch?: string[];
  /**
   * **Maximum searches per attempt.** Omitted means unlimited.
   *
   * Like G's `checks`, one round is one attempt, or one tree node. Retrying starts a new round
   * and allowance. Blocked searches do not consume it because they retrieved nothing.
   *
   * This limit is needed because **search consumes wall-clock time, not execution-unit slots**.
   * In one run, timed-out tasks spent half their hour searching without ever reaching their unit
   * budget. Increasing that budget cannot fix this; limiting search count can.
   */
  maxSearches?: number;
  /**
   * Verification function `G`, defining task success.
   *
   * **Attach it at publication as an admission requirement.** Validate and seal it immediately.
   * An invalid definition **rejects the entire task** rather than admitting a G that cannot evaluate.
   */
  objective?: unknown;
  /**
   * Whether the agent may read G's definition. **Required explicitly whenever G is supplied; no default.**
   *
   * The publisher knows whether the definition should be visible. A default would make that
   * policy decision implicitly on the publisher's behalf.
   */
  readable?: boolean;
}

function one(db: Conn, sql: string, params: unknown[] = []): Record<string, unknown> | null {
  const rows = all(db, sql, params);
  return rows.length ? rows[0] : null;
}

/**
 * Initial cycle: the one with an empty `from` list.
 *
 * **Never guess.** Multiple or missing entry cycles fail immediately. Guessing would start
 * a task at an unintended point while appearing to run successfully.
 */
function firstCycle(db: Conn, mode: string): string {
  const rows = all(db, `select cycle, "from" from cycle where mode = ?`, [mode]) as {
    cycle: string;
    from: string;
  }[];
  if (rows.length === 0) throw new Error(`no mode named ${mode} in the cycle table`);
  const heads = rows.filter((r) => {
    try {
      return (JSON.parse(r.from) as unknown[]).length === 0;
    } catch {
      throw new Error(`the from of ${mode}/${r.cycle} is not a readable list`);
    }
  });
  if (heads.length === 0) throw new Error(`${mode} has no entry point (every cycle has a non-empty from)`);
  if (heads.length > 1) {
    throw new Error(`${mode} has ${heads.length} entry points (${heads.map((h) => h.cycle).join(", ")}), so the task must name a cycle`);
  }
  return heads[0].cycle;
}

/**
 * Publish one task.
 *
 * Every failed check **rejects the entire task**. Do not admit a task that is known to be unrunnable.
 */
export function publish(
  db: Conn,
  p: Publish,
  sealed?: Sealed,
): { id: string; mode: string; cycle: string; instance: string; objective: boolean } {
  // Check for an object before checking missing fields. **This is the first HTTP admission check**.
  // Otherwise an empty request fails on `p.id` with an internal JavaScript error such as
  // `undefined is not an object`, neither explaining valid input nor distinguishing it from a server bug.
  if (p === null || typeof p !== "object") throw new Error("the request body must be a JSON object");
  if (!p.id || !p.id.trim()) throw new Error("the task id cannot be empty");
  if (!SOURCES.includes(p.source)) throw new Error(`unrecognised source: ${p.source} (must be one of ${SOURCES.join(" / ")})`);
  if (!p.description || !p.description.trim()) throw new Error("a task needs a description");
  if (one(db, `select id from task where id = ?`, [p.id])) throw new Error(`a task named ${p.id} already exists`);

  // ── Objective admission guard ──
  //
  // Tasks derived by agents inside the tree **must not carry G**. Allowing this lets an agent
  // set success criteria for itself or its descendants, effectively **escalating its own authority**.
  //
  // Check the source at the **sole entry point**, rather than trusting every derivation path.
  // The old approach relied on a caller happening not to supply the parameter and broke when
  // that caller's signature changed.
  if (p.objective !== undefined && p.objective !== null) {
    if (p.source === "agent") {
      throw new Error(`task ${p.id} has source agent (derived inside the tree by the agent) and may not carry a grading function - only a person can bind one, at publish time`);
    }
    if (typeof p.readable !== "boolean") {
      throw new Error(`task ${p.id} carries a grading function, so readable (whether the agent may read its definition) must be given explicitly - this bit has no default`);
    }
    if (!sealed) throw new Error("there is no sealed store, so a grading function cannot be kept");
  } else if (p.readable !== undefined) {
    throw new Error(`task ${p.id} carries no grading function, so it must not set readable`);
  }

  const agent = one(db, `select name from agent where name = ?`, [p.agent]);
  if (!agent) throw new Error(`no row in agent for ${p.agent}`);
  const place = one(db, `select place from workplace where place = ?`, [p.place]);
  if (!place) throw new Error(`no row in workplace for ${p.place}`);

  const cycle = p.cycle ?? firstCycle(db, p.mode);
  if (!one(db, `select cycle from cycle where mode = ? and cycle = ?`, [p.mode, cycle])) {
    throw new Error(`no row in the cycle table for ${p.mode}/${cycle}`);
  }

  const sub = tableNameOf("task_{}", p.mode);
  const ctx = tableNameOf("agent_{}_ctx", p.agent);
  const msg = tableNameOf("agent_{}_msg", p.agent);
  const missing = [sub, ctx, msg].filter(
    (t) => all(db, `select name from sqlite_master where type='table' and name = ?`, [t]).length === 0,
  );
  if (missing.length) {
    // Subtables derive from cycle / agent rows. Modes or agents newly declared over HTTP may
    // not have subtables yet. **Derive them now**; installation is idempotent. Otherwise configuring
    // and publishing entirely over HTTP would require an intervening restart.
    install(db);
    const still = missing.filter(
      (t) => all(db, `select name from sqlite_master where type='table' and name = ?`, [t]).length === 0,
    );
    if (still.length) throw new Error(`sub-tables could not be grown: ${still.join(", ")}`);
  }

  // Validate definitions **before creating any rows**. Rollback could remove partial writes,
  // but a task known to be unevaluable should be rejected before modifying the database.
  const g = p.objective === undefined || p.objective === null ? null : parseObjective(p.objective);
  if (g) {
    const errs = validate(g);
    if (errs.length) {
      throw new Error(`the grading function of task ${p.id} failed definition-time checks and was rejected:\n  - ${errs.join("\n  - ")}`);
    }
  }

  const instance = p.instance ?? `${p.id}#1`;
  const now = Date.now();
  // A readable=true G need not be hidden: acceptance criteria are part of the requirements.
  // Append its definition directly to the description, eliminating a separate "read G" operation.
  // Benchmark samples are the case requiring sealed criteria.
  const description =
    g && p.readable ? `${p.description}

## Acceptance criteria
${JSON.stringify(p.objective, null, 2)}` : p.description;

  // Create all rows or none.
  //
  // Use a savepoint, not begin: **batch publication already has an outer transaction**.
  // A second begin raises "cannot start a transaction within a transaction". Savepoints nest
  // and roll back with the outer transaction.
  db.exec("savepoint publish_one");
  try {
    run(
      db,
      `insert into task (id, mode, place, run, source, domain, description, created_at, workdir, objective, readable,
                         claimed_by, result, max_branches, max_dead_siblings, solve_seconds,
                         max_searches, no_search, state)
       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null, null, ?, ?, ?, ?, ?, 'open')`,
      [
        p.id, p.mode, p.place, p.run ?? "", p.source, p.domain ?? "", description, now, p.workdir ?? "",
        g ? "sealed" : null, g ? (p.readable ? 1 : 0) : null,
        p.maxBranches ?? 2, p.maxDeadSiblings ?? 3, p.solveSeconds ?? 1800,
        // Omitted means unlimited. **Treat zero and negative values as omitted too**. To prohibit
        // search, use `noSearch` or do not expose the tool; a quota field does not express disabling.
        Number.isFinite(Number(p.maxSearches)) && Number(p.maxSearches) > 0 ? Number(p.maxSearches) : null,
        // **Store the publisher's search restrictions unchanged.** Omission means unrestricted.
        // An empty list and a missing field are equivalent; callers need not choose between them.
        p.noSearch && p.noSearch.length ? JSON.stringify(p.noSearch) : null,
      ],
    );
    run(
      db,
      `insert into "${sub}" (task, cycle, unit, node, from_cycle, from_unit, agent, instance, place, at, done)
       values (?, ?, 1, 1, null, null, ?, ?, ?, ?, 0)`,
      [p.id, cycle, p.agent, instance, p.place, now],
    );
    run(db, `insert into "${ctx}" (instance, task, unit, place, done) values (?, ?, 1, ?, 0)`, [
      instance,
      p.id,
      p.place,
    ]);
    // The task description is the first context message. **The kernel does not interpret it**.
    // Use the sole delivery pipeline: `by` identifies who supplied it; kind, role, and the human
    // marker are inferred. Descriptions with `source=user` receive the human marker; other sources do not.
    deliver(db, {
      agent: p.agent,
      instance,
      unit: 1,
      by: p.source === "user" ? "user" : "world",
      body: description,
    });
    // Seal G **only after all rows are created successfully**, so row-creation failures cannot leave orphaned definitions.
    if (g) sealed!.seal(p.id, g);
    db.exec("release publish_one");
  } catch (e) {
    db.exec("rollback to publish_one");
    db.exec("release publish_one");
    throw e;
  }

  return { id: p.id, mode: p.mode, cycle, instance, objective: g !== null };
}
