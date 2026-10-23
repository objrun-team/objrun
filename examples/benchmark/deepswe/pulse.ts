/**
 * 每隔一阵子打一轮，**看它们在干嘛** —— 不是看成绩单。
 *
 * ```
 * bun examples/benchmark/deepswe/pulse.ts [这一跑叫什么] [隔多少秒]
 * ```
 *
 * 成绩单要几个钟头才有第一个数，那时候该改的早来不及了。所以每一轮出的是**正在跑的
 * 每一道**：走到第几站、上一条消息多久以前、问过几次判卷、上下文多大。
 *
 * 一行前面挂 `!` 的是**可疑**，判据只有三条，都是撞过的：
 *
 * | 挂了 `!` | 多半是什么 |
 * | --- | --- |
 * | 静了超过 15 分钟 | 那一站卡在一个工具里（扫盘的 grep、跑不完的测试），或者模型那条轨断了 |
 * | 站数不动 | 同上，但更死 —— 连超时都没回来 |
 * | 站过了 150 还一次判卷都没问过 | 它不知道要交 sha，或者根本没往交卷那条路走 |
 */

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
const RUN = process.argv[2] ?? "dsw-full";
const EVERY = Number(process.argv[3] ?? 1200) * 1000;

interface Row {
  id: string;
  stations: number;
  quiet_min: number | null;
  checks: number;
  bytes: number | null;
}

/** 引擎日志里那几件要紧的事。日志是一行一个 JSON，数行就够了。 */
async function fromLog(): Promise<string> {
  try {
    const text = await Bun.file(process.env.TGENGIN_LOG ?? "data/engine.log").text();
    const n = (re: RegExp) => (text.match(re) ?? []).length;
    const bad = n(/"level":5[0-9]/g);
    const cut = n(/sent at l/g);
    const nope = n(/could not be pressed/g);
    return `errors ${String(bad)}, compressed sends ${String(cut)}, press failures ${String(nope)}`;
  } catch {
    return "no engine log";
  }
}

const q = async (sql: string): Promise<Row[]> => {
  const r = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sql }),
  });
  const j = (await r.json()) as { rows?: Row[]; error?: string };
  if (j.error) throw new Error(j.error);
  return j.rows ?? [];
};

const SQL = `
  select t.id as id,
    (select count(*) from task_solve s where s.task = t.id) as stations,
    (select round((strftime('%s','now') * 1000 - max(m.at)) / 60000.0)
       from agent_bot_msg m where m.instance = t.id || '#1') as quiet_min,
    (select count(*) from agent_bot_msg m
      where m.instance = t.id || '#1' and m.kind = 'tool' and m.body like '%"name":"verify"%') as checks,
    (select sum(length(m.body)) + sum(length(coalesce(m.thought, '')))
       from agent_bot_msg m where m.instance = t.id || '#1') as bytes
  from task t
  where t.run = '${RUN}' and t.state not in ('done', 'failed')
  order by t.created_at`;

const COUNTS = `
  select 'x' as id, 0 as stations, 0 as quiet_min,
    (select count(*) from task where run = '${RUN}' and state = 'done') as checks,
    (select count(*) from task where run = '${RUN}' and state = 'failed') as bytes`;

// 一格一格地站着不动，就是卡住了 —— 所以上一轮的站数得记着。
const was = new Map<string, number>();

for (;;) {
  try {
    const rows = await q(SQL);
    const c = (await q(COUNTS))[0];
    const t = new Date().toTimeString().slice(0, 5);
    console.log(`${t}  ${String(c.checks)} done, ${String(c.bytes ?? 0)} failed, ${String(rows.length)} running  |  ${await fromLog()}`);
    for (const r of rows) {
      const name = String(r.id).replace(`${RUN}/`, "");
      const quiet = Number(r.quiet_min ?? 0);
      const stuck = was.get(name) === Number(r.stations);
      const bad = quiet > 15 || (stuck && quiet > 5) || (Number(r.stations) > 150 && Number(r.checks) === 0);
      was.set(name, Number(r.stations));
      console.log(
        `  ${bad ? "!" : " "} ${name.slice(0, 44).padEnd(45)}` +
          `station ${String(r.stations).padStart(4)}  quiet ${String(quiet).padStart(3)}m  ` +
          `checks ${String(r.checks).padStart(2)}  ${String(Math.round(Number(r.bytes ?? 0) / 1024)).padStart(6)} KB`,
      );
    }
  } catch (e) {
    console.log(`${new Date().toTimeString().slice(0, 5)}  cannot reach the engine: ${e instanceof Error ? e.message : String(e)}`);
  }
  await Bun.sleep(EVERY);
}
