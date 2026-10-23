import { expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { open, type Store } from "../app/src/H2H/db.ts";
import { taskRoutes } from "../app/src/api/tasks.ts";

const fixtureRoot = resolve(import.meta.dir, "../.scratch/task-query-regression-" + randomUUID());
mkdirSync(fixtureRoot, { recursive: true });
let serial = 0;
function fixture(): Store {
  const file = join(fixtureRoot, `case-${serial++}.sqlite`);
  const store = open({ db: { file, pragmas: { journal_mode: "DELETE", busy_timeout: 1000 } } } as never);
  store.rw.exec(`create table sample(id integer primary key, label text, payload blob)`);
  return store;
}

/** Holds real statements until assertions, so GC cannot mask missing scoped release. */
function observe(action: (seen: { finalized: boolean }[]) => void) {
  const original = Database.prototype.prepare;
  const seen: { finalized: boolean; dispose: () => void }[] = [];
  Database.prototype.prepare = function (...args: unknown[]) {
    const statement = original.apply(this, args as never);
    const dispose = statement.finalize.bind(statement);
    const mark = { finalized: false, dispose };
    seen.push(mark);
    statement.finalize = () => { mark.finalized = true; dispose(); };
    return statement;
  } as typeof original;
  try { action(seen); }
  finally { Database.prototype.prepare = original; for (const mark of seen) mark.dispose(); }
}

test("real Conn materializes named parameters and BLOBs before scoped statement release", () => {
  const store = fixture();
  try {
    observe(seen => {
      expect(store.rw.run("insert into sample(label,payload) values(:label,:payload)", { label: "hello", payload: new Uint8Array([0, 255, 65]) }).changes).toBe(1);
      const rows = store.ro.all("select id,label,payload from sample where label=:label", { label: "hello" });
      expect(rows).toEqual([{ id: 1, label: "hello", payload: { $blob: "AP9B", bytes: 3 } }]);
      expect(seen.length).toBe(2);
      expect(seen.every(item => item.finalized)).toBe(true);
      // These values remain materialized after each SQLite statement is finalized.
      expect(JSON.parse(JSON.stringify(rows))[0].payload.$blob).toBe("AP9B");
    });
  } finally { store.close(); }
});

test("real Conn releases both all and run statements when SQLite execution throws", () => {
  const store = fixture();
  try {
    observe(seen => {
      expect(() => store.ro.all("select json_extract('bad-json','$')")).toThrow();
      expect(() => store.rw.run("insert into sample(id,label) values(1,'a'),(1,'b')")).toThrow();
      expect(seen.length).toBe(2);
      expect(seen.every(item => item.finalized)).toBe(true);
    });
    expect(() => store.ro.all("select non_existing_column from sample")).toThrow();
    expect(store.ro.all("select count(*) as n from sample")).toEqual([{ n: 0 }]);
  } finally { store.close(); }
});

test("scoped release preserves transactions and the native read-only connection", () => {
  const store = fixture();
  try {
    store.rw.exec("begin transaction");
    store.rw.run("insert into sample(label) values(?)", ["rolled-back"]);
    expect(store.rw.all("select count(*) as n from sample")).toEqual([{ n: 1 }]);
    store.rw.exec("rollback");
    expect(store.ro.all("select count(*) as n from sample")).toEqual([{ n: 0 }]);
    observe(seen => {
      expect(() => store.ro.run("insert into sample(label) values(?)", ["forbidden"])).toThrow();
      expect(seen).toHaveLength(1);
      expect(seen[0].finalized).toBe(true);
    });
    expect(store.ro.all("select count(*) as n from sample")).toEqual([{ n: 0 }]);
  } finally { store.close(); }
});

function taskFixture() {
  const store = fixture();
  store.rw.exec(`
    create table task(id text primary key,mode text,state text,created_at integer,solve_seconds integer,objective integer,readable integer,result text,description text);
    create table task_repair(task text,cycle text,unit integer,from_cycle text,from_unit integer,agent text,instance text,place text,at integer,done integer,status text);
    create table agent(name text,unit text,apis text);
    create table cycle(mode text,cycle text,api_mode text);
    create table api(key_env text,model text,handle text,modes text);
    create table agent_bot_msg(instance text,unit integer,kind text);
    insert into agent values('bot','fn:unit.tools','[]');
    insert into cycle values('repair','ask',null);
  `);
  const created = Date.now() - 1000;
  store.rw.run("insert into task values(?,?,?,?,?,?,?,?,?)", ["fixture", "repair", "claimed", created, 600, 1, 0, null, "Public synthetic task"]);
  for (let unit = 1; unit <= 32; unit++) {
    store.rw.run("insert into task_repair values(?,?,?,?,?,?,?,?,?,?,?)", ["fixture", "ask", unit, unit === 1 ? null : "ask", unit === 1 ? null : unit - 1, "bot", "fixture#1", "local", created, unit < 32 ? 1 : 0, null]);
  }
  const routes = taskRoutes(store, { has: () => false } as never, {} as never, () => {});
  const full = routes.find(r => r.method === "GET" && r.path === "/tasks/:id")!;
  const status = routes.find(r => r.method === "GET" && r.path === "/tasks/:id/status");
  return { store, full, status };
}

test("independent task status stays one query for a deep tree and preserves terminal/finalization fields", async () => {
  const { store, full, status } = taskFixture();
  try {
    expect(status).toBeDefined();
    const reply = { code() { return this; }, send(value: unknown) { return value; } };
    for (const [state, result] of [["claimed", null], ["failed", '{"outcome":"finalization_pending"}'], ["failed", '{"valid":true,"outcome":"task_timeout"}'], ["done", '{"valid":true,"pass":1}']] as const) {
      store.rw.run("update task set state=?,result=? where id='fixture'", [state, result]);
      const original = store.ro.all.bind(store.ro);
      let queries = 0;
      store.ro.all = (sql, params) => { queries++; return original(sql, params); };
      const view = await status!.handler({ id: "fixture" }, undefined as never, reply as never) as Record<string, unknown>;
      store.ro.all = original;
      expect(queries).toBe(1);
      const old = await full.handler({ id: "fixture" }, undefined as never, reply as never) as Record<string, unknown>;
      for (const key of ["id", "state", "result", "created_at", "solve_seconds"]) expect(view[key]).toEqual(old[key]);
      expect(view).not.toHaveProperty("units");
      expect((view.solve as { limitSeconds: number }).limitSeconds).toBe((old.solve as { limitSeconds: number }).limitSeconds);
      expect(old.units).toHaveLength(32);
      expect((old.units as { chain: string }[])[31].chain).toBe(Array.from({ length: 32 }, (_, i) => `repair/ask#${i + 1}`).join(" > "));
    }
  } finally { store.close(); }
});

test("independent task status gives the same 404 contract for an unknown id", async () => {
  const { store, status } = taskFixture();
  try {
    expect(status).toBeDefined();
    let code = 200;
    const reply = { code(next: number) { code = next; return this; }, send(value: unknown) { return value; } };
    const result = await status!.handler({ id: "missing" }, undefined as never, reply as never);
    expect(code).toBe(404);
    expect(result).toEqual({ error: "no such task: missing" });
  } finally { store.close(); }
});
