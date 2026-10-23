/**
 * `verify` —— **让模型自己去问 G**。
 *
 * ## 为什么这是个真工具
 *
 * 判死之后，判决本来就会投进上下文（`msg/deliver.ts` 的 `deliverVerdict`），投的
 * 形状是「一次带结果的工具调用」，名字就叫 `verify`。可那之前它并**不是**一个注册
 * 过的工具 —— 于是上下文里躺着一条 `role: assistant` 的行写着「我调用了 verify」，
 * 而模型真去调就报「tool 表里没有 verify」。**看起来是工具，其实调不动**，
 * 那是在伪造它自己的轨迹。
 *
 * 补上它，那条轨迹就名副其实了。
 *
 * ## 让它看得见目标，不是漏题
 *
 * 要藏的只有一样：**GT**。至于「验收标准是什么」「我这份达标没有」——
 * 知道这两件事本来就是干活的一部分，藏起来只会让它在标准上翻车而不自知
 * （实测：五道里两道死在 `parsed=False`，是格式没合上官方 parser 的口径，
 * 不是不会做）。
 *
 * 所以这个工具回的是 `{pass, why}`：**过没过、为什么没过**。
 * 不回 `trace`（每个节点算出了什么），更不回题库里那份答案 —— 判卷台那一侧
 * 压根不往外发 `solution`。
 *
 * ## 次数由树管，不由保密管
 *
 * 「无限刷就成了完美 oracle 下的 best-of-N」是真的，但那是**预算**问题：
 * `max_branches` / `max_dead_siblings` / `solve_seconds` 就是那几个闸。
 * 靠「它找不到判卷台」来限次数是幻觉 —— 判决本来每轮就送到它面前。
 *
 * ## 分发条件：这道题有没有 G
 *
 * 不按 mode 分（`task_tree` 那两个才是只有走树才有意义）。**有 G 就该能问 G**，
 * 单链机制也一样。条件落进 `trigger`，跟别的工具走同一张表：
 * `task.objective = 'sealed'`。
 */

import type { Conn } from "../H2H/db.ts";
import { CANDIDATE } from "./store.ts";
import { SUBMIT } from "../tree/dfs.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { whereAmI } from "../tasks/where.ts";
import { tableNameOf } from "../install/index.ts";
import { declareTool } from "../tools/register.ts";
import { candidateInput, evaluate } from "./run.ts";
import type { Sealed } from "./store.ts";

const VERIFY_TOOL = {
  name: "verify",
  does:
    "Check one candidate answer against the bar for this task. Says whether it meets the bar and, when it does " +
    "not, what is wrong with it. It does not return the correct answer.",
  params: CANDIDATE,
  output: {
    type: "object",
    properties: {
      pass: { type: "integer", description: "1 = meets the bar, 0 = does not" },
      valid: { type: "boolean", description: "Whether the grader completed successfully. An unavailable grader is not an incorrect answer." },
      outcome: { type: "string", description: "passed, rejected, or grader_error" },
      why: { type: "string", description: "What is wrong with it. Empty when it passed." },
      note: { type: "string", description: "Whatever the bar itself had to add about this answer. Empty when it passed, and empty when the bar has nothing to add." },
      graded: { type: "string", description: "The exact text this verdict is about. If it passed, hand in this text unchanged." },
      left: { type: "integer", description: "How many checks remain in this attempt" },
    },
  },
  prompt:
    "The number of checks per attempt is fixed before the attempt starts; every completed grading decision spends one, pass or fail. Grader errors do not spend a check. " +
    "`left` says how many remain. A verdict applies to the exact text echoed back in `graded` and to nothing else.",
  expectMs: 120_000,
};

/** 注册 `verify`。`sealed` 是封存区 —— G 的定义只在那儿，主库全接口开放也翻不出来。 */
export function registerVerifyTool(db: Conn, reg: Registry, sealed: Sealed): string {
  reg.register(db, `fn:tool.${VERIFY_TOOL.name}`, VERIFY_TOOL.expectMs, async (arg) => {
    const a = (arg ?? {}) as { args?: { answer?: unknown }; instance?: string; agent?: string; unit?: number };
    const answer = String(a.args?.answer ?? "");
    if (!answer.trim()) return { error: "answer is required - an empty one cannot be graded" };

    // 哪道题**从库里问**，不收调用方传的 —— 收的话模型改一个参数就能拿别人那道
    // 题的 G 来问自己这一道。
    const at = whereAmI(db, String(a.instance));
    if (!at) return { error: `cannot tell which task ${String(a.instance)} belongs to` };
    if (!sealed.has(at.task)) return { error: `${at.task} has no grading function, nothing to check against` };

    const g = sealed.open(at.task)!;
    const task = all(db, `select * from task where id = ?`, [at.task])[0] as Record<string, unknown> | undefined;

    // ── 一轮里只许验这么几次 ──────────────────────────────────────────────
    //
    // **没有上限的话，最省事的策略是把答案空间枚举一遍。** 实测过：一道选项题
    // 被连着试了七十七个排列组合（`b;a` / `c;d` / `b;c;d` / `b;a;c;d` …），一次
    // 推理都没有。那样得来的分数量的是答案空间有多大，不是它会不会做。
    //
    // 而且**执行单元那个额度拦不住它**：一次请求可以带很多个工具调用，一格里
    // 试二十次跟试一次一样贵。所以闸得按「问了 G 几次」来算，不是按走了几站。
    //
    // 上限由**发布方**定（`task.max_checks`）。一轮 = 一个节点：判死之后开的新
    // 节点是一次全新的尝试，额度也是新的。**交卷那一次不算** —— 那一次是内核
    // 替它问的，落的是 `graded` 行，不是它自己调的 `call`。
    // **额度是 G 的性质，不是任务的** —— 能问几次，问的是这个盒子经得起被问几次。
    // 绑在任务上的话，同一个 G 换个发布方就能被问一百次，那道墙等于没有。
    const here = numberOf(sealed.checksOf(at.task), 5);
    const spent = checksIn(db, {
      sub: at.sub,
      task: at.task,
      agent: String(a.agent ?? ""),
      instance: String(a.instance ?? ""),
      unit: Number(a.unit ?? 0),
    });
    if (spent >= here) {
      return {
        error:
          `the ${String(here)} checks for this attempt are spent. A check is for finding the mistake in your ` +
          `reasoning, not for trying answers one after another - work out what the last verdict told you, and ` +
          `hand in what you get. What you hand in is graded either way.`,
        left: 0,
      };
    }

    // 形状跟 `tree/dfs.ts` 里那次一致 —— 同一个 G，同一批句柄，喂进去的东西
    // 不该因为「是谁问的」而变形。
    const v = await evaluate(g, reg, candidateInput(task ?? {}, answer));
    if (!v.valid) return { valid: false, outcome: "grader_error", error: v.why || "the grader did not complete", graded: answer, left: here - spent };
    // **回执带上判的是哪一份。** 只回一个 1 的话，隔几轮它就对不上号了 ——
    // 实测：模型验出过一份 equiv=True 的答案，后面又交了另一份。上下文里那条
    // `{pass:1, why:""}` 没说过的是哪一段，等于验了个寂寞。
    //
    // `trace`（每个节点算出了什么）仍然不回，那是给我们排障看的。
    return { pass: v.pass, valid: v.valid, outcome: v.outcome, why: v.why, note: v.note, graded: answer, left: here - spent - 1 };
  });
  // **落库走同一条路。** 以前这儿是手写的一条 upsert 加两条 `insert into trigger`，
  // 跟 `register.ts` 里那份各写各的 —— 而它们已经漂开了一列（那边更新
  // `concurrent`，这边不更新）。现在两边都调 `declareTool`。
  declareTool(db, {
    ...VERIFY_TOOL,
    concurrent: false,
    // **判决拿不回来。** 再问一次 G 要 3–97 秒（五种语言各量了一道），而且那次调用
    // 花的是这一轮的额度 —— 压上下文的时候它跟一次跑了四分钟的测试是一类东西。
    gives: "event",
    // 两条同一组 = AND：**这道题有 G，而且这一站不是交卷站。**
    //
    // 第一条：有 G 就该能问 G，不按 mode 分 —— 单链机制也一样。
    //
    // 第二条：跑工具的只有动作站（`api_mode` 为空、走 `agent.unit` 的那个），而交卷
    // 站是模型站、它的下一站也是模型站 —— 模型在那儿请求的任何工具都没有人会去跑，
    // 那次调用会一直挂着，直到补齐给它写一条「没跑成」。实测的样子：模型在交卷站调
    // `submit`，拿回一句「没跑成」。而交卷本来就不需要工具：交的是它说的话。
    when: [
      [
        { dim: "task", key: "objective", op: "eq", value: "sealed" },
        { dim: "cycle", key: "cycle", op: "ne", value: SUBMIT },
      ],
    ],
  });
  return VERIFY_TOOL.name;
}

function numberOf(v: unknown, fallback: number): number {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

/**
 * 这一轮已经**用掉**几次检查。**一轮 = 一个节点。**
 *
 * 数的是**拿到过判决的次数**，不是它调了几次：
 *
 * - 一轮里那几个调用可能**在同一行里**（一次请求可以带很多个工具调用）。按行数的话，
 *   第一个执行的时候就已经看见五个了，于是五个全被拦 —— 而它其实一次都还没用过
 * - 被拦下的那几次**不该扣数**：它没拿到任何关于候选的信息，凭什么算一次
 *
 * 工具结果是一个一个落的，所以按判决数天然就对：前几个拿到判决，后面的看见额度
 * 用完了被拦，而拦下来的不产生判决、也就不占额度。
 *
 * **交卷那一次不算** —— 那是内核替它问的（id 以 `g-` 开头，落的是 `graded` 那一对），
 * 不是它自己调的检查。
 *
 * 没有节点这一列的机制（不走树的那些）就按整条实例数：那种机制本来也只有一轮。
 */
function checksIn(db: Conn, at: { sub: string; task: string; agent: string; instance: string; unit: number }): number {
  const sub = at.sub;
  if (!at.agent || !at.instance) return 0;

  let units: number[] = [];
  try {
    const me = all(db, `select node from "${sub}" where task = ? and unit = ?`, [at.task, at.unit])[0] as
      | { node?: number }
      | undefined;
    const rows =
      me?.node === undefined || me.node === null
        ? (all(db, `select unit from "${sub}" where task = ?`, [at.task]) as { unit: number }[])
        : (all(db, `select unit from "${sub}" where task = ? and node = ?`, [at.task, me.node]) as { unit: number }[]);
    units = rows.map((r) => Number(r.unit));
  } catch {
    return 0; // 这张表还没长出来，那就还没用过
  }
  if (units.length === 0) return 0;

  const t = tableNameOf("agent_{}_msg", at.agent);
  const rows = all(
    db,
    `select body from "${t}" where instance = ? and kind = 'tool' and unit in (${units.map(() => "?").join(", ")})`,
    [at.instance, ...units],
  ) as { body: string }[];

  let n = 0;
  for (const r of rows) {
    try {
      const v = JSON.parse(r.body) as { id?: string; name?: string; value?: { pass?: unknown; valid?: unknown; outcome?: unknown } };
      if (v.name !== VERIFY_TOOL.name) continue;
      if (String(v.id ?? "").startsWith("g-")) continue; // 交卷那一次
      if (v.value?.valid === false || v.value?.outcome === "grader_error") continue;
      if (v.value?.pass !== 0 && v.value?.pass !== 1) continue;
      n++;
    } catch {
      // 读不出来的行不算
    }
  }
  return n;
}
