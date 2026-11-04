import { expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Registry } from "../../app/src/engine/registry.ts";
import type { Conn } from "../../app/src/H2H/db.ts";
import { install } from "../../app/src/install/index.ts";
import { registerTools } from "../../app/src/tools/register.ts";

const FAKE_TOKEN = "local-test-grader-token";

async function withAuth(origins: string | undefined, work: () => Promise<void>) {
  const oldToken = process.env.TGENGIN_GRADER_TOKEN;
  const oldOrigins = process.env.TGENGIN_GRADER_ORIGINS;
  process.env.TGENGIN_GRADER_TOKEN = FAKE_TOKEN;
  if (origins === undefined) delete process.env.TGENGIN_GRADER_ORIGINS;
  else process.env.TGENGIN_GRADER_ORIGINS = origins;
  try { await work(); }
  finally {
    if (oldToken === undefined) delete process.env.TGENGIN_GRADER_TOKEN; else process.env.TGENGIN_GRADER_TOKEN = oldToken;
    if (oldOrigins === undefined) delete process.env.TGENGIN_GRADER_ORIGINS; else process.env.TGENGIN_GRADER_ORIGINS = oldOrigins;
  }
}

function remote(url: string) {
  const raw = new Database(":memory:");
  raw.exec("create table handle(name text,expect_ms integer,module text)");
  raw.query("insert into handle values(?,1000,null)").run(url);
  const db: Conn = { all: (sql, args) => raw.query(sql).all(...((args ?? []) as never[])) as Record<string, unknown>[], exec: sql => raw.exec(sql), run() { throw new Error("read-only fixture"); }, close: () => raw.close() };
  const reg = new Registry();
  reg.sync(db);
  return { db, call: () => reg.get(url).call({ input: { task: { id: "test", result: "answer" } } }) };
}

test("the registered HTTP grading path authenticates only an explicitly trusted origin", async () => {
  const received: (string | null)[] = [];
  const grader = Bun.serve({ port: 0, async fetch(request) { received.push(request.headers.get("X-ObjRun-Grader-Token")); return Response.json(true); } });
  const base = `http://127.0.0.1:${grader.port}`;
  const f = remote(`${base}/grade`);
  try {
    await withAuth(base, async () => { expect(await f.call()).toBe(true); });
    await withAuth("http://127.0.0.1:1", async () => { expect(await f.call()).toBe(true); });
    expect(received).toEqual([FAKE_TOKEN, null]);
  } finally { f.db.close(); await grader.stop(true); }
});

test("a configured token with no origin refuses before any HTTP request", async () => {
  let requests = 0;
  const grader = Bun.serve({ port: 0, fetch() { requests++; return Response.json(true); } });
  const f = remote(`http://127.0.0.1:${grader.port}/grade`);
  try {
    await withAuth(undefined, async () => {
      await expect(f.call()).rejects.toThrow("TGENGIN_GRADER_ORIGINS");
    });
    expect(requests).toBe(0);
  } finally { f.db.close(); await grader.stop(true); }
});

test("an authenticated grader redirect never forwards the secret to another origin", async () => {
  let leaked = false;
  const sink = Bun.serve({ port: 0, fetch(request) { leaked = request.headers.has("X-ObjRun-Grader-Token"); return Response.json(true); } });
  const grader = Bun.serve({ port: 0, fetch() { return Response.redirect(`http://127.0.0.1:${sink.port}/capture`, 302); } });
  const base = `http://127.0.0.1:${grader.port}`;
  const f = remote(`${base}/grade`);
  try {
    await withAuth(base, async () => { await expect(f.call()).rejects.toThrow(); });
    expect(leaked).toBe(false);
  } finally { f.db.close(); await grader.stop(true); await sink.stop(true); }
});

test("a filesystem tool forwarded through workplace.identity authenticates the protected /place route", async () => {
  const receipts: { token: string | null; body: unknown }[] = [];
  const stand = Bun.serve({ port: 0, async fetch(request) {
    const token = request.headers.get("X-ObjRun-Grader-Token");
    receipts.push({ token, body: await request.json() });
    return token === FAKE_TOKEN ? Response.json({ content: "fixture file" }) : Response.json({ error: "unauthorized grader caller" }, { status: 403 });
  } });
  const base = `http://127.0.0.1:${stand.port}`;
  const raw = new Database(":memory:");
  const db: Conn = { all: (sql, args) => raw.query(sql).all(...((args ?? []) as never[])) as Record<string, unknown>[], exec: sql => raw.exec(sql), run: (sql, args) => { const result = raw.query(sql).run(...((args ?? []) as never[])); return { changes: Number(result.changes), lastInsertRowid: Number(result.lastInsertRowid) }; }, close: () => raw.close() };
  install(db);
  db.run("insert into handle(name,expect_ms,module) values(?,1000,null)", [`${base}/place`]);
  db.run("insert into workplace(place,identity,forward,tools,usable) values(?,?,1,?,1)", ["container-fixture", `${base}/place`, JSON.stringify([{ tool: "read", policy: "always" }])]);
  const reg = new Registry();
  registerTools(db, reg);
  reg.sync(db);
  const read = () => reg.get("fn:tool.read").call({ place: "container-fixture", args: { file_path: "/workspace/fixture.txt" } });
  try {
    await withAuth(base, async () => { expect(await read()).toEqual({ content: "fixture file" }); });
    await withAuth("http://127.0.0.1:1", async () => { await expect(read()).rejects.toThrow("403"); });
    expect(receipts.map(receipt => receipt.token)).toEqual([FAKE_TOKEN, null]);
    expect(receipts[0]?.body).toMatchObject({ place: "container-fixture", op: "call", tool: "read" });
    expect(JSON.stringify(receipts.map(receipt => receipt.body))).not.toContain(FAKE_TOKEN);
  } finally { db.close(); await stand.stop(true); }
});

async function offline(grader: string, origins: string, storedOutcome?: string) {
  const directory = mkdtempSync(join(tmpdir(), "tgengin-u-auth-"));
  const file = join(directory, "fixture.sqlite");
  const db = new Database(file);
  db.exec("create table task(id text,mode text,run text,created_at integer,solve_seconds integer,state text,result text); create table cycle(mode text,cycle text); create table task_demo(task text,agent text,instance text,unit integer,at integer); create table agent_bot_msg(instance text,unit integer,seq integer,kind text,body text,at integer); insert into task values('t','demo','u-test',1000,10,'done',null); insert into cycle values('demo','submit'); insert into task_demo values('t','bot','t#1',1,1000)");
  if (storedOutcome) db.query("update task set state='failed',result=? where id='t'").run(JSON.stringify({ pass: 0, valid: false, outcome: storedOutcome, why: "test infrastructure fault" }));
  db.query("insert into agent_bot_msg values('t#1',1,1,'call',?,1500)").run(JSON.stringify({ calls: [{ name: "submit", input: { answer: "answer" } }] }));
  db.close();
  writeFileSync(join(directory, "G.json"), JSON.stringify({ grader_port: 1, nodes: [{ name: "grade", moment: "task_done", domain: "bool", handle: "{GRADER}/grade" }], edges: [], sink: "grade", checks: 1 }));
  try {
    const process = Bun.spawn(["bun", join(import.meta.dir, "../../examples/benchmark/_lib/grade-unaided.ts"), "u-test", file], { env: { ...Bun.env, TGENGIN_BENCH_DIR: directory, TGENGIN_BENCH_GRADER: grader, TGENGIN_OUT: directory, TGENGIN_GRADER_TOKEN: FAKE_TOKEN, TGENGIN_GRADER_ORIGINS: origins }, stdout: "pipe", stderr: "pipe" });
    const [code, stdout, stderr] = await Promise.all([process.exited, new Response(process.stdout).text(), new Response(process.stderr).text()]);
    expect(code).toBe(0);
    expect(stdout + stderr).not.toContain(FAKE_TOKEN);
    return readFileSync(join(directory, "unaided.csv"), "utf8");
  } finally { rmSync(directory, { recursive: true, force: true }); }
}

test("the U offline grading path uses the same origin-scoped authentication", async () => {
  const received: (string | null)[] = [];
  const grader = Bun.serve({ port: 0, fetch(request) { const token = request.headers.get("X-ObjRun-Grader-Token"); received.push(token); return token === FAKE_TOKEN ? Response.json(true) : Response.json({ error: "unauthorized grader caller" }, { status: 403 }); } });
  const base = `http://127.0.0.1:${grader.port}`;
  try {
    expect(await offline(base, base)).toContain('"passed"');
    expect(await offline(base, "http://127.0.0.1:1")).toContain('"grader_error"');
    expect(received).toEqual([FAKE_TOKEN, null]);
  } finally { await grader.stop(true); }
}, 10000);

test("the U offline grading path rejects an explicitly invalid grading envelope", async () => {
  const grader = Bun.serve({ port: 0, fetch() { return Response.json({ value: true, valid: false, outcome: "grader_error" }); } });
  const base = `http://127.0.0.1:${grader.port}`;
  try { expect(await offline(base, base)).toContain('"grader_error"'); }
  finally { await grader.stop(true); }
}, 10000);

test("U offline grading cannot convert a provider-faulted generation into a valid score", async () => {
  let requests = 0;
  const grader = Bun.serve({ port: 0, fetch() { requests++; return Response.json(true); } });
  const base = `http://127.0.0.1:${grader.port}`;
  try {
    expect(await offline(base, base, "provider_error")).toContain('"provider_error"');
    expect(requests).toBe(0);
  } finally { await grader.stop(true); }
}, 10000);
