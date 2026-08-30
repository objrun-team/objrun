/**
 * 例子共用的那点脚手架。
 *
 * ## 每个例子自带一台机器
 *
 * `bun examples/xxx.ts` 一条命令就跑完：起一台**临时的**引擎（临时配置、临时库），
 * 跑完连库带配置一起扔。不碰你正在用的那个库 —— 例子把库搅乱了，比例子跑不起来
 * 更难查。
 *
 * ## 例子里**不打模型**
 *
 * 一个周期的 `apiMode` 留空，内核就调 `agent.unit`；而 `unit` 可以是一条
 * **外部 `http://` 句柄**。于是整条流程都由例子自己那台小服务器接管：
 *
 * - 不花钱、不看网络、每次结果一样
 * - 而且顺带验了一件更要紧的事：**外面确实能往里加东西**。
 *   例子里注册的每一样都是从进程外接进来的，一行内核代码没改
 *
 * ## 两部分
 *
 * 每个例子分成 **注册** 和 **使用层次的校验**：
 *
 * - 注册：能不能声明进去，声明错了报得清不清楚
 * - 使用：声明进去之后**真跑一趟**，看它到底生没生效
 *
 * 只验第一部分是不够的：这台机器最典型的毛病就是「写进去了，但永远不触发」——
 * 注册成功和真的生效，是两件事。
 */

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";

const ROOT = join(import.meta.dir, "..");

/** 找一个没人用的端口：开一个、记下号、关掉。 */
async function freePort(): Promise<number> {
  const s = Bun.serve({ port: 0, fetch: () => new Response("") });
  const p = s.port;
  await s.stop(true);
  if (p === undefined) throw new Error("要不到一个空闲端口");
  return p;
}

export interface Machine {
  /** 打一个口。4xx/5xx 会把服务端说的话原样抛出来 —— 例子里最有用的就是那句话。 */
  api<T = unknown>(method: string, path: string, body?: unknown): Promise<T>;
  /** 打一个口，**期待它失败**，把服务端回的那份 JSON 拿回来。 */
  bad(method: string, path: string, body?: unknown): Promise<Record<string, unknown>>;
  base: string;
  stop(): void;
}

/** 起一台临时引擎。 */
export async function machine(): Promise<Machine> {
  const dir = mkdtempSync(join(tmpdir(), "tgengin-example-"));
  const port = await freePort();
  writeFileSync(
    join(dir, "config.yaml"),
    [
      `server: { host: 127.0.0.1, port: ${port}, bodyLimit: 1048576, shutdownTimeout: 2000 }`,
      `log: { level: warn }`,
      `db: { file: ./data/h2h.sqlite, sealed: ./data/sealed.sqlite,`,
      `      pragmas: { journal_mode: WAL, synchronous: NORMAL, foreign_keys: ON, busy_timeout: 5000 } }`,
      `api: { prefix: /api, token: , allowQuery: true, allowWrite: true, maxRows: 500, defaultLimit: 100 }`,
      // `config.yaml` 缺一个键就当场炸（那是故意的），所以这儿得跟着 Config 走 ——
      // 漏了的表现是引擎起不来，而 `machine()` 只会一直等，看着像测试挂死。
      `llm: { maxTokens: 16384, retryTimes: 3, continueTimes: 3, reasoningEffort: high }`,
      `cors: { enabled: false, origin: "*" }`,
      "",
    ].join("\n"),
    "utf8",
  );

  const proc: ChildProcess = spawn(
    "bun",
    [`--env-file=${join(ROOT, ".env")}`, join(ROOT, "app", "src", "main.ts")],
    { env: { ...process.env, TGENGIN_CONFIG: join(dir, "config.yaml") }, stdio: ["ignore", "pipe", "pipe"] },
  );
  let log = "";
  proc.stdout?.on("data", (d: Buffer) => (log += d.toString()));
  proc.stderr?.on("data", (d: Buffer) => (log += d.toString()));

  const base = `http://127.0.0.1:${port}/api`;
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${base}/health`)).ok) break;
    } catch {
      // 还没起来，再等
    }
    if (i === 99) {
      proc.kill();
      throw new Error(`引擎没起来。它说：\n${log}`);
    }
    await Bun.sleep(100);
  }

  const call = async (method: string, path: string, body?: unknown) => {
    const res = await fetch(base + path, {
      method,
      ...(body === undefined ? {} : { headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
    });
    const text = await res.text();
    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      json = text;
    }
    return { res, json };
  };

  return {
    base,
    async api<T>(method: string, path: string, body?: unknown): Promise<T> {
      const { res, json } = await call(method, path, body);
      if (!res.ok) throw new Error(`${method} ${path} → ${res.status}\n${JSON.stringify(json, null, 2)}`);
      return json as T;
    },
    async bad(method: string, path: string, body?: unknown) {
      const { res, json } = await call(method, path, body);
      if (res.ok) throw new Error(`${method} ${path} 本该被拒，却回了 ${res.status}`);
      return json as Record<string, unknown>;
    },
    stop() {
      proc.kill();
      try {
        rmSync(dir, { recursive: true, force: true });
      } catch {
        // Windows 上库文件可能还被占着，扔在临时目录里就是了
      }
    },
  };
}

// ── 例子自己那台小服务器：把句柄接进来 ──────────────────────────────────────

/** 一条外部句柄：内核 POST 过来一份 JSON，回一份 JSON。 */
export type Impl = (arg: Record<string, unknown>) => unknown | Promise<unknown>;

export interface Outside {
  /** 这台小服务器的地址前缀，拼上路径就是句柄名。 */
  url(path: string): string;
  /** 每条句柄被调了几次、最后一次收到什么 —— 「它到底生效没有」就靠这个。 */
  calls: Record<string, Record<string, unknown>[]>;
  stop(): void;
}

/**
 * 起一台小服务器，把几条句柄挂上去。
 *
 * **这就是「外面往里加东西」那条路**：注册一条 `http://` 句柄，往库里写一行，
 * 内核下一圈醒来自己给它合成调用器 —— 不用碰内核代码，也不用重启。
 */
export async function outside(impls: Record<string, Impl>): Promise<Outside> {
  const calls: Record<string, Record<string, unknown>[]> = {};
  for (const k of Object.keys(impls)) calls[k] = [];

  const server = Bun.serve({
    port: 0,
    async fetch(req) {
      const path = new URL(req.url).pathname;
      const impl = impls[path];
      if (!impl) return new Response(JSON.stringify({ error: `这台小服务器没有 ${path}` }), { status: 404 });
      let arg: Record<string, unknown> = {};
      try {
        arg = (await req.json()) as Record<string, unknown>;
      } catch {
        // 空 body 也算一次调用
      }
      calls[path].push(arg);
      const out = await impl(arg);
      return new Response(JSON.stringify(out ?? null), { headers: { "content-type": "application/json" } });
    },
  });

  return {
    url: (path) => `http://127.0.0.1:${server.port}${path}`,
    calls,
    stop: () => void server.stop(true),
  };
}

// ── 说话和记分 ──────────────────────────────────────────────────────────────

let bad = 0;
let total = 0;

export function part(title: string): void {
  console.log(`\n━━ ${title} ━━`);
}

export function step(title: string): void {
  console.log(`\n${title}`);
}

export function ok(what: string, cond: boolean, saw?: unknown): void {
  total++;
  if (cond) {
    console.log(`  ✓ ${what}`);
    return;
  }
  bad++;
  console.log(`  ✗ ${what}${saw === undefined ? "" : `\n      实际拿到：${JSON.stringify(saw)}`}`);
}

/** 把一段（多半是错误信息）缩进打出来，例子里最值钱的往往就是这段话。 */
export function show(label: string, v: unknown): void {
  const s = typeof v === "string" ? v : JSON.stringify(v, null, 2);
  console.log(`  ${label}\n${s.split("\n").map((l) => "      " + l).join("\n")}`);
}

export function done(): never {
  console.log(bad === 0 ? `\n全过（${total} 条）。` : `\n${bad}/${total} 条没过。`);
  process.exit(bad === 0 ? 0 : 1);
}

/** 等到某件事成立。到点还不成立就把最后看到的东西一起抛出来。 */
export async function until<T>(what: string, f: () => Promise<T | null>, ms = 20_000): Promise<T> {
  const t0 = Date.now();
  let last: unknown = null;
  while (Date.now() - t0 < ms) {
    const v = await f();
    if (v !== null) return v;
    last = v;
    await Bun.sleep(200);
  }
  throw new Error(`等 ${what} 等了 ${ms}ms 还没成，最后看到的是 ${JSON.stringify(last)}`);
}
