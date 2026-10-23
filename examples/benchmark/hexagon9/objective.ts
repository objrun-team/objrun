/**
 * 九圈六边形振幅（平面 N=4 SYM，六胶子 MHV）的 G。草稿，未跑。
 *
 *   parsed ──→ hexagon ──→ physical ──→ antipodal
 *
 *   parsed   ：格式 —— 9 字母、权 18、余积坐标维数对得上、系数域是 ℚ ⊕ ℚ·MZV
 *   hexagon  ：定义 —— 可积、首项 ∈ {u,v,w}、(扩展) Steinmann；即"它是一个六边形函数"
 *   physical ：理论 —— 二面体对称、末项、共线归一、MRK 消失 + 全阶 BFKL、OPE 领头阶 = 通量管
 *   antipodal：独立路线 —— 反足映射后满足三点形状因子那套约束（根）
 *
 * 四格都是线性代数与极限展开，没有 LLM 判卷；也没有 gold —— 唯一解即答案。
 * 根建立在两条未证明的对偶/原理（反足对偶、扩展 Steinmann）上，record 必须写明。
 * 与 minif2f 的根本差别：一次判卷是小时到天，判卷成本 ≈ 求解成本。
 */

/** 一轮里能问几次。一次判卷小时级起步，候选不是"试一下"能改的，给 3。 */
export const CHECKS = Number(process.env.TGENGIN_HEX9_CHECKS ?? 3);

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
      { name: "hexagon", moment: "task_done", domain: "bool", handle: `${stand}/hexagon` },
      { name: "physical", moment: "task_done", domain: "bool", handle: `${stand}/physical` },
      { name: "antipodal", moment: "task_done", domain: "bool", handle: `${stand}/antipodal` },
    ],
    edges: [
      { src: "parsed", out: 0, dst: "hexagon" },
      { src: "hexagon", out: 0, dst: "physical" },
      { src: "physical", out: 0, dst: "antipodal" },
    ],
    sink: "antipodal",
    checks,
  };
}
