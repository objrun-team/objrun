/**
 * ChemBench 的 G。**一份定义，发批和续跑都读它。**
 *
 * 两个节点，句柄名就是台子的地址：
 *
 * ```
 *   parsed ──→ correct      parsed ：官方解析器从这份回答里读得出一个答案吗
 *                           correct：官方判据说全对吗（根）
 * ```
 *
 * 根**必须有入边** —— 没有的话它的值跟候选无关，G 恒定，那是个无效目标，
 * 发布这一关就拒（`objective/spec.ts`）。
 *
 * 而这两格正好是官方 pipeline 自己的两段（`prompter.BasePrompter._process_single_result`）：
 * 先 `prepare_mcq_answer` / `prepare_general_answer` 读答案，读出来才 `_calculate_metrics`
 * 算 `all_correct`。我们没有另立一把尺子，只是把官方那把拆开两段读。
 *
 * 台子那边（`stand.py`）解析失败不走 LLM 兜底 —— 官方那条兜底是「不按格式答也给分」，
 * 不确定，不包。`parsed` 判 0 时的 note 会把格式要求说给它。
 */

/**
 * **一轮里能问几次这个盒子。**
 *
 * 判一次是纯正则加一次浮点比较，毫秒级 —— 所以这个数跟成本无关，只跟意义有关。
 * ChemBench 的答案空间小到离谱：2542 道选择题里 1013 道只有两个选项，898 道四选一。
 * 问一次就是排除一个选项。**给 1**：够「答一版 → 验一次 → 照着 note 改 → 交卷」，
 * 多一次都是在枚举。哪怕这样，四选一也在 (K+1)(c+1)+1 = 7 次里枚举得完 ——
 * 这是题目的性质，不是这个数能救的（G.md「答案空间 m」那一节）。
 */
export const CHECKS = Number(process.env.TGENGIN_CHB_CHECKS ?? 1);

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
