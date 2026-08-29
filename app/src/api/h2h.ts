/**
 * 库那一层的口 —— **只做搬运**：把请求翻成一次库操作，把结果翻成 JSON。
 *
 * 这一层**不认得任何业务**：没有任务、没有智能体、没有 G。它认得的只有「表」和
 * 「行」。业务那一层在 `kernel.ts`。
 *
 * ## 这几个口是给谁的
 *
 * `/query` 和 `/exec` 收原始 SQL，**它们是给认得表的人用的**（我们自己、调试、
 * 迁移），不是给客户端的。客户端该用的是 `kernel.ts` 里那些封好的口 ——
 * 拿原始 SQL 去配一台机器，等于把表结构焊进客户端。
 *
 * 留着它们是因为「库是权威存储」这条：任何时候都得有一条路能把库里的实情看全，
 * 而不是只能看我们愿意给的那部分。要关掉就把 `api.allowQuery` / `api.allowWrite`
 * 关了。
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
    throw bad("params 要么是数组（按位置绑），要么是对象（按 :名字 绑）");
  }
  return { sql: String(a.sql), params: params as Params | undefined };
}

export function h2hRoutes(cfg: Config, store: Store, onWrite: () => void): Route[] {
  const DB = "库";
  return [
    {
      method: "GET",
      path: "/health",
      group: DB,
      does: "活着没、库在哪、几张表",
      why: "客户端拿它探活。**这个口不校验令牌** —— 令牌配错了也得探得出来机器是活的。",
      returns: { ok: true, db: "…/h2h.sqlite", tables: 12, write: true, query: true, uptimeMs: 4225 },
      handler: async () => ({
        ok: true,
        db: store.file,
        tables: tables(store.ro).length,
        write: cfg.api.allowWrite,
        query: cfg.api.allowQuery,
        uptimeMs: Date.now() - started,
      }),
    },
    {
      method: "GET",
      path: "/tables",
      group: DB,
      does: "有哪些表",
      returns: { tables: ["task", "agent", "cycle", "task_dfs", "agent_solver_msg"] },
      handler: async () => ({ tables: tables(store.ro) }),
    },
    {
      method: "GET",
      path: "/tables/:table/schema",
      group: DB,
      does: "一张表的形状",
      params: [{ name: "table", in: "path", kind: "string", required: true, note: "表名。不存在回 404" }],
      returns: { table: "task", columns: [{ name: "id", type: "text", notnull: 1 }] },
      errs: [{ code: 404, when: "没有这张表" }],
      handler: async (a) => schemaOf(store.ro, String(a.table)),
    },
    {
      method: "GET",
      path: "/tables/:table/rows",
      group: DB,
      does: "翻一张表",
      why: "截断了会明说（`truncated`）。不说的话，少的那部分看起来像是库里根本没有。",
      params: [
        { name: "table", in: "path", kind: "string", required: true, note: "表名" },
        { name: "limit", in: "query", kind: "int", def: cfg.api.defaultLimit, note: `要几行。超过 ${cfg.api.maxRows} 按 ${cfg.api.maxRows} 截` },
        { name: "offset", in: "query", kind: "int", def: 0, note: "从第几行开始" },
        { name: "order", in: "query", kind: "string", note: "按哪一列排。**只认这张表真有的列名**，别的当场拒" },
        { name: "dir", in: "query", kind: "string", only: ["asc", "desc"], def: "asc", note: "升还是降" },
      ],
      returns: { table: "task", total: 42, limit: 100, offset: 0, truncated: false, rows: [] },
      errs: [
        { code: 400, when: "limit/offset 是负数，或 order 不是这张表的列" },
        { code: 404, when: "没有这张表" },
      ],
      handler: async (a) => {
        const t = realTable(store.ro, String(a.table));
        const asked = Number(a.limit);
        if (asked < 0) throw bad("limit 得是个非负的数");
        const offset = Number(a.offset);
        if (offset < 0) throw bad("offset 得是个非负的数");
        const limit = Math.min(asked, cfg.api.maxRows);

        let orderBy = "";
        if (a.order) {
          const cols = (schemaOf(store.ro, t).columns as { name: string }[]).map((c) => c.name);
          if (!cols.includes(String(a.order))) throw bad(`这张表没有这一列：${String(a.order)}`);
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
      does: "原始 SQL 查",
      why: "**走一条独立的只读连接** —— 写不进去是连接层面的保证，不是靠认关键字。认关键字总有绕过去的写法。",
      params: [
        { name: "sql", in: "body", kind: "string", required: true, note: "一句 select" },
        { name: "params", in: "body", kind: "object", of: "数组按位置绑，对象按 :名字 绑", note: "绑定值。**别把值拼进 sql 里**" },
      ],
      returns: { count: 1, rows: [{ a: 1 }] },
      errs: [
        { code: 400, when: "SQL 有毛病" },
        { code: 403, when: "config.yaml 里 api.allowQuery 是关的" },
      ],
      handler: async (a, _req, reply) => {
        if (!cfg.api.allowQuery) return reply.code(403).send({ error: "config.yaml 里 api.allowQuery 是关的" });
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
      does: "原始 SQL 写",
      why: "**这个口是给认得表的人用的，不是给客户端的。** 客户端配机器该走 `/declare` —— 拿原始 SQL 去配，等于把表结构焊进客户端，表一改它就坏，而且坏得很安静。",
      params: [
        { name: "sql", in: "body", kind: "string", required: true, note: "一句 insert / update / delete" },
        { name: "params", in: "body", kind: "object", of: "数组按位置绑，对象按 :名字 绑", note: "绑定值" },
      ],
      returns: { changes: 1, lastInsertRowid: 7 },
      errs: [
        { code: 400, when: "SQL 有毛病" },
        { code: 403, when: "config.yaml 里 api.allowWrite 是关的" },
      ],
      handler: async (a, _req, reply) => {
        if (!cfg.api.allowWrite) return reply.code(403).send({ error: "config.yaml 里 api.allowWrite 是关的" });
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
      does: "往一张表里插一行",
      why: "比裸 SQL 稳一点：**列名对不上当场拒**，不会静静插进去一行少了半截的东西。",
      params: [
        { name: "table", in: "path", kind: "string", required: true, note: "表名" },
        { name: "row", in: "body", kind: "object", required: true, note: "一行。**键必须是这张表真有的列**，多一个就拒" },
      ],
      returns: { changes: 1, lastInsertRowid: 7 },
      errs: [
        { code: 400, when: "行是空的、或者有这张表没有的列" },
        { code: 403, when: "api.allowWrite 是关的" },
        { code: 404, when: "没有这张表" },
      ],
      handler: async (a, _req, reply) => {
        if (!cfg.api.allowWrite) return reply.code(403).send({ error: "config.yaml 里 api.allowWrite 是关的" });
        const t = realTable(store.rw, String(a.table));
        const row = a.row as Record<string, unknown>;
        const cols = (schemaOf(store.rw, t).columns as { name: string }[]).map((c) => c.name);
        const keys = Object.keys(row);
        if (keys.length === 0) throw bad("这一行是空的");
        const unknownCol = keys.find((k) => !cols.includes(k));
        if (unknownCol) throw bad(`这张表没有这一列：${unknownCol}（有的是 ${cols.join("、")}）`);
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
