/**
 * 一趟正在跑的时候，盯着它。
 *
 * ```
 * bun examples/benchmark/deepswe/watch.ts [这一跑叫什么] [--loop 60]
 * ```
 *
 * **要早点看出毛病，看的不能只是成绩单** —— 成绩单要几小时才有第一个数，而那时候
 * 该改的早就来不及了。所以每道题都摊开：走到第几站、上一条消息是多久以前、判过几次卷、
 * 判卷说了什么。
 *
 * 几种「不报错的坏」，这儿一眼能看出来：
 *
 * | 看到什么 | 多半是什么 |
 * | --- | --- |
 * | 每道题的 `站` 都停在 1，而且 `静了` 越来越大 | 模型那条轨没通（钥匙、额度、网络） |
 * | 站在涨，但一次 `verify` 都没有 | 它不知道要交 sha，或者根本没往交卷走 |
 * | `verify` 有，但 `补丁` 一直是 0 字节 | 它在改文件却没提交 —— 收集钩子取不到东西 |
 * | 判卷全是 `collect` 那一段 | 交上来的不是提交号 |
 * | 某一道 `站` 疯涨而别的不动 | 那道题卡在一个循环里，在烧额度 |
 */

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
const RUN = process.argv[2] ?? "dsw-l2";
const LOOP = Number((process.argv.find((a) => a.startsWith("--loop")) ?? "").split("=")[1] ?? 0) ||
  (process.argv.includes("--loop") ? 60 : 0);

async function sql<T>(q: string): Promise<T[]> {
  const r = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sql: q }),
  });
  if (!r.ok) throw new Error(`${q.slice(0, 40)}: ${r.status}`);
  return ((await r.json()) as { rows: T[] }).rows;
}

const ago = (ms: number) => (ms < 0 ? "?" : ms < 60_000 ? `${Math.round(ms / 1000)}s` : `${Math.round(ms / 60_000)}m`);

async function once(): Promise<void> {
  const now = Date.now();

  const tasks = await sql<{ id: string; state: string; result: string | null; created_at: number }>(
    `select id, state, result, created_at from task where run = '${RUN}' order by id`,
  );
  if (tasks.length === 0) {
    console.log(`${RUN}: 一道题都没有`);
    return;
  }

  // 走到第几站 —— 子表一行一站。
  const units = await sql<{ task: string; n: number; dead: number }>(
    `select task, count(*) as n, sum(case when status like 'dead%' then 1 else 0 end) as dead
     from task_solve where task like '${RUN}/%' group by task`,
  );
  // 上一条消息是什么时候 —— 静太久就是卡住了。
  const last = await sql<{ instance: string; at: number; n: number }>(
    `select instance, max(at) as at, count(*) as n from agent_bot_msg
     where instance like '${RUN}/%' group by instance`,
  );
  // 它自己问过几次 G。
  const checks = await sql<{ instance: string; n: number }>(
    `select instance, count(*) as n from agent_bot_msg
     where instance like '${RUN}/%' and kind = 'tool' and body like '%"verify"%' group by instance`,
  );

  const u = new Map(units.map((r) => [r.task, r]));
  const l = new Map(last.map((r) => [r.instance.split("#")[0], r]));
  const c = new Map<string, number>();
  for (const r of checks) c.set(r.instance.split("#")[0], (c.get(r.instance.split("#")[0]) ?? 0) + r.n);

  const done = tasks.filter((t) => t.state === "done").length;
  const failed = tasks.filter((t) => t.state === "failed").length;
  console.log(
    `\n${new Date().toTimeString().slice(0, 8)}  ${RUN}  ` +
      `${done} 做成 / ${failed} 判死 / ${tasks.length - done - failed} 在跑`,
  );
  console.log("  " + "题".padEnd(46) + "状态      站  判死  验  静了   开跑");
  for (const t of tasks) {
    const short = t.id.slice(RUN.length + 1);
    const uu = u.get(t.id);
    const ll = l.get(t.id);
    const verdict = t.result ? (JSON.parse(t.result) as { pass?: number; note?: string }) : null;
    const tail = verdict ? `  ${verdict.pass === 1 ? "PASS" : "FAIL"} ${String(verdict.note ?? "").slice(0, 60)}` : "";
    console.log(
      `  ${short.padEnd(46)}${t.state.padEnd(9)}` +
        `${String(uu?.n ?? 0).padStart(3)}${String(uu?.dead ?? 0).padStart(5)}` +
        `${String(c.get(t.id) ?? 0).padStart(4)}` +
        `${(ll ? ago(now - ll.at) : "-").padStart(6)}` +
        `${ago(now - t.created_at).padStart(7)}${tail}`,
    );
  }

  // 一次调用都没落地的话，上面那张表全是 0，看不出是「还没开始」还是「轨不通」。
  const sent = await sql<{ n: number; kind: string }>(
    `select kind, count(*) as n from agent_bot_msg where instance like '${RUN}/%' group by kind`,
  );
  console.log("  消息：" + (sent.map((r) => `${r.kind} ${r.n}`).join("  ") || "一条都没有"));
}

if (LOOP > 0) {
  for (;;) {
    try {
      await once();
    } catch (e) {
      console.log(`  看不了：${e instanceof Error ? e.message : String(e)}`);
    }
    await Bun.sleep(LOOP * 1000);
  }
} else {
  await once();
}
