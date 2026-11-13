/**
 * Shared task submission: read `$TGENGIN_BENCH_DIR/G.json`, fetch statements from the grader's `/problems`, and submit tasks with G to the engine.
 *
 *   cd app && TGENGIN_BENCH_DIR=../examples/benchmark/aime bun ../examples/benchmark/_lib/send.ts [count] [run-name]
 *
 * Environment: TGENGIN_BASE, TGENGIN_BENCH_GRADER (grader URL), TGENGIN_CMT_AT_ONCE, TGENGIN_CMT_ONLY (comma-separated IDs),
 * TGENGIN_CMT_SECONDS, TGENGIN_CMT_UNAIDED=1 (arm U: no G attached; append the same acceptance criteria to the description).
 *
 * See each benchmark's README for the G.json structure. `{GRADER}` is replaced with the grader URL.
 */
import { readFileSync } from "node:fs";

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
/** When api.publisherToken is configured, attaching grading criteria requires this key (X-TGEngin-Publisher). Read it from the environment; if unset, use an empty object to preserve existing behavior. */
const PUBLISHER: Record<string, string> = process.env.TGENGIN_PUBLISHER_TOKEN ? { "x-tgengin-publisher": process.env.TGENGIN_PUBLISHER_TOKEN } : {};
const DIR = process.env.TGENGIN_BENCH_DIR;
if (!DIR) {
  console.error("TGENGIN_BENCH_DIR is not set");
  process.exit(1);
}
const G = JSON.parse(readFileSync(`${DIR}/${process.env.TGENGIN_G_FILE ?? "G.json"}`, "utf8")) as {
  slug: string;
  grader_port: number;
  nodes: { name: string; moment: string; domain: string; handle: string }[];
  edges: { src: string; out: number; dst: string }[];
  sink: string;
  checks: number;
  reuse?: "text" | "never";
  task: Record<string, unknown>;
  suffix: string;
};
const GRADER = process.env.TGENGIN_BENCH_GRADER ?? `http://127.0.0.1:${G.grader_port}`;
const HOW_MANY = Number(process.argv[2] ?? 0);
const RUN = process.argv[3] ?? `${G.slug}-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}`;
const UNAIDED = process.env.TGENGIN_CMT_UNAIDED === "1";
const AT_ONCE = Number(process.env.TGENGIN_CMT_AT_ONCE ?? 0);
const ONLY = (process.env.TGENGIN_CMT_ONLY ?? "").split(",").map((x) => x.trim()).filter(Boolean);

const q = new URLSearchParams();
if (HOW_MANY > 0) q.set("n", String(HOW_MANY));
if (ONLY.length) q.set("only", ONLY.join(","));
const res0 = await fetch(`${GRADER}/problems${q.size ? "?" + q.toString() : ""}`);
if (!res0.ok) {
  console.error(`cannot fetch problems from ${GRADER}/problems: ${res0.status}`);
  process.exit(1);
}
const raw = (await res0.json()) as Record<string, unknown>[];
// The fields returned by /problems vary: AIME provides problem, GPQA provides question+choices, and ChemBench/ChemIQ provide prompt.
const items = raw.map((it, i) => {
  const id = String(it.id ?? `${G.slug}-${it.index ?? i}`);
  let prompt = String(it.prompt ?? it.problem ?? "");
  if (!prompt && it.question) {
    const ch = (it.choices ?? {}) as Record<string, string>;
    prompt = String(it.question) + "\n\n" + Object.keys(ch).map((k) => `${k}. ${ch[k]}`).join("\n");
  }
  // miniF2F: informal statement + official header + official theorem declaration (ending in := by; the model supplies the proof body).
  if (!prompt && it.statement) {
    prompt = (it.informal ? `${String(it.informal)}\n\n` : "") + "```lean\n" + String(it.header ?? "") + "\n" + String(it.statement) + "\n```";
  }
  return { id, prompt };
});

const objective = {
  nodes: G.nodes.map((n) => ({ ...n, handle: n.handle.replace("{GRADER}", GRADER) })),
  edges: G.edges,
  sink: G.sink,
  checks: G.checks,
  reuse: G.reuse ?? "never",
};

// TGENGIN_SKIP_EXISTING=1 resumes submission by skipping tasks already submitted in this run. To increase concurrency mid-run, stop the original sender and restart with a larger AT_ONCE.
let skip = new Set<string>();
if (process.env.TGENGIN_SKIP_EXISTING === "1") {
  const r = await fetch(`${BASE}/tasks?run=${RUN}&limit=5000`);
  if (r.ok) skip = new Set(((await r.json()) as { rows?: { id: string }[] }).rows?.map((x) => x.id) ?? []);
  console.log(`${RUN}: ${skip.size} already published, skipping them`);
}
// TGENGIN_CMT_ONLY submits only the named IDs. Filter here too because a grader may not support the only= parameter.
const onlySet = new Set(ONLY);
const tasks = items.filter((it) => !skip.has(it.id) && (onlySet.size === 0 || onlySet.has(it.id))).map((it) => ({
  id: it.id,
  mode: "solve",
  agent: "bot",
  place: "local",
  source: "user",
  solveSeconds: Number(process.env.TGENGIN_CMT_SECONDS ?? (G.task.solveSeconds as number) ?? 3600),
  ...G.task,
  // For benchmarks published online, disable search in arm U: TGENGIN_MAX_SEARCHES=0 overrides maxSearches from G.json.
  ...(process.env.TGENGIN_MAX_SEARCHES !== undefined ? { maxSearches: Number(process.env.TGENGIN_MAX_SEARCHES) } : {}),
  description: `${it.prompt}${G.suffix ?? ""}`,
  ...(UNAIDED ? {} : { objective, readable: true }),
}));
console.log(`${RUN}: ${tasks.length} tasks from ${G.slug}${UNAIDED ? " (UNAIDED: no objective mounted)" : ""}`);

async function busy(): Promise<number> {
  const r = await fetch(`${BASE}/bench/${RUN}`);
  if (!r.ok) return 0;
  const j = (await r.json()) as { running?: number; open?: number };
  return Number(j.running ?? 0) + Number(j.open ?? 0);
}

if (AT_ONCE > 0) {
  let sent = 0;
  for (const t of tasks) {
    while ((await busy()) >= AT_ONCE) await Bun.sleep(5000);
    const r = await fetch(`${BASE}/tasks`, { method: "POST", headers: { "content-type": "application/json", ...PUBLISHER }, body: JSON.stringify({ ...t, run: RUN }) });
    if (!r.ok) {
      console.error(`${t.id} was refused: ${((await r.json()) as { error?: string }).error}`);
      process.exit(1);
    }
    sent++;
    if (sent % 10 === 0 || sent === tasks.length) console.log(`  sent ${sent}/${tasks.length}`);
  }
} else {
  const r = await fetch(`${BASE}/bench`, { method: "POST", headers: { "content-type": "application/json", ...PUBLISHER }, body: JSON.stringify({ run: RUN, tasks }) });
  const got = (await r.json()) as { ids?: string[]; error?: string };
  if (!r.ok) {
    console.error(`the whole batch was not sent: ${got.error}`);
    process.exit(1);
  }
  console.log(`${RUN}: ${got.ids?.length} tasks sent`);
}
