/**
 * 接口。**这一层只做搬运**：把请求翻成一次库操作，把结果翻成 JSON。
 * 端口、令牌、能不能写、一次最多几行 —— 都从 config.yaml 来，这儿不设默认值。
 */

import Fastify, { type FastifyInstance } from "fastify";
import cors from "@fastify/cors";

import type { Config } from "./config.ts";
import {
  all,
  BadName,
  NoSuchTable,
  open,
  realTable,
  run,
  schemaOf,
  tables,
  type Params,
  type Store,
} from "./db.ts";

const started = Date.now();

function badSql(e: unknown) {
  const err = new Error(e instanceof Error ? e.message : String(e));
  (err as Error & { statusCode?: number }).statusCode = 400;
  return err;
}

function sqlOf(body: unknown): { sql: string; params?: Params } {
  if (body === null || typeof body !== "object") throw badSql("请求体得是 JSON 对象");
  const { sql, params } = body as { sql?: unknown; params?: unknown };
  if (typeof sql !== "string" || sql.trim() === "") throw badSql("要一句 sql");
  if (params !== undefined && (typeof params !== "object" || params === null)) {
    throw badSql("params 要么是数组（按位置绑），要么是对象（按 :名字 绑）");
  }
  return { sql, params: params as Params | undefined };
}

/** 写口被打了之后喊一声。**只是喊一声，不带数据** —— 带了就成内存队列了。 */
export interface Hooks {
  onWrite?: () => void;
}

export async function build(cfg: Config, hooks: Hooks = {}): Promise<FastifyInstance & { store: Store }> {
  const store = open(cfg);
  const app = Fastify({
    logger: { level: cfg.log.level },
    bodyLimit: cfg.server.bodyLimit,
  });

  if (cfg.cors.enabled) await app.register(cors, { origin: cfg.cors.origin });

  // 令牌。配置里留空就整个不校验 —— 本地默认这样。
  if (cfg.api.token) {
    app.addHook("onRequest", async (req, reply) => {
      if (req.url.startsWith(`${cfg.api.prefix}/health`)) return;
      const got = req.headers.authorization ?? "";
      if (got !== `Bearer ${cfg.api.token}`) {
        return reply.code(401).send({ error: "令牌不对：发 Authorization: Bearer <token>" });
      }
    });
  }

  const p = cfg.api.prefix;

  app.get(`${p}/health`, async () => ({
    ok: true,
    db: store.file,
    tables: tables(store.ro).length,
    write: cfg.api.allowWrite,
    query: cfg.api.allowQuery,
    uptimeMs: Date.now() - started,
  }));

  app.get(`${p}/tables`, async () => ({ tables: tables(store.ro) }));

  app.get<{ Params: { table: string } }>(`${p}/tables/:table/schema`, async (req) =>
    schemaOf(store.ro, req.params.table),
  );

  app.get<{ Params: { table: string }; Querystring: Record<string, string> }>(
    `${p}/tables/:table/rows`,
    async (req) => {
      const t = realTable(store.ro, req.params.table);
      const q = req.query;

      const asked = q.limit === undefined ? cfg.api.defaultLimit : Number(q.limit);
      if (!Number.isFinite(asked) || asked < 0) throw badSql("limit 得是个非负的数");
      const limit = Math.min(asked, cfg.api.maxRows);

      const offset = q.offset === undefined ? 0 : Number(q.offset);
      if (!Number.isFinite(offset) || offset < 0) throw badSql("offset 得是个非负的数");

      // 排序列拼进 SQL，所以只认这张表真有的列名。
      let orderBy = "";
      if (q.order) {
        const cols = (schemaOf(store.ro, t).columns as { name: string }[]).map((c) => c.name);
        if (!cols.includes(q.order)) throw badSql(`这张表没有这一列：${q.order}`);
        const dir = (q.dir ?? "asc").toLowerCase();
        if (dir !== "asc" && dir !== "desc") throw badSql("dir 只能是 asc 或 desc");
        orderBy = ` order by "${q.order}" ${dir}`;
      }

      const total = Number((all(store.ro, `select count(*) as c from "${t}"`)[0] as { c: number }).c);
      const rows = all(store.ro, `select * from "${t}"${orderBy} limit ? offset ?`, [limit, offset]);
      // 截了就说出来 —— 不说的话，少的那部分看起来像是库里没有。
      return { table: t, total, limit, offset, truncated: asked > cfg.api.maxRows, rows };
    },
  );

  app.post(`${p}/query`, async (req, reply) => {
    if (!cfg.api.allowQuery) return reply.code(403).send({ error: "config.yaml 里 api.allowQuery 是关的" });
    const { sql, params } = sqlOf(req.body);
    try {
      const rows = all(store.ro, sql, params); // 只读连接：写不进去
      return { count: rows.length, rows };
    } catch (e) {
      throw badSql(e);
    }
  });

  app.post(`${p}/exec`, async (req, reply) => {
    if (!cfg.api.allowWrite) return reply.code(403).send({ error: "config.yaml 里 api.allowWrite 是关的" });
    const { sql, params } = sqlOf(req.body);
    try {
      const r = run(store.rw, sql, params);
      hooks.onWrite?.();
      return r;
    } catch (e) {
      throw badSql(e);
    }
  });

  app.post<{ Params: { table: string } }>(`${p}/tables/:table/rows`, async (req, reply) => {
    if (!cfg.api.allowWrite) return reply.code(403).send({ error: "config.yaml 里 api.allowWrite 是关的" });
    const t = realTable(store.rw, req.params.table);
    const row = req.body;
    if (row === null || typeof row !== "object" || Array.isArray(row)) throw badSql("请求体得是一行：JSON 对象");

    const cols = (schemaOf(store.rw, t).columns as { name: string }[]).map((c) => c.name);
    const keys = Object.keys(row as Record<string, unknown>);
    if (keys.length === 0) throw badSql("这一行是空的");
    const unknownCol = keys.find((k) => !cols.includes(k));
    if (unknownCol) throw badSql(`这张表没有这一列：${unknownCol}`);

    try {
      const r = run(
        store.rw,
        `insert into "${t}" (${keys.map((k) => `"${k}"`).join(", ")})
         values (${keys.map(() => "?").join(", ")})`,
        keys.map((k) => (row as Record<string, unknown>)[k]),
      );
      hooks.onWrite?.();
      return reply.code(201).send(r);
    } catch (e) {
      throw badSql(e);
    }
  });

  // 领域里的错换成对应的状态码 —— 让 500 只剩下「真的是我这边坏了」。
  app.setErrorHandler(async (err: Error, req, reply) => {
    if (err instanceof NoSuchTable) return reply.code(404).send({ error: err.message });
    if (err instanceof BadName) return reply.code(400).send({ error: err.message });
    const code = (err as { statusCode?: number }).statusCode ?? 500;
    if (code >= 500) req.log.error(err);
    return reply.code(code).send({ error: err.message });
  });

  app.setNotFoundHandler(async (req, reply) =>
    reply.code(404).send({ error: `没有这个接口：${req.method} ${req.url}` }),
  );

  return Object.assign(app, { store }) as FastifyInstance & { store: Store };
}
