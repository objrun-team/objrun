/**
 * Endpoint declarations: **the contract belongs to the endpoint, not a separate document**.
 *
 * ## Why not maintain separate documentation
 *
 * A separate document can **drift silently**: its description and the implementation diverge
 * without any error. Clients discover the mismatch only when they make a request, then resort
 * to reading our tables. At that point, the two sides become tightly coupled.
 *
 * Instead, an endpoint's description and implementation are **one declaration**:
 *
 * ```
 *                     +-- Generate help, directly readable with curl
 * One declaration ----+-- Validate requests (missing/extra fields, types, ranges -> 400)
 *                     +-- Install the route, with its handler on the same record
 * ```
 *
 * **Drift becomes visible**: mismatches reject requests incorrectly, exposing the problem
 * immediately. This follows the repository's consistent approach: tables, tools, and APIs
 * are all declared.
 *
 * ## The parameter table defines the allowed operations
 *
 * Parameters and response shapes fully describe the client's available operations.
 * **Reject undeclared parameters rather than ignoring them.** Silently swallowing a typo such
 * as `max_units` instead of `maxUnits` would produce the wrong result without either side
 * reporting an error, exactly the kind of failure this system is designed to prevent.
 */

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

/** Allowed parameter types. **Only these types**; more complex structures belong in `shape`. */
export type Kind = "string" | "int" | "number" | "boolean" | "object" | "array";

export interface Param {
  name: string;
  /** Location: a path segment, query-string parameter, or request-body field. */
  in: "path" | "query" | "body";
  kind: Kind;
  /** An omitted value needs `def`; without either, reject the request. */
  required?: boolean;
  /** Default for an omitted value. **Declare it here, not in the handler**, so help can show the actual default. */
  def?: unknown;
  /** Allowed values. Reject misspellings immediately instead of letting a condition never match. */
  only?: readonly string[];
  /** What this means and **what happens when it is wrong**. The latter is the most useful part. */
  note: string;
  /** A concise description of an array or object's internal structure. */
  of?: string;
}

export interface Errs {
  code: number;
  when: string;
}

export type Handler = (
  /** The validated values with defaults applied. **Handlers must not retrieve parameters independently.** */
  arg: Record<string, unknown>,
  req: FastifyRequest,
  reply: FastifyReply,
) => Promise<unknown>;

export interface Route {
  method: "GET" | "POST" | "PUT" | "DELETE";
  /** Path without its prefix, such as `/tasks/:id/messages`. */
  path: string;
  /** Group used to organize help sections. */
  group: string;
  /** One sentence describing the endpoint's operation. */
  does: string;
  /**
   * Why this endpoint exists: **what would happen if a client assembled the operation itself**.
   *
   * This must be substantive. If an endpoint cannot explain this, it probably just exposes database
   * rows unchanged, and clients will eventually bypass it and read tables directly.
   */
  why?: string;
  params?: Param[];
  /** Response example with the **actual structure**, not a type name: clients use it to implement parsing. */
  returns?: unknown;
  errs?: Errs[];
  handler: Handler;
}

class Bad extends Error {
  statusCode = 400;
  constructor(
    message: string,
    readonly at: string,
  ) {
    super(message);
  }
}

function coerce(p: Param, raw: unknown): unknown {
  // Path and query parameters arrive as strings and need conversion to their declared types. Request bodies are already JSON.
  if (p.kind === "string") {
    if (typeof raw !== "string") throw new Bad(`${p.name} must be a string`, p.name);
    return raw;
  }
  if (p.kind === "int" || p.kind === "number") {
    const n = typeof raw === "number" ? raw : Number(String(raw));
    if (!Number.isFinite(n)) throw new Bad(`${p.name} must be a number, got ${JSON.stringify(raw)}`, p.name);
    if (p.kind === "int" && !Number.isInteger(n)) throw new Bad(`${p.name} must be an integer`, p.name);
    return n;
  }
  if (p.kind === "boolean") {
    if (typeof raw === "boolean") return raw;
    const s = String(raw).toLowerCase();
    if (s === "true" || s === "1") return true;
    if (s === "false" || s === "0") return false;
    throw new Bad(`${p.name} must be true or false`, p.name);
  }
  if (p.kind === "array") {
    if (!Array.isArray(raw)) throw new Bad(`${p.name} must be a list`, p.name);
    return raw;
  }
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Bad(`${p.name} must be an object`, p.name);
  }
  return raw;
}

/**
 * Validate a request against its declaration.
 *
 * **Reject undeclared parameters rather than ignoring them.** Otherwise a typo such as
 * `max_units` instead of `maxUnits` would silently produce an unintended result.
 * When rejecting a field, **list the recognized fields**, so callers need not guess its spelling.
 */
export function take(r: Route, req: FastifyRequest): Record<string, unknown> {
  const params = r.params ?? [];
  const out: Record<string, unknown> = {};
  const path = (req.params ?? {}) as Record<string, unknown>;
  const query = (req.query ?? {}) as Record<string, unknown>;
  const body = req.body;

  const bodyParams = params.filter((p) => p.in === "body");
  if (bodyParams.length > 0 && body !== undefined && body !== null) {
    if (typeof body !== "object" || Array.isArray(body)) {
      throw new Bad("the request body must be a JSON object", "body");
    }
  }
  const bag = (body ?? {}) as Record<string, unknown>;

  // Check extra fields in query strings and request bodies. Path segments are already selected by the router.
  const known = new Set(params.map((p) => p.name));
  const qNames = params.filter((p) => p.in === "query").map((p) => p.name);
  for (const k of Object.keys(query)) {
    if (!known.has(k)) {
      throw new Bad(`unknown query parameter ${k}${qNames.length ? ` (known: ${qNames.join(", ")})` : " (this route takes no query parameters)"}`, k);
    }
  }
  const bNames = bodyParams.map((p) => p.name);
  for (const k of Object.keys(bag)) {
    if (!known.has(k)) {
      throw new Bad(`unknown field ${k}${bNames.length ? ` (known: ${bNames.join(", ")})` : " (this route takes no body)"}`, k);
    }
  }

  for (const p of params) {
    const src = p.in === "path" ? path : p.in === "query" ? query : bag;
    const raw = src[p.name];
    if (raw === undefined || raw === null || raw === "") {
      if (p.required) throw new Bad(`${p.name} is missing: ${p.note}`, p.name);
      if (p.def !== undefined) out[p.name] = p.def;
      continue;
    }
    const v = coerce(p, p.in === "path" ? decodeURIComponent(String(raw)) : raw);
    if (p.only && !p.only.includes(String(v))) {
      throw new Bad(`${p.name} must be one of ${p.only.join(" / ")}, got ${JSON.stringify(v)}`, p.name);
    }
    out[p.name] = v;
  }
  return out;
}

// ── Help reads the same declarations as validation ──

function pad(s: string, n: number): string {
  // CJK characters occupy two terminal columns. Account for this to keep the parameter table aligned and readable.
  let w = 0;
  for (const ch of s) w += /[⺀-꓏가-힣豈-﫿︰-﹏＀-｠【】、—]/.test(ch) ? 2 : 1;
  return s + " ".repeat(Math.max(n - w, 1));
}

function paramLine(p: Param): string[] {
  const must = p.required ? "required" : p.def !== undefined ? `default ${JSON.stringify(p.def)}` : "optional";
  // When only a few values are allowed, **listing them is far more useful than a type name**: clients can copy a valid value.
  const kind = p.only ? p.only.join("|") : p.kind;
  const out = [`      ${pad(p.name, 16)}${pad(p.in, 7)}${pad(kind, 20)}${pad(must, 12)}${p.note}`];
  // Put the internal structure on a separate line. A long structure in the type column would
  // push every following column out of alignment and make the table unreadable.
  if (p.of) out.push(`      ${" ".repeat(16)}inside: ${p.of}`);
  return out;
}

/** Terminal-readable documentation: **one curl request explains the API**, without consulting another source. */
export function asText(prefix: string, routes: Route[], q?: string): string {
  const hit = q
    ? routes.filter((r) => (r.path + r.does + r.group).toLowerCase().includes(q.toLowerCase()))
    : routes;
  const out: string[] = [];
  out.push(`TgEngin ${prefix} - ${hit.length} routes${q ? ` (filtered by "${q}", ${routes.length} in total)` : ""}`);
  out.push(`Add ?format=json for the machine-readable form; add ?q=tasks to narrow it down.`);

  const groups = [...new Set(hit.map((r) => r.group))];
  for (const g of groups) {
    out.push("", `[${g}]`);
    for (const r of hit.filter((x) => x.group === g)) {
      out.push("", `  ${pad(r.method, 7)}${pad(prefix + r.path, 34)}${r.does}`);
      if (r.why) out.push(`      why this route exists: ${r.why}`);
      if (r.params?.length) {
        out.push(`      ${pad("name", 16)}${pad("in", 7)}${pad("type", 20)}${pad("given", 12)}note`);
        for (const p of r.params) out.push(...paramLine(p));
      }
      if (r.returns !== undefined) {
        out.push(`      returns: ${JSON.stringify(r.returns, null, 2).split("\n").join("\n      ")}`);
      }
      for (const e of r.errs ?? []) out.push(`      ${e.code}: ${e.when}`);
    }
  }
  return out.join("\n") + "\n";
}

/** Machine-readable documentation from **the same source**, not a second copy. */
export function asJson(prefix: string, routes: Route[]) {
  return {
    prefix,
    count: routes.length,
    routes: routes.map((r) => ({
      method: r.method,
      path: prefix + r.path,
      group: r.group,
      does: r.does,
      why: r.why,
      params: (r.params ?? []).map((p) => ({
        name: p.name,
        in: p.in,
        kind: p.kind,
        of: p.of,
        required: Boolean(p.required),
        def: p.def,
        only: p.only,
        note: p.note,
      })),
      returns: r.returns,
      errs: r.errs ?? [],
    })),
  };
}

/**
 * Install routes and generate `help` from their declarations.
 *
 * **Handlers receive validated parameters with defaults applied.** They must not independently
 * read `req.query` or specify defaults. Defaults hidden inside handlers cannot appear in help,
 * which would make the documented API differ from actual behavior.
 */
export function mount(app: FastifyInstance, prefix: string, routes: Route[]): void {
  for (const r of routes) {
    const wrap = async (req: FastifyRequest, reply: FastifyReply) => {
      let arg: Record<string, unknown>;
      try {
        arg = take(r, req);
      } catch (e) {
        if (e instanceof Bad) {
          // Include endpoint usage in errors so clients can correct a request without separately consulting help.
          return reply.code(400).send({
            error: e.message,
            at: e.at,
            usage: `${r.method} ${prefix}${r.path}`,
            params: (r.params ?? []).map((p) => `${p.name} (${p.in}, ${p.kind}${p.required ? ", required" : ""})`),
          });
        }
        throw e;
      }
      return await r.handler(arg, req, reply);
    };
    if (r.method === "GET") app.get(prefix + r.path, wrap);
    else if (r.method === "POST") app.post(prefix + r.path, wrap);
    else if (r.method === "PUT") app.put(prefix + r.path, wrap);
    else app.delete(prefix + r.path, wrap);
  }

}

/**
 * Install `help` **once, after every endpoint is registered**. Database and kernel routes are
 * registered separately, but help must list all of them. Omitting a group would make clients
 * assume it does not exist and fall back to reading tables.
 */
export function mountHelp(app: FastifyInstance, prefix: string, all: Route[]): void {
  const list = [...all].sort((a, b) => a.group.localeCompare(b.group) || a.path.localeCompare(b.path));
  const help = async (req: FastifyRequest, reply: FastifyReply) => {
    const q = (req.query ?? {}) as { format?: string; q?: string };
    const hit = q.q ? list.filter((r) => (r.path + r.does + r.group).toLowerCase().includes(q.q!.toLowerCase())) : list;
    if (q.format === "json") return asJson(prefix, hit);
    return reply.type("text/plain; charset=utf-8").send(asText(prefix, list, q.q));
  };
  // Show help at the bare prefix too: callers commonly probe a new address to learn what it provides.
  app.get(prefix, help);
  app.get(`${prefix}/help`, help);
}
