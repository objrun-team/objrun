import {mkdtempSync,rmSync,writeFileSync,readFileSync} from 'node:fs';import {tmpdir} from 'node:os';import {join,resolve} from 'node:path';import {spawn,type ChildProcess} from 'node:child_process';import {verifyPin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';const ROOT=resolve(import.meta.dir,'../../../..');
async function freePort():Promise<number>{const s=Bun.serve({port:0,fetch:()=>new Response('')});const p=s.port;await s.stop(true);if(p===undefined)throw Error('No port');return p;}
export interface Machine {
  /** PID of the actual Bun engine, rather than a package-manager shim. */
  pid: number;
  /** 打一个口。4xx/5xx 会把服务端说的话原样抛出来 —— 例子里最有用的就是那句话。 */
  api<T = unknown>(method: string, path: string, body?: unknown): Promise<T>;
  /** 打一个口，**期待它失败**，把服务端回的那份 JSON 拿回来。 */
  bad(method: string, path: string, body?: unknown): Promise<Record<string, unknown>>;
  base: string;
  directory: string;
  stop(): Promise<void>;
}

/** 起一台临时引擎。 */
export async function machine(llm: Record<string, string | number> = {}, options: { directory?: string; keep?: boolean } = {}): Promise<Machine> {
  const dir = options.directory ?? mkdtempSync(join(tmpdir(), "tgengin-example-"));
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
      // 例子可以顶掉其中几个 —— 比如把 `retryTimes` 调成 0，好让「打不通会怎样」
      // 这一类的例子几秒钟跑完，而不是干等三轮退避。
      `llm: { ${Object.entries({
        maxTokens: 16384,
        retryTimes: 3,
        continueTimes: 3,
        reasoningEffort: "high",
        temperature: 0,
        seed: 42,
        ...llm,
      })
        .map(([k, v]) => `${k}: ${String(v)}`)
        .join(", ")} }`,
      `cors: { enabled: false, origin: "*" }`,
      "",
    ].join("\n"),
    "utf8",
  );

  const proc: ChildProcess = spawn(
    process.execPath,
    [`--env-file=${join(ROOT, ".env")}`, (()=>{const proof=JSON.parse(readFileSync(join(ROOT,'docs/repair-2026-10-10/full-f-rerun/chemiq/submit-retry-build-current.json'),'utf8'));for(const pin of proof.files)verifyPin(pin);return proof.executable.path;})()],
    { env: { ...process.env, TGENGIN_CONFIG: join(dir, "config.yaml") }, stdio: ["ignore", "pipe", "pipe"], windowsHide: true },
  );
  const enginePid = proc.pid;
  if (enginePid === undefined) throw new Error("the test engine did not obtain a process ID");
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
      throw new Error(`the engine did not come up. It said:\n${log}`);
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
    pid: enginePid,
    base,
    directory: dir,
    async api<T>(method: string, path: string, body?: unknown): Promise<T> {
      const { res, json } = await call(method, path, body);
      if (!res.ok) throw new Error(`${method} ${path} → ${res.status}\n${JSON.stringify(json, null, 2)}`);
      return json as T;
    },
    async bad(method: string, path: string, body?: unknown) {
      const { res, json } = await call(method, path, body);
      if (res.ok) throw new Error(`${method} ${path} should have been rejected, but returned ${res.status}`);
      return json as Record<string, unknown>;
    },
    async stop() {
      if (proc.exitCode === null && proc.signalCode === null) {
        await new Promise<void>(resolve => {
          const hard = setTimeout(() => { proc.kill("SIGKILL"); }, 3000);
          proc.once("exit", () => { clearTimeout(hard); resolve(); });
          proc.kill();
        });
      }
      if (options.keep) return;
      try {
        rmSync(dir, { recursive: true, force: true });
      } catch {
        // Windows 上库文件可能还被占着，扔在临时目录里就是了
      }
    },
  };
}