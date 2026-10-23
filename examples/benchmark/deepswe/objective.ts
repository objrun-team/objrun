/**
 * 这套题的 G。**一份定义，发批和续跑都读它。**
 *
 * 两个节点，句柄名就是台子的地址：
 *
 * ```
 *   applies ──→ resolved      applies ：交出来的补丁打得上吗
 *                             resolved：官方判据说做成了吗（根）
 * ```
 *
 * 根**必须有入边** —— 没有的话它的值跟候选无关，G 恒定，那是个无效目标，
 * 发布这一关就拒（`objective/spec.ts`）。
 *
 * 而这两格正好是官方判据自己的两段：补丁打不上就写 `apply_failed=1` 并且**不跑测试**，
 * 打得上才跑两套（原有的 + 新加的）。我们没有另立一把尺子，只是把官方那把拆开两段读。
 *
 * **放在单独一个文件里**，是因为它有两个读者（`send.ts` 起一趟、`resume.ts` 把钟响了
 * 的那些接着跑）。各存一份的话，改了一处漏另一处不报错，表现是「两趟跑的不是同一道题」。
 * 库里那一行也拿不到它：G 的定义封在 sealed store 里，API 够不着（`tasks/publish.ts`）。
 */

/**
 * **一轮里能问几次这个盒子。**
 *
 * 判一次实测 3–97 秒（五种语言各量了一道），官方给判卷的上限是 1800 秒 —— 富余
 * 十几倍。**所以这个数不是成本问题，是意义问题**：它决定「命中」这件事是靠想清楚
 * 还是靠试。
 *
 * 给 6：够「做一版 → 验一次 → 照着 note 改 → 再验」来回三趟。
 */
export const CHECKS = Number(process.env.TGENGIN_DSW_CHECKS ?? 6);

export interface Objective {
  nodes: { name: string; moment: string; domain: string; handle: string }[];
  edges: { src: string; out: number; dst: string }[];
  sink: string;
  checks: number;
}

export function objectiveOf(stand: string, checks = CHECKS): Objective {
  return {
    nodes: [
      { name: "applies", moment: "task_done", domain: "bool", handle: `${stand}/applies` },
      { name: "resolved", moment: "task_done", domain: "bool", handle: `${stand}/resolved` },
    ],
    edges: [{ src: "applies", out: 0, dst: "resolved" }],
    sink: "resolved",
    checks,
  };
}
