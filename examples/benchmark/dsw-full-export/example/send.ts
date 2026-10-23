/**
 * 把 DeepSWE 的题拼成一批带 G 的任务，发给 `POST /bench`。
 *
 * ```
 * bun examples/benchmark/deepswe/send.ts [几道] [这一跑叫什么] [种子]
 * ```
 *
 * **它只干一件事：拼请求体** —— 一道题长什么样、G 长什么样，README 里有完整的一份。
 *
 * 题面进 `description`，参考解 **不进**，隐藏测试 **不进** —— 那两样不出台子那个进程。
 */

import { objectiveOf } from "./objective.ts";

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
const STAND = process.env.TGENGIN_DSW_STAND ?? "http://127.0.0.1:7902";
const HOW_MANY = Number(process.argv[2] ?? 10);
const RUN = process.argv[3] ?? `dsw-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}`;
const SEED = Number(process.argv[4] ?? process.env.TGENGIN_DSW_SEED ?? 0);
/**
 * **每道题最多给多久**，秒。官方 `task.toml` 那一栏是 10800（三小时），这儿封到
 * 7200（两小时），取两个里小的那个。`TGENGIN_DSW_SECONDS` 改这个上限。
 *
 * 时限比官方短，所以这一趟的分数跟榜上那些不是同一个实验 —— 榜上是三小时。
 */
const CAP_SECONDS = Number(process.env.TGENGIN_DSW_SECONDS ?? 7200);

/** 台子发过来的题面。**没有参考解,也没有隐藏测试。** */
interface Item {
  id: string;
  language: string;
  title: string;
  instruction: string;
  base_commit: string;
  /** 官方 `task.toml` 的 `[agent] timeout_sec`。**我们不另编一个数。** */
  seconds: number;
}

// **题从台子取,不从磁盘读。** 语料跟参考解在一起,装在台子那一侧（见 `setup.sh`）。
// 这个脚本跑在引擎那台机器上,读不到那个路径。
const res0 = await fetch(`${STAND}/problems?n=${HOW_MANY}&seed=${SEED}`);
if (!res0.ok) {
  console.error(`cannot fetch problems from the stand (${STAND}/problems): ${res0.status}`);
  process.exit(1);
}
const items = (await res0.json()) as Item[];

const objective = objectiveOf(STAND);

const tasks = items.map((it) => {
  // 官方那道题自己说的时限，跟这一趟的上限取小。
  const seconds = Math.min(it.seconds, CAP_SECONDS);
  return {
    /**
     * **id 得带上跑名。**
     *
     * `task.id` 是全局唯一的（`tasks/publish.ts`：重了当场拒），而 deepswe 的题号
     * 跨跑不变。写成裸题号的话，第一趟跑完就把那个名字占死了 —— 第二趟（换个级别、
     * 换个种子）整批发不出去，除非每次把库挪走重建。而**四个级别本来就是四趟**。
     */
    id: `${RUN}/${it.id}`,
    mode: "solve",
    agent: "bot",
    // **地址写法是我们自己的。** 位置由 `workplace.identity` 指着的那条句柄解析,
    // 内核不认得 `dsw:` —— 那正是加那一列的用处（`app/src/place/index.ts`）。
    //
    // 跑名也在里头：**一跑一个容器**。换个级别重跑的话，工作区是全新的，上一趟留下
    // 的东西渗不进来；同一趟里判死重来则共用同一个，那是有意的 —— 经验留着。
    place: `dsw:${RUN}/${it.id}`,
    source: "user",
    domain: "software",
    // 干活的地方是容器里的仓库根。
    workdir: "/app",
    /**
     * **每道题多久。** 官方那道题自己说的（`task.toml` 的 `[agent] timeout_sec`，
     * 现在是 10800 秒）跟这一趟的上限 `CAP_SECONDS` 取小 —— 现在是 7200。
     *
     * 时限要长过一次调用的死期,不能等于它：两个钟同时响的话任务那个先赢,
     * 「一次调用卡住 → 判死这一站 → 换个节点重来」那条路就永远走不到。
     */
    solveSeconds: seconds,
    // **只留时间这一个闸。** 额度、分支、判死重来的次数都给够 —— 卡在哪儿就该是
    // 「时间到了」,不该是「格子用完了」。
    maxBranches: 4,
    maxDeadSiblings: 8,
    /**
     * **不许搜。**
     *
     * 官方那套两侧都是 `no-network`,而我们的 `search` 不转发到 workplace（要的是
     * 网络和钥匙,不是那台机器上的文件系统,见 `main.ts`）—— 它是条真网络,而这套题
     * 的参考解就公开在 GitHub 上,按题目 id 一搜就是。
     *
     * 一个数都不给,那条工具在这一跑里根本不该摆出来（`run.sh` 里关掉它）。这几条
     * 是保险：万一哪次它又被摆出来了,这些词能挡住最直的那几条路。
     */
    noSearch: ["deepswe solution", "datacurve deep-swe", `${it.id} solution`],
    /** 官方题面，后面接这道题是怎么判的：判哪两点之间的 diff、交什么、时限多少。 */
    description:
      `${it.instruction}\n\n` +
      `## Grading\n\n` +
      `The repository is at /app, checked out at ${it.base_commit}.\n` +
      `What is graded is the diff from ${it.base_commit} to the commit whose sha is handed in. ` +
      `Changes left uncommitted in the working tree are not in that diff.\n\n` +
      `The wall-clock limit for this task is ${Math.round(seconds / 3600)} hours. ` +
      `Nothing reports how much of it is left.`,
    objective,
    // 带 G 就必须显式给：这道题的智能体读不读得到 G 的定义。
    //
    // **给 true。** 「补丁得打得上、原有的测试不许坏、题面列的行为要做出来」本来就该
    // 让它知道 —— 这套系统要量的是「给一个说得清楚的靶子,它能不能命中」,靶子藏起来
    // 量的就是别的东西了。
    readable: true,
  };
});

/**
 * **发之前先验一遍要丢给 G 的那个 HTTP 请求。**
 *
 * ```
 * bun examples/benchmark/deepswe/send.ts 10 dsw-l2 0 --dry
 * ```
 *
 * 验的不是「台子活着吗」（那是 `/health`），是**内核真会发出去的那个形状**：
 *
 * ```json
 * {"node":"applies","moment":"task_done","domain":"bool",
 *  "feed":[], "input":{"task":{…整行…},"chain":[],"result":{"kind":"prompt","body":"<sha>"}}}
 * ```
 *
 * 这一趟能当场发现的：句柄打不通、题号对不上（`id` 跟语料里那个不是一个）、
 * 回的东西不落值域（`bool` 那一格回了别的，G 会**归 0 并且不报错**）、
 * 上游判 0 时根节点没有短路。**一趟要跑几个钟头，这些错留到那时候发现就是整趟重来。**
 *
 * 这儿不起容器：那道题还没开工，`applies` 该说「取不到补丁」—— 那正是要看到的答案，
 * 说明它认出了题、走到了取补丁那一步。
 */
async function dryRun(): Promise<number> {
  console.log(`${RUN}: ${tasks.length} tasks assembled, nothing sent\n`);
  console.log("── 一道题的请求体（其余的只有 id / place / description 不同）──");
  console.log(JSON.stringify({ ...tasks[0], description: tasks[0].description.slice(0, 160) + " …" }, null, 2));

  console.log("\n── 拿内核真会发的形状打一遍 G ──");
  const shape = (node: string, task: (typeof tasks)[number], said: string, feed: unknown[]) => ({
    node,
    moment: "task_done",
    domain: "bool",
    feed,
    input: {
      task: { id: task.id, place: task.place, description: task.description, result: said },
      chain: [],
      result: { kind: "prompt", body: said },
    },
  });

  let bad = 0;
  const ask = async (url: string, body: unknown) => {
    const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`${r.status}`);
    return (await r.json()) as { value?: unknown; note?: unknown };
  };

  for (const t of tasks) {
    const line: string[] = [];
    let fine = true;
    try {
      // 那道题还没开工，所以这一问该判 0，而且得说得出「为什么」—— 取不到补丁。
      const a = await ask(objective.nodes[0].handle, shape("applies", t, "0000000000000000000000000000000000000000", []));
      // **值域封口**：`bool` 那一格必须回 bool。回别的的话 G 归 0 且不报错。
      if (typeof a.value !== "boolean") throw new Error(`applies returned ${typeof a.value}, not a bool`);
      if (a.value !== false) throw new Error(`applies said true for a task that has not started`);
      if (!a.note) throw new Error(`applies judged 0 but said nothing (note is empty)`);
      line.push(`applies=false note=${JSON.stringify(a.note).slice(0, 60)}`);

      // 上游判 0 的时候，根**不该再去判一次卷** —— 那是几十秒到几分钟。
      const t0 = Date.now();
      const r = await ask(objective.nodes[1].handle, shape("resolved", t, "0000000000000000000000000000000000000000", [{ from: "applies", out: 0, value: false }]));
      const ms = Date.now() - t0;
      if (typeof r.value !== "boolean") throw new Error(`resolved returned ${typeof r.value}, not a bool`);
      if (r.value !== false) throw new Error(`resolved said true behind a failed upstream`);
      if (ms > 5000) throw new Error(`resolved took ${ms}ms behind a failed upstream - it should short-circuit, not grade`);
      line.push(`resolved=false in ${ms}ms`);
    } catch (e) {
      bad++;
      fine = false;
      line.push(`FAILED: ${e instanceof Error ? e.message : String(e)}`);
    }
    console.log(`  ${fine ? "✓" : "✗"} ${t.id.padEnd(52)} ${line.join("  ")}`);
  }

  // 题号对不上的话，整趟跑完每道都判 0。
  console.log("\n── 题号对不上的时候它说得出来吗 ──");
  const ghost = await ask(objective.nodes[0].handle, shape("applies", { ...tasks[0], id: "no-such-task" }, "x", []));
  const knows = JSON.stringify(ghost.note ?? "").includes("not in the corpus");
  console.log(`  ${knows ? "✓" : "✗"} ${JSON.stringify(ghost)}`);
  if (!knows) bad++;

  console.log(`\n${bad === 0 ? `all ${tasks.length} tasks preflight clean` : `${bad} problems - nothing was sent`}`);
  return bad === 0 ? 0 : 1;
}

if (process.argv.includes("--dry")) process.exit(await dryRun());

/**
 * **同时做几道。** 0 = 整批一次全发出去。
 *
 * 内核那边是**来多少吃多少**：没出站过的行全部当场发出去。所以「同时做几道」这件事
 * 只能在发题这一侧管 —— 库里同时摆着几道没做完的，机器上就同时在做几道。
 *
 * 全集是 112 道。一次全发 = 112 个容器 + 112 个并发模型调用打给同一个供应商。
 * 它不会拒，它会排队 —— 而每道题的时限是按**墙上的钟**算的，于是题反而做不完。
 * 这台机器同时开十道时判卷已经要排队了（见台子日志的 `queued`）。
 *
 * **这是「同时 N 道」，不是「一批 N 道」**：做完一道补一道，不等这一批全做完。
 * 后者会被批里最慢的那道拖住整队。
 */
const AT_ONCE = Number(process.env.TGENGIN_DSW_AT_ONCE ?? 0);

/** 这一跑现在有几道还没做完（没开工的 + 在做的）。 */
async function busy(): Promise<number> {
  const r = await fetch(`${BASE}/bench/${RUN}`);
  if (!r.ok) return 0;
  const j = (await r.json()) as { running?: number; open?: number };
  return Number(j.running ?? 0) + Number(j.open ?? 0);
}

if (AT_ONCE > 0) {
  // 一道一道地发，发之前先看有没有空位。`POST /tasks` 那道准入检测是按题的
  // （G 过不了就拒这一道），所以拆开发不会松掉任何一条规矩 —— 但也就没有
  // 「一道不过整批不发」那层保护了，所以第一道要是被拒，这儿当场停。
  console.log(`${RUN}: ${tasks.length} tasks, keeping ${AT_ONCE} of them in flight (seed ${SEED})`);
  let sent = 0;
  let skipped = 0;
  for (const t of tasks) {
    while ((await busy()) >= AT_ONCE) await Bun.sleep(10_000);
    const r = await fetch(`${BASE}/tasks`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...t, run: RUN }),
    });
    if (!r.ok) {
      const e = (await r.json()) as { error?: string };
      // **这个名字已经在库里了 = 那一道上一趟发过了，跳过。** 一趟被打断之后接着发
      // 剩下的，就是这个形状：同一个跑名再走一遍，发过的按名字认出来。
      // 别的拒绝照旧当场停 —— 那些是这一趟本身有毛病。
      if ((e.error ?? "").includes("already exists")) {
        skipped++;
        continue;
      }
      console.error(`${t.id} was refused: ${e.error}`);
      process.exit(1);
    }
    sent++;
    console.log(`  [${String(sent + skipped)}/${tasks.length}] ${t.id.slice(RUN.length + 1)}`);
  }
  console.log(`${RUN}: ${sent} sent${skipped ? `, ${skipped} already there` : ""} (${tasks.length} in the corpus)`);
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
  console.log(`${got.run}: ${got.ids?.length} tasks (seed ${SEED})`);
  for (const it of items) console.log(`  ${it.id}  [${it.language}]`);
}
