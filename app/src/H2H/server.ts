/**
 * 起接口。**这一层只搭台子**：开库、装闸（令牌 / CORS / 请求体）、把路由装上。
 * 端口、令牌、能不能写、一次最多几行 —— 都从 config.yaml 来，这儿不设默认值。
 *
 * **每个口长什么样不在这儿**，在 `api/` 底下 —— 一个口的说明、它的参数表、
 * 它的实现是同一份声明。契约长在接口上，不在旁边的文档里：文档会漂，声明漂不了
 * （漂了请求就会被错误地拒，当场看得出来）。
 */

import Fastify, { type FastifyInstance } from "fastify";
import cors from "@fastify/cors";

import { h2hRoutes } from "../api/h2h.ts";
import { mount, type Route } from "../api/spec.ts";
import type { Config } from "./config.ts";
import { BadName, NoSuchTable, open, type Store } from "./db.ts";

/** 写口被打了之后喊一声。**只是喊一声，不带数据** —— 带了就成内存队列了。 */
export interface Hooks {
  onWrite?: () => void;
  /** 不校验令牌的路径（那张页本身）。**只放页，不放数据** —— 页里发的数据请求照样要令牌。 */
  public?: string[];
}

/** 起好的那台。`routes` 带着已经装上的口 —— 上面那层要拿它去装 help。 */
export type App = FastifyInstance & { store: Store; routes: Route[] };

export async function build(cfg: Config, hooks: Hooks = {}): Promise<App> {
  const store = open(cfg);
  const app = Fastify({
    logger: { level: cfg.log.level },
    bodyLimit: cfg.server.bodyLimit,
  });

  if (cfg.cors.enabled) await app.register(cors, { origin: cfg.cors.origin });

  // 有几个口**根本不收 body**（装表那种，打一下就干活）。而 Fastify 认的是
  // content-type：一个 `curl -X POST` 不带头、不带 body，它按「不认得这种媒体类型」
  // 顶回 415 —— 那句话指向的是格式，而请求里压根没有格式可言，人只会以为接口坏了。
  //
  // 所以在这儿兜一道，但**只兜空 body**：
  //
  // - 没有 body → 当没有 body（`undefined`），该干什么干什么
  // - 有 body 但格式不认得 → **还是 415**，而且说清不认得的是哪一种
  //
  // 一刀切成「什么都收下」的话，第二种就被吞了：发来一坨我们解不了的东西，
  // 接口回 200，而那份 body 悄悄没了。
  app.addContentTypeParser("*", { parseAs: "buffer" }, (req, body, done) => {
    if ((body as Buffer).length === 0) return done(null, undefined);
    const ct = req.headers["content-type"] ?? "(none given)";
    const err = new Error(`unsupported content-type: ${ct}`) as Error & { statusCode?: number };
    err.statusCode = 415;
    done(err, undefined);
  });

  // 令牌。配置里留空就整个不校验 —— 本地默认这样。
  // `/health` 放行：令牌配错了也得探得出来机器是活的，不然分不清是没起来还是没认证。
  if (cfg.api.token) {
    app.addHook("onRequest", async (req, reply) => {
      if (req.url.startsWith(`${cfg.api.prefix}/health`)) return;
      if ((hooks.public ?? []).includes(req.url.split("?")[0])) return;
      const got = req.headers.authorization ?? "";
      if (got !== `Bearer ${cfg.api.token}`) {
        return reply.code(401).send({ error: "bad token - send Authorization: Bearer <token>" });
      }
    });
  }

  // **封存域和绑判据这两道闸，在路由之前统一拦。**
  //
  // 1. 原始 SQL 不许 ATTACH / DETACH。只读连接挡得住写，挡不住把封存库挂进来读 ——
  //    `/query` 一句 ATTACH 就能读出全部判据定义（10-01 审计实测过）。拦关键词是下策，
  //    但够不到另一个库文件只有 ATTACH 这一个口，这里认这个词是准的。
  // 2. 绑判据要发布者令牌（`api.publisherToken`）。来源字段是调用方自报的：容器里的
  //    求解器能连到这个 API 时，报一个 `user` 就能给自己的任务绑判据。
  const pub = cfg.api.publisherToken;
  app.addHook("preHandler", async (req, reply) => {
    if (req.method !== "POST") return;
    const path = req.url.split("?")[0];
    const p = cfg.api.prefix;
    if (path === `${p}/query` || path === `${p}/exec`) {
      const sql = (req.body as { sql?: unknown } | undefined)?.sql;
      if (typeof sql === "string" && /\b(attach|detach)\b/i.test(sql)) {
        return reply.code(403).send({ error: "ATTACH and DETACH are refused: the sealed store is a separate access domain and no route may open it" });
      }
    }
    if (pub && (path === `${p}/tasks` || path === `${p}/bench`)) {
      const b = req.body as { objective?: unknown; tasks?: Array<{ objective?: unknown } | null> } | undefined;
      const binds = (b?.objective !== undefined && b?.objective !== null) ||
        (Array.isArray(b?.tasks) && b.tasks.some((t) => t?.objective !== undefined && t?.objective !== null));
      if (binds && req.headers["x-tgengin-publisher"] !== pub) {
        return reply.code(403).send({ error: "binding an objective needs the publisher token: send X-TGEngin-Publisher: <token>" });
      }
    }
  });
  if (!pub) {
    app.log.warn("api.publisherToken is not set: any caller that reaches /tasks or /bench can bind an objective by declaring a non-agent source. Set it (or TGENGIN_PUBLISHER_TOKEN) and keep it out of the solver's reach.");
  }

  const routes = h2hRoutes(cfg, store, () => hooks.onWrite?.());
  mount(app, cfg.api.prefix, routes);

  // 领域里的错换成对应的状态码 —— 让 500 只剩下「真的是我这边坏了」。
  //
  // **错身上带的细节要一起送出去。** 只送 `message` 的话，`/declare` 那句
  // 「这份声明有 4 处不对」就成了一句空话 —— 它承诺过要把全部问题一次说全，
  // 而列表在 `problems` 上，被这儿吞掉了。承诺了没给，比不承诺更糟。
  app.setErrorHandler(async (err: Error, req, reply) => {
    if (err instanceof NoSuchTable) return reply.code(404).send({ error: err.message });
    if (err instanceof BadName) return reply.code(400).send({ error: err.message });
    const e = err as Error & { statusCode?: number; problems?: string[]; at?: string; refs?: string[] };
    const code = e.statusCode ?? 500;
    if (code >= 500) req.log.error(err);
    return reply.code(code).send({
      error: err.message,
      ...(e.problems ? { problems: e.problems } : {}),
      ...(e.at ? { at: e.at } : {}),
      ...(e.refs ? { refs: e.refs } : {}),
    });
  });

  // 打错地址的时候把 help 指出来 —— 不指的话他只能去猜，或者去读表。
  app.setNotFoundHandler(async (req, reply) =>
    reply.code(404).send({
      error: `no such route: ${req.method} ${req.url}`,
      help: `GET ${cfg.api.prefix}/help`,
    }),
  );

  return Object.assign(app, { store, routes }) as App;
}
