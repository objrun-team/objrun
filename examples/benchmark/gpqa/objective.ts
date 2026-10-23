/**
 * GPQA Diamond 的 G。**一份定义，发批和续跑都读它。**
 *
 * 两个节点，句柄名就是台子的地址：
 *
 * ```
 *   parsed ──→ correct       parsed ：官方正则从回答里抠得出一个 A–D 吗
 *                            correct：抠出来的那个字母是不是正确选项（根）
 * ```
 *
 * 根**必须有入边**（`objective/spec.ts`：没有的话 G 恒定，发布就拒）。这两格正好是
 * 官方 `run_baseline.py` 自己的两步：`parse_sampled_answer` 回 None 就记一次 refusal
 * 并且**不比对**，抠得出来才 `LETTER_TO_INDEX[letter] == correct_index`。我们没有另立
 * 一把尺子，只是把官方那把拆开两段读。
 */

/**
 * **一轮里能问几次这个盒子。**
 *
 * 四选一，m = 4。按 N = (K+1)(c+1)+1，**只要 c ≥ 1 且 K ≥ 1 就 N ≥ 5 ≥ m** ——
 * 全部 198 道都枚举可达，问几次都是在量「答案空间多大」而不是「会不会做」。
 * 所以这儿给 1，而且 K 也该给 0（见 G.md「答案空间」）。
 *
 * **给不了 0。** `parseObjective` 把 0 当「没给」，换成默认的 5（`objective/spec.ts`）。
 * 1 已经是内核能表达的最小值。
 */
export const CHECKS = Number(process.env.TGENGIN_GPQA_CHECKS ?? 1);

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
