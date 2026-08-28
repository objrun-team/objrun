/**
 * 执行链路串 —— 触发条件里 `dim=chain` 比的就是它。
 *
 * # 这是协议，不是实现细节
 *
 * 拼法一改，所有 `dim=chain` 的条件同时**静默失效** —— 不报错，只是再也不触发。
 * 所以拼法写死在这一个函数里，改它等于改协议：得连着把库里已有的条件一起改。
 *
 * ## 格式
 *
 * 从任务的头节点，沿着 `from_cycle` / `from_unit` 一路走到当前这个执行单元，
 * 每一段写成 `模式/周期#单位`，段与段之间用 ` > ` 连。
 *
 * ```
 * dfs/open#1 > dfs/scope#1 > dfs/act#2
 * ```
 *
 * 段的顺序是**从头到当前**，不是倒着 —— `prefix` 这类比较才有意义。
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";

export interface Unit {
  task: string;
  cycle: string;
  unit: number;
  from_cycle: string | null;
  from_unit: number | null;
}

const SEP = " > ";

function seg(mode: string, u: { cycle: string; unit: number }): string {
  return `${mode}/${u.cycle}#${u.unit}`;
}

/**
 * 拼当前这一行的链路串。
 *
 * 沿 `from` 指针往上走，走到没有前驱为止。**带环的话当场炸** —— 一个执行单元
 * 顺着 from 走回自己，那是数据坏了，静静地转下去只会挂死在这儿。
 */
export function chainOf(db: Conn, sub: string, mode: string, at: Unit): string {
  const segs: string[] = [seg(mode, at)];
  const seen = new Set<string>([`${at.cycle}#${at.unit}`]);
  let cur = at;

  while (cur.from_cycle !== null && cur.from_unit !== null) {
    const key = `${cur.from_cycle}#${cur.from_unit}`;
    if (seen.has(key)) throw new Error(`${sub} 里 ${at.task} 的链路成环了，在 ${key}`);
    seen.add(key);
    const rows = all(
      db,
      `select task, cycle, unit, from_cycle, from_unit from "${sub}"
        where task = ? and cycle = ? and unit = ?`,
      [cur.task, cur.from_cycle, cur.from_unit],
    ) as unknown as Unit[];
    if (rows.length === 0) {
      throw new Error(`${sub} 里 ${at.task} 的 ${seg(mode, cur)} 说它从 ${key} 来，但那一行不在`);
    }
    cur = rows[0];
    segs.unshift(seg(mode, cur));
  }
  return segs.join(SEP);
}
