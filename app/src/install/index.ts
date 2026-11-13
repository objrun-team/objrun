/**
 * Install tables.
 *
 * **Tables are declared rather than hard-coded.** This module knows no specific table or column
 * names. It creates missing tables from declarations, checks existing tables against their
 * declarations and fails on mismatches, then derives subtables from database content.
 *
 * Immediate failure is intentional: when declarations change but the database retains an old
 * shape, the application can keep running with permanently empty columns or queries returning
 * nothing, without errors. Check the schema during installation instead.
 *
 * Declarations are imported modules bundled with the program, so they survive compilation into
 * one executable. Only `config.yaml` is read from disk at runtime; configuration is a separate concern.
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import decl from "./tables.json" with { type: "json" };

const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;

export interface ColumnDecl {
  name: string;
  type: string;
  notnull?: boolean;
}

export interface TableDecl {
  name: string;
  columns: ColumnDecl[];
  pk: string[];
  unique?: string[][];
}

interface TemplateDecl {
  pattern: string;
  source: { table: string; column: string };
  columns: ColumnDecl[];
  pk: string[];
  unique?: string[][];
}

function ident(s: string, what: string): string {
  if (!IDENT.test(s)) throw new Error(`illegal ${what}: ${s}`);
  return s;
}

/** A table creation statement, with columns in declaration order. */
export function ddl(t: TableDecl): string {
  ident(t.name, "table name");
  if (t.columns.length === 0) throw new Error(`table ${t.name} has no columns`);
  const cols = t.columns.map((c) => {
    ident(c.name, "column name");
    return `"${c.name}" ${c.type}${c.notnull ? " not null" : ""}`;
  });
  if (t.pk.length === 0) throw new Error(`table ${t.name} has no primary key`);
  t.pk.forEach((c) => {
    if (!t.columns.some((x) => x.name === c)) throw new Error(`primary key ${c} of table ${t.name} is not among its columns`);
  });
  const parts = [...cols, `primary key (${t.pk.map((c) => `"${c}"`).join(", ")})`];
  for (const u of t.unique ?? []) {
    u.forEach((c) => {
      if (!t.columns.some((x) => x.name === c)) throw new Error(`unique constraint ${c} of table ${t.name} is not among its columns`);
    });
    parts.push(`unique (${u.map((c) => `"${c}"`).join(", ")})`);
  }
  return `create table "${t.name}" (\n  ${parts.join(",\n  ")}\n)`;
}

/**
 * Values embedded in table names may not be valid identifiers (`researcher-01`, for example).
 * Normalize them with underscores. **Fail immediately on collisions**: silently sharing a table
 * would mix two agents' contexts without reporting an error.
 */
export function tableNameOf(pattern: string, value: string): string {
  const safe = value.replace(/[^A-Za-z0-9_]/g, "_");
  const name = pattern.replace("{}", safe);
  return ident(name, "grown table name");
}

/** Whether the table exists and, if it does, its current schema. */
function shapeOf(db: Conn, table: string) {
  const rows = all(db, `pragma table_info("${table}")`) as {
    name: string;
    type: string;
    notnull: number;
  }[];
  return rows.length === 0 ? null : rows;
}

/** Derive required subtables from database rows. Empty source data creates no subtables. */
export function subTables(db: Conn): TableDecl[] {
  const out: TableDecl[] = [];
  const seen = new Map<string, string>();
  for (const t of decl.templates as TemplateDecl[]) {
    if (shapeOf(db, t.source.table) === null) continue; // The source table does not exist yet, so no subtables can be derived.
    const rows = all(
      db,
      `select distinct "${ident(t.source.column, "column name")}" as v from "${ident(t.source.table, "table name")}"`,
    ) as { v: string }[];
    for (const r of rows) {
      const name = tableNameOf(t.pattern, String(r.v));
      const from = `${t.source.table}.${t.source.column} = ${r.v}`;
      const already = seen.get(name);
      if (already && already !== from) {
        throw new Error(`two different values grow the same table name ${name}: ${already} and ${from}`);
      }
      seen.set(name, from);
      out.push({ name, columns: t.columns, pk: t.pk, ...(t.unique ? { unique: t.unique } : {}) });
    }
  }
  return out;
}

export interface Plan {
  create: string[];
  ok: string[];
  /** Columns added during this invocation, as `table.column`. */
  added: string[];
  drift: { table: string; why: string[] }[];
  extra: string[];
}

function compare(db: Conn, want: TableDecl[], plan: Plan, declared: Set<string>) {
  for (const t of want) {
    declared.add(t.name);
    const got = shapeOf(db, t.name);
    if (got === null) {
      plan.create.push(t.name);
      continue;
    }
    const why: string[] = [];
    for (const c of t.columns) {
      const hit = got.find((g) => g.name === c.name);
      if (!hit) {
        // **A missing column can be added**, unlike modifying an existing column. Adding a column
        // preserves current data; changing its type or constraints requires rebuilding the table and
        // guessing the intended migration. A NOT NULL column without a default is an exception:
        // SQLite cannot add it without inventing values for existing rows.
        if (c.notnull) why.push(`missing column ${c.name}, and it is not null - that cannot be added to rows that already exist`);
        else plan.added.push(`${t.name}.${c.name}`);
        continue;
      }
      if (hit.type.toLowerCase() !== c.type.toLowerCase()) {
        why.push(`column ${c.name} type: declared ${c.type}, in database ${hit.type || "(empty)"}`);
      }
      if (Boolean(hit.notnull) !== Boolean(c.notnull)) {
        why.push(`column ${c.name} not null: declared ${Boolean(c.notnull)}, in database ${Boolean(hit.notnull)}`);
      }
    }
    for (const g of got) {
      if (!t.columns.some((c) => c.name === g.name)) why.push(`extra column ${g.name} (not in the declaration)`);
    }
    if (why.length) plan.drift.push({ table: t.name, why });
    else plan.ok.push(t.name);
  }
}

/** Inspect without modifying: differences between declarations and the current database. */
export function plan(db: Conn): Plan {
  const p: Plan = { create: [], ok: [], added: [], drift: [], extra: [] };
  const declared = new Set<string>();
  compare(db, decl.tables as TableDecl[], p, declared);
  compare(db, subTables(db), p, declared);
  const inDb = (
    all(db, `select name from sqlite_master where type = 'table' and name not like 'sqlite_%'`) as {
      name: string;
    }[]
  ).map((r) => r.name);
  p.extra = inDb.filter((n) => !declared.has(n));
  return p;
}

/**
 * Create tables.
 *
 * **Idempotent**: skip existing tables with the correct shape; a second invocation does nothing.
 * **Do not modify existing tables**: reject mismatched schemas. Automatically applying ALTER
 * would guess the intended migration, with existing data at risk if that guess is wrong.
 *
 * Run in two passes: create fixed tables first, then derive subtables from database content.
 * Their shape cannot be known until the fixed tables contain rows.
 */
export function install(db: Conn): Plan {
  const all: TableDecl[] = [...(decl.tables as TableDecl[])];
  const fixed: Plan = { create: [], ok: [], added: [], drift: [], extra: [] };
  compare(db, decl.tables as TableDecl[], fixed, new Set());
  bail(fixed);
  for (const name of fixed.create) {
    db.exec(ddl((decl.tables as TableDecl[]).find((t) => t.name === name)!));
  }
  add(db, all, fixed.added);

  const grown = subTables(db);
  all.push(...grown);
  const sub: Plan = { create: [], ok: [], added: [], drift: [], extra: [] };
  compare(db, grown, sub, new Set());
  bail(sub);
  for (const name of sub.create) db.exec(ddl(grown.find((t) => t.name === name)!));
  add(db, all, sub.added);

  // Report **what this invocation actually created**, not the post-installation state.
  // The latter would always say every table already exists and therefore convey nothing useful.
  const after = plan(db);
  return {
    ...after,
    create: [...fixed.create, ...sub.create],
    added: [...fixed.added, ...sub.added],
    ok: after.ok.filter((n) => !fixed.create.includes(n) && !sub.create.includes(n)),
  };
}

/**
 * Add missing columns. **Only add columns; do not change existing data.**
 *
 * Existing rows remain usable with empty values in the new columns. Type or constraint changes
 * to existing columns cannot reach this code; `bail` rejects them first.
 */
function add(db: Conn, want: TableDecl[], columns: string[]): void {
  for (const one of columns) {
    const cut = one.lastIndexOf(".");
    const table = one.slice(0, cut);
    const column = one.slice(cut + 1);
    const c = want.find((t) => t.name === table)?.columns.find((x) => x.name === column);
    if (!c) throw new Error(`cannot add ${one}: it is not in the declaration`);
    db.exec(`alter table "${ident(table, "table name")}" add column "${ident(column, "column name")}" ${c.type}`);
  }
}

/**
 * Stop on incompatible schemas. **Only changes to existing columns remain here**:
 * changed types or constraints, or extra database columns absent from the declaration.
 * `compare` already classified missing columns as additions.
 *
 * The rejected changes require rebuilding the table, which would guess the intended migration
 * and risk data loss if that guess is wrong.
 */
function bail(p: Plan) {
  if (!p.drift.length) return;
  const lines = p.drift.map((d) => `  ${d.table}: ${d.why.join("; ")}`).join("\n");
  throw new Error(`the tables in the database do not match the declaration; nothing was changed:\n${lines}`);
}
