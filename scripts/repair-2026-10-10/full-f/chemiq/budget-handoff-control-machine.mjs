import { mkdtempSync, rmSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawn } from "node:child_process";
import { verifyPin } from "../../../repair-2026-10-08/paid-resource-proof-v2.ts";
const ROOT = resolve(import.meta.dir, "../../../..");
async function freePort() {
  const s = Bun.serve({ port: 0, fetch: () => new Response("") });
  const p = s.port;
  await s.stop(true);
  if (p === undefined)
    throw Error("No port");
  return p;
}
export async function machine(llm = {}, options = {}) {
  const dir = options.directory ?? mkdtempSync(join(tmpdir(), "tgengin-example-"));
  const port = await freePort();
  writeFileSync(join(dir, "config.yaml"), [
    `server: { host: 127.0.0.1, port: ${port}, bodyLimit: 1048576, shutdownTimeout: 2000 }`,
    `log: { level: warn }`,
    `db: { file: ./data/h2h.sqlite, sealed: ./data/sealed.sqlite,`,
    `      pragmas: { journal_mode: WAL, synchronous: NORMAL, foreign_keys: ON, busy_timeout: 5000 } }`,
    `api: { prefix: /api, token: , allowQuery: true, allowWrite: true, maxRows: 500, defaultLimit: 100 }`,
    `llm: { ${Object.entries({
      maxTokens: 16384,
      retryTimes: 3,
      continueTimes: 3,
      reasoningEffort: "high",
      temperature: 0,
      seed: 42,
      ...llm
    }).map(([k, v]) => `${k}: ${String(v)}`).join(", ")} }`,
    `cors: { enabled: false, origin: "*" }`,
    ""
  ].join(`
`), "utf8");
  const proc = spawn(process.execPath, [`--env-file=${join(ROOT, ".env")}`, (() => {
    const proof = JSON.parse(readFileSync("F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\docs\\repair-2026-10-10\\full-f-rerun\\chemiq\\budget-handoff-staging\\1791702044567\\build-proof.json", "utf8"));
    for (const pin of proof.files)
      verifyPin(pin);
    return proof.executable.path;
  })()], { env: { ...process.env, TGENGIN_CONFIG: join(dir, "config.yaml") }, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  const enginePid = proc.pid;
  if (enginePid === undefined)
    throw new Error("the test engine did not obtain a process ID");
  let log = "";
  proc.stdout?.on("data", (d) => log += d.toString());
  proc.stderr?.on("data", (d) => log += d.toString());
  const base = `http://127.0.0.1:${port}/api`;
  for (let i = 0;i < 100; i++) {
    try {
      if ((await fetch(`${base}/health`)).ok)
        break;
    } catch {}
    if (i === 99) {
      proc.kill();
      throw new Error(`the engine did not come up. It said:
${log}`);
    }
    await Bun.sleep(100);
  }
  const call = async (method, path, body) => {
    const res = await fetch(base + path, {
      method,
      ...body === undefined ? {} : { headers: { "content-type": "application/json" }, body: JSON.stringify(body) }
    });
    const text = await res.text();
    let json;
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
    async api(method, path, body) {
      const { res, json } = await call(method, path, body);
      if (!res.ok)
        throw new Error(`${method} ${path} → ${res.status}
${JSON.stringify(json, null, 2)}`);
      return json;
    },
    async bad(method, path, body) {
      const { res, json } = await call(method, path, body);
      if (res.ok)
        throw new Error(`${method} ${path} should have been rejected, but returned ${res.status}`);
      return json;
    },
    async stop() {
      if (proc.exitCode === null && proc.signalCode === null) {
        await new Promise((resolve) => {
          const hard = setTimeout(() => {
            proc.kill("SIGKILL");
          }, 3000);
          proc.once("exit", () => {
            clearTimeout(hard);
            resolve();
          });
          proc.kill();
        });
      }
      if (options.keep)
        return;
      try {
        rmSync(dir, { recursive: true, force: true });
      } catch {}
    }
  };
}
