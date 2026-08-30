/**
 * 活库检查 —— 库里的行**互相对得上吗**。
 *
 * `check.ts` 查的是触发条件写得对不对；这一份查的是**数据之间的一致性**。
 * 两件事都只有一个目的：让「静默不生效」变成看得见的。
 *
 * ## 这几条是老代码踩出来的
 *
 * 降解那个模块的注释里留着一串「别再犯的」，其中三条根本不是降解专有的：
 *
 * > `task_prefix` 落进 `**kw` 会被基类吞掉，于是**这批任务谁都不接，而且不报错**。
 *
 * 「谁都不接而且不报错」是这一类问题的通名：任务躺在库里，状态永远是 `open`，
 * 没人知道为什么。所以要有一条检查专门问「这个任务真有人能接吗」。
 *
 * > 建节点一律走带信号的那条路，直接插等于造一条**不发信号的旁路**。
 *
 * 我们这边内核每推一行都会喊时刻，所以从外面直接往子表插一行执行单元不会漏掉
 * 钩子 —— 内核挑到它的时候照样喊。但**跳过发布口直接插 `task` 行**会漏掉那道
 * 准入闸（来源、G、readable），所以这儿查一遍。
 *
 * > `result` 只能写在终止节点上。
 *
 * 对应到我们这儿：`result` 有内容 ⟺ `state` 是 `done` 或 `failed`。半路写 result
 * 的任务，事后没人说得清那个答案是哪一步给的。
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import { tableNameOf } from "../install/index.ts";
import type { Registry } from "../engine/registry.ts";
import { MODE_NAMES, SERVES } from "../llm/index.ts";

export interface Bad {
  what: string;
  why: string;
}

function tables(db: Conn): Set<string> {
  return new Set(
    (all(db, `select name from sqlite_master where type='table'`) as { name: string }[]).map((r) => r.name),
  );
}

/**
 * 把整库过一遍。返回问题列表；空 = 全通。
 *
 * `reg` 给进来就顺带做**句柄的两层核对**：库里登记的 `fn:` 在进程里注册过没有。
 * 不给就跳过那一档 —— 这个函数也该能在没起内核的时候跑。
 */
export function checkData(db: Conn, reg?: Registry): Bad[] {
  const out: Bad[] = [];
  const has = tables(db);
  const say = (what: string, why: string) => out.push({ what, why });

  // ── 任务 ──────────────────────────────────────────────────────────────
  for (const t of all(db, `select id, mode, place, state, result from task`) as {
    id: string; mode: string; place: string; state: string; result: string | null;
  }[]) {
    if (all(db, `select 1 from cycle where mode = ?`, [t.mode]).length === 0) {
      say(`task ${t.id}`, `its mode ${t.mode} is not in the cycle table - nobody can pick this task up, and nothing reports it`);
    }
    if (all(db, `select 1 from workplace where place = ?`, [t.place]).length === 0) {
      say(`task ${t.id}`, `its place ${t.place} is not registered`);
    }
    // result 只能写在终止的时候。半路写的话，事后没人说得清那个答案是哪一步给的。
    const done = t.state === "done" || t.state === "failed";
    if (t.result !== null && !done) say(`task ${t.id}`, `state=${t.state} but result is already set - result should only be written at the terminal moment`);
    if (t.result === null && t.state === "failed") say(`task ${t.id}`, `marked failed but has no result - a failure must say why`);

    const sub = tableNameOf("task_{}", t.mode);
    if (!has.has(sub)) {
      say(`task ${t.id}`, `the sub-table ${sub} has not been grown yet - run POST /install once`);
      continue;
    }

    // ── 执行单元 ────────────────────────────────────────────────────────
    const units = all(
      db,
      `select cycle, unit, from_cycle, from_unit, agent, instance, status, done from "${sub}" where task = ?`,
      [t.id],
    ) as {
      cycle: string; unit: number; from_cycle: string | null; from_unit: number | null;
      agent: string; instance: string; status: string | null; done: number;
    }[];
    if (units.length === 0) say(`task ${t.id}`, `no execution units at all - most likely a task row inserted directly, bypassing the publish route`);

    const perCycle = new Map<string, number>();
    for (const u of units) {
      const cyc = all(db, `select max_units from cycle where mode = ? and cycle = ?`, [t.mode, u.cycle])[0] as
        | { max_units: number } | undefined;
      if (!cyc) {
        say(`${sub} ${t.id} ${u.cycle}#${u.unit}`, `cycle ${u.cycle} does not belong to ${t.mode}`);
        continue;
      }
      perCycle.set(u.cycle, (perCycle.get(u.cycle) ?? 0) + 1);

      // 父指的那一行得真在
      if (u.from_cycle !== null && u.from_unit !== null) {
        if (!units.some((x) => x.cycle === u.from_cycle && x.unit === u.from_unit)) {
          say(`${sub} ${t.id} ${u.cycle}#${u.unit}`, `says it came from ${u.from_cycle}#${u.from_unit}, but that row is missing`);
        }
      }

      // 两边对咬：任务这边记「谁在干我」，智能体那边记「我在干谁」
      const ctx = tableNameOf("agent_{}_ctx", u.agent);
      if (!has.has(ctx)) {
        say(`${sub} ${t.id} ${u.cycle}#${u.unit}`, `the context table for agent ${u.agent} has not been grown yet`);
        continue;
      }
      const mate = all(db, `select task, done from "${ctx}" where instance = ? and unit = ?`, [u.instance, u.unit])[0] as
        | { task: string; done: number } | undefined;
      if (!mate) {
        say(`${sub} ${t.id} ${u.cycle}#${u.unit}`, `${ctx} has no matching row - the two-sided record does not line up`);
      } else {
        if (mate.task !== t.id) say(`${sub} ${t.id} ${u.cycle}#${u.unit}`, `the other side says it is working on ${mate.task}, not ${t.id}`);
        if (Number(mate.done) !== Number(u.done)) {
          say(`${sub} ${t.id} ${u.cycle}#${u.unit}`, `done disagrees across the two sides: ${u.done} here, ${mate.done} in ${ctx}`);
        }
      }
    }
    for (const [cycle, n] of perCycle) {
      const cap = all(db, `select max_units from cycle where mode = ? and cycle = ?`, [t.mode, cycle])[0] as
        | { max_units: number } | undefined;
      if (cap && n > Number(cap.max_units)) {
        say(`task ${t.id}`, `${cycle} opened ${n} units, over max_units=${cap.max_units}`);
      }
    }
  }

  // ── 智能体接得住吗 ────────────────────────────────────────────────────
  for (const a of all(db, `select name, unit, apis from agent`) as { name: string; unit: string; apis: string }[]) {
    let apis: [string, string][] = [];
    try {
      apis = JSON.parse(a.apis || "[]") as [string, string][];
    } catch {
      say(`agent ${a.name}`, `apis is not a readable list: ${a.apis}`);
    }
    for (const [keyEnv, model] of apis) {
      if (all(db, `select 1 from api where key_env = ? and model = ?`, [keyEnv, model]).length === 0) {
        say(`agent ${a.name}`, `${keyEnv}/${model} in apis is not registered in the api table`);
      }
    }
  }

  // ── 轨对得上吗 ────────────────────────────────────────────────────────
  //
  // 「谁都不接而且不报错」在这一块有三个入口，全是**静默**的：
  //
  // 1. `api.modes` 写错一个字母（`duplx`）→ 那条轨永远挑不中
  // 2. `cycle.api_mode` 要一种没人支持的 mode → 那个周期的每一行都走不了
  // 3. 一行的 `modes` 含 `duplex`，`handle` 却是 chat 那条 → **挑中了，
  //    然后调进另一种适配器**。这条最坏：它不报错，只是那一站的行为
  //    完全不是你想的那样
  // 比的是**实现认得什么**，不是 `mode` 表里躺着什么。那张表是灌进去给人查的；
  // 拿它当判据的话，手插一行 `duplx` 就成了「合法」，而实现照样不认。
  const modeOK = MODE_NAMES;
  const served = new Map<string, Set<string>>(); // mode → 哪些句柄接得住
  for (const a of all(db, `select key_env, model, handle, modes from api`) as {
    key_env: string; model: string; handle: string; modes: string;
  }[]) {
    const at = `api ${a.key_env}/${a.model}`;
    const modes = String(a.modes ?? "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    if (modes.length === 0) say(at, `modes is empty - nothing will ever select this row`);
    const can = SERVES.get(a.handle);
    for (const m of modes) {
      if (!modeOK.has(m)) {
        say(at, `${m} in modes is not a known api mode (known: ${[...modeOK].join(", ")}) - this lane will never be selected`);
        continue;
      }
      // 外面注册进来的句柄接得住什么我们不知道，跳过不查。
      if (can && !can.has(m)) {
        say(at, `modes claims ${m}, but handle=${a.handle} cannot serve it (it serves only ${[...can].join(", ")})`);
      }
      if (!served.has(m)) served.set(m, new Set());
      served.get(m)!.add(a.handle);
    }
  }
  for (const c of all(db, `select mode, cycle, api_mode from cycle where api_mode is not null and trim(api_mode) <> ''`) as {
    mode: string; cycle: string; api_mode: string;
  }[]) {
    const want = String(c.api_mode).trim();
    if (!modeOK.has(want)) {
      say(`cycle ${c.mode}/${c.cycle}`, `api_mode=${want} is not a known api mode (known: ${[...modeOK].join(", ")})`);
    } else if (!served.has(want)) {
      say(`cycle ${c.mode}/${c.cycle}`, `needs a ${want} lane, but no row in the api table serves one - every unit of this cycle is stuck`);
    }
  }

  // ── 句柄两层核对 ──────────────────────────────────────────────────────
  //
  // 库里登记过、进程里没注册的 `fn:` 句柄 —— 不查的话，要等到某个任务真走到
  // 那一步才炸，而那时候已经在半路上了。
  if (reg) {
    for (const h of all(db, `select name from handle`) as { name: string }[]) {
      if (h.name.startsWith("fn:") && !reg.has(h.name)) {
        say(`handle ${h.name}`, `registered in the database but never registered in this process`);
      }
    }
  }
  // 反过来：被引用而库里根本没登记的
  const known = new Set((all(db, `select name from handle`) as { name: string }[]).map((r) => r.name));
  const refs: [string, string][] = [
    ...(all(db, `select 'api.handle' as at, handle as h from api`) as { at: string; h: string }[]).map(
      (r) => [r.at, r.h] as [string, string],
    ),
    ...(all(db, `select 'agent.unit' as at, unit as h from agent`) as { at: string; h: string }[]).map(
      (r) => [r.at, r.h] as [string, string],
    ),
    ...(all(db, `select 'cycle.infer' as at, infer as h from cycle`) as { at: string; h: string }[]).map(
      (r) => [r.at, r.h] as [string, string],
    ),
  ];
  for (const [at, h] of refs) {
    if (h && !known.has(h)) say(at, `references ${h}, which is not registered in the handle table`);
  }

  return out;
}
