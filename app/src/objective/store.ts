/**
 * Sealed storage for G definitions.
 *
 * ## Why not use the main database
 *
 * There are two boundaries: **no direct reading of G's definition**, and **no modification**.
 * Querying the black box is allowed; inferring its behavior through queries is test-time
 * scaling itself, not a vulnerability.
 *
 * Enforcement means **making the definition unreachable**, not merely forbidding access.
 * The main database has a complete query API: an agent can read any table through `/query`.
 * **Storing G there would eliminate the boundary entirely.**
 *
 * Keep definitions in a **separate database file** that H2H never opens and its API cannot
 * reach. The main database stores only `objective` (whether G exists and its identity),
 * `readable` (the visibility policy), and verdict-derived `result` / `state`.
 *
 * ## readable=true definitions need not be hidden
 *
 * For real tasks, acceptance criteria are part of the requirements. Hiding them can be wrong.
 * When `readable=true`, **append G's definition to the task description** as requirement text,
 * without a separate "read G" operation. Benchmark samples are the case requiring secrecy.
 *
 * There is one storage boundary, without separate implementations: **all definitions are sealed**.
 * `readable` determines only whether an **additional copy** appears in the task description.
 */

import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

import { Database } from "bun:sqlite";
import type { Objective } from "./spec.ts";
import { parseObjective, validate } from "./spec.ts";

/**
 * **The candidate structure** accepted by G.
 *
 * This declaration belongs to G, not a tool. The kernel exposes G through `verify`, and final
 * submission queries the same G, so both must accept exactly the same input. Declare it once
 * here for both tools. Duplicated literals would eventually diverge after a field addition,
 * letting a model follow one description while the other endpoint silently receives less data.
 */
export const CANDIDATE = {
  type: "object",
  properties: {
    answer: {
      type: "string",
      description:
        "The answer, verbatim (keep the \\boxed{} if the task asks for one). This exact text is what gets " +
        "graded, not your derivation.",
    },
  },
  required: ["answer"],
} as const;

export interface Sealed {
  /** Seal a G definition. **Reject invalid definitions before writing anything.** */
  seal(task: string, g: Objective): void;
  /** Retrieve G. **Only the kernel side can call this**; the agent-facing path receives verdicts only. */
  open(task: string): Objective | null;
  /** This task's accepted candidate structure, or `null` if no G has been sealed. */
  paramsOf(task: string): Record<string, unknown> | null;
  /** Maximum queries to this G per attempt, or `null` if it has not been sealed. */
  checksOf(task: string): number | null;
  has(task: string): boolean;
  forget(task: string): void;
  close(): void;
}

export function openSealed(file: string): Sealed {
  mkdirSync(dirname(file), { recursive: true });
  const db = new Database(file, { create: true });
  db.exec("pragma journal_mode = WAL");
  db.exec(`create table if not exists objective (
    task   text not null primary key,
    body   text not null,
    params text not null,
    checks integer not null,
    at     integer not null
  )`);

  return {
    seal(task, g) {
      const errs = validate(g);
      if (errs.length) {
        // **Reject the entire task**, rather than storing an invalid G for later. An unevaluable G
        // would leave the task hanging indefinitely without a success/failure decision or explanation.
        throw new Error(`the grading function failed definition-time checks and was rejected:\n  - ${errs.join("\n  - ")}`);
      }
      // **Seal the candidate schema together with G.** Both `verify` and submission query the same G;
      // they obtain their input schema from this column rather than duplicating literals.
      db.prepare(
        `insert into objective (task, body, params, checks, at) values (?, ?, ?, ?, ?)
         on conflict(task) do update set body = excluded.body, params = excluded.params, checks = excluded.checks, at = excluded.at`,
      ).run(task, JSON.stringify(g), JSON.stringify(CANDIDATE), g.checks, Date.now());
    },
    open(task) {
      const row = db.prepare(`select body from objective where task = ?`).get(task) as { body: string } | null;
      return row ? parseObjective(JSON.parse(row.body)) : null;
    },
    checksOf(task) {
      const row = db.prepare(`select checks from objective where task = ?`).get(task) as
        | { checks?: number }
        | undefined;
      return row?.checks === undefined ? null : Number(row.checks);
    },
    paramsOf(task) {
      const row = db.prepare(`select params from objective where task = ?`).get(task) as
        | { params?: string }
        | undefined;
      if (!row?.params) return null;
      try {
        return JSON.parse(row.params) as Record<string, unknown>;
      } catch {
        return null;
      }
    },
    has(task) {
      return db.prepare(`select 1 from objective where task = ?`).get(task) !== null;
    },
    forget(task) {
      db.prepare(`delete from objective where task = ?`).run(task);
    },
    close() {
      db.close();
    },
  };
}
