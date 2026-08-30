/**
 * 一个推断函数：**这一站走完之后去哪儿。**
 *
 * 内核只认三种回答：
 *
 * | 回什么 | 意思 |
 * | --- | --- |
 * | `null` | 到此为止 |
 * | `"周期名"` | 走那个周期，**从当前这一行接** |
 * | `{to, from_cycle, from_unit, status}` | 走那个周期，**从指定那一行接**，顺带给当前这一行盖个终止状态 |
 *
 * 挑出候选（`next`）之外的东西当场炸 —— 内核不许它自由发挥。
 *
 * 这个例子里的图：
 *
 * ```
 *   plan ──→ work ──→ wrap
 *              ↑         │
 *              └─────────┘        work 觉得没干完就自己转自己，够了才去 wrap
 * ```
 */

interface At {
  next?: string[];
  cycle?: { cycle?: string };
  task?: { id?: string };
  result?: { body?: unknown };
  unit?: number;
}

/** 模型这一站说的话里有没有这个词。 */
function said(r: At["result"], word: string): boolean {
  return String((r ?? {}).body ?? "").includes(word);
}

export async function infer(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  const here = a.cycle?.cycle;
  const next = a.next ?? [];

  // plan 走完只有一条路
  if (here === "plan") return pick("work", a);

  if (here === "work") {
    // 模型自己说「收尾」了才往下走，否则在 work 上再转一圈。
    // `max_units` 是兜底：转不动了内核会拦，不用在这儿数。
    return pick(said(a.result, "收尾") ? "wrap" : "work", a);
  }

  // wrap 是终点
  return pick(null, a);

  function pick(to: string | null, at: At): unknown {
    console.log(`[steps] ${at.task?.id} ${here}#${at.unit} → ${to ?? "到此为止"}（候选 ${next.join("、") || "无"}）`);
    return to;
  }
}

/** 故意推一个候选之外的周期出来，看内核拦不拦。 */
export async function wild(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  console.log(`[steps] ${a.task?.id} ${a.cycle?.cycle}#${a.unit} → 乱来（候选是 ${(a.next ?? []).join("、")}）`);
  return "nowhere";
}
