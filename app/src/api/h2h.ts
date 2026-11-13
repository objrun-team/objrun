/**
 * Database endpoints **only translate** requests into database operations and results into JSON.
 *
 * This layer knows **nothing about domain behavior**: no tasks, agents, or G. It knows only
 * tables and rows. Domain operations belong in `kernel.ts`.
 *
 * ## Intended callers
 *
 * `/query` and `/exec` accept raw SQL and are **for people who understand the tables**:
 * maintainers, debugging, and migrations. Application clients should use the encapsulated
 * endpoints in `kernel.ts`. Configuring a machine through raw SQL couples the client to its schema.
 *
 * These endpoints preserve the database's role as authoritative storage. There must always be
 * an avenue to inspect all stored facts, not only the subset the API chooses to expose.
 * Disable them with `api.allowQuery` / `api.allowWrite` when necessary.
 */

import type { Config } from "../H2H/config.ts";
import { all, realTable, run, schemaOf, tables, type Params, type Store } from "../H2H/db.ts";
import type { Route } from "./spec.ts";

const started = Date.now();

function bad(msg: string): Error {
  const e = new Error(msg) as Error & { statusCode?: number };
  e.statusCode = 400;
  return e;
}

function sqlOf(a: Record<string, unknown>): { sql: string; params?: Params } {
  const params = a.params;
  if (params !== undefined && (typeof params !== "object" || params === null)) {
    throw bad("params must be either an array (bound by position) or an object (bound by :name)");
  }
  return { sql: String(a.sql), params: params as Params | undefined };
}

export function h2hRoutes(cfg: Config, store: Store, onWrite: () => void): Route[] {
  const DB = "database";
  return [
    {
      method: "GET",
      path: "/health",
      group: DB,
      does: "Alive, where the database is, how many tables",
      why: "A client uses it as a liveness probe. This route does not check the token - a misconfigured token must still leave the machine detectably alive.",
      returns: { ok: true, db: "…/h2h.sqlite", tables: 12, write: true, query: true, uptimeMs: 4225 },
      handler: async () => ({
        ok: true,
        db: store.file,
        tables: tables(store.ro).length,
        write: cfg.api.allowWrite,
        query: cfg.api.allowQuery,
        // Whether objective publication is protected by a token or relies on self-reported source. Clients and auditors can immediately see the strength of this boundary.
        objectiveGate: cfg.api.publisherToken ? "publisher-token" : "open",
        uptimeMs: Date.now() - started,
      }),
    },
    {
      method: "GET",
      path: "/tables",
      group: DB,
      does: "Which tables exist",
      returns: { tables: ["task", "agent", "cycle", "task_dfs", "agent_solver_msg"] },
      handler: async () => ({ tables: tables(store.ro) }),
    },
    {
      method: "GET",
      path: "/tables/:table/schema",
      group: DB,
      does: "The shape of one table",
      params: [{ name: "table", in: "path", kind: "string", required: true, note: "Table name. A missing one returns 404" }],
      returns: { table: "task", columns: [{ name: "id", type: "text", notnull: 1 }] },
      errs: [{ code: 404, when: "no such table" }],
      handler: async (a) => schemaOf(store.ro, String(a.table)),
    },
    {
      method: "GET",
      path: "/tables/:table/rows",
      group: DB,
      does: "Page through one table",
      why: "Truncation is stated outright (`truncated`). Unstated, the missing part looks like it was never in the database.",
      params: [
        { name: "table", in: "path", kind: "string", required: true, note: "Table name" },
        { name: "limit", in: "query", kind: "int", def: cfg.api.defaultLimit, note: `How many rows. Anything over ${cfg.api.maxRows} is cut to ${cfg.api.maxRows}` },
        { name: "offset", in: "query", kind: "int", def: 0, note: "Which row to start at" },
        { name: "order", in: "query", kind: "string", note: "Which column to order by. Only real column names of this table are accepted; anything else is rejected outright" },
        { name: "dir", in: "query", kind: "string", only: ["asc", "desc"], def: "asc", note: "Ascending or descending" },
      ],
      returns: { table: "task", total: 42, limit: 100, offset: 0, truncated: false, rows: [] },
      errs: [
        { code: 400, when: "limit/offset is negative, or order is not a column of this table" },
        { code: 404, when: "no such table" },
      ],
      handler: async (a) => {
        const t = realTable(store.ro, String(a.table));
        const asked = Number(a.limit);
        if (asked < 0) throw bad("limit must be a non-negative number");
        const offset = Number(a.offset);
        if (offset < 0) throw bad("offset must be a non-negative number");
        const limit = Math.min(asked, cfg.api.maxRows);

        let orderBy = "";
        if (a.order) {
          const cols = (schemaOf(store.ro, t).columns as { name: string }[]).map((c) => c.name);
          if (!cols.includes(String(a.order))) throw bad(`this table has no such column: ${String(a.order)}`);
          orderBy = ` order by "${String(a.order)}" ${String(a.dir)}`;
        }
        const total = Number((all(store.ro, `select count(*) as c from "${t}"`)[0] as { c: number }).c);
        const rows = all(store.ro, `select * from "${t}"${orderBy} limit ? offset ?`, [limit, offset]);
        return { table: t, total, limit, offset, truncated: asked > cfg.api.maxRows, rows };
      },
    },
    {
      method: "POST",
      path: "/query",
      group: DB,
      does: "Raw SQL read",
      why: "It runs on a separate read-only connection: not being able to write is guaranteed at the connection level, not by recognising keywords. There is always a phrasing that gets past keyword matching.",
      params: [
        { name: "sql", in: "body", kind: "string", required: true, note: "One select statement" },
        { name: "params", in: "body", kind: "object", of: "An array binds by position, an object binds by :name", note: "Bound values. Do not concatenate values into the sql" },
      ],
      returns: { count: 1, rows: [{ a: 1 }] },
      errs: [
        { code: 400, when: "the SQL is malformed" },
        { code: 403, when: "api.allowQuery is off in config.yaml" },
      ],
      handler: async (a, _req, reply) => {
        if (!cfg.api.allowQuery) return reply.code(403).send({ error: "api.allowQuery is off in config.yaml" });
        const { sql, params } = sqlOf(a);
        try {
          const rows = all(store.ro, sql, params);
          return { count: rows.length, rows };
        } catch (e) {
          throw bad(e instanceof Error ? e.message : String(e));
        }
      },
    },
    {
      method: "POST",
      path: "/exec",
      group: DB,
      does: "Raw SQL write",
      why: "This route is for someone who knows the tables, not for a client. A client configures the machine through `/declare`; configuring it with raw SQL welds the schema into the client, so a schema change breaks it, and breaks it quietly.",
      params: [
        { name: "sql", in: "body", kind: "string", required: true, note: "One insert / update / delete statement" },
        { name: "params", in: "body", kind: "object", of: "An array binds by position, an object binds by :name", note: "Bound values" },
      ],
      returns: { changes: 1, lastInsertRowid: 7 },
      errs: [
        { code: 400, when: "the SQL is malformed" },
        { code: 403, when: "api.allowWrite is off in config.yaml" },
      ],
      handler: async (a, _req, reply) => {
        if (!cfg.api.allowWrite) return reply.code(403).send({ error: "api.allowWrite is off in config.yaml" });
        const { sql, params } = sqlOf(a);
        try {
          const r = run(store.rw, sql, params);
          onWrite();
          return r;
        } catch (e) {
          throw bad(e instanceof Error ? e.message : String(e));
        }
      },
    },
    {
      method: "POST",
      path: "/tables/:table/rows",
      group: DB,
      does: "Insert one row into a table",
      why: "Steadier than raw SQL: a column name that does not match is rejected outright, rather than quietly inserting a row that is missing half of itself.",
      params: [
        { name: "table", in: "path", kind: "string", required: true, note: "Table name" },
        { name: "row", in: "body", kind: "object", required: true, note: "One row. Every key must be a real column of this table; one extra key rejects it" },
      ],
      returns: { changes: 1, lastInsertRowid: 7 },
      errs: [
        { code: 400, when: "the row is empty, or names a column this table does not have" },
        { code: 403, when: "api.allowWrite is off" },
        { code: 404, when: "no such table" },
      ],
      handler: async (a, _req, reply) => {
        if (!cfg.api.allowWrite) return reply.code(403).send({ error: "api.allowWrite is off in config.yaml" });
        const t = realTable(store.rw, String(a.table));
        const row = a.row as Record<string, unknown>;
        const cols = (schemaOf(store.rw, t).columns as { name: string }[]).map((c) => c.name);
        const keys = Object.keys(row);
        if (keys.length === 0) throw bad("this row is empty");
        const unknownCol = keys.find((k) => !cols.includes(k));
        if (unknownCol) throw bad(`this table has no such column: ${unknownCol} (it has: ${cols.join(", ")})`);
        try {
          const r = run(
            store.rw,
            `insert into "${t}" (${keys.map((k) => `"${k}"`).join(", ")})
             values (${keys.map(() => "?").join(", ")})`,
            keys.map((k) => row[k]),
          );
          onWrite();
          return reply.code(201).send(r);
        } catch (e) {
          throw bad(e instanceof Error ? e.message : String(e));
        }
      },
    },
  ];
}
