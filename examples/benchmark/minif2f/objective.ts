/**
 * 这套题的 G。**一份定义，发批和续跑都读它。**
 *
 * 三个节点，句柄名就是台子的地址：
 *
 * ```
 *   stated ──→ compiles ──→ sound      stated  ：theorem 声明没被动过（跟原始陈述逐字比）
 *                                      compiles：Lean 编译没有 error
 *                                      sound   ：没有 sorry、公理只在允许的集合里（根）
 * ```
 *
 * 根**必须有入边** —— 没有的话它的值跟候选无关，G 恒定，那是个无效目标，
 * 发布这一关就拒（`objective/spec.ts`）。
 *
 * 这三格是 Lean 判卷本来就有的三段，不是另立的尺子：
 *
 * - `stated` 是 Lean 判卷特有的前置：题就是那条声明，改了声明就是换了题。台子送去
 *   编译的永远是官方声明 + 候选的证明体（DeepSeek-Prover-V1.5 的协议），这一格只是把
 *   「你交的前缀跟官方不一样」说出来。
 * - `compiles` = Kimina `is_error` 取反：REPL 回来的消息里没有 severity=error。
 * - `sound` = Kimina `has_sorry` 取反 + `#print axioms` 只见 Lean 那三条核心公理
 *   （默认再加 native_decide 的 `Lean.ofReduceBool`，榜上各家都认它）。
 *
 * 没有单独的 `kernel_ok`：Lean 每加一条声明内核就查一次，elaboration 没 error 就是内核过了。
 * 绕内核的路只有两条 —— 引公理（`sound` 里现形）、`set_option debug.skipKernelTC`（顶格的
 * 命令，`stated` 拦下）。第三格查不到更多东西，所以并进 `sound`。
 *
 * **放在单独一个文件里**，是因为它有两个读者（发批一趟、续跑一趟）。各存一份的话，
 * 改了一处漏另一处不报错，表现是「两趟跑的不是同一道题」。
 */

/**
 * **一轮里能问几次这个盒子。**
 *
 * 一次判卷 = 一次 Lean 编译，实测量级 5–60 秒（`maxHeartbeats 0`，300 秒墙上超时兜底）。
 * 答案空间是证明文本，m = ∞，枚举不出来 —— 所以这个数也不是防穷举的，是防「拿一串
 * hammer 一条条试」：`norm_num` / `nlinarith` / `omega` / `simp` / `decide` / `aesop`……
 * Kimina 公开的 197 份证明里 45 份是一行 tactic，那 18% 的题光靠试就能中。
 *
 * 给 12：够「写一版 → 编译 → 照着 open_goals 改 → 再编译」来回五六趟，
 * 不够把一张二三十条的 hammer 单子过一遍。
 */
export const CHECKS = Number(process.env.TGENGIN_MF2F_CHECKS ?? 12);

export interface Objective {
  nodes: { name: string; moment: string; domain: string; handle: string }[];
  edges: { src: string; out: number; dst: string }[];
  sink: string;
  checks: number;
}

export function objectiveOf(stand: string, checks = CHECKS): Objective {
  return {
    nodes: [
      { name: "stated", moment: "task_done", domain: "bool", handle: `${stand}/stated` },
      { name: "compiles", moment: "task_done", domain: "bool", handle: `${stand}/compiles` },
      { name: "sound", moment: "task_done", domain: "bool", handle: `${stand}/sound` },
    ],
    edges: [
      { src: "stated", out: 0, dst: "compiles" },
      { src: "compiles", out: 0, dst: "sound" },
    ],
    sink: "sound",
    checks,
  };
}
