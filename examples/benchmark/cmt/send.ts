/**
 * 把 `cmt_data.jsonl` 拼成一批带 G 的题，发给 `POST /bench`。
 *
 * ```
 * bun examples/benchmark/cmt/send.ts [几道] [这一跑叫什么]
 * ```
 *
 * 50 道题没法在文档里一条条 curl，所以有这么个脚本。**它只干一件事：拼请求体**
 * —— 一道题长什么样、G 长什么样，README 里有完整的一份。
 *
 * 题面进 `description`，`solution` **不进** —— 智能体那一侧看不到答案。
 */

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
const GRADER = process.env.TGENGIN_CMT_GRADER ?? "http://127.0.0.1:7901";
const HOW_MANY = Number(process.argv[2] ?? 0);
const RUN = process.argv[3] ?? `cmt-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}`;

/** 判卷台发过来的题面。**没有 `solution`** —— 那一栏不出它的进程。 */
interface Item {
  index: number;
  prompt: string;
  parameters: string;
  functions: string;
  type: string;
}

// **题从判卷台取，不从磁盘读。**
//
// 题库跟答案在一起，装在判卷台那一侧（见 `setup.sh`）。这个脚本跑在引擎那台机器上，
// 读不到那个路径 —— 那正是我们要的：solver 手上有 read / glob / bash，干活的地方
// 就是这台机器，题库放这儿的话它 glob 一下就找到（实测它已经摸到门口了）。
//
// 所以走 HTTP 取题：`/problems` 只回题面，`solution` 一个字都不过来。
const res0 = await fetch(`${GRADER}/problems${HOW_MANY > 0 ? `?n=${HOW_MANY}` : ""}`);
if (!res0.ok) {
  console.error(`cannot fetch problems from the grader (${GRADER}/problems): ${res0.status}`);
  process.exit(1);
}
const items = (await res0.json()) as Item[];

/**
 * 每道题的 G。两个节点，**句柄名就是判卷台的地址**：
 *
 * ```
 *   parsed ──→ equiv        parsed：给没给出 \boxed{}
 *                           equiv ：跟 GT 等不等价（根）
 * ```
 *
 * 根**必须有入边** —— 没有的话它的值跟候选无关，G 恒定，那是个无效目标，
 * 发布这一关就拒。而这两格正好是原基准自己报的那两栏（`parse` / `equiv`）。
 */
const objective = {
  nodes: [
    { name: "parsed", moment: "task_done", domain: "bool", handle: `${GRADER}/parsed` },
    { name: "equiv", moment: "task_done", domain: "bool", handle: `${GRADER}/equiv` },
  ],
  edges: [{ src: "parsed", out: 0, dst: "equiv" }],
  sink: "equiv",
};

const tasks = items.map((it) => ({
  id: `cmt-${it.index}`,
  mode: "solve",
  agent: "bot",
  place: "local",
  source: "user",
  // 这是哪一类问题。**扩展按它分发** —— 跟 `mode`（推理机制）是两回事。
  // 平的一个值，不往里塞层级：要收紧就在 `when` 里跨维多写几条条件。
  domain: "physics",
  // The budget has to be big enough for the mechanism to run at all. One attempt takes
  // five or six turns in practice; with a budget of six, the first hand-in lands exactly
  // when the budget is gone, so a verdict of 0 can never be followed by a second attempt
  // - verifier-guided retry never runs. Two attempts need twice that.
  //
  // This is room to run, not tuning: picking numbers by watching this dataset would be
  // fitting the benchmark, and the score would mean nothing.
  solveSeconds: 900,
  maxBranches: 2,
  maxDeadSiblings: 3,
  description:
    `${it.prompt}\n\n` +
    (it.parameters ? `Symbols: ${it.parameters}\n` : "") +
    (it.functions ? `Functions: ${it.functions}\n` : "") +
    `\nPut the final answer inside \\boxed{}.`,
  objective,
  // 带 G 就必须显式给：这道题的智能体读不读得到 G 的定义。
  //
  // **给 true。** 要藏的只有 GT，不是验收标准 —— 「答案得在 \boxed{} 里、
  // 而且要被官方 parser 读得出来」本来就该让它知道。藏着的那一跑五道里两道
  // 死在 parsed=False：不是不会做，是不知道尺子长什么样。
  readable: true,
}));

const res = await fetch(`${BASE}/bench`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ run: RUN, tasks }),
});
const got = (await res.json()) as { run?: string; ids?: string[]; error?: string };
if (!res.ok) {
  console.error(`the whole batch was not sent: ${got.error}`);
  process.exit(1);
}
console.log(`${got.run}: ${got.ids?.length} tasks`);
