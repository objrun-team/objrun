import {mkdtempSync,rmSync,writeFileSync,readFileSync} from 'node:fs';import {tmpdir} from 'node:os';import {join,resolve} from 'node:path';import {spawn,type ChildProcess} from 'node:child_process';import {verifyPin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';const ROOT=resolve(import.meta.dir,'../../../..');
async function freePort():Promise<number>{const s=Bun.serve({port:0,fetch:()=>new Response('')});const p=s.port;await s.stop(true);if(p===undefined)throw Error('No port');return p;}
export interface Machine {
  /** PID of the actual Bun engine, rather than a package-manager shim. */
  pid: number;
  /** Call an endpoint. On 4xx/5xx, throw the server message verbatim; it is the most useful diagnostic in these examples. */
  api<T = unknown>(method: string, path: string, body?: unknown): Promise<T>;
  /** Call an endpoint, **expecting failure**, and return the server's JSON response. */
  bad(method: string, path: string, body?: unknown): Promise<Record<string, unknown>>;
  base: string;
  directory: string;
  stop(): Promise<void>;
}

/** Start a temporary engine. */
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
      // A missing `config.yaml` key fails immediately by design, so this must track Config.
      // A missing key prevents startup, while `machine()` keeps waiting and looks like a hung test.
      // Examples can override individual settings, such as setting `retryTimes` to 0 so that
      // connection-failure scenarios finish in seconds instead of waiting through three backoffs.
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
      // Not ready yet; keep waiting.
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
        // Windows may still hold the database file open; leave it in the temporary directory.
      }
    },
  };
}