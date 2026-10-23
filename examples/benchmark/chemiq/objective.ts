/**
 * ChemIQ 这套题的 G。**一份定义，发批和续跑都读它。**
 *
 * 两个节点，句柄名就是台子的地址：
 *
 * ```
 *   parsed ──→ correct      parsed ：官方 AnswerParser 从回答里抠得出一个答案吗
 *                           correct：官方 AnswerVerifier.check_answer 说对吗（根）
 * ```
 *
 * 根**必须有入边** —— 没有的话它的值跟候选无关，G 恒定，发布这一关就拒（`objective/spec.ts`）。
 *
 * 这两格正好是官方 `analysis.ipynb` 里的两步：先 `parser.parse(uuid, raw)`，再
 * `verifier.check_answer(uuid, parsed)`。抠不出来的官方记成 False、直接判错。我们没有
 * 另立尺子，只是把官方那两步拆开两格读。
 *
 * 判卷只回 bool，题面是一句话短答 —— 所以这份 G 跟 cmt 一样薄。
 */

/**
 * **一轮里能问几次这个盒子。**
 *
 * 这套题有 226 道整数题（数碳 3–27、数环 1–6、最短路 3–20），答案空间小到能猜：
 * 问得多了，命中量的是答案空间不是它会不会数。给 3：够「答一版 → 验一次 → 照 note 改 →
 * 再验」一个来回，不够把 1–27 扫一遍。理由见 G.md「budget」。
 */
export const CHECKS = Number(process.env.TGENGIN_CHEMIQ_CHECKS ?? 3);

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
