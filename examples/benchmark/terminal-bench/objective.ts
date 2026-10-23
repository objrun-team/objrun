/**
 * 这套题的 G。**一份定义，发批和续跑都读它。**
 *
 * 两个节点，句柄名就是台子的地址：
 *
 * ```
 *   ran ──→ passed      ran   ：官方 tests/test.sh 在它的容器里跑完了、写出了一份读得懂的 reward
 *                       passed：那份 reward == 1（根）
 * ```
 *
 * 根**必须有入边** —— 没有的话它的值跟候选无关，G 恒定，发布这一关就拒（`objective/spec.ts`）。
 *
 * 这两格正好是官方判据自己的两段：harbor 先跑 `test.sh`，再用 `_parse_reward_text` 读
 * `/logs/verifier/reward.txt` —— 读不出来（没写、空、非数）是一种失败，读出来是 0 是另一种。
 * 我们没有另立一把尺子，只是把官方那把拆开两段读。deepswe 那边叫 applies → resolved。
 *
 * 跟 deepswe 不同的一点：**候选不是一份补丁，是容器本身。** 求解器交上来的字符串只是这一份
 * 候选的名字（把两格对到同一次判卷），内容不参与判断。
 */

/**
 * **一轮里能问几次这个盒子。**
 *
 * 判一次 = 在活容器里跑一遍 test.sh：装 uv、跑 pytest，几十秒到几分钟，官方上限
 * 900–12000 秒。而且**每判一次容器就被改一次**（test.sh 自己 apt-get），并且隐藏测试有
 * 几十秒在求解器的文件系统里可见。所以这个数比 deepswe 的 6 再紧一格。
 *
 * 给 4：够「做一版 → 验一次 → 照着 note 改 → 再验」来回两趟。
 */
export const CHECKS = Number(process.env.TGENGIN_TB_CHECKS ?? 4);

export interface Objective {
  nodes: { name: string; moment: string; domain: string; handle: string }[];
  edges: { src: string; out: number; dst: string }[];
  sink: string;
  checks: number;
}

export function objectiveOf(stand: string, checks = CHECKS): Objective {
  return {
    nodes: [
      { name: "ran", moment: "task_done", domain: "bool", handle: `${stand}/ran` },
      { name: "passed", moment: "task_done", domain: "bool", handle: `${stand}/passed` },
    ],
    edges: [{ src: "ran", out: 0, dst: "passed" }],
    sink: "passed",
    checks,
  };
}
