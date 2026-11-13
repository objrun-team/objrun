/**
 * The kernel.
 *
 * **One loop, with every decision grounded in tables.** This file must contain no specific mode, cycle, agent, tool, or rule names. Any such name means something belongs in a table but has not been placed there.
 *
 * The kernel supplies only these mechanisms; everything else comes from table lookups:
 *
 * 1. The loop itself: read → assemble → store → call → store → infer → write.
 * 2. The handle registry (`registry.ts`): resolve names to implementations.
 * 3. Death detection: `now - at > expect_ms`.
 * 4. Persistence order: **store before sending, never the reverse**.
 * 5. Derive the main table's `state` from subtables.
 *
 * ## A row's current phase is **computed** from the database, not held in memory
 *
 * | Outbound record stored? | Return stored? | Phase |
 * | --- | --- | --- |
 * | No | — | Not started: advance it this cycle |
 * | Yes | No | Running: leave it alone unless it times out |
 * | Yes | Yes | Finished: infer the next step |
 *
 * The kernel therefore needs **no in-memory list of running work**. After a crash and restart, the same database yields the same one of these three phases. This is what makes snapshots possible.
 */

import type { Conn, Store } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import { tableNameOf } from "../install/index.ts";
import { bodiesAt, pressNode, readyLevels, swapClosed, type Level, type Line } from "../msg/press.ts";
import { SUBMIT } from "../tree/dfs.ts";
import { chainOf, type Unit } from "./chain.ts";
import type { Registry } from "./registry.ts";
import { answerMissing, mendPairs, type Pair, checkBody, deliver, type Said, sentAsIn } from "../msg/deliver.ts";
import { fire, type Facts } from "./trigger.ts";

type Row = Record<string, unknown>;

export interface Log {
  info(msg: string): void;
  warn(msg: string): void;
  error(msg: string): void;
}

interface Pending extends Unit {
  mode: string;
  sub: string;
  agent: string;
  instance: string;
  place: string;
  at: number;
}

function one(db: Conn, sql: string, params: unknown[] = []): Row | null {
  const rows = all(db, sql, params);
  return rows.length ? rows[0] : null;
}

/** Hooks exposed by the kernel. **The kernel does not know what they do**; it only announces the relevant moment. */
/** Possible successor stations. **Facts from the transition table**, not a judgment. */
function nextOf(db: Conn, mode: string, cycle: string): string[] {
  const r = all(db, `select next from cycle where mode = ? and cycle = ?`, [mode, cycle])[0] as
    | { next?: string }
    | undefined;
  try {
    const v = JSON.parse(String(r?.next ?? "[]")) as unknown;
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

export interface Hooks {
  /** All execution units of a task have finished. Others decide success; the kernel reports only execution completion. */
  /** The problem has stopped. A populated `expired` means the time limit forced it to stop rather than natural completion. */
  onDone?(task: string, expired?: string): void | Promise<void>;
}

export class Kernel {
  #store: Store;
  #log: Log;
  #reg: Registry;
  #hooks: Hooks;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #ticking = false;
  /** Bad rows already reported, to avoid repeatedly logging the same one. */
  #cried = new Set<string>();
  #again = false;
  #stopped = true;
  /** Only deduplicate live finalization calls; the pending work itself remains in task.result. */
  #finalizing = new Set<string>();

  constructor(store: Store, log: Log, reg: Registry, hooks: Hooks = {}) {
    this.#store = store;
    this.#log = log;
    this.#reg = reg;
    this.#hooks = hooks;
  }

  /**
   * Wake the loop.
   *
   * **The signal carries no data.** Including the row to process would turn it into an in-memory queue: losing one signal would permanently lose work without any database evidence. Signals may be lost; database records may not. A lost signal at worst delays work until the timer, rather than losing the work itself.
   */
  wake(): void {
    if (this.#stopped) return;
    if (this.#ticking) {
      this.#again = true;
      return;
    }
    void this.#tick();
  }

  start(): void {
    this.#stopped = false;
    this.wake();
  }

  stop(): void {
    this.#stopped = true;
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = null;
  }

  async #tick(): Promise<void> {
    this.#ticking = true;
    try {
      this.#reg.sync(this.#store.rw);
      this.#resumeFinalization();
      const rows = this.#scan();
      this.#reap(rows);
      for (const p of this.#ready(rows)) void this.#advance(p);
      this.#arm(rows);
    } catch (e) {
      this.#log.error(`kernel tick did not finish: ${msg(e)}`);
    } finally {
      this.#ticking = false;
      if (this.#again) {
        this.#again = false;
        this.wake();
      }
    }
  }

  /** Subtables to inspect: one per mode in the task cycle table. Do not guess table names. */
  #subs(): { mode: string; sub: string }[] {
    const modes = all(this.#store.ro, `select distinct mode from cycle`) as { mode: string }[];
    return modes.map((m) => ({ mode: m.mode, sub: tableNameOf("task_{}", m.mode) }));
  }

  /** Recompute from the database each time; retain no list. */
  #scan(): Pending[] {
    const out: Pending[] = [];
    for (const { mode, sub } of this.#subs()) {
      // **Do not select rows of already graded problems.**
      //
      // The death-handling comment says to record failure first so the task is not scheduled again. Previously this query checked only whether a row was finished, never whether its task remained active. After timeout finalization, unfinished rows were still selected and dispatched to models. One measured run opened 105 additional execution units across 15 dead problems; the worst continued for 33 minutes. They cost real money but could not affect the score fixed at death.
      //
      // This also prevents a series of errors: a call in flight at death can return an unanswered tool request after finalization has already completed missing results. Further dispatch would then send invalid context (`An assistant message with 'tool_calls' must be followed by...`). Without further dispatch, that path disappears.
      //
      // Use `not in`, not an inner join with `task`, to preserve prior behavior for orphan rows without a main-table entry. An inner join would silently discard them, exactly the kind of silence to avoid here.
      const rows = all(
        this.#store.ro,
        `select task, cycle, unit, from_cycle, from_unit, agent, instance, place, at
           from "${sub}"
          where done = 0
            and task not in (select id from task where state in ('done', 'failed'))`,
      ) as unknown as Pending[];
      for (const r of rows) out.push({ ...r, mode, sub });
    }
    return out;
  }

  /**
   * Choose the handle for this row.
   *
   * **The cycle table's `api_mode` chooses this station's track**:
   *
   * - Nonempty: select an `agent.apis` entry whose `modes` includes it, and call that row's `api.handle`.
   * - Empty: call `agent.unit` (no model at this station, for example executing tools requested in the previous step).
   *
   * **Select here; adapters only call.** If an adapter selects again, track selection has two authorities that will eventually drift.
   */
  #handleOf(p: Pending): { handle: string; api: { key_env: string; model: string; base_url: string; retry_on: string; compress_at: number | null } | null } {
    const agent = one(this.#store.ro, `select unit, apis from agent where name = ?`, [p.agent]);
    if (!agent) throw new Error(`no row in agent for ${p.agent}`);

    const cyc = one(this.#store.ro, `select api_mode from cycle where mode = ? and cycle = ?`, [p.mode, p.cycle]);
    const want = String(cyc?.api_mode ?? "").trim();
    if (!want) return { handle: String(agent.unit), api: null };

    let apis: [string, string][];
    try {
      apis = JSON.parse(String(agent.apis ?? "[]")) as [string, string][];
    } catch {
      throw new Error(`agent ${p.agent} has apis that is not a readable list`);
    }
    for (const [keyEnv, model] of apis) {
      const row = one(this.#store.ro, `select key_env, model, handle, modes, base_url, retry_on, compress_at from api where key_env = ? and model = ?`, [
        keyEnv,
        model,
      ]);
      if (!row) continue;
      const modes = String(row.modes ?? "")
        .split(",")
        .map((x) => x.trim());
      if (modes.includes(want)) {
        return {
          handle: String(row.handle),
          api: {
            key_env: keyEnv,
            model,
            base_url: String(row.base_url),
            retry_on: String(row.retry_on),
            // Empty = never compress. **This api row owns the threshold**; another credential or model may have a different value.
            compress_at: row.compress_at === null || row.compress_at === undefined ? null : Number(row.compress_at),
          },
        };
      }
    }
    throw new Error(`${p.mode}/${p.cycle} needs a ${want} lane, but none of agent ${p.agent} apis supports it`);
  }

  /** A row's time limit comes from the handle actually called at this station. */
  #expectOf(p: Pending): number {
    return this.#reg.get(this.#handleOf(p).handle).expectMs;
  }

  /**
   * Report rows whose time limits cannot be resolved (misconfigured tracks, unregistered handles), without stopping the whole cycle.
   *
   * **One bad row should affect only itself.** Propagating its exception would stall other tasks in the same cycle while logging only one error, making healthy but motionless tasks especially hard to diagnose.
   */
  #expectSafe(p: Pending): number | null {
    try {
      return this.#expectOf(p);
    } catch (e) {
      // Report the same bad row only once. Logging it every cycle would let one misconfigured task flood the log,
      // hiding the real failure among noise.
      const key = `${p.sub}\u0000${p.task}\u0000${p.cycle}\u0000${p.unit}`;
      if (!this.#cried.has(key)) {
        this.#cried.add(key);
        this.#log.error(`${p.sub} ${p.task} ${p.cycle}#${p.unit} cannot run: ${msg(e)}`);
      }
      return null;
    }
  }

  /**
   * Report timeouts. **Add no new column**: death is computed, not stored separately.
   *
   * Two limits govern different things:
   *
   * - **Unit level**: `now - at > expect_ms`; this step is stuck.
   * - **Task level**: `now - created_at > solve_seconds`; the whole problem is out of time and its tree must stop. Without this limit, a tree continually opening siblings could grow forever.
   */
  #reap(rows: Pending[]): void {
    const now = Date.now();
    for (const t of all(
      this.#store.ro,
      `select id, created_at, solve_seconds, state from task where state not in ('done','failed')`,
    ) as { id: string; created_at: number; solve_seconds: number; state: string }[]) {
      if (now - Number(t.created_at) <= Number(t.solve_seconds) * 1000) continue;
      const key = `task expired\u0000${t.id}`;
      if (this.#cried.has(key)) continue;
      // **One faulty problem must not stop the whole scan.** Other tasks and execution units still need checking.
      // Throwing here would skip every later item and repeat from the start next cycle, letting one bad problem disable all death detection.
      this.#log.warn(`task ${t.id} expired: ran ${Math.round((now - Number(t.created_at)) / 1000)}s, limit ${t.solve_seconds}s`);
      const closing = JSON.stringify({ pass: 0, valid: false, outcome: "task_timeout", why: `over solve_seconds=${t.solve_seconds}s` });
      try {
        // Record failure first to prevent rescheduling; if G exists, the callback below replaces it with the verdict.
        run(this.#store.rw, `update task set state = 'failed', result = ? where id = ?`, [
          closing,
          t.id,
        ]);
        // **Query G even on timeout.** Previously this path simply wrote failed, making a correct answer submitted before the deadline
        // but not yet finalized indistinguishable in the report from a problem with no solution.
        this.#finalize(t.id, `over solve_seconds=${t.solve_seconds}s`, closing);
        this.#cried.add(key);
      } catch (e) {
        this.#cried.delete(key);
        this.#log.error(`task ${t.id} expired but could not be closed: ${msg(e)}`);
      }
    }
    for (const r of rows) {
      const cap = this.#expectSafe(r);
      if (cap === null || now - r.at <= cap) continue;

      // **Marking a row dead must actually close it, not merely log a warning.**
      //
      // Logging alone leaves it pending forever: the timer sees an expired deadline, wakes after 50ms, logs again, and schedules another 50ms wake-up. One stuck row can trap the kernel in a busy loop. A measured run produced 12732 identical warnings while the problem never finalized.
      //
      // Close it like normal completion (the final two lines of `#infer`): set a terminal state and both done flags, then **open another node**. A call failing to return is not proof the problem is unsolvable; retry it as after a submission verdict of 0.
      this.#log.warn(
        `declared dead: ${r.sub} ${r.task} ${r.cycle}#${r.unit} (${r.agent}/${r.instance}) has been ${now - r.at}ms, over ${cap}ms`,
      );
      run(
        this.#store.rw,
        `update "${r.sub}" set done = 1, status = 'dead_failed' where task = ? and cycle = ? and unit = ?`,
        [r.task, r.cycle, r.unit],
      );
      run(this.#store.rw, `update "${tableNameOf("agent_{}_ctx", r.agent)}" set done = 1 where instance = ? and unit = ?`, [
        r.instance,
        r.unit,
      ]);
      // Also leave a context message. Logs alone make the row appear to vanish inexplicably through the API.
      try {
        deliver(this.#store.rw, {
          agent: r.agent,
          instance: r.instance,
          unit: r.unit,
          by: "kernel",
          body: JSON.stringify({ stuck: `over expect_ms (${cap}ms), the kernel closed this station` }),
        });
      } catch {
        // If even this row cannot be stored (usually because its subtable does not exist), only the log remains.
      }
      this.#reopen(r);
      this.#restate(r.task, r.sub);
    }
  }

  /**
   * A station missed its response deadline: **mark this node dead and open another**.
   *
   * Previously the row was marked dead, the chain ended, and the task finished. But a call failing to return differs from an unsolvable problem: retry it as after a submission verdict of 0. Measurements showed one transient fault could leave a problem with nothing and no second chance.
   *
   * Attach a fresh slot after the dead row at the **entry station** (empty `from`). A new attempt begins with reasoning, not tool execution. The node number increments automatically: a parent with a terminal state starts a new node, and we just assigned `dead_failed`.
   *
   * **`max_dead_siblings` limits retries**, sharing the submission-failure gate. Otherwise an unstable machine could restart a problem indefinitely and spend its entire time allowance restarting.
   */
  #reopen(r: Pending): void {
    const entry = all(this.#store.ro, `select cycle from cycle where mode = ? and "from" = '[]'`, [r.mode]) as {
      cycle: string;
    }[];
    const to = entry[0]?.cycle;
    if (!to) return; // This mechanism has no entry-station concept, so it cannot restart.

    const task = one(this.#store.ro, `select max_dead_siblings from task where id = ?`, [r.task]) as
      | { max_dead_siblings?: number }
      | undefined;
    const cap = Number(task?.max_dead_siblings ?? 3);
    const dead = all(
      this.#store.ro,
      `select distinct node from "${r.sub}" where task = ? and status is not null and status like 'dead%'`,
      [r.task],
    ).length;
    if (dead >= cap) {
      this.#log.warn(`${r.task}: ${String(dead)} attempts have died, at the limit of ${String(cap)} - not reopening`);
      return;
    }

    const node =
      Number(one(this.#store.ro, `select coalesce(max(node), 0) as m from "${r.sub}" where task = ?`, [r.task])!.m) + 1;
    const unit =
      Number(one(this.#store.ro, `select coalesce(max(unit), 0) as m from "${r.sub}" where task = ?`, [r.task])!.m) + 1;
    run(
      this.#store.rw,
      `insert into "${r.sub}" (task, cycle, unit, node, from_cycle, from_unit, agent, instance, place, at, done)
       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`,
      [r.task, to, unit, node, r.cycle, r.unit, r.agent, r.instance, r.place, Date.now()],
    );
    run(this.#store.rw, `insert into "${tableNameOf("agent_{}_ctx", r.agent)}" (instance, task, unit, place, done) values (?, ?, ?, ?, 0)`, [
      r.instance,
      r.task,
      unit,
      r.place,
    ]);
    this.#log.warn(`${r.task}: ${r.cycle}#${r.unit} never answered - opening attempt ${String(node)} at ${to}#${String(unit)}`);
  }

  /**
   * Select the not-started phase: **the outbound row has not been stored**.
   *
   * Use the kernel's outbound record, not absence of all messages. A unit may have preloaded questions (data anyone can insert); messages do not imply dispatch. A message-existence test would classify units with preset prompts as running and never schedule them.
   */
  #ready(rows: Pending[]): Pending[] {
    return rows.filter((r) => !this.#sentOut(r));
  }

  /**
   * Whether this unit has been dispatched.
   *
   * **`kind = 'inject'` alone is insufficient.** The value covers kernel outbound bookkeeping (`by: "kernel"` → role=system) and system-injected user-side messages (`by: "world"` → role=user). **Descriptions of nonhuman-submitted tasks use the latter**: the publishing endpoint delivers them with `by: "world"` when `source` is not `user`. Such tasks therefore start with an inject row; checking only kind would mark the station as already dispatched and leave all `agent` / `world` / `eacn` tasks silently unscheduled forever.
   *
   * Inspect `role` too: only the kernel outbound record combines `inject` and `system`.
   */
  #sentOut(r: Pending): boolean {
    const t = this.#msgTable(r.agent);
    const got = one(
      this.#store.ro,
      `select count(*) as c from "${t}" where instance = ? and unit = ? and kind = 'inject' and role = 'system'`,
      [r.instance, r.unit],
    );
    return Number(got?.c ?? 0) > 0;
  }

  #msgTable(agent: string): string {
    return tableNameOf("agent_{}_msg", agent);
  }

  #seqMax(r: Pending): number {
    const t = this.#msgTable(r.agent);
    const got = one(this.#store.ro, `select coalesce(max(seq), 0) as m from "${t}" where instance = ? and unit = ?`, [
      r.instance,
      r.unit,
    ]);
    return Number(got?.m ?? 0);
  }

  /**
   * Advance one row.
   *
   * The order is mandatory: **store injected content → send → store the return**. Reversing it allows a crash to leave a sent call absent from the database, an unrecoverable state.
   */
  async #advance(p: Pending): Promise<void> {
    if (["done", "failed"].includes(String(one(this.#store.ro, "select state from task where id = ?", [p.task])?.state))) return;
    // **Reserve the row before working.** Record dispatch **before any await**: `#ready` uses this record to select work.
    //
    // Without reservation, a race opens: one cycle selects the row and starts it with `void`; `#advance` yields at its first await before writing the marker. Any database write can call `wake()`, causing the next cycle to see an undispatched row and **dispatch it again**. Two model responses then occupy one slot. Adjacent tool-request messages without intervening results make the model reject the entire context, leaving the problem spinning until timeout. Measurements found four such cases in just over five hundred slots, each losing a problem.
    //
    // `#ticking` cannot prevent this: it blocks simultaneous loop cycles, not work still in flight from a previous cycle. Work started with `void` is outside that guard from the outset.
    const mark = deliver(this.#store.rw, {
      agent: p.agent,
      instance: p.instance,
      unit: p.unit,
      by: "kernel",
      // **Include the expected deadline.** A dispatch receipt must also state when waiting becomes failure.
      // If no reply arrives, the kernel marks the station dead and starts another node (see `#reap`).
      body: JSON.stringify({ sent: true, deadline: Date.now() + (this.#expectSafe(p) ?? 0) }),
    });

    try {
      const facts = this.#factsOf(p);
      await this.#atMoment(p, facts, "unit_start");

      // Skills to inject this round: store them first.
      for (const identity of fire(this.#store.ro, "skill", facts)) {
        const s = one(this.#store.ro, `select body, role, usable from skill where identity = ?`, [identity]);
        if (!s || !Number(s.usable)) continue;
        const body = s.body ?? (await this.#reg.get(identity).call({ facts }));
        // **Use the sole delivery pipeline**: infer kind and role there, not here.
        deliver(this.#store.rw, {
          agent: p.agent,
          instance: p.instance,
          unit: p.unit,
          by: "skill",
          who: identity,
          body: text(body),
        });
      }

      // Tools attached this round = **system tools ∪ trigger matches**.
      // Everyone receives system tools (the read/write group) unconditionally; otherwise the rule that no conditions means never triggered would make them unavailable to all agents.
      // Both sets come from queries; the kernel still knows no specific tool names.
      const tools = new Map<string, Row>();
      for (const t of all(this.#store.ro, `select * from tool where system = 1 and usable = 1`)) {
        tools.set(String(t.name), t);
      }
      for (const n of fire(this.#store.ro, "tool", facts)) {
        const t = one(this.#store.ro, `select * from tool where name = ? and usable = 1`, [n]);
        if (t) tools.set(String(t.name), t);
      }

      const kit = [...tools.values()];
      const rules = fire(this.#store.ro, "rule", facts);

      // Outbound payload: **assemble context along the chain** plus this round's resources. **Store before sending.**
      const context = this.#contextOf(p);
      // The outbound row is **the snapshot's receipt for this call**: which tools and usage conventions the model received.
      // Without it, later inspection cannot explain its choices. Complete the reservation row now: it is **the snapshot's call receipt**, recording those tools and conventions so the step can be understood afterward.
      //
      // Update the same row rather than inserting another. The delivery pipeline assigned its identity (`kind` / `role` / `seq`); only fill its content here.
      //
      // Use ASCII keys throughout: **clients can read this row** (`/tasks/:id/messages` decodes it). Chinese keys would force Chinese-literal property access and risk corruption at encoding boundaries.
      run(
        this.#store.rw,
        `update "${this.#msgTable(p.agent)}" set body = ? where instance = ? and unit = ? and seq = ?`,
        [
          JSON.stringify({
            sent: true,
            tools: kit.map((t) => t.name),
            prompts: kit.map((t) => t.prompt).filter(Boolean),
            rules,
          }),
          p.instance,
          p.unit,
          mark,
        ],
      );

      // A stored outbound row means this station is active, so the main-table state should now be `claimed`.
      // Deriving state only after step completion would leave it `open` for the entire model-call duration. Polling clients would see an unclaimed task that is actually running.
      this.#restate(p.task, p.sub);

      await this.#atMoment(p, facts, "pre_send");

      const pickd = this.#handleOf(p);
      const back = await this.#reg.get(pickd.handle).call({
        ...facts,
        place: p.place,
        instance: p.instance,
        unit: p.unit,
        // The selected track for this station. The adapter uses it directly without selecting again.
        api: pickd.api,
        context,
        // Which roles enter messages versus instructions: **the table is authoritative**, without an adapter-local copy.
        sentAs: sentAsIn(this.#store.ro),
        // The required tool for this station (`cycle.must_call`). Empty = the model chooses.
        mustCall: String(facts.cycle.must_call ?? "") || null,
        // This round's task view, **computed afresh each round** rather than stored as a message.
        // Sibling branches cannot reach a view stored as a message (see `#viewOf`).
        view: this.#viewOf(p, facts.task),
        tools: kit,
        rules,
      });

      // Store the return as another row.
      // The model's own message **bypasses the delivery pipeline**: its trajectory is stored directly,
      // and the adapter must provide kind (prompt or call), which cannot be inferred here.
      const r = (back ?? {}) as { role?: string; kind?: string; body?: unknown } & Partial<Said>;
      this.#push(p, r.role ?? "assistant", r.kind ?? "prompt", text(r.body ?? back), r);

      // A late HTTP/model response may be recorded, but cannot reopen a closed task or unit.
      const taskState = String(one(this.#store.ro, "select state from task where id = ?", [p.task])?.state);
      const unitDone = Number(one(this.#store.ro, `select done from "${p.sub}" where task = ? and unit = ?`, [p.task, p.unit])?.done) === 1;
      if (["done", "failed"].includes(taskState) || unitDone) {
        run(this.#store.rw, `update "${p.sub}" set done = 1 where task = ? and unit = ?`, [p.task, p.unit]);
        run(this.#store.rw, `update "${tableNameOf("agent_{}_ctx", p.agent)}" set done = 1 where instance = ? and unit = ?`, [p.instance, p.unit]);
        this.#answerAll(p.task, p.sub);
        this.wake();
        return;
      }

      // Tool units can receive an account fault from a nested searcher even though their own handle succeeds.
      for (const receipt of all(this.#store.ro, `select body from "${this.#msgTable(p.agent)}" where instance = ? and unit = ? and kind = 'tool'`, [p.instance, p.unit])) {
        let value: { valid?: unknown; outcome?: unknown; httpStatus?: unknown; error?: unknown } | undefined;
        try { value = (JSON.parse(String(receipt.body)) as { value?: typeof value }).value; } catch { continue; }
        const status = Number(value?.httpStatus);
        if (value?.valid === false && value.outcome === "provider_error" && [401, 402, 403].includes(status)) {
          this.#providerFault(p, status, String(value.error ?? "provider refused the nested request"));
          return;
        }
      }

      await this.#atMoment(p, facts, "post_send");
      await this.#infer(p, facts, back);
      // Wake the next cycle only after successful advancement. **Do not wake on failure**: that would create a hot loop,
      // reselecting the same runnable row, failing, and waking again.
      // Leave the failed row to the deadline timer below, which marks it dead on timeout.
      this.wake();
    } catch (e) {
      const why = msg(e);
      const serviceError = e as { statusCode?: unknown; cause?: { statusCode?: unknown }; lastError?: { statusCode?: unknown } };
      const httpStatus = Number(serviceError?.statusCode ?? serviceError?.cause?.statusCode ?? serviceError?.lastError?.statusCode);
      if ([401, 402, 403].includes(httpStatus)) {
        this.#providerFault(p, httpStatus, why);
        return;
      }
      this.#log.error(`${p.sub} ${p.task} ${p.cycle}#${p.unit} is stuck: ${why}`);
      // **Store the error too.** Logs alone make the row look inexplicably stuck through the API, the only interface clients have.
      // Server-log readers and blocked users are different people.
      //
      // Store the same message for a row only once. A blocked row may be retried every cycle; inserting every time would let one misconfigured task fill the context table.
      const key = `stuck ${p.sub} ${p.task} ${p.cycle} ${p.unit} ${why}`;
      if (!this.#cried.has(key)) {
        this.#cried.add(key);
        try {
          deliver(this.#store.rw, {
            agent: p.agent,
            instance: p.instance,
            unit: p.unit,
            by: "kernel",
            body: JSON.stringify({ stuck: why }),
          });
        } catch {
          // If even this row cannot be stored (usually because its subtable does not exist), only the log remains.
        }
      }
    }
  }

  #providerFault(p: Pending, httpStatus: number, why: string): void {
    run(this.#store.rw, `update task set state = 'failed', result = ? where id = ?`, [JSON.stringify({ pass: 0, valid: false, outcome: "provider_error", httpStatus, why }), p.task]);
    run(this.#store.rw, `update "${p.sub}" set done = 1, status = 'dead_service' where task = ? and done = 0`, [p.task]);
    run(this.#store.rw, `update "${tableNameOf("agent_{}_ctx", p.agent)}" set done = 1 where instance = ?`, [p.instance]);
    this.#answerAll(p.task, p.sub);
    this.#log.error(`${p.task} stopped after provider ${httpStatus}: ${why}`);
    this.wake();
  }

  #pendingFinalizations(): { id: string; result: string }[] {
    return all(this.#store.ro, `select id,result from task where state in ('done','failed') and json_valid(result) and json_extract(result,'$.outcome') in ('finalization_pending','finalization_error')`) as { id: string; result: string }[];
  }

  #resumeFinalization(): void {
    for (const row of this.#pendingFinalizations()) {
      if (this.#finalizing.has(row.id)) continue;
      const prior = JSON.parse(row.result) as { expired?: string; retryAt?: number };
      if (Number(prior.retryAt ?? 0) > Date.now()) continue;
      this.#finalize(row.id, prior.expired);
    }
  }

  #finalize(task: string, expired?: string, fallback: string | null = null): void {
    if (!this.#hooks.onDone || this.#finalizing.has(task)) return;
    const pending = JSON.stringify({ pass: 0, valid: false, outcome: "finalization_pending", ...(expired ? { expired, why: expired } : {}) });
    run(this.#store.rw, "update task set result = ? where id = ?", [pending, task]);
    this.#finalizing.add(task);
    const finish = () => {
      if (this.#stopped) return; // Persist the marker if shutdown interrupts finalization.
      run(this.#store.rw, "update task set result = ? where id = ? and result = ?", [fallback, task, pending]);
    };
    const fail = (e: unknown) => {
      if (this.#stopped) return;
      const failure = JSON.stringify({ pass: 0, valid: false, outcome: "finalization_error", why: msg(e), retryAt: Date.now() + 1000, ...(expired ? { expired } : {}) });
      run(this.#store.rw, "update task set state = 'failed', result = ? where id = ? and result = ?", [failure, task, pending]);
      this.#log.error(`task ${task} could not be finalized: ${msg(e)}`);
    };
    try {
      const closed = this.#hooks.onDone(task, expired);
      if (closed) {
        void closed.then(finish).catch(fail).finally(() => { this.#finalizing.delete(task); this.wake(); });
      } else {
        finish();
        this.#finalizing.delete(task);
      }
    } catch (e) {
      try { fail(e); } finally { this.#finalizing.delete(task); }
    }
  }

  /**
   * Announce a moment and run matching rules. **That is a hook.**
   *
   * The kernel knows no rule names; it reports the current moment, and `trigger` (`dim=moment`) determines attachments. The old implementation used one directory per hook moment; here a moment is a data value, not a separate table.
   *
   * **One failed rule affects only itself.** Hooks run on the main path; allowing one to stop a step would let a malformed rule stall every task.
   */
  async #atMoment(p: Pending, facts: Facts, moment: string): Promise<void> {
    const at = { ...facts, moment };
    for (const identity of fire(this.#store.ro, "rule", at)) {
      try {
        await this.#reg.get(identity).call({ ...at, sub: p.sub, unit: p.unit, instance: p.instance });
      } catch (e) {
        this.#log.error(`rule ${identity} threw at moment ${moment}: ${msg(e)}`);
      }
    }
  }

  /**
   * Context visible to this station: **messages from all execution units along the path from root to itself, in order**.
   *
   * Do not inspect only the current slot. Otherwise the second unit would start with nothing: no original problem, previous tool requests, or tool results. It would speak into a vacuum. Multi-station tree execution depends on this inheritance.
   *
   * Follow `from_unit` pointers, the same ancestry used by chain strings:
   *
   * - **Ancestors are visible; siblings are not.** A sibling is a different attempt; injecting another branch's speech would mix the attempts.
   * - Fail immediately on a cycle. Following from pointers back to the same row means corrupted data; continuing silently would hang.
   */
  /**
   * This round's **task view**: the problem, the current tree position, and other attempted paths.
   *
   * ## Why this view is necessary
   *
   * Context is assembled **up one chain**: ancestors are visible and siblings deliberately are not. The task description is delivered **as a message to the first station** at publication. Together these rules mean a root-level sibling opened after failure has **no ancestors and cannot see the problem**; only its own skills and bookkeeping remain. In practice the model received a methodology injection, acknowledged understanding the general method, and asked for the question's specific options. It really had never seen the problem.
   *
   * The root cause is treating **task facts as one station's message**. Facts should be a freshly computed view each round, like the score report: derived, not stored separately. Storing them as messages lets ancestry hide them.
   *
   * ## Supply facts, not phrasing
   *
   * Return structured data; rendering it to the model belongs to the adapter (`llm/index.ts`). The kernel does not know prompt wording.
   *
   * ## Provide only a tree outline
   *
   * Other branches are **excluded by default**: shared progress means visibility, not direct inheritance. Report which paths were tried and whether they died. Detailed inspection and retrieval of another branch's context belong to tools.
   */
  #viewOf(p: Pending, task: Row): Row {
    const rows = all(
      this.#store.ro,
      `select cycle, unit, node, status, done from "${p.sub}" where task = ? order by unit`,
      [p.task],
    ) as { cycle: string; unit: number; node: number; status: string | null; done: number }[];

    // **Report nodes, not rows.** `task_tree` and `node_load` use nodes. A view reporting row ids would lead the model to pass them as node ids,
    // wasting calls as observed with `node_load(8)` returning "there is no such node in this task".
    const byNode = new Map<number, typeof rows>();
    for (const r of rows) {
      const k = Number(r.node);
      const got = byNode.get(k) ?? [];
      got.push(r);
      byNode.set(k, got);
    }
    return {
      task: {
        id: task.id,
        description: task.description,
        domain: task.domain,
        source: task.source,
        place: task.place,
        workdir: task.workdir,
        objective: task.objective !== null,
      },
      // **Current station and whether a successor exists**: facts from the transition table.
      //
      // Without them, the model does not know it is at a terminal station. In practice it called `bash` at submission without a following tool-execution station, so the call never ran and no answer was submitted. It was not disobedient; **it could not see where it was**.
      here: {
        cycle: p.cycle,
        unit: p.unit,
        chain: chainOf(this.#store.ro, p.sub, p.mode, p),
        next: nextOf(this.#store.ro, p.mode, p.cycle),
      },
      budget: this.#budgetOf(p, task),
      tried: [...byNode.entries()]
        .sort((x, y) => x[0] - y[0])
        .map(([node, g]) => ({
          node,
          at: g.map((r) => `${r.cycle}#${r.unit}`).join(" > "),
          status: g[g.length - 1].status,
          done: g.every((r) => Number(r.done) === 1),
          mine: g.some((r) => Number(r.unit) === p.unit),
        })),
    };
  }

  /**
   * **Remaining allowance**: include it in the view instead of making the model guess.
   *
   * Previously it was absent, with measured consequences: the model spent its entire budget exploring the environment (`cmt-0`: 12 execution units checking Python/Node, no answer text), leaving nothing at finalization. The issue was **invisible remaining budget**, not inability to plan.
   *
   * **Report facts, not policy wording**: station usage, remaining slots, and remaining seconds are kernel bookkeeping. Which station and tool perform submission belongs to the **declaration layer**, through the transition table, skills, and task description. Kernel-injected strategy text would exceed its role, become false under another mode, and be impossible to fix through declarations.
   */
  #budgetOf(p: Pending, task: Row): Row {
    const caps = all(this.#store.ro, `select cycle, max_units from cycle where mode = ?`, [p.mode]) as {
      cycle: string;
      max_units: number;
    }[];
    const used = new Map(
      (
        // Report the allowance for **this node**, the resources it can currently spend.
        all(
          this.#store.ro,
          `select cycle, count(*) as n from "${p.sub}"
            where task = ? and node = (select node from "${p.sub}" where task = ? and cycle = ? and unit = ?)
            group by cycle`,
          [p.task, p.task, p.cycle, p.unit],
        ) as { cycle: string; n: number }[]
      ).map((r) => [r.cycle, Number(r.n)]),
    );
    const left = Math.max(
      0,
      Math.round(Number(task.solve_seconds ?? 0) - (Date.now() - Number(task.created_at ?? Date.now())) / 1000),
    );
    const hasG = task.objective !== null;
    const handed =
      hasG &&
      all(this.#store.ro, `select unit from "${p.sub}" where task = ? and cycle = ? limit 1`, [p.task, SUBMIT])
        .length > 0;
    return {
      units: caps.map((c) => ({
        cycle: c.cycle,
        used: used.get(c.cycle) ?? 0,
        cap: Number(c.max_units),
        left: Math.max(0, Number(c.max_units) - (used.get(c.cycle) ?? 0)),
      })),
      secondsLeft: left,
      ...(hasG ? { submitted: handed } : {}),
    };
  }

  /** Estimate outbound size in tokens. **The kernel has no tokenizer**: count bytes and divide by 4. One measured problem used 4234989 bytes versus the model's reported 1033906 tokens. */
  #tokensOf(rows: Row[]): number {
    let n = 0;
    for (const r of rows) {
      n += Buffer.byteLength(String(r.body ?? ""), "utf8") + Buffer.byteLength(String(r.thought ?? ""), "utf8");
    }
    return Math.round(n / 4);
  }

  /**
   * Replace **closed nodes** with their compressed versions. Leave the active node unchanged; its messages remain in use.
   *
   * Replace by **node**, not slot. A call and result may occupy adjacent slots; replacing only one leaves an orphaned result that makes the model reject the whole context.
   *
   * Send original text for uncompressed nodes (empty `press`). Compression occurs at closure; its failure must not also break this request.
   */
  /**
   * Increase compression until the context fits the threshold. **No compression by default.**
   *
   * The threshold is `api.compress_at`, the limit for this credential and model; empty means never compress. If the payload does not fit, try progressively stronger levels through the last **fully configured** level (`readyLevels`: every `msg_part` row must fill that column; `l4` is currently empty, so there are three). If it still exceeds the threshold, send it and let the provider reject it. No stronger level exists, and pretending otherwise would be worse.
   */
  #fit(p: Pending, rows: Row[], line: number[]): Row[] {
    const api = this.#handleOf(p).api;
    const cap = Number(api?.compress_at ?? 0);
    if (!cap || this.#tokensOf(rows) <= cap) return rows;
    let out = rows;
    const levels = readyLevels(this.#store.ro);
    for (const level of levels) {
      out = swapClosed(this.#store.ro, p, rows as unknown as Line[], line, level) as unknown as Row[];
      const now = this.#tokensOf(out);
      if (now <= cap) {
        this.#log.info(`${p.task} ${p.cycle}#${p.unit}: context ${String(this.#tokensOf(rows))} tok > ${String(cap)}, sent at ${level} (${String(now)} tok)`);
        return out;
      }
    }
    this.#log.warn(`${p.task} ${p.cycle}#${p.unit}: still ${String(this.#tokensOf(out))} tok at ${levels.at(-1) ?? "l0"}, over ${String(cap)}`);
    return out;
  }

  #contextOf(p: Pending): Row[] {
    const line: number[] = [];
    const seen = new Set<string>();
    let cur: Unit = p;
    for (;;) {
      const key = `${cur.cycle}#${cur.unit}`;
      if (seen.has(key)) throw new Error(`chain for ${p.task} in ${p.sub} is cyclic, at ${key}`);
      seen.add(key);
      line.unshift(cur.unit);
      if (cur.from_cycle === null || cur.from_unit === null) break;
      const up = one(
        this.#store.ro,
        `select task, cycle, unit, from_cycle, from_unit from "${p.sub}" where task = ? and cycle = ? and unit = ?`,
        [p.task, cur.from_cycle, cur.from_unit],
      ) as unknown as Unit | null;
      if (!up) {
        throw new Error(`${p.sub} ${p.task} ${cur.cycle}#${cur.unit} says it came from ${cur.from_cycle}#${cur.from_unit}, but that row is missing`);
      }
      cur = up;
    }

    const t = this.#msgTable(p.agent);
    const holes = line.map(() => "?").join(", ");
    // Order by unit, then seq. Unit ids increase monotonically within a task, so this is chronological order.
    let rows = all(
      this.#store.ro,
      `select unit, seq, role, kind, body, thought from "${t}"
        where instance = ? and unit in (${holes}) order by unit, seq`,
      [p.instance, ...line],
    );
    // **Complete missing results instead of removing calls**, but only when this station cannot be the one responsible for answering.
    //
    // The table identifies the responder: an empty `api_mode` invokes `agent.unit`, which executes tools and writes results. A nonempty api_mode calls a model, which cannot answer them. While assembling context for the former, tools **have not run yet**: unanswered means not yet, not never. Adding a placeholder then would produce two results for the same id after actual execution, also rejected (`Messages with role 'tool' must be a response to a preceding message with 'tool_calls'`). Five observed problems stalled at their third station this way.
    //
    // Finalization handles the remaining cases (see `#answerAll`). Only at the end does an unanswered call definitively mean it will never be answered.
    const cyc = one(this.#store.ro, `select api_mode from cycle where mode = ? and cycle = ?`, [p.mode, p.cycle]);
    if (String(cyc?.api_mode ?? "").trim() === "") return rows;

    // **Complete results before compressing.** The reverse order caused failures: completion identifies answered calls by `kind='tool'`,
    // but compressed closed nodes already represent calls and results as prose, hiding all matches and missing required completions. Orphaned original calls then reached the provider path and were rejected locally by the SDK: `Tool result is missing for tool call …`. Eight stations failed this way, all submission stations.
    const typed = rows as unknown as { unit: number; seq: number; kind: string; body: string }[];
    if (answerMissing(this.#store.rw, p.agent, p.instance, typed) > 0) {
      rows = all(
        this.#store.ro,
        `select unit, seq, role, kind, body, thought from "${t}"
          where instance = ? and unit in (${holes}) order by unit, seq`,
        [p.instance, ...line],
      );
    }
    return this.#mend(p, this.#fit(p, rows, line));
  }

  /**
   * Final pre-send check: do calls still match results? Remove only unmatched fragments; **do not revert compression**.
   *
   * Normally this does nothing. Any removal means an earlier stage lost a result, so always warn with the slot and call identity. Silent removal would leave the defect for next time, visible only as the model seeming to miss something.
   */
  #mend(p: Pending, rows: Row[]): Row[] {
    const got = mendPairs(rows as unknown as Pair[]);
    if (got.dropped.length === 0) return rows;
    this.#log.warn(
      `${p.task} ${p.cycle}#${p.unit}: context did not hold together, dropped ${String(got.dropped.length)}: ${got.dropped.slice(0, 3).join("; ")}`,
    );
    return got.rows as unknown as Row[];
  }

  /** Append a context row. `seq` is consecutive within this unit. */
  #push(p: Pending, role: string, kind: string, body: string, said?: Said): void {
    // **Apply the same validation to this row.** It inserts directly instead of using `deliver()`.
    // If shape constraints existed on only one path, the other would admit malformed rows.
    checkBody(kind, body);
    const t = this.#msgTable(p.agent);
    const seq = this.#seqMax(p) + 1;
    // Keep usage and provenance with this row, **not in another table**. They explain how this row arose;
    // separating them would require joining three keys, with silent errors for wrong joins. Providers whose adapters omit metrics leave nulls, visibly meaning unreported rather than zero.
    run(
      this.#store.rw,
      `insert into "${t}" (instance, unit, seq, role, kind, body, at,
                           thought, prompt_tokens, completion_tokens, reasoning_tokens, cached_tokens)
       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        p.instance,
        p.unit,
        seq,
        role,
        kind,
        body,
        Date.now(),
        said?.thought || null,
        said?.prompt_tokens ?? null,
        said?.completion_tokens ?? null,
        said?.reasoning_tokens ?? null,
        said?.cached_tokens ?? null,
      ],
    );
  }

  /** Facts available for condition matching. Build the chain string as in `chain.ts`: that is the protocol. */
  #factsOf(p: Pending): Facts {
    const agent = one(this.#store.ro, `select * from agent where name = ?`, [p.agent]);
    const task = one(this.#store.ro, `select * from task where id = ?`, [p.task]);
    const cycle = one(this.#store.ro, `select * from cycle where mode = ? and cycle = ?`, [p.mode, p.cycle]);
    if (!agent) throw new Error(`no row in agent for ${p.agent}`);
    if (!task) throw new Error(`no row in task for ${p.task}`);
    if (!cycle) throw new Error(`no row in cycle for ${p.mode}/${p.cycle}`);
    return { agent, task, cycle, place: p.place, chain: chainOf(this.#store.ro, p.sub, p.mode, p) };
  }

  /**
   * Infer the next cycle and write a new row.
   *
   * **Candidates (columns 4 and 5) determine the inference function**, which chooses one candidate. Reject any selection outside the candidates immediately; do not allow arbitrary choices.
   *
   * The inference function may return three shapes:
   *
   * | Return | Meaning |
   * | --- | --- |
   * | `null` | Stop here |
   * | `"cycleName"` | Enter that cycle, **continuing from the current row** |
   * | `{to, from_cycle, from_unit, status}` | Enter that cycle, **continuing from the specified row**, and optionally assign the current row a terminal state |
   *
   * The third supports trees: opening a sibling after death attaches to **the same parent**, while backtracking attaches to **an ancestor**, neither to the current row. The kernel recognizes the shape, not the meaning of siblings or backtracking.
   */
  async #infer(p: Pending, facts: Facts, result: unknown): Promise<void> {
    const cyc = facts.cycle as { next: string; infer: string };
    const next = JSON.parse(String(cyc.next)) as string[];

    // Pass both facts and the current row's identity to inference: siblings and backtracking need the tree position.
    // **Consult inference even at terminal stations.** Empty `next` means no successor, not that success need not be judged. Inference supplies terminal states (reached / dead_*). Previously short-circuiting to null left every terminal station's status empty, hiding whether it succeeded or died. Submission is terminal; short-circuiting it would prevent grading entirely.
    const picked = await this.#reg
      .get(String(cyc.infer))
      .call({ ...facts, next, result, sub: p.sub, unit: p.unit });
    const said = picked !== null && typeof picked === "object" ? (picked as Record<string, unknown>) : null;
    const to = picked == null ? null : said ? (said.to == null ? null : String(said.to)) : String(picked);
    // **Omitted differs from explicitly root**: omit the parent to continue from the current row;
    // `null` attaches at the root with no parent. Conflating them would attach a root sibling under the root itself, silently creating the wrong tree shape.
    const saidFrom = said !== null && "from_cycle" in said;
    const fromCycle = saidFrom ? (said!.from_cycle == null ? null : String(said!.from_cycle)) : p.cycle;
    const fromUnit = saidFrom ? (said!.from_unit == null ? null : Number(said!.from_unit)) : p.unit;
    const status = said && said.status != null ? String(said.status) : null;

    run(this.#store.rw, `update "${p.sub}" set done = 1, status = ? where task = ? and cycle = ? and unit = ?`, [
      status,
      p.task,
      p.cycle,
      p.unit,
    ]);
    // **Compress a node when it closes**, meaning this station acquires a nonempty terminal `status`.
    // Compress the completed node, never one still producing messages that remain in use.
    //
    // Compression failure must not undo a genuinely completed station. Its `press` stays empty, and context assembly sends original text for it (see `#contextOf`).
    if (status !== null) {
      const node = one(this.#store.ro, `select node from "${p.sub}" where task = ? and cycle = ? and unit = ?`, [
        p.task,
        p.cycle,
        p.unit,
      ]);
      if (node) {
        try {
          const n = await pressNode(this.#store.rw, this.#reg, {
            sub: p.sub,
            task: p.task,
            node: Number(node.node),
            agent: p.agent,
            instance: p.instance,
          });
          if (n > 0) this.#log.info(`${p.task} node ${String(node.node)}: pressed ${String(n)} unit(s)`);
        } catch (e) {
          this.#log.warn(`${p.task} node ${String(node.node)}: could not be pressed: ${msg(e)}`);
        }
      }
    }
    const ctx = tableNameOf("agent_{}_ctx", p.agent);
    run(this.#store.rw, `update "${ctx}" set done = 1 where instance = ? and unit = ?`, [p.instance, p.unit]);

    if (to !== null) {
      // **The `next` allowlist applies only to forward transitions.**
      //
      // Sibling creation and backtracking return the third shape with `from_cycle`, attaching to a specified row. Their `to` is **the current cycle** for siblings or **an ancestor's cycle** for backtracking, naturally outside `next`. Applying next universally would prevent all siblings after failure, reporting that fn:infer.dfs selected ask when the candidate was act.
      //
      // This was previously hidden because the model always requested tools at each station, so ask never claimed arrival and was never judged or killed. A model answering directly exposed it.
      //
      // Skipping the allowlist does not skip validation: the later `no row in cycle for ${p.mode}/${to}` check still rejects invented cycle names.
      if (!saidFrom && !next.includes(to)) {
        throw new Error(`${cyc.infer} returned ${to}, which is not among the candidates (${next.join(", ")})`);
      }
      // **Which node this row belongs to.**
      //
      // A node is one complete attempt spanning several execution units, closed by the row with a terminal state (`status` is reached / dead_*, fixed when assigned). Therefore:
      //
      //   Parent still open → share the parent's node.
      //   Parent closed → this row starts the next node.
      //
      // **Store this rather than repeatedly inferring it.** Inference would traverse the parent chain and need to know which cycle closes a node. Hard-coding that knowledge would silently misread another mechanism.
      const parent =
        fromCycle === null || fromUnit === null
          ? undefined
          : (one(this.#store.ro, `select node, status from "${p.sub}" where task = ? and cycle = ? and unit = ?`, [
              p.task,
              fromCycle,
              fromUnit,
            ]) as { node?: number; status?: string | null } | undefined);
      const node = parent === undefined ? 1 : Number(parent.node ?? 1) + (parent.status == null ? 0 : 1);

      const cap = one(this.#store.ro, `select max_units from cycle where mode = ? and cycle = ?`, [p.mode, to]);
      if (!cap) throw new Error(`no row in cycle for ${p.mode}/${to}`);

      // **Count allowances within this node, not the entire problem.**
      //
      // A node is one complete attempt with its own budget. Exhaust it, submit, and if judged dead move to a new node with a fresh allowance. Counting per problem would let the first node consume everything, allowing only one submission and preventing retry on another path.
      //
      // The number of nodes a problem may try is a separate dimension, controlled by `max_dead_siblings` and `solve_seconds`.
      const used = Number(
        one(this.#store.ro, `select count(*) as c from "${p.sub}" where task = ? and cycle = ? and node = ?`, [
          p.task,
          to,
          node,
        ])!.c,
      );
      if (used >= Number(cap.max_units)) {
        this.#log.warn(
          `${p.task}: ${p.mode}/${to} has used all ${cap.max_units} units of node ${node}, not opening more`,
        );
      } else {
        // **Ids increase monotonically across the task, without restarting per cycle.** The agent ctx table's key is (instance, unit),
        // without cycle; restarting would collide think#1 and act#1 in one row.
        // max_units limits row count under a cycle, independently of ids.
        const unit =
          Number(one(this.#store.ro, `select coalesce(max(unit), 0) as m from "${p.sub}" where task = ?`, [p.task])!.m) +
          1;
        run(
          this.#store.rw,
          `insert into "${p.sub}" (task, cycle, unit, node, from_cycle, from_unit, agent, instance, place, at, done)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`,
          [p.task, to, unit, node, fromCycle, fromUnit, p.agent, p.instance, p.place, Date.now()],
        );
        // Create the matching agent-side half at the same time; both sides must align.
        run(
          this.#store.rw,
          `insert into "${ctx}" (instance, task, unit, place, done) values (?, ?, ?, ?, 0)`,
          [p.instance, p.task, unit, p.place],
        );
      }
    }

    // If this step makes all task work complete, announce `task_done`.
    //
    // **Every moment listed in `MOMENTS` must actually be emitted.** Otherwise attached rules never run, while `check` sees valid conditions and logs reveal nothing, exactly the silent failure this engine must avoid.
    if (this.#restate(p.task, p.sub)) await this.#atMoment(p, facts, "task_done");
  }

  /**
   * Derive the main-table state from subtables instead of maintaining it independently. Its four-state domain includes:
   *
   * | Subtable state | Task state |
   * | --- | --- |
   * | No execution units | `open`: awaiting claim |
   * | Some unfinished units | `claimed`: work in progress |
   * | All units finished | `done` |
   *
   * `failed` cannot be derived by counting: it is a **judgment**. The verifier layer must write it explicitly when implemented. Inventing it here would make the column untruthful.
   *
   * Return whether this operation just transitioned to `done`, letting the upper layer announce `task_done`. Compute that here instead of recounting above: two counts could drift and omit or duplicate the event.
   */
  /**
   * Complete all unanswered calls across this problem's instances in one pass.
   *
   * A task may have several instances (one context per agent), so first discover them through the execution-unit table.
   */
  #answerAll(task: string, sub: string): void {
    const who = all(this.#store.ro, `select distinct agent, instance from "${sub}" where task = ?`, [task]) as {
      agent: string;
      instance: string;
    }[];
    for (const w of who) {
      try {
        const t = this.#msgTable(w.agent);
        const rows = all(
          this.#store.ro,
          `select unit, seq, kind, body from "${t}" where instance = ? order by unit, seq`,
          [w.instance],
        ) as unknown as { unit: number; seq: number; kind: string; body: string }[];
        const put = answerMissing(this.#store.rw, w.agent, w.instance, rows);
        if (put > 0) this.#log.info(`${w.instance}: answered ${put} call(s) that nobody ever ran`);
      } catch (e) {
        // Failure to complete missing results must not block task finalization: missing rows do not mean the problem is unfinished.
        this.#log.warn(`${w.instance}: could not answer the calls left open: ${msg(e)}`);
      }
    }
  }
  #restate(task: string, sub: string): boolean {
    const got = one(this.#store.ro, `select count(*) as n, coalesce(sum(done), 0) as d from "${sub}" where task = ?`, [
      task,
    ])!;
    const n = Number(got.n);
    const d = Number(got.d);
    const now = one(this.#store.ro, `select state from task where id = ?`, [task]);
    const was = String(now?.state ?? "");
    if (was === "failed") return false; // Do not derive a previously failed task back into another state.
    const next = n === 0 ? "open" : d === n ? "done" : "claimed";
    run(this.#store.rw, `update task set state = ? where id = ?`, [next, task]);
    const justDone = next === "done" && was !== "done";
    // **Complete unanswered calls before finalization.** Normally completion runs while assembling context, but nobody reads context after the final station.
    // If it requests a tool that nobody executes, the unmatched call would remain forever, preventing the table from being a complete snapshot.
    if (justDone) this.#answerAll(task, sub);
    // Announce completion. **The kernel does not know what the recipient does**; judging success is not its responsibility.
    if (justDone) {
      this.#finalize(task);
    }
    return justDone;
  }

  /**
   * Schedule the timer for **the nearest database deadline**, not a fixed polling interval.
   *
   * A timeout means nobody wrote anything: no write means no signal, so only a clock can detect it. Continuous scans are unnecessary. Without new writes, wake precisely when death is due; after a new write, recompute.
   */
  #arm(rows: Pending[]): void {
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = null;
    if (this.#stopped) return;
    const now = Date.now();

    // Execution-unit level: whether this step is stuck.
    const deadlines = rows
      .map((r) => {
        const cap = this.#expectSafe(r);
        return cap === null ? null : r.at + cap;
      })
      .filter((d): d is number => d !== null);

    // **Include task-level deadlines too.** Scheduling only unit deadlines could let a problem exceed `solve_seconds` indefinitely:
    // the limits differ substantially (15 minutes per step versus 5 minutes for the whole problem), and without database writes nothing else wakes the kernel.
    //
    // Observed: two problems with `solve_seconds=300` remained claimed after 1306 seconds. They were stuck in long model calls; no writes meant no timeout checks.
    for (const t of all(
      this.#store.ro,
      `select created_at, solve_seconds from task where state not in ('done','failed')`,
    ) as { created_at: number; solve_seconds: number }[]) {
      deadlines.push(Number(t.created_at) + Number(t.solve_seconds) * 1000);
    }
    for (const row of this.#pendingFinalizations()) {
      if (!this.#finalizing.has(row.id)) deadlines.push(Number((JSON.parse(row.result) as { retryAt?: number }).retryAt ?? now));
    }

    if (deadlines.length === 0) return;
    const soonest = Math.min(...deadlines);
    this.#timer = setTimeout(() => this.wake(), Math.max(soonest - now, 50));
    this.#timer.unref?.();
  }
}

function text(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v ?? null);
}

/**
 * Render an error as one line, **including its `cause`**.
 *
 * The outer message alone is insufficient, as observed with AI SDK: after HTTP 200, it maps the response into its own structure. Mapping failure wraps the error as `Failed to process successful response`, while **the actual reason lives in `cause`** (`postToApi` in `@ai-sdk/provider-utils`). Without it, partial-body disconnection, a mismatched field shape, and an empty response look identical. Diagnosis stalls, leaving a run with a dozen identical messages.
 *
 * Also include the endpoint's response (`statusCode` / `responseBody`). For HTTP 400, that text often gives the diagnosis directly; this exposed `Thinking mode does not support this tool_choice`.
 */
export function msg(e: unknown): string {
  const out: string[] = [];
  let cur: unknown = e;
  for (let i = 0; cur && i < 5; i++) {
    const x = cur as { message?: unknown; name?: unknown; statusCode?: unknown; responseBody?: unknown; cause?: unknown };
    const one = typeof x.message === "string" ? x.message : String(cur);
    const extra: string[] = [];
    if (x.statusCode) extra.push(`status ${String(x.statusCode)}`);
    if (typeof x.responseBody === "string" && x.responseBody) extra.push(`body ${x.responseBody.slice(0, 300)}`);
    out.push(one + (extra.length ? ` (${extra.join(", ")})` : ""));
    cur = x.cause;
    // Do not repeat identical messages across wrapper layers; some wrappers forward message unchanged.
    if (typeof (cur as { message?: unknown } | null)?.message === "string" && (cur as { message: string }).message === one) {
      cur = (cur as { cause?: unknown }).cause;
    }
  }
  return out.join(" <- ");
}
