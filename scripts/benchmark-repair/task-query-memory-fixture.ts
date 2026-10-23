/** F-only bounded diagnosis. Uses synthetic rows and the real frozen taskRoutes handler. */
import { Database } from "bun:sqlite";
import { heapStats } from "bun:jsc";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { createHash } from "node:crypto";
import { open, plain, type Conn, type Store } from "../../app/src/H2H/db.ts";
import { taskRoutes } from "../../app/src/api/tasks.ts";

const args = process.argv.slice(2);
const directory = resolve(args[0] ?? "");
const shape = args[1];
const lifecycle = args[2];
const count = Number(args[3] ?? 256);
const targetPolls = shape === "full" ? (count <= 256 ? 3 : 1) : 1200;
if (!directory.startsWith(resolve(import.meta.dir, "../../.scratch/task-query-memory-") + "") ||
    !["full", "light", "status"].includes(shape) || !["prepare", "finalize", "source"].includes(lifecycle) ||
    !Number.isInteger(count) || count < 8 || count > 512) throw new Error("invalid F-only fixture arguments");
mkdirSync(directory, { recursive: true });
const dbPath = join(directory, "synthetic.sqlite");
const db = new Database(dbPath, { create: true });
db.exec(`
  create table task(id text primary key, mode text, state text, created_at integer,
    solve_seconds integer, objective integer, readable integer, result text, description text);
  create table task_repair(task text, cycle text, unit integer, node integer,
    from_cycle text, from_unit integer, agent text, instance text, place text,
    at integer, done integer, status text, primary key(task,cycle,unit));
  create table agent(name text primary key, unit text, apis text);
  create table cycle(mode text, cycle text, api_mode text);
  create table api(key_env text, model text, handle text, modes text);
  create table agent_bot_msg(instance text, unit integer, kind text);
  insert into task values('fixture','repair','claimed',1,1800,1,0,null,'Public synthetic fixture');
  insert into agent values('bot','fn:unit.tools','[["SYNTHETIC_KEY","synthetic-model"]]');
  insert into cycle values('repair','ask','chat');
  insert into api values('SYNTHETIC_KEY','synthetic-model','fn:synthetic','chat');
`);
const insert = db.prepare("insert into task_repair values(?,?,?,?,?,?,?,?,?,?,?,?)");
const message = db.prepare("insert into agent_bot_msg values(?,?,?)");
for (let unit = 1; unit <= count; unit++) {
  insert.run("fixture", "ask", unit, unit, unit === 1 ? null : "ask", unit === 1 ? null : unit - 1,
    "bot", "fixture#1", "local", unit, unit < count ? 1 : 0, unit < count ? "dead_failed" : null);
  message.run("fixture#1", unit, "inject");
}
insert.finalize(); message.finalize(); db.close();

function finalized(raw: Database): Conn {
  return {
    exec: sql => raw.exec(sql),
    all(sql, params) {
      const stmt = raw.prepare(sql);
      try { return (stmt.all(...((params ?? []) as never[])) as Record<string, unknown>[]).map(r => plain(r) as Record<string, unknown>); }
      finally { stmt.finalize(); }
    },
    run(sql, params) {
      const stmt = raw.prepare(sql);
      try { const result = stmt.run(...((params ?? []) as never[])); return { changes: Number(result.changes), lastInsertRowid: Number(result.lastInsertRowid) }; }
      finally { stmt.finalize(); }
    },
    close: () => raw.close(),
  };
}
let store: Store;
if (lifecycle !== "finalize") store = open({ db: { file: dbPath, pragmas: { journal_mode: "DELETE", busy_timeout: 1000 } } } as never);
else {
  const rw = finalized(new Database(dbPath));
  const ro = finalized(new Database(dbPath, { readonly: true }));
  store = { file: dbPath, rw, ro, close() { ro.close(); rw.close(); } };
}
const actual = store.ro.all.bind(store.ro);
let queries = 0, chainSteps = 0;
const distinctSql = new Set<string>();
const safetyBytes = 448 * 1024 * 1024;
class NativeMemoryGuard extends Error {}
store.ro.all = (sql, params) => {
  queries++;
  if (sql.includes("select task, cycle, unit, from_cycle, from_unit")) chainSteps++;
  distinctSql.add(sql);
  if ((queries & 127) === 0 && process.memoryUsage().rss > safetyBytes) throw new NativeMemoryGuard("native_rss_guard_448MiB");
  if (queries % 4096 === 0) console.log(JSON.stringify({ event: "query_progress", ...sample() }));
  return actual(sql, params);
};
const registry = { has: () => true, get: () => ({ expectMs: 120000 }) };
const routes = taskRoutes(store, registry as never, {} as never, () => {});
const route = routes.find(r => r.method === "GET" && r.path === "/tasks/:id")!;
const statusRoute = routes.find(r => r.method === "GET" && r.path === "/tasks/:id/status");
const reply = { code() { return this; }, send(value: unknown) { return value; } };
const started = performance.now();
const samples: Record<string, unknown>[] = [];
let polls = 0, responseBytes = 0, outcome = "bounded_complete", error: string | undefined;
function sample() {
  const memory = process.memoryUsage();
  const stats = heapStats();
  return { poll: polls, elapsedMs: performance.now() - started, queries, chainSteps,
    rssBytes: memory.rss, heapUsedBytes: memory.heapUsed, heapTotalBytes: memory.heapTotal,
    externalBytes: memory.external, jscHeapSizeBytes: stats.heapSize, jscObjectCount: stats.objectCount,
    responseBytes };
}
samples.push(sample());
try {
  while (performance.now() - started < 24000 && polls < targetPolls) {
    const result = shape === "full"
      ? await route.handler({ id: "fixture" }, undefined as never, reply as never)
      : shape === "status"
      ? await statusRoute!.handler({ id: "fixture" }, undefined as never, reply as never)
      : store.ro.all("select state,result from task where id = ?", ["fixture"])[0];
    responseBytes += Buffer.byteLength(JSON.stringify(result));
    polls++;
    if (polls < 5 || polls % 25 === 0) { const point = sample(); samples.push(point); console.log(JSON.stringify({ event: "sample", ...point })); }
    if (process.memoryUsage().rss > safetyBytes) { outcome = "native_rss_guard"; break; }
    if (polls % 10 === 0) await Bun.sleep(0);
  }
} catch (failure) {
  error = failure instanceof Error ? failure.message : String(failure);
  outcome = error.includes("native_rss_guard") ? "native_rss_guard" : "runtime_error";
} finally {
  samples.push(sample());
  const result = { schemaVersion: 1, diagnosticOnly: true, modelCalls: 0, originalDatabaseOpened: false,
    shape, lifecycle, count, runtime: { version: Bun.version, executable: process.execPath },
    outcome, error, polls, targetPolls, queries, chainSteps, distinctSql: distinctSql.size,
    singleLinearTreeExpectedFullQueries: 3 + 5 * count + count * (count - 1) / 2,
    responseBytes, elapsedMs: performance.now() - started, safety: { internalRssStopBytes: safetyBytes, parentLimitBytes: 512 * 1024 * 1024 },
    samples, sources: ["app/src/api/tasks.ts", "app/src/H2H/db.ts", "app/src/engine/chain.ts"].map(path => ({
      path, sha256: createHash("sha256").update(readFileSync(resolve(import.meta.dir, "../..", path))).digest("hex") })),
    limits: ["Synthetic worst-case linear ancestry, not a replay of CMT or a reproduced original 500",
      "Light handler is a proposed status projection fixture, not a change to the frozen taskRoutes API",
      "Finalize arm only changes statement lifetime in its private Conn; source/prepare import the real open() bound by recorded source SHA",
      "Status arm calls the real independent /tasks/:id/status handler; no HTTP or original engine"] };
  writeFileSync(join(directory, "result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ event: "result", ...result, samples: undefined }));
  store.close();
}
