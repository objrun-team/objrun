/**
 * Start the API. **This layer only sets up infrastructure**: open the database, install guards
 * (token, CORS, and body limits), and register routes. Ports, tokens, write permissions, and row
 * limits come from config.yaml; there are no defaults here.
 *
 * **Endpoint contracts live in `api/`**, not here. Each endpoint's description, parameter table,
 * and implementation share a declaration. The contract belongs to the endpoint rather than a
 * separate document: prose can drift silently, whereas declaration drift incorrectly rejects
 * requests and is immediately visible.
 */

import Fastify, { type FastifyInstance } from "fastify";
import cors from "@fastify/cors";

import { h2hRoutes } from "../api/h2h.ts";
import { mount, type Route } from "../api/spec.ts";
import type { Config } from "./config.ts";
import { BadName, NoSuchTable, open, type Store } from "./db.ts";

/** Signal after a write endpoint is called. **The signal carries no data**, or it would become an in-memory queue. */
export interface Hooks {
  onWrite?: () => void;
  /** Paths exempt from token checks: the UI page itself. **Only the page, not its data**; its data requests still require a token. */
  public?: string[];
}

/** The running server. `routes` contains registered endpoints so the higher layer can build help. */
export type App = FastifyInstance & { store: Store; routes: Route[] };

export async function build(cfg: Config, hooks: Hooks = {}): Promise<App> {
  const store = open(cfg);
  const app = Fastify({
    logger: { level: cfg.log.level },
    bodyLimit: cfg.server.bodyLimit,
  });

  if (cfg.cors.enabled) await app.register(cors, { origin: cfg.cors.origin });

  // Some endpoints **accept no body at all**, such as table installation. Fastify checks
  // content-type, however: `curl -X POST` with neither headers nor body receives 415 for an
  // unsupported media type. The message suggests a format problem when there is no body
  // whose format could be wrong, making the endpoint appear broken.
  //
  // Handle this centrally, but **only for empty bodies**:
  //
  // - No body: use `undefined` and let the endpoint proceed normally.
  // - A body with an unsupported format: **still return 415**, naming the unsupported type.
  //
  // Accepting everything indiscriminately would swallow the second case: an undecodable body
  // would disappear silently while the endpoint returned 200.
  app.addContentTypeParser("*", { parseAs: "buffer" }, (req, body, done) => {
    if ((body as Buffer).length === 0) return done(null, undefined);
    const ct = req.headers["content-type"] ?? "(none given)";
    const err = new Error(`unsupported content-type: ${ct}`) as Error & { statusCode?: number };
    err.statusCode = 415;
    done(err, undefined);
  });

  // Token validation is entirely disabled when the configuration value is empty, the local default.
  // Allow `/health`: even with a misconfigured token, a probe must distinguish a running service
  // from one that never started.
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

  // **Enforce sealed-database isolation and objective-publishing authorization before routing.**
  //
  // 1. Raw SQL cannot ATTACH / DETACH. A read-only connection blocks writes but cannot prevent
  //    attaching the sealed database to read it. One ATTACH through `/query` exposed all objective
  //    definitions in the 10-01 audit. Keyword filtering is a fallback, but ATTACH is the only SQL
  //    mechanism for reaching that other database file, so matching this keyword is appropriate.
  // 2. Attaching objectives requires the publisher token (`api.publisherToken`). Callers report
  //    their own source: a solver container with access to the API could otherwise claim `user`
  //    and attach an objective to its own task.
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

  // Map domain errors to appropriate status codes, reserving 500 for actual server failures.
  //
  // **Include the error's details too.** Sending only `message` makes `/declare`'s "4 problems
  // in this declaration" useless: it promises all problems together, but their list lives in
  // `problems` and would be discarded here. Breaking that promise is worse than not making it.
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

  // Point unknown routes to help; otherwise callers must guess or inspect database tables.
  app.setNotFoundHandler(async (req, reply) =>
    reply.code(404).send({
      error: `no such route: ${req.method} ${req.url}`,
      help: `GET ${cfg.api.prefix}/help`,
    }),
  );

  return Object.assign(app, { store, routes }) as App;
}
