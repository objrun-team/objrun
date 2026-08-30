/**
 * 库。开两条连接：
 *
 * - `rw` —— 建表、跑 PRAGMA、写。
 * - `ro` —— 只读。所有查询走它。
 *
 * **只读是连接层面的保证，不是靠认关键字。** 「SQL 里有没有 update」
 * 那种判法永远数不全（`with ... insert`、注释、大小写、分号串），
 * 而漏掉一次就是一次真写进去。
 *
 * 驱动是 Bun 自带的 `bun:sqlite` —— **没有一个 native 依赖**。这不是洁癖：
 * 引一个要编译的 sqlite（better-sqlite3 之类），交叉编译当场就废了。
 *
 * 全项目只有这一个文件认得 sqlite。
 */

import { Database, type SQLQueryBindings } from "bun:sqlite";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

import type { Config } from "./config.ts";

/** 一次写的结果。两边的驱动都给这两个数，只是可能是 BigInt。 */
export interface Written {
  changes: number;
  lastInsertRowid: number;
}

/** 一条连接。上面所有代码只认这个形状，不认底下是谁。 */
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

/** 参数：数组按位置绑（`?`），对象按名字绑（`:name`）。别的形状不认。 */
export type Params = unknown[] | Record<string, unknown>;

/**
 * 名字绑的键统一带上前缀。
 *
 * **`bun:sqlite` 在这儿会静默出错**：`:b` 传 `{":b"}` 才认，传 `{b}`
 * 不报错 —— 它当成没绑，查出来是空的。空结果看起来就像「库里没有」，
 * 这种错最难查，所以在这儿一次抹平。
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
      const rows = raw.prepare(sql).all(...bind(params)) as Record<string, unknown>[];
      return rows.map((r) => plain(r) as Record<string, unknown>);
    },
    run: (sql, params) => {
      const r = raw.prepare(sql).run(...bind(params));
      return { changes: Number(r.changes), lastInsertRowid: Number(r.lastInsertRowid) };
    },
    close: () => raw.close(),
  };
}

export function open(cfg: Config): Store {
  // 目录不在就先建 —— 不建的话 SQLite 报「unable to open database file」，
  // 那句话看不出是目录缺了。
  mkdirSync(dirname(cfg.db.file), { recursive: true });

  const rw = wrap(new Database(cfg.db.file, { create: true }));
  for (const [k, v] of Object.entries(cfg.db.pragmas)) {
    rw.exec(`PRAGMA ${k} = ${typeof v === "number" ? v : String(v)}`);
  }

  // 只读连接。选项名是 readonly，全小写 —— 拼错一个字母的后果不是报错，
  // 是这条连接照样能写。
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

/** 一行里可能有 JSON 装不下的东西：大整数、BLOB。都换成能发出去的形状。 */
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

/** 名字不像个标识符。 */
export class BadName extends Error {}
/** 库里没有这张表。 */
export class NoSuchTable extends Error {}

/**
 * 表名只能是标识符，而且得真在库里 —— 拼进 SQL 的东西一律先这么过一道，
 * 因为表名没法用占位符绑。
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
