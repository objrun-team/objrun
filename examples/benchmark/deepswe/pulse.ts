/**
 * Poll periodically to see **what running tasks are doing**, rather than waiting for a score report.
 *
 * ```
 * bun examples/benchmark/deepswe/pulse.ts [run-name] [interval-seconds]
 * ```
 *
 * The first score can take hours, too late to correct problems. Each poll reports every active problem: current station, time since the last message, grading-query count, and context size.
 *
 * A leading ! marks a **suspicious** row using three previously observed conditions:
 *
 * | Condition | Likely cause |
 * | --- | --- |
 * | Silent for over 15 minutes | A tool is stuck (disk-wide grep or endless tests), or the model connection failed |
 * | Station count does not advance | Similar, but even the timeout has not returned |
 * | Over 150 stations without any grading query | The solver does not know to submit a SHA, or never follows the submission path |
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

/** Important engine-log events. Logs contain one JSON object per line, so count matching lines. */
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

// An unchanged station count indicates a stall; retain the preceding poll's count.
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
