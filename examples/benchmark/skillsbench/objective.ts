/**
 * SkillsBench 1.1 的 G。**一份定义，发批和续跑都读它。**
 *
 * 两个节点，句柄名就是台子的地址：
 *
 * ```
 *   verified ──→ passed      verified：官方 verifier/test.sh 跑完、写出了 reward.txt
 *                            passed  ：reward == 1.0（根）
 * ```
 *
 * 根**必须有入边** —— 没有的话它的值跟候选无关，G 恒定，发布那一关就拒（`objective/spec.ts`）。
 *
 * 这两格正好是官方 harness 自己的两步：跑 `test.sh`，读 `/logs/verifier/reward.txt`。
 * 文件没写出来（崩了、超时、OOM）和写了个 0 在榜上都是 0，但对求解器是两种信息 ——
 * 前者多半是环境不是答案。我们没另立尺子，只是把官方那把拆开两段读。
 *
 * **判据是二值的。** 论文：reward = 1 当且仅当 test_outputs.py 的断言全过。7 道题的
 * test.sh 写的是分数（47/48 = 0.979），榜单 `mean(reward)` 给部分分，这儿只认 1.0 ——
 * 跟论文一致，跟榜单在那 7 道上差一点（更严）。分数进 `note`，事后要算榜单口径能算。
 */

/**
 * **一轮里能问几次这个盒子。**
 *
 * 一次判卷是一趟 pytest（几十秒到几分钟；官方给判卷的上限 `verifier.timeout_sec`
 * 中位 1800 秒）。所以这个数不是成本问题，是意义问题：给 6，够「做一版 → 验一次 →
 * 照着 note 改 → 再验」来回三趟，不够穷举 —— 何况产物是整个文件，穷举无从谈起。
 */
export const CHECKS = Number(process.env.TGENGIN_SKB_CHECKS ?? 6);

export interface Objective {
  nodes: { name: string; moment: string; domain: string; handle: string }[];
  edges: { src: string; out: number; dst: string }[];
  sink: string;
  checks: number;
}

export function objectiveOf(stand: string, checks = CHECKS): Objective {
  return {
    nodes: [
      { name: "verified", moment: "task_done", domain: "bool", handle: `${stand}/verified` },
      { name: "passed", moment: "task_done", domain: "bool", handle: `${stand}/passed` },
    ],
    edges: [{ src: "verified", out: 0, dst: "passed" }],
    sink: "passed",
    checks,
  };
}
