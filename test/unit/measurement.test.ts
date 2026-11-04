import { describe, expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import type { Conn } from "../../app/src/H2H/db.ts";
import { ddl, install, type TableDecl } from "../../app/src/install/index.ts";
import declarations from "../../app/src/install/tables.json" with { type: "json" };
import { Registry } from "../../app/src/engine/registry.ts";
import { Kernel } from "../../app/src/engine/loop.ts";
import { evaluate } from "../../app/src/objective/run.ts";
import { parseObjective } from "../../app/src/objective/spec.ts";
import type { Sealed } from "../../app/src/objective/store.ts";
import { registerVerifyTool } from "../../app/src/objective/tool.ts";
import { registerTree } from "../../app/src/tree/dfs.ts";

function fixture() {
  const raw = new Database(":memory:");
  const db: Conn = {
    exec: sql => raw.exec(sql),
    all: (sql, params) => raw.query(sql).all(...((params ?? []) as never[])) as Record<string, unknown>[],
    run: (sql, params) => { const r = raw.query(sql).run(...((params ?? []) as never[])); return { changes: Number(r.changes), lastInsertRowid: Number(r.lastInsertRowid) }; },
    close: () => raw.close(),
  };
  install(db);
  for (const [pattern, name] of [["task_{}", "task_demo"], ["agent_{}_msg", "agent_bot_msg"]]) {
    const template = declarations.templates.find(t => t.pattern === pattern)!;
    db.exec(ddl({ ...template, name } as TableDecl));
  }
  db.run('insert into cycle (mode, cycle, max_units, "from", next, infer) values (?, ?, 4, ?, ?, ?)', ["demo", "ask", "[]", '["submit"]', "fn:infer.dfs"]);
  db.run("insert into task (id,mode,place,run,source,domain,description,created_at,max_branches,max_dead_siblings,solve_seconds,state) values ('t','demo','local','test','user','test','test',0,4,2,30,'claimed')");
  for (const [unit, cycle] of [[1, "ask"], [2, "submit"]]) db.run("insert into task_demo(task,cycle,unit,node,agent,instance,place,at,done) values('t',?,?,1,'bot','t#1','local',0,0)", [cycle, unit]);
  const reg = new Registry();
  let gradingCalls = 0;
  let fault = false;
  reg.register(db, "fn:test.grade", 1000, async () => { gradingCalls++; if (fault) throw new Error("grader connection failed"); return true; });
  reg.register(db, "fn:test.root", 1000, async arg => (arg as { feed: { value: unknown }[] }).feed[0]?.value === true);
  const objective = parseObjective({ nodes: [{ name: "grade", moment: "done", domain: "bool", handle: "fn:test.grade" }, { name: "root", moment: "done", domain: "bool", handle: "fn:test.root" }], edges: [{ src: "grade", out: 0, dst: "root" }], sink: "root", checks: 1 });
  Object.assign(objective, { reuse: "text" });
  const sealed: Sealed = { has: () => true, open: () => objective, checksOf: () => 1, paramsOf: () => ({}), seal() {}, forget() {}, close() {} };
  registerTree(db, reg, sealed);
  registerVerifyTool(db, reg, sealed);
  let seq = 0;
  const record = (unit: number, kind: string, body: unknown) => db.run("insert into agent_bot_msg(instance,unit,seq,role,kind,body,at) values('t#1',?,?,?, ?,?,0)", [unit, ++seq, kind === "tool" ? "tool" : "assistant", kind, JSON.stringify(body)]);
  return { db, reg, objective, sealed, record, fault: (v: boolean) => { fault = v; }, calls: () => gradingCalls, close: () => db.close(),
    verify: () => reg.get("fn:tool.verify").call({ args: { answer: "correct" }, agent: "bot", instance: "t#1", unit: 1 }),
    submit: () => reg.get("fn:infer.dfs").call({ task: { id: "t", mode: "demo", max_dead_siblings: 2 }, cycle: { cycle: "submit" }, agent: { name: "bot" }, chain: [], next: ["ask"], result: {}, sub: "task_demo", unit: 2 }),
  };
}

describe("measurement regressions through registered handlers", () => {
  test("a refused verify cannot replace the final grading decision", async () => {
    const f = fixture();
    try {
      f.record(1, "call", { calls: [{ id: "refused", name: "verify", input: { answer: "correct" } }] });
      f.record(1, "tool", { id: "refused", name: "verify", value: { error: "checks exhausted", left: 0 } });
      f.record(2, "call", { calls: [{ id: "submit", name: "submit", input: { answer: "correct" } }] });
      expect(await f.submit()).toMatchObject({ status: "reached" });
      expect(f.calls()).toBe(1);
    } finally { f.close(); }
  });

  test("a grading outage is explicitly invalid and leaves the effective check budget available", async () => {
    const f = fixture();
    try {
      f.fault(true);
      const out = await f.verify();
      expect(out).toMatchObject({ outcome: "grader_error", valid: false, left: 1 });
      expect(out).not.toHaveProperty("pass");
      f.record(1, "tool", { id: "outage", name: "verify", value: out });
      f.fault(false);
      expect(await f.verify()).toMatchObject({ pass: 1, valid: true, left: 0 });
      expect(f.calls()).toBe(2);
    } finally { f.close(); }
  });

  test("evaluate distinguishes a valid rejection from an evaluator failure", async () => {
    const f = fixture();
    try {
      f.fault(true);
      expect(await evaluate(f.objective, f.reg, {})).toMatchObject({ pass: 0, valid: false, outcome: "grader_error" });
      f.reg.adopt("fn:test.grade", 1000, async () => false);
      expect(await evaluate(f.objective, f.reg, {})).toMatchObject({ pass: 0, valid: true, outcome: "rejected" });
    } finally { f.close(); }
  });

  test("an invalid stored decision is not reused even if it contains a numeric pass", async () => {
    const f = fixture();
    try {
      f.record(1, "call", { calls: [{ id: "outage", name: "verify", input: { answer: "correct" } }] });
      f.record(1, "tool", { id: "outage", name: "verify", value: { pass: 0, valid: false, outcome: "grader_error" } });
      f.record(2, "call", { calls: [{ id: "submit", name: "submit", input: { answer: "correct" } }] });
      expect(await f.submit()).toMatchObject({ status: "reached" });
      expect(f.calls()).toBe(1);
    } finally { f.close(); }
  });

  test("a failed timeout write can be retried on the next kernel wake", async () => {
    const f = fixture();
    f.db.run("delete from cycle");
    const originalRun = f.db.run;
    let failOnce = true;
    f.db.run = (sql, params) => {
      if (failOnce && sql.includes("update task set state = 'failed'")) { failOnce = false; throw new Error("temporary write failure"); }
      return originalRun(sql, params);
    };
    let closed = 0;
    const kernel = new Kernel({ rw: f.db, ro: f.db, file: ":memory:", close() {} }, { info() {}, warn() {}, error() {} }, f.reg, { onDone() { closed++; } });
    try {
      kernel.start();
      await Bun.sleep(10);
      kernel.wake();
      await Bun.sleep(10);
      expect(closed).toBe(1);
      expect(f.db.all("select state from task where id='t'")[0]?.state).toBe("failed");
    } finally { kernel.stop(); f.close(); }
  });

  test("a broken upstream grader cannot be turned into success by the root handle", async () => {
    const f = fixture();
    try {
      f.fault(true);
      f.reg.adopt("fn:test.root", 1000, async () => true);
      expect(await evaluate(f.objective, f.reg, {})).toMatchObject({ pass: 0, valid: false, outcome: "grader_error" });
    } finally { f.close(); }
  });

  test("an explicitly invalid grader envelope cannot supply a passing value or spend c", async () => {
    const f = fixture();
    try {
      f.reg.adopt("fn:test.grade", 1000, async () => ({ value: true, valid: false, outcome: "grader_error" }));
      expect(await evaluate(f.objective, f.reg, {})).toMatchObject({ pass: 0, valid: false, outcome: "grader_error" });
      expect(await f.verify()).toMatchObject({ valid: false, outcome: "grader_error", left: 1 });
    } finally { f.close(); }
  });

  test("mutable artifacts are regraded even when their label matches a prior passing check", async () => {
    const f = fixture();
    try {
      Object.assign(f.objective, { reuse: "never" });
      f.record(1, "call", { calls: [{ id: "prior", name: "verify", input: { answer: "correct" } }] });
      f.record(1, "tool", { id: "prior", name: "verify", value: { pass: 1, valid: true, outcome: "passed" } });
      f.record(2, "call", { calls: [{ id: "submit", name: "submit", input: { answer: "correct" } }] });
      f.reg.adopt("fn:test.grade", 1000, async () => false);
      expect(await f.submit()).toMatchObject({ status: "dead_failed" });
    } finally { f.close(); }
  });

  test("an asynchronously failed timeout finalization is retried without spending a grader decision", async () => {
    const f = fixture();
    f.db.run("delete from cycle");
    let attempts = 0;
    const kernel = new Kernel({ rw: f.db, ro: f.db, file: ":memory:", close() {} }, { info() {}, warn() {}, error() {} }, f.reg, {
      async onDone() {
        attempts++;
        if (attempts === 1) throw new Error("temporary asynchronous finalization failure");
        f.db.run("update task set result=? where id='t'", [JSON.stringify({ pass: 0, valid: false, outcome: "no_candidate" })]);
      },
    });
    try {
      kernel.start();
      for (let i = 0; attempts < 2 && i < 300; i++) { await Bun.sleep(5); kernel.wake(); }
      expect(attempts).toBe(2);
      expect(JSON.parse(String(f.db.all("select result from task where id='t'")[0]?.result))).toMatchObject({ valid: false, outcome: "no_candidate" });
    } finally { kernel.stop(); f.close(); }
  });

  for (const outcome of ["finalization_pending", "finalization_error"]) test(`a restarted kernel resumes persisted ${outcome} without sending the task again`, async () => {
    const f = fixture();
    f.db.run("delete from cycle");
    f.db.run("update task set state='done',result=? where id='t'", [JSON.stringify({ pass: 0, valid: false, outcome })]);
    let attempts = 0;
    const kernel = new Kernel({ rw: f.db, ro: f.db, file: ":memory:", close() {} }, { info() {}, warn() {}, error() {} }, f.reg, {
      async onDone() {
        attempts++;
        f.db.run("update task set result=? where id='t'", [JSON.stringify({ pass: 1, valid: true, outcome: "passed" })]);
      },
    });
    try {
      kernel.start();
      await Bun.sleep(10);
      kernel.wake();
      await Bun.sleep(10);
      expect(attempts).toBe(1);
      expect(JSON.parse(String(f.db.all("select result from task where id='t'")[0]?.result))).toMatchObject({ pass: 1, valid: true, outcome: "passed" });
      expect(f.calls()).toBe(0);
    } finally { kernel.stop(); f.close(); }
  });
});
