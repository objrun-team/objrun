/**
 * 把**钟响了**的那些题再拉起来，接着上一趟的工作区跑。
 *
 * ```
 * bun examples/benchmark/deepswe/resume.ts [原来那一跑] [新跑名] [再给多少秒]
 * bun examples/benchmark/deepswe/resume.ts dsw-full dsw-full-r2 7200 --dry
 * ```
 *
 * ## 接着跑，接的是什么
 *
 * **工作容器不回档**（判据容器每次回，那是另一侧的事）。所以上一趟改的文件、开的分支、
 * 提的每一个提交都还在 `/app` 里 —— 这一趟的 `place` 指的就是**同一个容器**，
 * 只有 `id` 是新的（`task.id` 全局唯一，`tasks/publish.ts` 重了当场拒）。
 *
 * 带过去的是**工作区**，不是上下文：新任务从空的消息列表开始。上一趟说过的话、
 * 它那棵树，都在库里留着（`agent_bot_msg`、`task_solve`），但不接进来 ——
 * 那些正是把上下文撑到顶的东西，而它自己提的提交 `git log` 一句就读得到。
 *
 * ## 题面从库里读，不重新拼
 *
 * `task` 那一行存着整道题：`description`、`readable`、`workdir`、`no_search`、
 * 两个上限。原样搬过来，**只换 id、只换时限**。重新拼一份的话就是同一份定义两个副本，
 * 改了一处漏另一处不报错，而表现是「两趟跑的根本不是同一道题」。
 *
 * 只有 G 搬不过来：它的定义封在 sealed store 里，库里那一列只写着 `sealed`
 * （`tasks/publish.ts`）。所以 G 从 `objective.ts` 那一份共用定义重新拿 ——
 * 那正是 `send.ts` 起这一趟时用的同一份。
 */

import { objectiveOf } from "./objective.ts";

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
/** 引擎设了 api.publisherToken 时，绑判据要带这把钥匙（X-TGEngin-Publisher）。从环境变量取；没设就是空对象，老行为不变。 */
const PUBLISHER: Record<string, string> = process.env.TGENGIN_PUBLISHER_TOKEN ? { "x-tgengin-publisher": process.env.TGENGIN_PUBLISHER_TOKEN } : {};
const STAND = process.env.TGENGIN_DSW_STAND ?? "http://127.0.0.1:7902";
const FROM = process.argv[2] ?? "dsw-full";
const RUN = process.argv[3] ?? `${FROM}-r2`;
const SECONDS = Number(process.argv[4] ?? 7200);
/** 同时做几道。0 = 一次全发。跟 `send.ts` 同一个环境变量。 */
const AT_ONCE = Number(process.env.TGENGIN_DSW_AT_ONCE ?? 0);

interface Row {
  id: string;
  place: string;
  mode: string;
  source: string;
  domain: string;
  workdir: string;
  description: string;
  readable: number;
  max_branches: number;
  max_dead_siblings: number;
  max_searches: number | null;
  no_search: string;
  result: string;
}

async function sql<T>(q: string): Promise<T[]> {
  const r = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: { "content-type": "application/json", ...PUBLISHER },
    body: JSON.stringify({ sql: q }),
  });
  if (!r.ok) throw new Error(`${r.status} on: ${q.slice(0, 60)}`);
  return ((await r.json()) as { rows: T[] }).rows;
}

// **只挑钟响了的那些。** 判 0 有很多种：交出来的补丁打不上、行为没做出来、把原有的
// 测试弄坏了 —— 那几种再给两个钟也是同一个答案。时间不够那种不一样：它当时还在往前走。
const rows = await sql<Row>(`
  select id, place, mode, source, domain, workdir, description, readable,
         max_branches, max_dead_siblings, max_searches, no_search, result
  from task
  where run = '${FROM}' and state = 'failed' and result like '%over solve_seconds%'
  order by id`);

if (rows.length === 0) {
  console.log(`${FROM}: 没有一道是钟响了判死的`);
  process.exit(0);
}

/** 上一趟停在哪儿 —— 判卷台最后说的那句，拿来看这一趟值不值得再给两个钟。 */
const near = (result: string): string => {
  const note = (JSON.parse(result) as { note?: string }).note ?? "";
  const m = /"new_behaviours":"([^"]+)"/.exec(note);
  return m ? m[1] : "nothing gradable";
};

const tasks = rows.map((r) => {
  const task = r.id.slice(FROM.length + 1);
  return {
    // 新 id，**同一个位置** —— 那个容器里就是它上一趟干的活。
    id: `${RUN}/${task}`,
    place: r.place,
    mode: r.mode,
    agent: "bot",
    source: r.source,
    domain: r.domain,
    workdir: r.workdir,
    // 题面原样，后面补一句**这个工作区不是空的**。不说的话它多半从头再做一遍，
    // 而那正是这一趟不想要的：给的是接着干的时间，不是重来一次的时间。
    description:
      `${r.description}\n\n` +
      `## Where this starts\n\n` +
      `/app carries the work of an earlier attempt at this same task: its branch and its commits are there, ` +
      `and \`git log\` reads them. Nothing else from that attempt is here.\n` +
      `That attempt ran out of its wall-clock limit with ${near(r.result)} of the new behaviours passing.`,
    objective: objectiveOf(STAND),
    readable: r.readable === 1,
    maxBranches: r.max_branches,
    maxDeadSiblings: r.max_dead_siblings,
    ...(r.max_searches === null ? {} : { maxSearches: r.max_searches }),
    noSearch: JSON.parse(r.no_search) as string[],
    // 唯一另一个变的数：再给多久。
    solveSeconds: SECONDS,
  };
});

if (process.argv.includes("--dry")) {
  console.log(`${FROM} → ${RUN}: ${tasks.length} 道钟响了的，每道再给 ${SECONDS} 秒\n`);
  for (const [i, r] of rows.entries()) {
    console.log(`  ${r.id.slice(FROM.length + 1).padEnd(50)} ${near(r.result).padEnd(16)} → ${tasks[i].id}`);
  }
  console.log(`\n位置不变（同一个容器），题面、G、上限都是库里那一行原样搬的。`);
  process.exit(0);
}

/** 这一跑现在有几道还没做完。 */
async function busy(): Promise<number> {
  const r = await fetch(`${BASE}/bench/${RUN}`);
  if (!r.ok) return 0;
  const j = (await r.json()) as { running?: number; open?: number };
  return Number(j.running ?? 0) + Number(j.open ?? 0);
}

console.log(`${FROM} → ${RUN}: ${tasks.length} 道，每道 ${SECONDS} 秒${AT_ONCE > 0 ? `，同时 ${AT_ONCE} 道` : ""}`);
let sent = 0;
for (const t of tasks) {
  if (AT_ONCE > 0) while ((await busy()) >= AT_ONCE) await Bun.sleep(10_000);
  const r = await fetch(`${BASE}/tasks`, {
    method: "POST",
    headers: { "content-type": "application/json", ...PUBLISHER },
    body: JSON.stringify({ ...t, run: RUN }),
  });
  if (!r.ok) {
    const e = (await r.json()) as { error?: string };
    console.error(`${t.id} was refused: ${e.error}`);
    process.exit(1);
  }
  sent++;
  console.log(`  [${sent}/${tasks.length}] ${t.id.slice(RUN.length + 1)}`);
}
console.log(`${RUN}: all ${tasks.length} sent`);
