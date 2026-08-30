/**
 * 动态 skill：`body` 留空的那一种。触发那一刻内核来调它，它现拼一段话回去。
 *
 * 拿到的是这一轮的**事实**（跟触发条件比的是同一份），所以能按这个任务、这一站
 * 的具体情况说话 —— 写死的那种做不到。
 */

export async function run(arg: unknown): Promise<unknown> {
  const { facts } = (arg ?? {}) as {
    facts?: {
      task?: { id?: string; description?: string; source?: string };
      cycle?: { cycle?: string };
      place?: string;
    };
  };
  const t = facts?.task;
  const line = `【现生成的】这道题是 ${t?.id}（${t?.source} 发的，在 ${facts?.place}）：${t?.description}`;
  console.log(`[recap] ${line}`);
  return line;
}
