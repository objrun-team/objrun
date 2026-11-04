import { expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import type { Conn } from "../../app/src/H2H/db.ts";
import { finalCandidate } from "../../app/src/objective/candidate.ts";

function fixture() {
  const raw = new Database(":memory:");
  raw.exec("create table task(id text,mode text,created_at integer,solve_seconds integer); create table cycle(mode text,cycle text); create table task_demo(task text,agent text,instance text,unit integer); create table agent_bot_msg(instance text,unit integer,seq integer,kind text,body text,at integer default 1500); insert into task values('t','demo',1000,1); insert into task_demo values('t','bot','t#1',1);");
  const db: Conn = { all: (sql, params) => raw.query(sql).all(...((params ?? []) as never[])) as Record<string, unknown>[], exec: sql => raw.exec(sql), run() { throw new Error("read-only test"); }, close() { raw.close(); } };
  return { db, raw };
}
test("an explicitly empty final hand-in does not fall back to an earlier answer", () => {
  const f = fixture();
  try {
    f.raw.query("insert into agent_bot_msg(instance,unit,seq,kind,body) values('t#1',1,1,'prompt','earlier correct thought')").run();
    f.raw.query("insert into agent_bot_msg(instance,unit,seq,kind,body) values('t#1',1,2,'call',?)").run(JSON.stringify({ calls: [{ name: "submit", input: { answer: "" } }] }));
    expect(finalCandidate(f.db, "t")).toEqual({ body: "", how: "submitted" });
  } finally { f.db.close(); }
});
test("a verify candidate is never promoted to delivery in a mode with submit", () => {
  const f = fixture();
  try {
    f.raw.exec("insert into cycle values('demo','submit')");
    f.raw.query("insert into agent_bot_msg(instance,unit,seq,kind,body) values('t#1',1,1,'call',?)").run(JSON.stringify({ text: "thinking", calls: [{ name: "verify", input: { answer: "correct" } }] }));
    expect(finalCandidate(f.db, "t")).toBeUndefined();
  } finally { f.db.close(); }
});
test("a single-turn mode without submit uses the final prompt for both live and offline grading", () => {
  const f = fixture();
  try {
    f.raw.exec("insert into agent_bot_msg(instance,unit,seq,kind,body) values('t#1',1,1,'prompt','final answer')");
    expect(finalCandidate(f.db, "t")).toEqual({ body: "final answer", how: "last words" });
  } finally { f.db.close(); }
});

test("a hand-in received after solve_seconds is not a final candidate", () => {
  const f = fixture();
  try {
    f.raw.exec("insert into cycle values('demo','submit')");
    f.raw.query("insert into agent_bot_msg values('t#1',1,1,'call',?,2001)").run(JSON.stringify({ calls: [{ name: "submit", input: { answer: "late correct answer" } }] }));
    expect(finalCandidate(f.db, "t")).toBeUndefined();
  } finally { f.db.close(); }
});

test("a late hand-in does not hide an earlier candidate received within the limit", () => {
  const f = fixture();
  try {
    f.raw.exec("insert into cycle values('demo','submit')");
    f.raw.query("insert into agent_bot_msg values('t#1',1,1,'call',?,2000)").run(JSON.stringify({ calls: [{ name: "submit", input: { answer: "on time" } }] }));
    f.raw.query("insert into agent_bot_msg values('t#1',1,2,'call',?,2001)").run(JSON.stringify({ calls: [{ name: "submit", input: { answer: "late" } }] }));
    expect(finalCandidate(f.db, "t")).toEqual({ body: "on time", how: "submitted" });
  } finally { f.db.close(); }
});

test("a single-turn baseline cannot acquire a candidate after solve_seconds", () => {
  const f = fixture();
  try {
    f.raw.exec("insert into agent_bot_msg values('t#1',1,1,'prompt','late baseline',2001)");
    expect(finalCandidate(f.db, "t")).toBeUndefined();
  } finally { f.db.close(); }
});
