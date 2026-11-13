/**
 * Assemble SkillsBench 1.1 tasks into a batch for the engine (based on deepswe/send.ts, with a U arm).
 *
 *   cd app && bun ../examples/benchmark/skillsbench/send.ts [count] [run-name] [seed]
 *
 * Environment variables: TGENGIN_BASE, TGENGIN_SKB_STAND (service, default 7903), TGENGIN_SKB_CHECKS (c),
 * TGENGIN_SKB_DEAD (K, maxDeadSiblings), TGENGIN_SKB_SECONDS (T cap; uncapped by default, using the official timeout),
 * TGENGIN_SKB_AT_ONCE, TGENGIN_SKB_UNAIDED=1 (U arm: no G; append the same acceptance criteria to the description),
 * TGENGIN_SKB_ONLY (comma-separated task IDs), TGENGIN_SKIP_EXISTING=1 (resume submission).
 *
 * The problem statement becomes description; reference solutions and hidden tests stay in the service process.
 */
import { objectiveOf } from "./objective.ts";

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
/** When api.publisherToken is configured, attaching grading criteria requires this key (X-TGEngin-Publisher). Read it from the environment; if unset, use an empty object to preserve existing behavior. */
const PUBLISHER: Record<string, string> = process.env.TGENGIN_PUBLISHER_TOKEN ? { "x-tgengin-publisher": process.env.TGENGIN_PUBLISHER_TOKEN } : {};
const STAND = process.env.TGENGIN_SKB_STAND ?? "http://127.0.0.1:7905";
const GRADER_TOKEN = process.env.TGENGIN_GRADER_TOKEN ?? "";
const GRADER_ORIGINS_RAW = (process.env.TGENGIN_GRADER_ORIGINS ?? "").trim();
let GRADER_ORIGINS: string[] = [];
try {
  const entries = GRADER_ORIGINS_RAW.startsWith("[") ? JSON.parse(GRADER_ORIGINS_RAW) : GRADER_ORIGINS_RAW.split(",");
  if (!Array.isArray(entries) || !entries.length) throw new Error();
  GRADER_ORIGINS = entries.map((entry) => {
    const url = new URL(String(entry).trim());
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.pathname !== "/" || url.search || url.hash) throw new Error();
    return url.origin;
  });
} catch {
  console.error("TGENGIN_GRADER_ORIGINS must contain valid HTTP URL origins (comma-separated or a JSON array).");
  process.exit(1);
}
if (!GRADER_TOKEN || !GRADER_ORIGINS.includes(new URL(STAND).origin)) {
  console.error("Set TGENGIN_GRADER_TOKEN and explicitly allow this stand origin in TGENGIN_GRADER_ORIGINS before publishing.");
  process.exit(1);
}
const GRADER_HEADERS = { "X-ObjRun-Grader-Token": GRADER_TOKEN };
const HOW_MANY = Number(process.argv[2] ?? 0);
const RUN = process.argv[3] ?? `skb-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}`;
const SEED = Number(process.argv[4] ?? 0);
const CAP = Number(process.env.TGENGIN_SKB_SECONDS ?? 0);
const DEAD = Number(process.env.TGENGIN_SKB_DEAD ?? 8);
const UNAIDED = process.env.TGENGIN_SKB_UNAIDED === "1";
const AT_ONCE = Number(process.env.TGENGIN_SKB_AT_ONCE ?? 0);
const ONLY = (process.env.TGENGIN_SKB_ONLY ?? "").split(",").map((x) => x.trim()).filter(Boolean);

interface Item { id: string; category: string; difficulty: string; instruction: string; seconds: number; workdir: string; skills: { name: string; description: string }[] }

const health = await fetch(`${STAND}/health`, { redirect: "error" });
if (!health.ok) { console.error(`stand health check failed: ${health.status}`); process.exit(1); }
const ready = await health.json() as { isolationReady?: boolean; authenticated?: boolean; unsafeDiagnostic?: boolean };
if (!ready.isolationReady || !ready.authenticated || ready.unsafeDiagnostic) {
  console.error("This stand has not established an authenticated grading isolation boundary. Formal task publication is blocked.");
  process.exit(1);
}
const res0 = await fetch(`${STAND}/problems?n=${HOW_MANY}&seed=${SEED}`, { headers: GRADER_HEADERS, redirect: "error" });
if (!res0.ok) { console.error(`cannot fetch problems from ${STAND}/problems: ${res0.status}`); process.exit(1); }
let items = (await res0.json()) as Item[];
if (ONLY.length) items = items.filter((it) => ONLY.includes(it.id));

let skip = new Set<string>();
if (process.env.TGENGIN_SKIP_EXISTING === "1") {
  const r = await fetch(`${BASE}/tasks?run=${RUN}&limit=5000`);
  if (r.ok) skip = new Set(((await r.json()) as { rows?: { id: string }[] }).rows?.map((x) => x.id) ?? []);
  console.log(`${RUN}: ${skip.size} already published, skipping them`);
}

const objective = objectiveOf(STAND);

const tasks = items.filter((it) => !skip.has(`${RUN}/${it.id}`)).map((it) => {
  const seconds = CAP > 0 ? Math.min(it.seconds, CAP) : it.seconds;
  return {
    id: `${RUN}/${it.id}`,
    mode: "solve",
    agent: "bot",
    place: `skb:${RUN}/${it.id}`,
    source: "user",
    domain: "software",
    workdir: it.workdir,
    // T: use agent timeout_sec from official task.toml, not an invented value. TGENGIN_SKB_SECONDS can cap it.
    solveSeconds: seconds,
    maxBranches: 4,
    maxDeadSiblings: DEAD,
    noSearch: ["skillsbench solution", "skillsbench oracle", `${it.id} solution`, `${it.id} solve.sh`],
    description:
      `${it.instruction}\n\n` +
      (it.skills.length
        ? `## Skills available in this container\n\n` +
          `The following skills are installed at /root/skills (also /root/.claude/skills); each is a directory with a SKILL.md you can read with the read tool:\n` +
          it.skills.map((s) => `- ${s.name}: ${s.description}`).join("\n") + `\n\n`
        : "") +
      `## Grading\n\n` +
      `You are working inside the task's container (working directory ${it.workdir}); every bash / read / write / edit / glob / grep call runs there.\n` +
      `What is graded is the state of this container at the moment you hand in: the benchmark's official tests run against a snapshot of its filesystem (files under /tmp are not part of the snapshot). ` +
      `The string you hand in is only a label for the attempt (for example "v1"); its content is not graded.\n\n` +
      `The wall-clock limit for this task is ${Math.round(seconds / 60)} minutes. Nothing reports how much of it is left.` +
      (UNAIDED ? `\n\n## Acceptance criteria\n${JSON.stringify(objective, null, 2)}` : ""),
    ...(UNAIDED ? {} : { objective, readable: true }),
  };
});
console.log(`${RUN}: ${tasks.length} tasks, c=${objective.checks}, K=${DEAD}${CAP ? `, T<=${CAP}s` : ", T=official"}${UNAIDED ? " (UNAIDED: no objective mounted)" : ""}`);

async function busy(): Promise<number> {
  const r = await fetch(`${BASE}/bench/${RUN}`);
  if (!r.ok) return 0;
  const j = (await r.json()) as { running?: number; open?: number };
  return Number(j.running ?? 0) + Number(j.open ?? 0);
}

if (AT_ONCE > 0) {
  let sent = 0;
  for (const t of tasks) {
    while ((await busy()) >= AT_ONCE) await Bun.sleep(10_000);
    const r = await fetch(`${BASE}/tasks`, { method: "POST", headers: { "content-type": "application/json", ...PUBLISHER }, body: JSON.stringify({ ...t, run: RUN }) });
    if (!r.ok) {
      const e = (await r.json()) as { error?: string };
      if ((e.error ?? "").includes("already exists")) continue;
      console.error(`${t.id} was refused: ${e.error}`);
      process.exit(1);
    }
    sent++;
    console.log(`  [${sent}/${tasks.length}] ${t.id.slice(RUN.length + 1)}  (${Math.round(t.solveSeconds / 60)} min)`);
  }
  console.log(`${RUN}: ${sent} sent`);
} else {
  const r = await fetch(`${BASE}/bench`, { method: "POST", headers: { "content-type": "application/json", ...PUBLISHER }, body: JSON.stringify({ run: RUN, tasks }) });
  const got = (await r.json()) as { ids?: string[]; error?: string };
  if (!r.ok) { console.error(`the whole batch was not sent: ${got.error}`); process.exit(1); }
  console.log(`${RUN}: ${got.ids?.length} tasks sent`);
}
