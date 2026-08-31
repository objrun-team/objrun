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
  // **一轮里能问几次这个黑盒。** 跟干活的额度配着给：一轮二十格，问十次是宽的 ——
  // 够它「算出来 → 验一次 → 照着 why 改 → 再验」来回好几趟。
  //
  // 有上限这件事本身才是要紧的：不设的话，最省事的策略是把答案空间枚举一遍
  // （实测过一道题被连着试了七十七个排列组合），而那样得来的分数量的是答案空间
  // 有多大，不是它会不会做。
  checks: 10,
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
  // **时限要长过一次调用的死期，不能等于它。** 模型那条句柄的 `expect_ms` 是 15 分钟；
  // 时限也给 15 分钟的话，两个钟同时响，而任务那个先赢 —— 于是「一次调用卡住 →
  // 判死这一站 → 换个节点重来」那条路永远走不到，整道题跟着一次抖动一起没。
  //
  // 而且 15 分钟本身就不够：实测慢的那几道走到第七站才用掉十二格额度里的四格，
  // 时间先没了 —— 它们从来没走到过交卷站，连一份错答案都交不出来。
  solveSeconds: 3600,
  // **只留时间这一个闸。** 额度、分支、判死重来的次数都给够 —— 卡在哪儿就该是
  // 「时间到了」，不该是「格子用完了」。哪一样先撞上，成绩单说的就是哪一样，
  // 而我们想量的是前者。
  maxBranches: 4,
  maxDeadSiblings: 8,
  /**
   * **不许搜到这套题本身。**
   *
   * 搜文献是本事 —— 题目的物理就发表在某篇论文里，找到它、读懂它、照着推，那是解题。
   * 搜到**这套基准的答案册**不是：那量的是「这份数据集好不好扒」。
   *
   * 这条不是假想。实测一跑：十五分钟里 834 个开过的页面，**143 个落在这份数据集
   * 上**，而且绕得很有章法 ——
   *
   * ```
   * huggingface.co/datasets/…/resolve/main/cmt_data.jsonl    主站
   * hf-mirror.com/…/raw/main/cmt_data.jsonl                  主站不通换镜像
   * r.jina.ai/https://…/cmt_data.jsonl                       镜像不通换文本代理
   * web.archive.org/web/…/rows?…&offset=1&length=1            再不通换存档站
   * ```
   *
   * 查询串直接写着 `cmt_benchmark row 1 answer`、`"cmt_benchmark" "answer": "$\Delta"`，
   * 甚至拿着答案原文回去反查数据集。那一跑它得手了，轨迹里留着一句
   * 「The web search found the reference answer」。
   *
   * 所以**按域名挡不住** —— 每条备用路都得单列一遍，而下一条永远列不到。
   *
   * ## 不能是连写的，而且一条不够
   *
   * 列 `cmt_benchmark` 这种连写太松：同一跑里它还摸到了第三方的一份拷贝
   * （`Infektyd/syntra-evals-dataset/…/cmt-physics.jsonl`），名字完全不一样，
   * 连写那条一个都拦不住 —— 可那照样是答案册。
   *
   * 所以一条项是**一组词，全都出现才算命中**（见 `tools/search.ts` 的 `tripped`）：
   * 中间隔着什么、连字符还是下划线、顺序如何，一概不管。
   *
   * 那为什么不是一条 `"cmt benchmark"` 就完了 —— 拿那一跑真实的 168 次检索量过：
   *
   * | 判据 | 漏 | 误伤 |
   * | --- | --- | --- |
   * | `cmt benchmark` | **5** | 0 |
   * | `cmt` | 0 | **1** |
   * | 下面这三条 | **0** | **0** |
   *
   * 漏的那 5 次是它**直接拉原始 jsonl**：返回里有 `cmt`，却没有 `benchmark` 这个词。
   * 只列 `cmt` 又会误伤正经文献。三条各挡一种说法，多列两条不花什么代价，而少列
   * 一条就是那个洞。
   */
  noSearch: ["cmt benchmark", "cmt dataset", "cmt jsonl"],
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

/**
 * **同时做几道。** 0 = 不管，整批一次全发出去（老行为）。
 *
 * 内核那边是**来多少吃多少**：没出站过的行全部当场发出去。所以「同时做几道」
 * 这件事只能在发题这一侧管 —— 库里同时摆着几道没做完的，机器上就同时在做几道。
 *
 * 为什么要管：五十道一起发，就是五十个并发调用一起打给同一个供应商。它不会拒，
 * 它会排队 —— 实测二十道并发时每次调用的耗时中位数就到了一分半、长尾十分钟。
 * **吞吐没涨，延迟涨了**，而每道题的时限是按墙上的钟算的，于是题反而做不完。
 *
 * **这是「同时二十道」，不是「一批二十道」**：做完一道就补一道进去，而不是等
 * 二十道全做完再发下一批。后者会被那一批里最慢的一道拖住整队。
 */
const AT_ONCE = Number(process.env.TGENGIN_CMT_AT_ONCE ?? 0);

/** 这一跑现在有几道还没做完（没开工的 + 在做的）。 */
async function busy(): Promise<number> {
  const r = await fetch(`${BASE}/bench/${RUN}`);
  if (!r.ok) return 0;
  const j = (await r.json()) as { running?: number; open?: number };
  return Number(j.running ?? 0) + Number(j.open ?? 0);
}

if (AT_ONCE > 0) {
  // 一道一道地发，发之前先看有没有空位。`POST /tasks` 那道准入检测是按题的
  // （G 过不了就拒这一道），所以拆开发不会松掉任何一条规矩。
  console.log(`${RUN}: ${tasks.length} tasks, keeping ${AT_ONCE} of them in flight`);
  let sent = 0;
  for (const t of tasks) {
    while ((await busy()) >= AT_ONCE) await Bun.sleep(5000);
    const r = await fetch(`${BASE}/tasks`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...t, run: RUN }),
    });
    if (!r.ok) {
      const e = (await r.json()) as { error?: string };
      console.error(`${t.id} was refused: ${e.error}`);
      process.exit(1);
    }
    sent++;
    if (sent % 5 === 0 || sent === tasks.length) console.log(`  sent ${sent}/${tasks.length}`);
  }
  console.log(`${RUN}: all ${tasks.length} sent`);
} else {
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
}
