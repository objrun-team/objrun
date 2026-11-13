/**
 * Database access through two connections:
 *
 * - `rw`: create tables, execute PRAGMAs, and write.
 * - `ro`: read-only; all queries use this connection.
 *
 * **Read-only access is enforced by the connection, not by keyword detection.** Checking SQL
 * for `update` cannot cover every form (`with ... insert`, comments, case, or semicolon-separated
 * statements). Every missed case would permit a real write.
 *
 * The driver is Bun's built-in `bun:sqlite`, with **no native dependency**. This is practical:
 * adding a SQLite package that requires compilation, such as better-sqlite3, would break
 * cross-compilation immediately.
 *
 * This is the only file in the project that knows about SQLite.
 */

import { Database, type SQLQueryBindings } from "bun:sqlite";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

import type { Config } from "./config.ts";

/** The result of a write. Both drivers provide these two values, possibly as BigInt. */
export interface Written {
  changes: number;
  lastInsertRowid: number;
}

/** A connection. Higher-level code depends only on this interface, not on its implementation. */
export interface Conn {
  exec(sql: string): void;
  all(sql: string, params?: Params): Record<string, unknown>[];
  run(sql: string, params?: Params): Written;
  close(): void;
}

export interface Store {
  rw: Conn;
  ro: Conn;
  file: string;
  close(): void;
}

/** Parameters: arrays bind by position (`?`), objects by name (`:name`). Reject other shapes. */
export type Params = unknown[] | Record<string, unknown>;

/**
 * Add the required prefix to every named parameter key.
 *
 * **`bun:sqlite` can fail silently here**: `:b` accepts `{":b"}`, but `{b}` produces no error;
 * it is treated as unbound and the query returns no rows. That looks like missing database
 * content, making diagnosis difficult. Normalize the keys once here.
 */
function bind(params?: Params): SQLQueryBindings[] {
  if (params === undefined) return [];
  if (Array.isArray(params)) return params as SQLQueryBindings[];
  const named: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(params)) {
    named[/^[:$@]/.test(k) ? k : `:${k}`] = v;
  }
  return [named as SQLQueryBindings];
}

function wrap(raw: Database): Conn {
  return {
    exec: (sql) => raw.exec(sql),
    all: (sql, params) => {
      const stmt = raw.prepare(sql);
      try {
        const rows = stmt.all(...bind(params)) as Record<string, unknown>[];
        return rows.map((r) => plain(r) as Record<string, unknown>);
      } finally {
        stmt.finalize();
      }
    },
    run: (sql, params) => {
      const stmt = raw.prepare(sql);
      try {
        const r = stmt.run(...bind(params));
        return { changes: Number(r.changes), lastInsertRowid: Number(r.lastInsertRowid) };
      } finally {
        stmt.finalize();
      }
    },
    close: () => raw.close(),
  };
}

export function open(cfg: Config): Store {
  // Create the directory first if needed. SQLite otherwise reports "unable to open database file",
  // which does not identify a missing directory as the cause.
  mkdirSync(dirname(cfg.db.file), { recursive: true });

  const rw = wrap(new Database(cfg.db.file, { create: true }));
  for (const [k, v] of Object.entries(cfg.db.pragmas)) {
    rw.exec(`PRAGMA ${k} = ${typeof v === "number" ? v : String(v)}`);
  }

  // Read-only connection. The option is `readonly`, entirely lowercase. A misspelling does not
  // raise an error; it leaves the connection writable.
  const ro = wrap(new Database(cfg.db.file, { readonly: true }));
  const busy = cfg.db.pragmas.busy_timeout;
  if (busy !== undefined) ro.exec(`PRAGMA busy_timeout = ${Number(busy)}`);

  return {
    rw,
    ro,
    file: cfg.db.file,
    close() {
      ro.close();
      rw.close();
    },
  };
}

/** A row may contain values JSON cannot represent, such as large integers and BLOBs. Convert them into serializable forms. */
export function plain(v: unknown): unknown {
  if (typeof v === "bigint") return v.toString();
  if (v instanceof Uint8Array) return { $blob: Buffer.from(v).toString("base64"), bytes: v.length };
  if (Array.isArray(v)) return v.map(plain);
  if (v !== null && typeof v === "object") {
    return Object.fromEntries(Object.entries(v as Record<string, unknown>).map(([k, x]) => [k, plain(x)]));
  }
  return v;
}

export function all(db: Conn, sql: string, params?: Params) {
  return db.all(sql, params);
}

export function run(db: Conn, sql: string, params?: Params): Written {
  return db.run(sql, params);
}

export interface TableInfo {
  name: string;
  type: string;
  rows: number;
}

export function tables(db: Conn): TableInfo[] {
  const rows = all(
    db,
    `select name, type from sqlite_master
      where type in ('table','view') and name not like 'sqlite_%'
      order by type, name`,
  ) as { name: string; type: string }[];
  return rows.map((t) => ({
    ...t,
    rows: Number((all(db, `select count(*) as c from "${t.name}"`)[0] as { c: number }).c),
  }));
}

/** The name is not a valid identifier. */
export class BadName extends Error {}
/** The table does not exist in the database. */
export class NoSuchTable extends Error {}

/**
 * Table names must be valid identifiers and must exist in the database. Validate every name
 * before interpolating it into SQL, because identifiers cannot be bound through placeholders.
 */
export function realTable(db: Conn, name: string): string {
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) throw new BadName(`illegal table name: ${name}`);
  const hit = all(
    db,
    `select name from sqlite_master where type in ('table','view') and name = ? limit 1`,
    [name],
  );
  if (hit.length === 0) throw new NoSuchTable(`no such table: ${name}`);
  return (hit[0] as { name: string }).name;
}

export function schemaOf(db: Conn, table: string) {
  const t = realTable(db, table);
  return {
    table: t,
    columns: all(db, `pragma table_info("${t}")`),
    indexes: all(db, `pragma index_list("${t}")`),
    sql: (all(db, `select sql from sqlite_master where name = ?`, [t])[0] as { sql: string } | undefined)?.sql ?? null,
  };
}
