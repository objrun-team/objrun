/**
 * 这套题的 G。**一份定义，发批和续跑都读它。**
 *
 * 两个节点，句柄名就是判卷台的地址：
 *
 * ```
 *   parsed ──→ correct       parsed ：答卷里解析得出一个 0–999 的整数吗
 *                            correct：这个整数跟官方答案相等吗（根）
 * ```
 *
 * 根**必须有入边** —— 没有的话它的值跟候选无关，G 恒定，那是个无效目标，
 * 发布这一关就拒（`objective/spec.ts`）。
 *
 * 这两格正好是 AIME 规则自己的两段：答案得是 0–999 的整数（答题卡只认三位数），
 * 然后相等。我们没有另立一把尺子，只是把官方那把拆开两段读。
 */

/**
 * **一轮里能问几次这个盒子。**
 *
 * 判一次是毫秒级，所以这个数不是成本问题，是意义问题。答案空间 m = 1000：
 * 只回对错的话，一次判卷只划掉一个数 —— 问 c 次加上交卷那一次，瞎猜命中率是
 * (c+1)/1000。给 10：瞎猜 1.1%，而「算出两三个候选逐个试」够用。
 *
 * 全预算 N = (K+1)(c+1)+1 = 100 < 1000，没有一道题是枚举可达的（见 G.md）。
 */
export const CHECKS = Number(process.env.TGENGIN_AIME_CHECKS ?? 10);

export interface Objective {
  nodes: { name: string; moment: string; domain: string; handle: string }[];
  edges: { src: string; out: number; dst: string }[];
  sink: string;
  checks: number;
}

export function objectiveOf(stand: string, checks = CHECKS): Objective {
  return {
    nodes: [
      { name: "parsed", moment: "task_done", domain: "bool", handle: `${stand}/parsed` },
      { name: "correct", moment: "task_done", domain: "bool", handle: `${stand}/correct` },
    ],
    edges: [{ src: "parsed", out: 0, dst: "correct" }],
    sink: "correct",
    checks,
  };
}
