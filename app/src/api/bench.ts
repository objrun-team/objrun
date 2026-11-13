/**
 * Benchmark scoring and diagnostics.
 *
 * The diagnostic endpoints are **essential functionality**, not optional debugging extras.
 * An invalid condition can fail silently: the rule never triggers while the system otherwise
 * runs normally. The old implementation explicitly warned that a typical mistake "silently
 * has no effect and cannot be detected by simply running the system."
 */

import type { Store } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import type { Sealed } from "../objective/store.ts";
import { runBench, runs, score, type Bench } from "../tasks/bench.ts";
import { check, explain } from "../trigger/check.ts";
import { checkData } from "../trigger/data.ts";
import type { Route } from "./spec.ts";

const BENCH = "bench";
const DIAG = "diagnostics";

export function benchRoutes(store: Store, reg: Registry, sealed: Sealed, wake: () => void): Route[] {
  return [
    {
      method: "POST",
      path: "/bench",
      group: BENCH,
      does: "Publish a batch of graded tasks",
      why: "One bad task rejects the whole batch. Publishing half of it makes the denominator on the scorecard wrong, and nobody can tell which ones are missing.",
      params: [
        { name: "run", in: "body", kind: "string", note: "What this run is called. Omitted, one is generated from the clock. A duplicate name is rejected outright - two scorecards mixed together explain nothing" },
        { name: "tasks", in: "body", kind: "array", required: true, of: "Same shape as POST /tasks takes, each carrying its own objective", note: "The tasks in this batch" },
      ],
      returns: { run: "2026-08-29T12-00-00", ids: ["b-1", "b-2"] },
      errs: [{ code: 400, when: "Duplicate run name, an empty batch, or any single task failing the publish gate (the whole batch is rejected)" }],
      handler: async (a, _req, reply) => {
        // As with `/tasks`, rejected input is a request error and always returns 400.
        let r: unknown;
        try {
          r = runBench(store.rw, a as unknown as Bench, sealed);
        } catch (e) {
          return reply.code(400).send({ error: e instanceof Error ? e.message : String(e) });
        }
        wake();
        return reply.code(201).send(r);
      },
    },
    {
      method: "GET",
      path: "/bench",
      group: BENCH,
      does: "Which runs exist",
      returns: { runs: [{ run: "2026-08-29T12-00-00", n: 4 }] },
      handler: async () => ({ runs: runs(store.ro) }),
    },
    {
      method: "GET",
      path: "/bench/:run",
      group: BENCH,
      does: "The scorecard for one run",
      why: "Counted, not stored. A stored copy drifts from the truth, and the drift is never reported.",
      params: [{ name: "run", in: "path", kind: "string", required: true, note: "The name of the run" }],
      returns: { run: "2026-08-29T12-00-00", total: 4, done: 2, failed: 1, running: 1, tasks: [] },
      handler: async (a) => score(store.ro, String(a.run)),
    },
    {
      method: "GET",
      path: "/check",
      group: DIAG,
      does: "Sweep the whole database: are the trigger terms well formed, and does the data line up with itself",
      why: "This also runs once at boot; problems warn but do not block startup. A client should surface it on its config page - a broken declaration raises no error, the machine simply does nothing.",
      returns: {
        trigger: [{ owner_kind: "tool", owner: "read", group: 0, why: "unknown operator contain" }],
        data: [{ what: "task t-1", why: "its mode dfs is not in the cycle table - nobody can pick this task up, and nothing reports it" }],
      },
      handler: async () => ({ trigger: check(store.ro), data: checkData(store.ro, reg) }),
    },
    {
      method: "GET",
      path: "/trigger/check",
      group: DIAG,
      does: "Sweep only the trigger terms",
      why: "Verifiable without running the system. The usual consequence of a malformed term is silence: the rule never fires while everything else carries on. So this is not a debugging convenience, it is the precondition for the table being usable at all.",
      returns: { problems: [] },
      handler: async () => ({ problems: check(store.ro) }),
    },
    {
      method: "POST",
      path: "/trigger/explain",
      group: DIAG,
      does: "Why this one did not match - group by group, with the values actually read",
      why: "Saying only \"no match\" leaves the reader guessing whether the word was mistyped or simply absent from the text. Showing the actual value removes the guess.",
      params: [
        { name: "kind", in: "body", kind: "string", required: true, only: ["rule", "skill", "tool"], note: "Which kind of owner to ask about (`owner_kind`)" },
        { name: "owner", in: "body", kind: "string", required: true, note: "Which one (rule identity / skill / tool name)" },
        { name: "agent", in: "body", kind: "string", note: "Which agent to take as fact. Omitted, that dimension is treated as absent" },
        { name: "task", in: "body", kind: "string", note: "Which task to take as fact" },
        { name: "mode", in: "body", kind: "string", note: "Which mode the cycle belongs to; give it together with `cycle`" },
        { name: "cycle", in: "body", kind: "string", note: "Which cycle" },
        { name: "chain", in: "body", kind: "string", note: "The chain string, e.g. `dfs/open#1 > dfs/act#2`" },
        { name: "place", in: "body", kind: "string", note: "Which workplace to take as fact. This is the station of the execution unit, not the task" },
      ],
      returns: {
        fired: false,
        groups: [{ group: 0, ok: false, items: [{ dim: "task", key: "source", op: "eq", value: "user", actual: "agent", ok: false }] }],
      },
      errs: [{ code: 400, when: "the named agent / task / cycle has no row in the database" }],
      handler: async (a, _req, reply) => {
        try {
          const row = (what: string, sql: string, p: unknown[]) => {
            const r = all(store.ro, sql, p)[0];
            if (!r) throw new Error(`no such row in ${what}`);
            return r;
          };
          return explain(store.ro, String(a.kind), String(a.owner), {
            agent: a.agent ? row("agent", `select * from agent where name = ?`, [a.agent]) : {},
            task: a.task ? row("task", `select * from task where id = ?`, [a.task]) : {},
            cycle: a.mode ? row("cycle", `select * from cycle where mode = ? and cycle = ?`, [a.mode, a.cycle]) : {},
            chain: a.chain ? String(a.chain) : "",
            place: a.place ? String(a.place) : "",
          });
        } catch (e) {
          return reply.code(400).send({ error: e instanceof Error ? e.message : String(e) });
        }
      },
    },
  ];
}
