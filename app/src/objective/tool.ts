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
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { whereAmI } from "../tasks/where.ts";
import { evaluate } from "./run.ts";
import type { Sealed } from "./store.ts";

const VERIFY_TOOL = {
  name: "verify",
  does:
    "Submit a candidate answer to be graded. Returns whether it passes and, if not, why. " +
    "It never reveals the correct answer - only whether what you handed in meets the bar. " +
    "This is how you hand work in: the final grade is taken from the last answer you submit here.",
  params: {
    type: "object",
    properties: {
      answer: {
        type: "string",
        description: "The answer to submit, verbatim (keep the \boxed{} if the task asks for one). The grader reads this final text, not your derivation.",
      },
    },
    required: ["answer"],
  },
  output: {
    type: "object",
    properties: {
      pass: { type: "integer", description: "1 = passed, 0 = did not pass" },
      why: { type: "string", description: "Why it did not pass. Empty when it passed." },
      graded: { type: "string", description: "The exact text this verdict is about. If it passed, hand in this text unchanged." },
    },
  },
  prompt:
    "You may check a candidate with verify before handing it in. A verdict is about the exact text it echoes " +
    "back in `graded` and nothing else: change one character and it no longer applies. If a check passes, " +
    "hand that text in unchanged - do not rewrite it. " +
    "**Several checks in one turn cost the same as one.** Every tool call you make in a turn is run before you " +
    "are asked again, and the results come back together - so when a quantity could plausibly be any of a few " +
    "forms, check them all at once rather than one per turn. What is scarce is turns, not checks.",
  expectMs: 120_000,
};

/** 注册 `verify`。`sealed` 是封存区 —— G 的定义只在那儿，主库全接口开放也翻不出来。 */
export function registerVerifyTool(db: Conn, reg: Registry, sealed: Sealed): string {
  reg.register(db, `fn:tool.${VERIFY_TOOL.name}`, VERIFY_TOOL.expectMs, async (arg) => {
    const a = (arg ?? {}) as { args?: { answer?: unknown }; instance?: string };
    const answer = String(a.args?.answer ?? "");
    if (!answer.trim()) return { error: "answer is required - an empty one cannot be graded" };

    // 哪道题**从库里问**，不收调用方传的 —— 收的话模型改一个参数就能拿别人那道
    // 题的 G 来问自己这一道。
    const at = whereAmI(db, String(a.instance));
    if (!at) return { error: `cannot tell which task ${String(a.instance)} belongs to` };
    if (!sealed.has(at.task)) return { error: `${at.task} has no grading function, nothing to check against` };

    const g = sealed.open(at.task)!;
    const task = all(db, `select * from task where id = ?`, [at.task])[0] as Record<string, unknown> | undefined;
    // 形状跟 `tree/dfs.ts` 里那次一致 —— 同一个 G，同一批句柄，喂进去的东西
    // 不该因为「是谁问的」而变形。
    const v = await evaluate(g, reg, {
      task: { ...(task ?? {}), result: answer },
      chain: [],
      result: { kind: "prompt", body: answer },
    });
    // **回执带上判的是哪一份。** 只回一个 1 的话，隔几轮它就对不上号了 ——
    // 实测：模型验出过一份 equiv=True 的答案，后面又交了另一份。上下文里那条
    // `{pass:1, why:""}` 没说过的是哪一段，等于验了个寂寞。
    //
    // `trace`（每个节点算出了什么）仍然不回，那是给我们排障看的。
    return { pass: v.pass, why: v.why, graded: answer };
  });

  run(
    db,
    `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable)
     values (?, ?, ?, ?, ?, ?, 0, 0, null, 1)
     on conflict(name) do update set
       identity = excluded.identity, does = excluded.does, params = excluded.params,
       output = excluded.output, prompt = excluded.prompt, system = excluded.system`,
    [
      VERIFY_TOOL.name,
      `fn:tool.${VERIFY_TOOL.name}`,
      VERIFY_TOOL.does,
      JSON.stringify(VERIFY_TOOL.params),
      JSON.stringify(VERIFY_TOOL.output),
      VERIFY_TOOL.prompt,
    ],
  );
  run(db, `delete from trigger where owner_kind = 'tool' and owner = ?`, [VERIFY_TOOL.name]);
  run(
    db,
    `insert into trigger (owner_kind, owner, "group", dim, "key", op, value)
     values ('tool', ?, 0, 'task', 'objective', 'eq', 'sealed')`,
    [VERIFY_TOOL.name],
  );
  return VERIFY_TOOL.name;
}

