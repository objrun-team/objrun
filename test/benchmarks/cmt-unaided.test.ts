import { expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const TOKEN = "cmt-local-fixture-token";
type RequestRow = { path: string; token: string | null; body: Record<string, unknown> };
const sha = (file: string) => createHash("sha256").update(readFileSync(file)).digest("hex");

function csvRows(csv: string): Record<string, string>[] {
  const rows: string[][] = [], row: string[] = [];
  let cell = "", quoted = false;
  for (let i = 0; i < csv.length; i++) {
    const c = csv[i];
    if (c === '"') { if (quoted && csv[i + 1] === '"') { cell += '"'; i++; } else quoted = !quoted; }
    else if (c === "," && !quoted) { row.push(cell); cell = ""; }
    else if (c === "\n" && !quoted) { row.push(cell.replace(/\r$/, "")); rows.push([...row]); row.length = 0; cell = ""; }
    else cell += c;
  }
  return rows.slice(1).filter(row => row.length === rows[0]?.length).map(row => Object.fromEntries(rows[0]!.map((name, i) => [name, row[i]!])));
}

async function offline(base: string, options: { origins?: string; state?: string; storedOutcome?: string; submissions?: { answer: string; at: number }[] } = {}) {
  const directory = mkdtempSync(join(tmpdir(), "tgengin-cmt-u-"));
  const file = join(directory, "fixture.sqlite");
  const db = new Database(file);
  db.exec("create table task(id text,mode text,run text,created_at integer,solve_seconds integer,state text,result text); create table cycle(mode text,cycle text); create table task_demo(task text,agent text,instance text,unit integer,at integer); create table agent_bot_msg(instance text,unit integer,seq integer,kind text,body text,at integer); insert into task values('cmt-0','demo','cmt-u-test',1000,10,'done',null); insert into cycle values('demo','submit')");
  if (options.state) db.query("update task set state=?").run(options.state);
  if (options.storedOutcome) db.query("update task set state='failed',result=?").run(JSON.stringify({ pass: 0, valid: false, outcome: options.storedOutcome, why: "fixture infrastructure failure" }));
  const submissions = options.submissions ?? [{ answer: "timely answer", at: 1500 }, { answer: "late answer", at: 11001 }];
  for (let i = 0; i < Math.max(1, submissions.length); i++) {
    db.query("insert into task_demo values('cmt-0','bot','cmt-0#1',?,?)").run(i + 1, 1000 + i * 2000);
    if (submissions[i]) db.query("insert into agent_bot_msg values('cmt-0#1',?,1,'call',?,?)").run(i + 1, JSON.stringify({ calls: [{ name: "submit", input: { answer: submissions[i]!.answer } }] }), submissions[i]!.at);
  }
  db.close();
  const before = sha(file);
  const child = spawn(process.execPath, [join(import.meta.dir, "../../examples/benchmark/cmt/grade-unaided.ts"), "cmt-u-test", file], { env: { ...process.env, TGENGIN_CMT_GRADER: base, TGENGIN_OUT: directory, TGENGIN_GRADER_TOKEN: TOKEN, TGENGIN_GRADER_ORIGINS: options.origins ?? base }, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "", stderr = "";
  child.stdout!.on("data", chunk => { stdout += chunk.toString(); });
  child.stderr!.on("data", chunk => { stderr += chunk.toString(); });
  try {
    const code = await new Promise<number | null>((resolve, reject) => { child.on("error", reject); child.on("close", resolve); });
    expect(code).toBe(0);
    expect(stdout + stderr).not.toContain(TOKEN);
    expect(sha(file)).toBe(before);
    return csvRows(readFileSync(join(directory, "unaided.csv"), "utf8"));
  } finally { if (child.exitCode === null) child.kill(); rmSync(directory, { recursive: true, force: true }); }
}

test("CMT U grades the timely candidate with the shared graph, authentication and input shape", async () => {
  const requests: RequestRow[] = [];
  const grader = Bun.serve({ port: 0, async fetch(request) {
    requests.push({ path: new URL(request.url).pathname, token: request.headers.get("X-ObjRun-Grader-Token"), body: await request.json() as Record<string, unknown> });
    return request.headers.get("X-ObjRun-Grader-Token") === TOKEN ? Response.json(true) : Response.json({ error: "unauthorized" }, { status: 403 });
  } });
  try {
    const rows = await offline(`http://127.0.0.1:${grader.port}`);
    expect(rows[0]).toMatchObject({ task: "cmt-0", submitted: "1", parsed: "1", equiv: "1", seconds: "2", units: "2", valid: "1", outcome: "passed", error: "" });
    expect(requests.map(row => row.path)).toEqual(["/parsed", "/equiv"]);
    expect(requests.map(row => row.token)).toEqual([TOKEN, TOKEN]);
    expect(requests[0]?.body.input).toMatchObject({ task: { id: "cmt-0", result: "timely answer" }, chain: [], result: { kind: "prompt", body: "timely answer" } });
    expect(requests[1]?.body.feed).toEqual([{ from: "parsed", out: 0, value: true }]);
    expect(JSON.stringify(requests.map(row => row.body))).not.toContain(TOKEN);
  } finally { await grader.stop(true); }
}, 10000);

test("CMT U does not send credentials to another origin or broadcast a token without origins", async () => {
  const tokens: (string | null)[] = [];
  const grader = Bun.serve({ port: 0, fetch(request) { tokens.push(request.headers.get("X-ObjRun-Grader-Token")); return Response.json({ error: "unauthorized" }, { status: 403 }); } });
  try {
    const base = `http://127.0.0.1:${grader.port}`;
    expect((await offline(base, { origins: "http://127.0.0.1:1" }))[0]).toMatchObject({ valid: "0", outcome: "grader_error" });
    expect(tokens).toEqual([null, null]);
    const before = tokens.length;
    expect((await offline(base, { origins: "" }))[0]).toMatchObject({ valid: "0", outcome: "grader_error" });
    expect(tokens.length).toBe(before);
  } finally { await grader.stop(true); }
}, 10000);

test("CMT U preserves grader HTTP and explicit validity failures even when the sink says true", async () => {
  for (const failure of ["http", "envelope", "domain"] as const) {
    const grader = Bun.serve({ port: 0, fetch(request) {
      if (new URL(request.url).pathname === "/equiv") return Response.json(true);
      if (failure === "http") return Response.json({ error: "fixture unavailable" }, { status: 503 });
      if (failure === "envelope") return Response.json({ value: true, valid: false, outcome: "grader_error" });
      return Response.json(1);
    } });
    try { expect((await offline(`http://127.0.0.1:${grader.port}`))[0]).toMatchObject({ valid: "0", outcome: "grader_error", parsed: "0", equiv: "1" }); }
    finally { await grader.stop(true); }
  }
}, 10000);

test("CMT U cannot turn an unfinished or provider-faulted generation into a scored success", async () => {
  let requests = 0;
  const grader = Bun.serve({ port: 0, fetch() { requests++; return Response.json(true); } });
  try {
    for (const outcome of ["provider_error", "grader_error", "finalization_pending", "finalization_error"]) expect((await offline(`http://127.0.0.1:${grader.port}`, { storedOutcome: outcome }))[0]).toMatchObject({ valid: "0", outcome, equiv: "0" });
    expect((await offline(`http://127.0.0.1:${grader.port}`, { state: "running" }))[0]).toMatchObject({ valid: "0", outcome: "finalization_pending", equiv: "0" });
    expect(requests).toBe(0);
  } finally { await grader.stop(true); }
}, 10000);

test("CMT U distinguishes no hand-in from an explicitly empty timely hand-in", async () => {
  const candidates: string[] = [];
  const grader = Bun.serve({ port: 0, async fetch(request) {
    const body = await request.json() as { input: { result: { body: string } } };
    candidates.push(body.input.result.body);
    return Response.json(false);
  } });
  try {
    const base = `http://127.0.0.1:${grader.port}`;
    expect((await offline(base, { submissions: [] }))[0]).toMatchObject({ submitted: "0", valid: "0", outcome: "no_candidate" });
    expect(candidates).toEqual([]);
    expect((await offline(base, { submissions: [{ answer: "", at: 11000 }] }))[0]).toMatchObject({ submitted: "1", valid: "1", outcome: "rejected" });
    expect(candidates).toEqual(["", ""]);
  } finally { await grader.stop(true); }
}, 10000);
