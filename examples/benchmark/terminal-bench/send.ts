/**
 * 把 Terminal-Bench 2.1 的题拼成一批任务发给引擎（照 deepswe/send.ts，加了 U 臂）。
 *
 *   cd app && bun ../examples/benchmark/terminal-bench/send.ts [几道] [这一跑叫什么] [种子]
 *
 * 环境变量：TGENGIN_BASE、TGENGIN_TB_STAND（台子，默认 7903）、TGENGIN_TB_CHECKS（c）、
 * TGENGIN_TB_DEAD（K，maxDeadSiblings）、TGENGIN_TB_SECONDS（T 上限；默认不封，用官方 timeout）、
 * TGENGIN_TB_AT_ONCE、TGENGIN_TB_UNAIDED=1（U 臂：不挂 G，描述末尾拼同一段验收标准）、
 * TGENGIN_TB_ONLY（逗号分隔题号）、TGENGIN_SKIP_EXISTING=1（续发）。
 *
 * 题面进 description；参考解、隐藏测试不出台子那个进程。
 */
import { objectiveOf } from "./objective.ts";

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
/** 引擎设了 api.publisherToken 时，绑判据要带这把钥匙（X-TGEngin-Publisher）。从环境变量取；没设就是空对象，老行为不变。 */
const PUBLISHER: Record<string, string> = process.env.TGENGIN_PUBLISHER_TOKEN ? { "x-tgengin-publisher": process.env.TGENGIN_PUBLISHER_TOKEN } : {};
const STAND = process.env.TGENGIN_TB_STAND ?? "http://127.0.0.1:7903";
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
const RUN = process.argv[3] ?? `tb-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}`;
const SEED = Number(process.argv[4] ?? 0);
const CAP = Number(process.env.TGENGIN_TB_SECONDS ?? 0);
const DEAD = Number(process.env.TGENGIN_TB_DEAD ?? 8);
const UNAIDED = process.env.TGENGIN_TB_UNAIDED === "1";
const AT_ONCE = Number(process.env.TGENGIN_TB_AT_ONCE ?? 0);
const ONLY = (process.env.TGENGIN_TB_ONLY ?? "").split(",").map((x) => x.trim()).filter(Boolean);

interface Item { id: string; category: string; difficulty: string; instruction: string; seconds: number; workdir: string }

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
    place: `tb:${RUN}/${it.id}`,
    source: "user",
    domain: "software",
    workdir: it.workdir,
    // T：官方 task.toml 的 agent timeout_sec（不另编）。TGENGIN_TB_SECONDS 可封顶。
    solveSeconds: seconds,
    maxBranches: 4,
    maxDeadSiblings: DEAD,
    noSearch: ["terminal-bench solution", "terminal-bench-2-1", `${it.id} solution`, `${it.id} solve.sh`],
    description:
      `${it.instruction}\n\n` +
      `## Grading\n\n` +
      `You are working inside the task's container (working directory ${it.workdir}); every bash / read / write / edit / glob / grep call runs there.\n` +
      `What is graded is the live state of this container at the moment you hand in, using the benchmark's official tests. ` +
      `Long-running services you were asked to start must still be running then. ` +
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
