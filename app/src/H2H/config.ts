/**
 * 读 `config.yaml`。
 *
 * **这是整台机器唯一一处认路的地方。** 别处不许出现「相对我这个源文件
 * 往上几层」那种写法 —— 打包成单文件之后，源文件的位置是包里的虚拟路径，
 * 那种写法一律失效。
 *
 * 缺了的键当场炸，并且说得出缺的是哪个 —— 悄悄套个默认值的话，
 * 配置写错了系统照常跑，那是最难查的一类（「我明明改了」）。
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";

import { parse } from "yaml";

/**
 * 配置文件在哪儿，只有两步：
 *
 *   1. **程序自己所在的目录** —— 装完之后 `config.yaml` 就躺在这儿，不用配任何东西
 *   2. 上一步没有，才读 `TGENGIN_CONFIG`
 *
 * 两步都不成就当场停。**不往上找、不试第三个地方** —— 找错配置不报错，
 * 只是那台机器看起来「什么都没有」，而那是最难查的一类。
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
    allowQuery: boolean;
    allowWrite: boolean;
    maxRows: number;
    defaultLimit: number;
  };
  cors: { enabled: boolean; origin: string | string[] };
  /**
   * 调模型时那几个旋钮。**这台机器一份，不按智能体分** —— 要按智能体分的时候
   * 再往 `agent.apis` 那一列上加，那一列本来就是 JSON。
   */
  llm: {
    /** **一次调用**最多生成多少 token。不是一个执行单元的上限 —— 截断了会续写。 */
    maxTokens: number;
    /** 一次调用炸了之后最多重打几次，每次多等 5 秒。0 = 不重打。 */
    retryTimes: number;
    /** 截断之后最多再续几次。0 = 不续。 */
    continueTimes: number;
    /** 思考强度。原样发给那家 —— 认不认得是那家的事，我们不替它猜。 */
    reasoningEffort: string;
  };
}

/** `${VAR}` 从环境变量取。取不到就是空 —— 由用它的地方去判缺不缺。 */
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
    },
  };
}
