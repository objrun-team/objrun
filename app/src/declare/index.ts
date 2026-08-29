/**
 * 声明这一层 —— **外面把一台机器配起来，只走这一个口。**
 *
 * ## 为什么不是让人去插表
 *
 * 库是全接口开放的，`/exec` 一句 `insert into cycle …` 就能灌。但那是给认得表的人
 * 用的，不是给用户的：**给他一个自由接口，等于把表结构甩给他**，而且写错了还不报错。
 *
 * 更要命的是**模式是一张图，而 insert 是一行一行的**。写第三行的时候没人知道第一行的
 * `next` 指错了地方 —— 图的完整性只有在全部写完之后才成立，那时候已经写进库了。
 * 于是得到一台看着像好的、实际走不通的机器：任务发得出去，走到某一步停住，
 * 状态永远是 `claimed`，零报错。
 *
 * ## 所以：一整份收，整份验，一处不过整份不写
 *
 * 跟 `/bench` 那条「一道不过就整批不发」是同一个道理。发一半的话，
 * 用户手上那台机器的毛病要等到跑任务那一刻才露出来，而且露出来的样子跟
 * 「模型不听话」分不开。
 *
 * 三样一起收，因为**它们互相依赖**：智能体的轨要 `api` 表有那一行，周期要的调用
 * 形状得有句柄接得住，任务要三样齐全。拆成三个口的话，用户可以合法地把系统灌成
 * 「一半声明」，而那正是这个文件要防的东西。
 *
 * 验完在一个事务里写，然后把子表现长出来 —— 灌完直接 `POST /tasks`，不用重启。
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { install, tableNameOf } from "../install/index.ts";
import { MODE_NAMES } from "../llm/index.ts";
import { hops } from "../place/index.ts";

/** 一个能干活的地方。 */
export interface PlaceDecl {
  /** 带层级的地址串：`local` / `wsl` / `ssh://box-7` / `wsl/docker:build-01` …… */
  place: string;
  /** 要送过去的那个运行时（本机文件路径）。`local` 留空。 */
  runtime?: string | null;
  /** 工具调用转不转发过去。默认不转。 */
  forward?: boolean;
  /** 白名单：哪些工具能转发过去，各自什么细则（`always` / `agent`）。 */
  tools?: { tool: string; policy: string }[];
  /** 登记的可用性。**是登记不是探活**，默认可用。 */
  usable?: boolean;
}

/** 一个模式里的一个周期。 */
export interface CycleDecl {
  cycle: string;
  /** 这一站要哪种调用形状（`chat` / `duplex` / ……）。**留空 = 这一站不用模型**。 */
  apiMode?: string | null;
  /** 这个周期最多开几个执行单位。默认 1。 */
  maxUnits?: number;
  /** 一般从这个模式里哪几个周期转过来。**空 = 它是入口**。 */
  from?: string[];
  /** 一般下一个是哪几个周期。**空 = 到此为止**。 */
  next?: string[];
  /** 推断函数的句柄名 —— 在候选（`next`）里挑一个。 */
  infer: string;
}

/** 一个模式 = 一组周期连成的图。 */
export interface ModeDecl {
  mode: string;
  cycles: CycleDecl[];
  note?: string;
}

/** 一个智能体。 */
export interface AgentDecl {
  name: string;
  /** 挂哪几条轨，每项 `[key_env, model]` —— 要在 `api` 表里真有那一行。 */
  apis: [string, string][];
  /** 执行单元句柄：这一站不用模型的时候调它。 */
  unit: string;
  config?: string | null;
  state?: string;
}

/** 一整份声明。三样都可以缺，但缺了的那样就不许被别的引用。 */
export interface Declare {
  places?: PlaceDecl[];
  modes?: ModeDecl[];
  agents?: AgentDecl[];
}

/** 灌完了，回什么。 */
export interface Declared {
  places: string[];
  modes: string[];
  cycles: number;
  agents: string[];
  /** 这一趟长出来的子表。 */
  tables: string[];
  /** 每个模式的入口周期。**不止一个的话，发任务得指定 `cycle`** —— 在这儿说出来。 */
  entries: Record<string, string[]>;
}

const POLICIES = ["always", "agent"];

function list(v: unknown, what: string, bad: string[]): string[] {
  if (v === undefined) return [];
  if (!Array.isArray(v) || v.some((x) => typeof x !== "string")) {
    bad.push(`${what} 得是一串周期名`);
    return [];
  }
  return v as string[];
}

/**
 * 把一整份声明验一遍。**返回全部问题，不是逮着第一个就抛。**
 *
 * 一次只说一条的话，用户就得「改一行、再发一次、再看下一条」——十处错来回十趟。
 * 这份声明本来就是一次性写完的东西，问题也该一次性给全。
 */
export function inspect(db: Conn, reg: Registry, d: Declare): string[] {
  const bad: string[] = [];
  const say = (s: string) => bad.push(s);

  // ── 在哪儿干 ──────────────────────────────────────────────────────────
  const places = new Set<string>();
  for (const p of d.places ?? []) {
    const at = `place ${p.place || "(没名字)"}`;
    if (!p.place || !p.place.trim()) {
      say(`有一个 place 没名字`);
      continue;
    }
    if (places.has(p.place)) say(`${at}：这一份里出现了两次`);
    places.add(p.place);
    // 位置串认不得的话，等到真去转发那一刻才炸 —— 那时候任务已经在半路上了。
    try {
      hops(p.place);
    } catch (e) {
      say(`${at}：${e instanceof Error ? e.message : String(e)}`);
    }
    for (const t of p.tools ?? []) {
      if (!POLICIES.includes(t.policy)) {
        say(`${at}：工具 ${t.tool} 的 policy 不认得（只能是 ${POLICIES.join(" / ")}）`);
      }
    }
    if (p.forward) {
      // 转发是要把运行时送过去的。没登记送什么，`openPlace` 会在第一次调用时炸。
      if (p.place !== "local" && !p.runtime) say(`${at}：说要转发，但没给 runtime —— 没东西可送过去`);
      // 开了总闸而白名单是空的 = 一个工具都不会转发。**合法，但一定不是本意。**
      if ((p.tools ?? []).length === 0) say(`${at}：转发开着，可白名单是空的 —— 一个工具都不会转过去`);
    }
  }

  // ── 模式：验的是图，不是行 ────────────────────────────────────────────
  const modes = new Set<string>();
  for (const m of d.modes ?? []) {
    const at = `mode ${m.mode || "(没名字)"}`;
    if (!m.mode || !m.mode.trim()) {
      say(`有一个 mode 没名字`);
      continue;
    }
    if (modes.has(m.mode)) say(`${at}：这一份里出现了两次`);
    modes.add(m.mode);
    // 模式名要能长成一张表（`task_<mode>`）。长不出来的话装表那一步才炸。
    try {
      tableNameOf("task_{}", m.mode);
    } catch (e) {
      say(`${at}：${e instanceof Error ? e.message : String(e)}`);
    }
    if (!Array.isArray(m.cycles) || m.cycles.length === 0) {
      say(`${at}：一个周期都没有`);
      continue;
    }

    const names = new Set<string>();
    for (const c of m.cycles) {
      if (!c.cycle || !c.cycle.trim()) {
        say(`${at}：有一个周期没名字`);
        continue;
      }
      if (names.has(c.cycle)) say(`${at}/${c.cycle}：这个周期名出现了两次`);
      names.add(c.cycle);
    }

    for (const c of m.cycles) {
      const cat = `${at}/${c.cycle}`;
      const next = list(c.next, `${cat} 的 next`, bad);
      const from = list(c.from, `${cat} 的 from`, bad);
      // 指到这个模式外面去的周期永远走不到，而内核不会说什么 —— 它只是停在那儿。
      for (const n of next) if (!names.has(n)) say(`${cat}：next 指的 ${n} 不在这个模式里`);
      for (const f of from) if (!names.has(f)) say(`${cat}：from 指的 ${f} 不在这个模式里`);

      if (c.maxUnits !== undefined && (!Number.isInteger(c.maxUnits) || c.maxUnits < 1)) {
        say(`${cat}：max_units 得是个正整数`);
      }
      // 推断函数没注册 → 走到这一站才炸，而那时候任务已经跑了一半。
      if (!c.infer || !c.infer.trim()) say(`${cat}：没给 infer`);
      else if (!reg.has(c.infer)) say(`${cat}：infer 是 ${c.infer}，但进程里没有这个句柄`);

      const want = (c.apiMode ?? "").trim();
      if (want) {
        if (!MODE_NAMES.has(want)) {
          say(`${cat}：apiMode=${want} 不是认得的调用形状（认得的是 ${[...MODE_NAMES].join("、")}）`);
        } else if (!servedBy(db, want)) {
          say(`${cat}：要一条 ${want} 的轨，但 api 表里没有一行支持 —— 这个周期的每一行都走不了`);
        }
      }
    }

    // 起点：`from` 为空的那些。一个都没有 = 这个模式根本进不去。
    const entries = m.cycles.filter((c) => list(c.from, "", []).length === 0).map((c) => c.cycle);
    if (entries.length === 0) say(`${at}：一个起点都没有（每个周期的 from 都非空），这个模式进不去`);

    // 谁都指不到的周期。**它永远不会被走到，而且不报错** —— 声明里躺着一段死代码，
    // 而写的人多半以为它在跑。
    const seen = new Set(entries);
    const queue = [...entries];
    while (queue.length) {
      const cur = queue.shift()!;
      const row = m.cycles.find((c) => c.cycle === cur);
      for (const n of list(row?.next, "", [])) {
        if (names.has(n) && !seen.has(n)) {
          seen.add(n);
          queue.push(n);
        }
      }
    }
    for (const c of m.cycles) {
      if (c.cycle && !seen.has(c.cycle)) say(`${at}/${c.cycle}：从起点走不到它 —— 这个周期永远不会被用上`);
    }
  }

  // ── 智能体 ────────────────────────────────────────────────────────────
  const agents = new Set<string>();
  for (const a of d.agents ?? []) {
    const at = `agent ${a.name || "(没名字)"}`;
    if (!a.name || !a.name.trim()) {
      say(`有一个 agent 没名字`);
      continue;
    }
    if (agents.has(a.name)) say(`${at}：这一份里出现了两次`);
    agents.add(a.name);
    try {
      tableNameOf("agent_{}_ctx", a.name);
    } catch (e) {
      say(`${at}：${e instanceof Error ? e.message : String(e)}`);
    }
    if (!a.unit || !a.unit.trim()) say(`${at}：没给 unit`);
    else if (!reg.has(a.unit)) say(`${at}：unit 是 ${a.unit}，但进程里没有这个句柄`);

    if (!Array.isArray(a.apis)) {
      say(`${at}：apis 得是一串 [key_env, model]`);
      continue;
    }
    for (const pair of a.apis) {
      if (!Array.isArray(pair) || pair.length !== 2) {
        say(`${at}：apis 里有一项不是 [key_env, model]`);
        continue;
      }
      const [keyEnv, model] = pair;
      if (all(db, `select 1 from api where key_env = ? and model = ?`, [keyEnv, model]).length === 0) {
        say(`${at}：挂的 ${keyEnv}/${model} 在 api 表里没登记 —— 这条轨挑不中`);
      }
    }
  }

  return bad;
}

/**
 * 灌一整份。**先整份验，一处不过整份不写。**
 *
 * 写在一个事务里 —— 中途炸的话已经写进去的那部分得整个退回去，不然就成了
 * 「写了一半」，而那正是这个模块存在的理由。
 *
 * 写完把子表现长出来（`install` 是幂等的）。不长的话，灌完声明还得重启一趟，
 * 「外面纯用 HTTP 把机器配起来」就断在这儿。
 */
export function apply(db: Conn, reg: Registry, d: Declare): Declared {
  const bad = inspect(db, reg, d);
  if (bad.length) {
    const e = new Error(`这份声明有 ${bad.length} 处不对，什么都没写`) as Error & {
      statusCode?: number;
      problems?: string[];
    };
    e.statusCode = 400;
    e.problems = bad;
    throw e;
  }

  const before = new Set(tableNames(db));
  db.exec("begin");
  try {
    for (const p of d.places ?? []) {
      run(
        db,
        `insert into workplace (place, runtime, forward, tools, usable) values (?, ?, ?, ?, ?)
         on conflict(place) do update set runtime = excluded.runtime, forward = excluded.forward,
           tools = excluded.tools, usable = excluded.usable`,
        [
          p.place,
          p.runtime ?? null,
          p.forward ? 1 : 0,
          JSON.stringify(p.tools ?? []),
          p.usable === false ? 0 : 1,
        ],
      );
    }

    for (const m of d.modes ?? []) {
      run(db, `insert into mode (name, note) values (?, ?) on conflict(name) do update set note = excluded.note`, [
        m.mode,
        m.note ?? null,
      ]);
      // **整个模式换一遍**，不是逐行 upsert：少给一个周期就该是「删掉它」，
      // 而 upsert 会把它留在库里 —— 那一行谁都指不到，是段死代码，且不报错。
      run(db, `delete from cycle where mode = ?`, [m.mode]);
      for (const c of m.cycles) {
        run(
          db,
          `insert into cycle (mode, cycle, api_mode, max_units, "from", next, infer) values (?, ?, ?, ?, ?, ?, ?)`,
          [
            m.mode,
            c.cycle,
            (c.apiMode ?? "").trim() || null,
            c.maxUnits ?? 1,
            JSON.stringify(c.from ?? []),
            JSON.stringify(c.next ?? []),
            c.infer,
          ],
        );
      }
    }

    for (const a of d.agents ?? []) {
      run(
        db,
        `insert into agent (name, config, apis, unit, state) values (?, ?, ?, ?, ?)
         on conflict(name) do update set config = excluded.config, apis = excluded.apis,
           unit = excluded.unit, state = excluded.state`,
        [a.name, a.config ?? null, JSON.stringify(a.apis), a.unit, a.state ?? "idle"],
      );
    }
    db.exec("commit");
  } catch (e) {
    db.exec("rollback");
    throw e;
  }

  install(db);
  const grown = tableNames(db).filter((t) => !before.has(t));

  const entries: Record<string, string[]> = {};
  for (const m of d.modes ?? []) {
    entries[m.mode] = m.cycles.filter((c) => (c.from ?? []).length === 0).map((c) => c.cycle);
  }

  return {
    places: (d.places ?? []).map((p) => p.place),
    modes: (d.modes ?? []).map((m) => m.mode),
    cycles: (d.modes ?? []).reduce((n, m) => n + m.cycles.length, 0),
    agents: (d.agents ?? []).map((a) => a.name),
    tables: grown,
    entries,
  };
}

/**
 * 把库里现在的声明**原样导出来** —— 形状跟 `apply` 收的一模一样，可以直接回灌。
 *
 * 于是「导出这台机器的配置 / 在另一台上重建」就是两次调用，客户端不用自己拼。
 */
export function dump(db: Conn): Declare {
  const places = (all(db, `select place, runtime, forward, tools, usable from workplace order by place`) as {
    place: string; runtime: string | null; forward: number; tools: string; usable: number;
  }[]).map((r) => ({
    place: r.place,
    runtime: r.runtime,
    forward: Boolean(r.forward),
    tools: safeJson(r.tools, []) as { tool: string; policy: string }[],
    usable: Boolean(r.usable),
  }));

  const modes: ModeDecl[] = [];
  for (const m of all(db, `select name, note from mode order by name`) as { name: string; note: string | null }[]) {
    const cycles = all(db, `select cycle, api_mode, max_units, "from", next, infer from cycle where mode = ? order by cycle`, [
      m.name,
    ]) as { cycle: string; api_mode: string | null; max_units: number; from: string; next: string; infer: string }[];
    // `mode` 表登记的是**调用形状**（chat/duplex），任务模式只在 cycle 里 ——
    // 所以没有周期的那些名字不是模式，不导。
    if (cycles.length === 0) continue;
    modes.push({
      mode: m.name,
      ...(m.note ? { note: m.note } : {}),
      cycles: cycles.map((c) => ({
        cycle: c.cycle,
        apiMode: c.api_mode,
        maxUnits: c.max_units,
        from: safeJson(c.from, []) as string[],
        next: safeJson(c.next, []) as string[],
        infer: c.infer,
      })),
    });
  }

  const agents = (all(db, `select name, config, apis, unit, state from agent order by name`) as {
    name: string; config: string | null; apis: string; unit: string; state: string;
  }[]).map((r) => ({
    name: r.name,
    config: r.config,
    apis: safeJson(r.apis, []) as [string, string][],
    unit: r.unit,
    state: r.state,
  }));

  return { places, modes, agents };
}

function safeJson(s: string, fallback: unknown): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return fallback;
  }
}

function tableNames(db: Conn): string[] {
  return (all(db, `select name from sqlite_master where type='table' and name not like 'sqlite_%'`) as {
    name: string;
  }[]).map((r) => r.name);
}

/** 有没有哪一行 api 接得住这种调用形状。 */
function servedBy(db: Conn, want: string): boolean {
  return (all(db, `select modes from api`) as { modes: string }[]).some((r) =>
    String(r.modes ?? "")
      .split(",")
      .map((x) => x.trim())
      .includes(want),
  );
}
