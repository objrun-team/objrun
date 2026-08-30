/**
 * 一个执行单元实例在哪儿 —— **哪道任务、哪张子表**。
 *
 * 工具句柄只拿得到 `{args, place, agent, instance, unit}`（见 `tools/unit.ts` 的
 * `runOne`），任务是哪一道得自己回头问库。**不靠调用方传** —— 传的会漏，而且模型
 * 能改参数：真让它传 task 的话，它就能拿别人那道题的 G 去问自己这一道。
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import { tableNameOf } from "../install/index.ts";

export interface Where {
  /** 任务 id。 */
  task: string;
  /** 这道题跑在哪张子表上（`task_<mode>`）。 */
  sub: string;
}

/** 从实例号反查。找不到回 `null` —— 那说明这个实例根本没登记过。 */
export function whereAmI(db: Conn, instance: string): Where | null {
  for (const m of all(db, `select distinct mode from cycle`) as { mode: string }[]) {
    const sub = tableNameOf("task_{}", m.mode);
    const r = all(db, `select task from "${sub}" where instance = ? limit 1`, [instance])[0] as
      | { task: string }
      | undefined;
    if (r) return { task: r.task, sub };
  }
  return null;
}
