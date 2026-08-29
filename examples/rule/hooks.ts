/**
 * 两条规则，一个文件。**挂在时刻上就是钩子。**
 *
 * | 导出 | 挂哪一刻 | 干什么 |
 * | --- | --- | --- |
 * | `audit` | `pre_send` | 出站前记一笔：这一站要往哪条轨上发 |
 * | `archive` | `task_done` | 任务收尾时往 `done.log` 里追一行 |
 *
 * 两条句柄落在同一个文件上 = 同一个 worker、同一份模块状态，所以 `audit` 数的那个
 * 计数 `archive` 看得见 —— 归档那一行里的「审了几次」就是这么来的。
 */

import { appendFile } from "node:fs/promises";
import { join } from "node:path";

const LOG = process.env.TGENGIN_RULE_LOG ?? join(process.cwd(), "examples", "rule", "done.log");

/** 这一趟审了几次。活在这个 worker 的内存里，不落库。 */
let audited = 0;

interface At {
  moment?: string;
  place?: string;
  task?: { id?: string; source?: string; description?: string; result?: string | null };
  cycle?: { cycle?: string; api_mode?: string | null };
  chain?: string;
  unit?: number;
}

export async function audit(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  audited++;
  console.log(
    `[hooks] ${a.moment}｜${a.task?.id} 第 ${a.unit} 站｜轨=${a.cycle?.api_mode ?? "（不用模型）"}｜链路=${a.chain}`,
  );
  return { audited };
}

export async function archive(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  const line = JSON.stringify({
    at: new Date().toISOString(),
    task: a.task?.id,
    source: a.task?.source,
    audited,
    result: (a.task?.result ?? "").slice(0, 60),
  });
  await appendFile(LOG, line + "\n", "utf8");
  console.log(`[hooks] ${a.moment}｜归档 ${a.task?.id} → ${LOG}`);
  return { archived: a.task?.id };
}
