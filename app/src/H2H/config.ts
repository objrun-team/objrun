/**
 * Read `config.yaml`.
 *
 * **This is the only place that locates files for the application.** Other modules must not
 * resolve paths by walking upward from their source file. Once compiled into one executable,
 * source locations are virtual paths inside the bundle and those relative paths no longer work.
 *
 * Fail immediately on missing keys and name the missing key. Silently applying defaults would
 * let an incorrectly configured system keep running, producing the hard-to-diagnose complaint:
 * "I changed the configuration, but nothing happened."
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";

import { parse } from "yaml";

/**
 * Find the configuration file in exactly two steps:
 *
 * 1. **The executable's own directory.** An installed `config.yaml` lives here without extra setup.
 * 2. Only if it is absent there, consult `TGENGIN_CONFIG`.
 *
 * Stop immediately if neither works. **Do not search parent directories or try a third location.**
 * Loading the wrong configuration may produce no error, just a machine that appears to contain
 * nothing, which is particularly difficult to diagnose.
 */
export function findConfig(): string {
  const beside = resolve(dirname(process.execPath), "config.yaml");
  if (existsSync(beside)) return beside;

  const given = process.env.TGENGIN_CONFIG;
  if (!given) {
    throw new Error(`config.yaml not found: not next to ${beside}, and TGENGIN_CONFIG was not set`);
  }
  const file = resolve(given);
  if (!existsSync(file)) throw new Error(`the file TGENGIN_CONFIG points at does not exist: ${file}`);
  return file;
}

export interface Config {
  file: string;
  server: { host: string; port: number; bodyLimit: number; shutdownTimeout: number };
  log: { level: string };
  db: { file: string; sealed: string; pragmas: Record<string, string | number> };
  api: {
    prefix: string;
    token: string | null;
    /**
     * **Who may attach objectives.** When configured, publishing tasks with an objective through
     * `/tasks` or `/bench` requires `X-TGEngin-Publisher: <token>`; otherwise return 403. If unset,
     * preserve the old behavior: callers declare their own source, and anyone who can reach the
     * API may attach an objective. Startup warns about this. `TGENGIN_PUBLISHER_TOKEN` takes priority.
     * The solver's tools must not be able to read this token through environment variables, readable
     * files, or reachable ports; otherwise the protection is ineffective.
     */
    publisherToken: string | null;
    allowQuery: boolean;
    allowWrite: boolean;
    maxRows: number;
    defaultLimit: number;
  };
  cors: { enabled: boolean; origin: string | string[] };
  /**
   * Model-call settings. **One configuration per machine, not per agent.** If per-agent settings
   * are needed, extend `agent.apis`, which is already JSON.
   */
  llm: {
    /** Maximum output tokens for **one call**, not for an execution unit: truncated calls are continued. */
    maxTokens: number;
    /** Maximum retries after a failed call, waiting an additional 5 seconds each time. 0 disables retries. */
    retryTimes: number;
    /** Maximum continuations after truncation. 0 disables continuation. */
    continueTimes: number;
    /** Reasoning effort, passed through unchanged. The provider decides whether it supports the value. */
    reasoningEffort: string;
    /** Sampling temperature. 0 makes a run reproducible. */
    temperature: number;
    /** Sampling seed. Only some vendors honour it; harmless where they do not. */
    seed: number;
  };
}

/** Resolve `${VAR}` from the environment. Missing variables become empty strings; consumers decide whether a value is required. */
function expand(v: unknown): unknown {
  if (typeof v !== "string") return v;
  return v.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (_, k) => process.env[k] ?? "");
}

function at(doc: unknown, path: string): unknown {
  let cur: unknown = doc;
  for (const k of path.split(".")) {
    if (cur === null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[k];
  }
  return expand(cur);
}

function str(doc: unknown, path: string): string {
  const v = at(doc, path);
  if (typeof v !== "string" || v === "") throw new Error(`config.yaml: ${path} must be a non-empty string`);
  return v;
}

function num(doc: unknown, path: string): number {
  const v = at(doc, path);
  if (typeof v !== "number" || !Number.isFinite(v)) throw new Error(`config.yaml: ${path} must be a number`);
  return v;
}

function bool(doc: unknown, path: string): boolean {
  const v = at(doc, path);
  if (typeof v !== "boolean") throw new Error(`config.yaml: ${path} must be true or false`);
  return v;
}


export function readConfig(file = findConfig()): Config {
  const doc: unknown = parse(readFileSync(file, "utf8"));
  if (doc === null || typeof doc !== "object") throw new Error(`config.yaml is empty: ${file}`);

  const near = (p: string) => (isAbsolute(p) ? p : resolve(dirname(file), p));

  const pragmasRaw = at(doc, "db.pragmas");
  if (pragmasRaw === null || typeof pragmasRaw !== "object") {
    throw new Error("config.yaml: db.pragmas must be a key/value map");
  }
  const pragmas: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(pragmasRaw as Record<string, unknown>)) {
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(k)) throw new Error(`config.yaml: illegal PRAGMA name - ${k}`);
    if (typeof v !== "string" && typeof v !== "number") {
      throw new Error(`config.yaml: PRAGMA ${k} must be a string or a number`);
    }
    pragmas[k] = v;
  }

  const prefix = str(doc, "api.prefix");
  if (!prefix.startsWith("/")) throw new Error("config.yaml: api.prefix must start with /");

  const token = at(doc, "api.token");
  const publisher = process.env.TGENGIN_PUBLISHER_TOKEN ?? at(doc, "api.publisherToken");
  const origin = at(doc, "cors.origin");
  if (typeof origin !== "string" && !Array.isArray(origin)) {
    throw new Error('config.yaml: cors.origin must be "*" or a list of origins');
  }

  return {
    file,
    server: {
      host: str(doc, "server.host"),
      port: num(doc, "server.port"),
      bodyLimit: num(doc, "server.bodyLimit"),
      shutdownTimeout: num(doc, "server.shutdownTimeout"),
    },
    log: { level: str(doc, "log.level") },
    db: { file: near(str(doc, "db.file")), sealed: near(str(doc, "db.sealed")), pragmas },
    api: {
      prefix: prefix === "/" ? "" : prefix.replace(/\/$/, ""),
      token: typeof token === "string" && token !== "" ? token : null,
      publisherToken: typeof publisher === "string" && publisher !== "" ? publisher : null,
      allowQuery: bool(doc, "api.allowQuery"),
      allowWrite: bool(doc, "api.allowWrite"),
      maxRows: num(doc, "api.maxRows"),
      defaultLimit: num(doc, "api.defaultLimit"),
    },
    cors: { enabled: bool(doc, "cors.enabled"), origin: origin as string | string[] },
    llm: {
      maxTokens: num(doc, "llm.maxTokens"),
      retryTimes: num(doc, "llm.retryTimes"),
      continueTimes: num(doc, "llm.continueTimes"),
      reasoningEffort: str(doc, "llm.reasoningEffort"),
      temperature: num(doc, "llm.temperature"),
      seed: num(doc, "llm.seed"),
    },
  };
}
