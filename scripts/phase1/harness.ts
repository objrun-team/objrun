import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { machine, type Machine } from "../../test/_lib.ts";
import type { ToolDecl } from "../../app/src/declare/index.ts";

const root = resolve(import.meta.dir, "../..");
const pilotRoot = join(root, "docs/phase1/pilots");
export function priorPilotCost(): number {
  let cost = 0;
  for (const name of readdirSync(pilotRoot)) {
    try { const summary = JSON.parse(readFileSync(join(pilotRoot, name, "summary.json"), "utf8")); cost += Number(summary.usdUpperBound ?? 0); } catch {}
  }
  try {
    const reconciliation = JSON.parse(readFileSync(join(root, "docs/phase1/cost-reconciliation.json"), "utf8"));
    cost += Number(reconciliation.additionalKnownUsageUpperBoundUsd ?? 0) + Number(reconciliation.unreportedUsageReserveUsd ?? 0);
  } catch {}
  return cost;
}

export class Pilot {
  private m!: Machine;
  readonly run: string;
  readonly output: string;
  readonly databaseDir: string;
  readonly results: Record<string, unknown>[] = [];
  private previousCost: number;
  private cost = 0;
  private taskSeconds = 300;
  private constructor(slug: string) {
    this.run = `phase1-${slug}-${new Date().toISOString().replace(/[:.]/g, "-")}`;
    this.output = join(pilotRoot, this.run);
    this.databaseDir = join(root, ".phase1-data/pilots", this.run);
    mkdirSync(this.output, { recursive: true });
    mkdirSync(this.databaseDir, { recursive: true });
    this.previousCost = priorPilotCost();
  }
  static async start(slug: string, nodes: { name: string; handle: string }[], metadata: Record<string, unknown>, options: { tools?: ToolDecl[]; cycleMaxUnits?: number; taskSeconds?: number } = {}): Promise<Pilot> {
    const p = new Pilot(slug);
    p.taskSeconds = options.taskSeconds ?? 300;
    const tools = options.tools ?? [];
    const permissions = ["verify", "submit", "task_tree", "node_load", ...tools.map(tool => tool.name)];
    if (permissions.some(name => !/^[a-zA-Z0-9_]+$/.test(name))) throw new Error("Invalid pilot tool identifier");
    const snapshotPath = join(p.output, "source.json");
    execFileSync("bun", [join(root, "scripts/phase1/source-snapshot.ts"), snapshotPath], { cwd: root });
    const snapshot = JSON.parse(readFileSync(snapshotPath, "utf8"));
    writeFileSync(join(p.output, "manifest.json"), JSON.stringify({ schemaVersion: 1, run: p.run, purpose: "Preparation pilot; not a formal efficacy result", model: "deepseek-flash", resolvedVersion: "DeepSeek-V4.1-Flash", provider: "https://api.deepseek.com", temperature: 0, seed: 42, maxTokens: 2048, reasoningEffort: "none", taskSeconds: p.taskSeconds, maxChecksPerAttempt: 2, maxDeadSiblings: 1, toolPermissions: permissions, budgetUsd: 30, priorPilotCostUpperBoundUsd: p.previousCost, sourceDigest: snapshot.sourceDigest, sourceHead: snapshot.head, databaseDir: p.databaseDir, pricesSource: "https://api-docs.deepseek.com/quick_start/pricing/", ratesUsdPerMillionUpperBound: { uncachedInput: 0.3, cachedInput: 0.006, output: 1.2 }, ...metadata }, null, 2) + "\n");
    p.m = await machine({ maxTokens: 2048, retryTimes: 1, continueTimes: 0, reasoningEffort: "none" }, { directory: p.databaseDir, keep: true });
    await p.m.api("POST", "/exec", { sql: "insert or ignore into api (key_env,model,handle,modes,base_url,retry_on) select key_env, 'deepseek-flash', handle, modes, base_url, retry_on from api where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'" });
    await p.m.api("POST", "/declare", { handles: [...nodes.map(n => ({ name: n.handle, expectMs: 120000 })), ...tools.map(tool => ({ name: tool.identity, expectMs: 10000 }))], tools, places: [{ place: "local" }], modes: [{ mode: "pilot", cycles: [{ cycle: "ask", apiMode: "chat", maxUnits: options.cycleMaxUnits ?? 2, from: [], next: ["act"], infer: "fn:infer.dfs" }, { cycle: "act", maxUnits: options.cycleMaxUnits ?? 2, from: ["ask"], next: ["ask"], infer: "fn:infer.dfs" }] }], agents: [{ name: "bot", apis: [["DEEPSEEK_API_KEY", "deepseek-flash"]], unit: "fn:unit.tools" }] });
    await p.m.api("POST", "/exec", { sql: `update tool set usable=0 where name not in (${permissions.map(name => `'${name}'`).join(",")})` });
    return p;
  }
  async task(officialId: string, prompt: string, objective: unknown) {
    // Require conservative per-task headroom in this small pilot; reconcile all recorded usage and canceled requests.
    if (this.previousCost + this.cost + 5 > 30) throw new Error("Cannot reserve the next task within the shared $30 pilot limit");
    const id = `${this.run}/${officialId}`;
    const started = Date.now();
    await this.m.api("POST", "/tasks", { id, run: this.run, mode: "pilot", agent: "bot", place: "local", source: "user", description: prompt, objective, readable: false, solveSeconds: this.taskSeconds, maxBranches: 1, maxDeadSiblings: 1, noSearch: ["all"] });
    let verdict: unknown;
    let state = "unverified";
    while (Date.now() - started < 420000) {
      const task = await this.m.api<{ state: string; result: string | null }>("GET", `/tasks/${encodeURIComponent(id)}`);
      if ((task.state === "done" || task.state === "failed") && task.result) { verdict = JSON.parse(task.result); state = task.state; break; }
      await Bun.sleep(500);
    }
    if (state === "unverified") throw new Error(`${officialId} did not terminate within the pilot deadline`);
    const trace = await this.m.api<{ rows: Record<string, unknown>[] }>("POST", "/query", { sql: "select unit,seq,role,kind,body,at,thought,prompt_tokens,completion_tokens,reasoning_tokens,cached_tokens from agent_bot_msg where instance like :prefix order by unit,seq", params: { prefix: `${id}#%` } });
    const usage = trace.rows.reduce<{ input: number; output: number; cached: number }>((s, row) => ({ input: s.input + Number(row.prompt_tokens ?? 0), output: s.output + Number(row.completion_tokens ?? 0), cached: s.cached + Number(row.cached_tokens ?? 0) }), { input: 0, output: 0, cached: 0 });
    const usdUpperBound = ((usage.input - usage.cached) * 0.3 + usage.cached * 0.006 + usage.output * 1.2) / 1e6;
    this.cost += usdUpperBound;
    let answer = "";
    for (const row of trace.rows) {
      if (row.kind !== "call") continue;
      try { for (const call of JSON.parse(String(row.body)).calls ?? []) if (call.name === "submit") answer = String(call.input?.answer ?? ""); } catch {}
    }
    const result = { officialId, id, state, verdict, seconds: (Date.now() - started) / 1000, usage, usdUpperBound, promptSha256: createHash("sha256").update(prompt).digest("hex"), answer };
    writeFileSync(join(this.output, `task-${this.results.length}.json`), JSON.stringify({ ...result, trace: trace.rows }, null, 2) + "\n");
    this.results.push(result);
    this.save(false);
    console.log(JSON.stringify({ officialId, state, seconds: result.seconds, usdUpperBound: this.cost, sharedPilotCostUpperBoundUsd: this.previousCost + this.cost }));
    return result;
  }
  save(completed: boolean) { writeFileSync(join(this.output, "summary.json"), JSON.stringify({ run: this.run, tasks: this.results.length, usdUpperBound: this.cost, priorPilotCostUpperBoundUsd: this.previousCost, completed, results: this.results }, null, 2) + "\n"); }
  stop(completed = false) { this.save(completed); this.m.stop(); }
}
