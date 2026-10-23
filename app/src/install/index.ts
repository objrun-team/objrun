/**
 * 装表。
 *
 * **表是声明出来的，不是写死的。** 这个文件不认得任何一个表名、列名 ——
 * 它只干三件事：照着声明把没有的建出来；把已有的跟声明比一遍，对不上就炸；
 * 照着库里的数据把子表长出来。
 *
 * 「对不上就炸」不是洁癖：声明改了而库还是老形状，系统照样跑，只是那一列
 * 永远是空的、那个查询永远查不到 —— 零报错。所以在装的这一刻就问清楚。
 *
 * 声明是 `import` 进来的，不是运行时读文件 —— 它随程序走，打包成单文件之后
 * 也在。运行时才读的是 `config.yaml`，那是配置，两回事。
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

/** 一张表的建表语句。列的顺序就是声明里的顺序。 */
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
 * 表名里塞进去的东西不一定是合法标识符（`researcher-01` 就不是），
 * 统一换成下划线。**换完撞车了当场炸** —— 悄悄合成一张表的话，
 * 两个智能体的上下文会混在一起，而那不报错。
 */
export function tableNameOf(pattern: string, value: string): string {
  const safe = value.replace(/[^A-Za-z0-9_]/g, "_");
  const name = pattern.replace("{}", safe);
  return ident(name, "grown table name");
}

/** 库里现在有这张表没有；有的话它是什么形状。 */
function shapeOf(db: Conn, table: string) {
  const rows = all(db, `pragma table_info("${table}")`) as {
    name: string;
    type: string;
    notnull: number;
  }[];
  return rows.length === 0 ? null : rows;
}

/** 照着库里的数据，把子表该有哪些算出来。数据是空的就一张都不长。 */
export function subTables(db: Conn): TableDecl[] {
  const out: TableDecl[] = [];
  const seen = new Map<string, string>();
  for (const t of decl.templates as TemplateDecl[]) {
    if (shapeOf(db, t.source.table) === null) continue; // 源表还没建，谈不上长
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
  /** 这一趟补上去的列，`表.列`。 */
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
        // **少一列是能补的**，跟「原来那列变了」不是一回事：补一列不动任何已有的
        // 数据，而改一列的类型或者约束要重建整张表，那才是在猜你想要哪种改法。
        // 带 not null 又没有默认值的除外 —— sqlite 加不上去，已有的行填什么都是编的。
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

/** 只看不动：声明跟库现在差在哪。 */
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
 * 把表建出来。
 *
 * **幂等**：已经在且形状对的跳过，跑第二遍什么都不做。
 * **不改已有的表**：形状对不上就炸 —— 自动 ALTER 是在猜你想要哪种改法，
 * 猜错的代价是数据。
 *
 * 分两趟：先建固定的那些，再照着库里的数据长子表 —— 子表长成什么样，
 * 得等固定表里有行了才知道。
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

  // 报的是**这一趟真建了什么**，不是建完之后再看一眼的样子 ——
  // 后者永远是「一张没建，全都在」，等于什么都没说。
  const after = plan(db);
  return {
    ...after,
    create: [...fixed.create, ...sub.create],
    added: [...fixed.added, ...sub.added],
    ok: after.ok.filter((n) => !fixed.create.includes(n) && !sub.create.includes(n)),
  };
}

/**
 * 把少掉的那几列补上去。**只加列，不动已有的数据。**
 *
 * 加完就是老库能接着用：原来那些行照旧，新列是空的。声明里改了某一列的类型或者
 * 约束的话走不到这儿 —— 那种在 `bail` 那儿就停了。
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
 * 形状对不上就停。**这儿拦的只剩「原来那些列变了」** —— 类型变了、约束变了、
 * 库里多出声明里没有的列。少一列那种在 `compare` 那儿已经归到「补一列」里了。
 *
 * 拦的这几种都要重建整张表，而重建就是在猜你想要哪种改法，猜错的代价是数据。
 */
function bail(p: Plan) {
  if (!p.drift.length) return;
  const lines = p.drift.map((d) => `  ${d.table}: ${d.why.join("; ")}`).join("\n");
  throw new Error(`the tables in the database do not match the declaration; nothing was changed:\n${lines}`);
}
