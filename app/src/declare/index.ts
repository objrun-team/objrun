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
import { registrable, type Registry } from "../engine/registry.ts";
import { DIMS, MOMENTS, OPS } from "../engine/trigger.ts";
import type { Servers } from "../mcp/client.ts";
import { inspectServer, pull, type ServerDecl } from "../mcp/register.ts";
import { install, tableNameOf } from "../install/index.ts";
import { MODE_NAMES } from "../llm/index.ts";
import { HOPS_HANDLE, hops } from "../place/index.ts";
import { withSubmit } from "../tree/dfs.ts";

/** MCP 工具没说多久算死时给多少。一次工具调用，不是一次求解。 */
export const MCP_EXPECT_MS = 120_000;

/** 一个能干活的地方。 */
export interface PlaceDecl {
  /** 带层级的地址串：`local` / `wsl` / `ssh://box-7` / `wsl/docker:build-01` …… */
  place: string;
  /**
   * **谁把工具调用送到这个位置去** → `handle.name`。
   *
   * 转发的话必须给（下面那道闸）。内置那条是 `fn:place.hops`（`wsl` / `ssh` /
   * `docker` 那套命令前缀）；写 `http://…` 或者一条带 `module` 的 `fn:`，
   * 就是那台机器自己说了算 —— 「怎么到那个位置」是句柄的事，不是内核的事。
   */
  identity?: string | null;
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
  mustCall?: string | null;
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
  /**
   * 这个智能体**固定用哪几个模型参数**。不给的那几个落回整跑的配置。
   *
   * 放在智能体身上，是因为它本来就是智能体的性质，不是这一跑的性质：一个「去查、
   * 把查到的说清楚」的智能体不需要思考，而它服务的那个求解者要想得越多越好 ——
   * 一个旋钮当不了两件事。实测同一个问题 `none` 是 14.5 秒、`low` 是 113 秒。
   */
  knobs?: Record<string, unknown>;
}

/**
 * 一条触发条件项。
 *
 * `dim` 是在哪一维上问（`agent` / `task` / `cycle` / `chain` / `moment` / `place`），
 * `key` 是那一维上的哪个属性 —— **`chain`、`moment`、`place` 不看属性，留空**。
 */
export interface TermDecl {
  dim: string;
  key?: string;
  op: string;
  value: string;
}

/**
 * 什么时候轮到它。**外层是组，组间 or；组内 and。**
 *
 * 组号由这边按下标算，客户端不用管 —— 让客户端自己编组号的话，它得先知道
 * 「同组 and、组间 or」这条语义，还得保证不跟已有的组撞号。
 *
 * **一条都不给 = 永远不触发**，不是「总是触发」。反过来定的话，忘了写条件的
 * 东西会到处乱开。（系统工具 `system: true` 例外，它不看条件。）
 */
export type WhenDecl = TermDecl[][];

/** 外面注册进来的句柄。 */
export interface HandleDecl {
  name: string;
  /** 调它多久算死。超过这个时间内核判死，**内外一视同仁**。 */
  expectMs: number;
  /**
   * `fn:` 的实现从哪儿来：`路径#导出名`（导出名不给就取 `default`）。
   *
   * **给了它，`fn:` 就能从外面注册** —— 那个模块在内核进程里跑，调用没有 IPC。
   * 传不过来的是函数对象，不是函数在哪儿。进程外的句柄用不到这一项。
   */
  module?: string | null;
}

/** 一个工具。`identity` 指向一个句柄 —— 进程内的 `fn:` 或外面的 `http://`。 */
export interface ToolDecl {
  /** 给模型看的名字，也是 `workplace` 白名单引用的那个。 */
  name: string;
  identity: string;
  /** 给模型看的描述。 */
  does: string;
  /** 给模型看的参数 schema。 */
  params: unknown;
  /** 返回值的 schema，也是给模型看的。 */
  output: unknown;
  /** 要往系统提示里加的一段用法约定。 */
  prompt?: string | null;
  /** 能不能跟别的工具同时跑。 */
  concurrent?: boolean;
  /** 系统工具：所有智能体一上来就有，**不看 `when`**。 */
  system?: boolean;
  /**
   * 它的返回是哪一类东西 → `msg_part.name`。压上下文的时候按这个决定丢得起什么。
   *
   * `look` 再看一眼就有、而且会过期；`event` 拿不回来了；`receipt` 一行账。
   * 不填 = `event`：把拿不回来的当成能再拿一次，是唯一赔不起的那个方向。
   */
  gives?: string | null;
  access?: string | null;
  usable?: boolean;
  when?: WhenDecl;
}

/**
 * 一种压法。**跟工具同一个形状** —— 名字、干这件事的句柄、收什么、回什么。
 *
 * 声明进来的和内置的那几种是同一种行（`press_how`），所以「需要一个模型才做得了的
 * 压法」不用进内核：在外面实现，声明一下就是了。
 */
export interface HowDecl {
  /** `msg_part` 的 l1/l2/l3 三列填的就是这个名字。 */
  name: string;
  identity: string;
  /** 收什么，JSON schema。 */
  params: unknown;
  /** 回什么，JSON schema。 */
  output: unknown;
  note?: string | null;
}

/** 一条规则。挂在时刻上就是钩子（`dim: "moment"`）。 */
export interface RuleDecl {
  identity: string;
  does: string;
  params: unknown;
  /** 声明它会动哪几张表怎么动。 */
  writes: unknown;
  /** 能动哪些行。结构化匹配式，不用 SQL 片段。 */
  scope: unknown;
  /** 外部规则够着库的办法。**密钥只存环境变量名。** */
  access?: unknown;
  when?: WhenDecl;
}

/** 一个 skill。模型不挑它，是按条件塞进去的。 */
export interface SkillDecl {
  identity: string;
  does: string;
  params: unknown;
  /** 固定的一段。留空 = 动态生成，由句柄现给。 */
  body?: string | null;
  role: string;
  usable?: boolean;
  when?: WhenDecl;
}

/**
 * 一整份声明。每样都可以缺，但缺了的那样就不许被别的引用。
 *
 * **一处不过整份不写** —— 这几样互相引用（工具的 `identity` 要有句柄、
 * 触发条件的 owner 要真存在、智能体的轨要 `api` 表有那一行），分开灌的话
 * 可以合法地灌成「一半声明」，而错要等到跑起来才冒出来。
 */
export interface Declare {
  /**
   * MCP server —— **一条批量来源**，不是另一种注册方式。
   *
   * 形状跟 `claude_desktop_config.json` 里那个 `mcpServers` 一样：`command` /
   * `args` / `env` 起个子进程，或者 `url` / `headers` 走 HTTP。有哪些工具是
   * server 自己用 `tools/list` 报的 —— 省得一个个写。
   *
   * **想一个个写也行**：`tools` 那一项直接给，`identity` 指一条 `http://` 句柄。
   * 两条路落到库里是同样的行。
   *
   * `tools` 那一项是**我们补的**：什么时候把它摆给模型（`when`）、多久算死
   * （`expectMs`）、要不要谁都有（`system`）。MCP 里没有这几样。
   */
  servers?: ServerDecl[];
  handles?: HandleDecl[];
  places?: PlaceDecl[];
  modes?: ModeDecl[];
  agents?: AgentDecl[];
  tools?: ToolDecl[];
  hows?: HowDecl[];
  rules?: RuleDecl[];
  skills?: SkillDecl[];
}

/** 灌完了，回什么。 */
export interface Declared {
  /** 每个 server 连上之后报了哪些工具。 */
  servers: Record<string, string[]>;
  handles: string[];
  places: string[];
  modes: string[];
  cycles: number;
  agents: string[];
  tools: string[];
  rules: string[];
  skills: string[];
  /** 这一趟长出来的子表。 */
  tables: string[];
  /** 每个模式的入口周期。**不止一个的话，发任务得指定 `cycle`** —— 在这儿说出来。 */
  entries: Record<string, string[]>;
}

const POLICIES = ["always", "agent"];

function list(v: unknown, what: string, bad: string[]): string[] {
  if (v === undefined) return [];
  if (!Array.isArray(v) || v.some((x) => typeof x !== "string")) {
    bad.push(`${what} must be a list of cycle names`);
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

  // ── MCP server ────────────────────────────────────────────────────────
  //
  // 连不连得上要真去连，那是 `apply` 的事；这儿只看声明本身对不对。
  const servers = new Set<string>();
  for (const s of d.servers ?? []) {
    for (const w of inspectServer(s)) say(w);
    if (s.name) {
      if (servers.has(s.name)) say(`server ${s.name}: appears twice in this declaration`);
      servers.add(s.name);
    }
  }

  // ── 外面注册进来的句柄。**先验这一段** ────────────────────────────────
  //
  // 后面的模式、智能体、工具、规则、skill 都要引用句柄，所以得先知道这一份里
  // 声明了哪些 —— 不然「同一份里先声明句柄、再用它」这条最自然的写法会被拒。
  //
  // **只能是 `http://` / `https://`。** `fn:` 的句柄是进程内的真函数，只有那个
  // 进程持有得住 —— 从外面往 `handle` 表写一个 `fn:` 名字，库里就有了一条
  // 进程里没人认领的句柄，而错要等到某个任务真走到那一步才炸。
  const handles = new Set<string>();
  for (const h of d.handles ?? []) {
    const at = `handle ${h.name || "(unnamed)"}`;
    if (!h.name || !h.name.trim()) {
      say(`a handle has no name`);
      continue;
    }
    if (handles.has(h.name)) say(`${at}: appears twice in this declaration`);
    handles.add(h.name);
    if (!registrable(h.name, h.module)) {
      say(
        `${at}: recognised forms are http:// or https:// (another process), ` +
          `and fn: plus module (in-process, implementation on disk, written as path#exportName). ` +
          `a bare fn: name cannot be turned into a function - what cannot cross the wire is the function object, not where it lives`,
      );
    }
    if (!Number.isFinite(h.expectMs) || h.expectMs <= 0) say(`${at}: expectMs must be a positive number`);
  }

  /**
   * 这个句柄够得着吗：这一份里刚声明的、进程里注册过的、或者库里已经登记过的。
   *
   * 三处都算数 —— 外部句柄本来就该能当 `infer` / `agent.unit` / 工具实现用，
   * 那正是「外面能往里加东西」这条路。只认进程内注册表的话，这条路就断了。
   */
  const handleThere = (name: string) =>
    handles.has(name) || reg.has(name) || all(db, `select 1 from handle where name = ?`, [name]).length > 0;

  /** 句柄不在时那句话。得说清「在 handles 里一起声明」，不然人不知道下一步做什么。 */
  const noHandle = (name: string) =>
    `there is no handle named ${name} - in-process fn: handles are registered by code, and http:// ones are given in the handles of this same declaration`;

  // ── 在哪儿干 ──────────────────────────────────────────────────────────
  const places = new Set<string>();
  for (const p of d.places ?? []) {
    const at = `place ${p.place || "(unnamed)"}`;
    if (!p.place || !p.place.trim()) {
      say(`a place has no name`);
      continue;
    }
    if (places.has(p.place)) say(`${at}: appears twice in this declaration`);
    places.add(p.place);
    for (const t of p.tools ?? []) {
      if (!POLICIES.includes(t.policy)) {
        say(`${at}: unrecognised policy for tool ${t.tool} (must be one of ${POLICIES.join(" / ")})`);
      }
    }
    if (p.forward) {
      // **转发就必须说清由谁转。**
      //
      // 以前这儿没有这一问，因为「怎么到那个位置」是编译进内核的：`hops` 只认
      // `wsl` / `ssh` / `docker` 三种，命令怎么拼也写死。于是「这台机器上的
      // docker 装在 snap 里、只在登录 shell 的 PATH 上」这种**机器的性质**没地方
      // 安放，唯一的落点是改内核那三个函数。
      //
      // 现在位置跟工具、跟 G 的节点一样由句柄接住。不给的话，任务会一路走到某件
      // 工具真要转发的那一刻才炸 —— 那时候它已经在半路上了。
      const identity = String(p.identity ?? "").trim();
      if (!identity) {
        say(`${at}: it forwards, but no handle was given to carry the calls there - name one in identity`);
      } else if (!handleThere(identity)) {
        say(`${at}: ${noHandle(identity)}`);
      }
      // ── 下面两条只问内置那条实现 ────────────────────────────────────
      //
      // **地址串怎么读，是那条句柄的事。** `fn:place.hops` 读的是一串跳板
      // （`wsl` / `ssh` / `docker`），拿去拼命令前缀，所以认不得的写法当场就得炸
      // —— 猜的话会连到别的地方去。换一条句柄，地址就该按它自己的写法读：
      // `modal:sandbox-7` 在它那儿是合法的，在这儿不该被拦。
      if (identity === HOPS_HANDLE) {
        try {
          hops(p.place);
        } catch (e) {
          say(`${at}: ${e instanceof Error ? e.message : String(e)}`);
        }
        // 它是要把运行时送过去的。没登记送什么，第一次调用才炸。
        // **别的实现不问这一句** —— 送不送、送什么，一样是那条句柄自己的事。
        if (p.place !== "local" && !p.runtime) {
          say(`${at}: ${HOPS_HANDLE} ships a runtime over, but none was given - there is nothing to ship`);
        }
      }
      // 开了总闸而白名单是空的 = 一个工具都不会转发。**合法，但一定不是本意。**
      if ((p.tools ?? []).length === 0) say(`${at}: forwarding is on but the allow-list is empty - not a single tool would be forwarded`);
    }
  }

  // ── 模式：验的是图，不是行 ────────────────────────────────────────────
  const modes = new Set<string>();
  for (const m of d.modes ?? []) {
    const at = `mode ${m.mode || "(unnamed)"}`;
    if (!m.mode || !m.mode.trim()) {
      say(`a mode has no name`);
      continue;
    }
    if (modes.has(m.mode)) say(`${at}: appears twice in this declaration`);
    modes.add(m.mode);
    // 模式名要能长成一张表（`task_<mode>`）。长不出来的话装表那一步才炸。
    try {
      tableNameOf("task_{}", m.mode);
    } catch (e) {
      say(`${at}: ${e instanceof Error ? e.message : String(e)}`);
    }
    if (!Array.isArray(m.cycles) || m.cycles.length === 0) {
      say(`${at}: it has no cycles`);
      continue;
    }
    // 走树那套机制自带一个交卷站（`tree/dfs.ts` 的 `withSubmit`）。**验的是补完之后
    // 那张图** —— 验之前那张的话，「从起点走不到它」这类检查会漏掉补出来的那一站。
    m.cycles = withSubmit(m.cycles as never) as never;

    const names = new Set<string>();
    for (const c of m.cycles) {
      if (!c.cycle || !c.cycle.trim()) {
        say(`${at}: one of its cycles has no name`);
        continue;
      }
      if (names.has(c.cycle)) say(`${at}/${c.cycle}: this cycle name appears twice`);
      names.add(c.cycle);
    }

    for (const c of m.cycles) {
      const cat = `${at}/${c.cycle}`;
      const next = list(c.next, `the next of ${cat}`, bad);
      const from = list(c.from, `the from of ${cat}`, bad);
      // 指到这个模式外面去的周期永远走不到，而内核不会说什么 —— 它只是停在那儿。
      for (const n of next) if (!names.has(n)) say(`${cat}: next names ${n}, which is not in this mode`);
      for (const f of from) if (!names.has(f)) say(`${cat}: from names ${f}, which is not in this mode`);

      if (c.maxUnits !== undefined && (!Number.isInteger(c.maxUnits) || c.maxUnits < 1)) {
        say(`${cat}: max_units must be a positive integer`);
      }
      // 推断函数没注册 → 走到这一站才炸，而那时候任务已经跑了一半。
      if (!c.infer || !c.infer.trim()) say(`${cat}: infer is missing`);
      else if (!handleThere(c.infer)) say(`${cat}: infer is ${c.infer}, but ${noHandle(c.infer)}`);

      const want = (c.apiMode ?? "").trim();
      if (want) {
        if (!MODE_NAMES.has(want)) {
          say(`${cat}: apiMode=${want} is not a known api mode (known: ${[...MODE_NAMES].join(", ")})`);
        } else if (!servedBy(db, want)) {
          say(`${cat}: it needs a ${want} lane, but no row in the api table serves one - every unit of this cycle is stuck`);
        }
      }
    }

    // 起点：`from` 为空的那些。一个都没有 = 这个模式根本进不去。
    const entries = m.cycles.filter((c) => list(c.from, "", []).length === 0).map((c) => c.cycle);
    if (entries.length === 0) say(`${at}: no entry point (every cycle has a non-empty from), so this mode cannot be entered`);

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
      if (c.cycle && !seen.has(c.cycle)) say(`${at}/${c.cycle}: unreachable from any entry point - this cycle would never be used`);
    }
  }

  // ── 智能体 ────────────────────────────────────────────────────────────
  const agents = new Set<string>();
  for (const a of d.agents ?? []) {
    const at = `agent ${a.name || "(unnamed)"}`;
    if (!a.name || !a.name.trim()) {
      say(`an agent has no name`);
      continue;
    }
    if (agents.has(a.name)) say(`${at}: appears twice in this declaration`);
    agents.add(a.name);
    try {
      tableNameOf("agent_{}_ctx", a.name);
    } catch (e) {
      say(`${at}: ${e instanceof Error ? e.message : String(e)}`);
    }
    if (!a.unit || !a.unit.trim()) say(`${at}: unit is missing`);
    else if (!handleThere(a.unit)) say(`${at}: unit is ${a.unit}, but ${noHandle(a.unit)}`);

    if (!Array.isArray(a.apis)) {
      say(`${at}: apis must be a list of [key_env, model]`);
      continue;
    }
    for (const pair of a.apis) {
      if (!Array.isArray(pair) || pair.length !== 2) {
        say(`${at}: one entry of apis is not a [key_env, model] pair`);
        continue;
      }
      const [keyEnv, model] = pair;
      if (all(db, `select 1 from api where key_env = ? and model = ?`, [keyEnv, model]).length === 0) {
        say(`${at}: ${keyEnv}/${model} is not registered in the api table - this lane can never be selected`);
      }
    }
  }

  // ── 触发条件 ──────────────────────────────────────────────────────────
  //
  // 跟 `check` 查的是同一套，只是提前到了**写进去之前**。写进去之后再查的话，
  // 那条件已经在库里躺着了 —— 而它的表现是「永远不触发」，不是报错。
  const colsOf = (t: string) => (all(db, `pragma table_info("${t}")`) as { name: string }[]).map((r) => r.name);
  const dimKeys: Record<string, string[]> = {
    agent: colsOf("agent"),
    task: colsOf("task"),
    cycle: colsOf("cycle"),
  };
  const checkWhen = (at: string, when: WhenDecl | undefined) => {
    for (const [i, group] of (when ?? []).entries()) {
      if (!Array.isArray(group) || group.length === 0) {
        say(`${at}: group ${i} is empty - an empty group never matches in full, so writing it changes nothing`);
        continue;
      }
      for (const t of group) {
        const where = `${at} group ${i}`;
        if (!(DIMS as readonly string[]).includes(t.dim)) {
          say(`${where}: unknown dimension ${t.dim} (known: ${DIMS.join(" / ")})`);
          continue;
        }
        if (!(OPS as readonly string[]).includes(t.op)) {
          say(`${where}: unknown operator ${t.op} (known: ${OPS.join(" / ")})`);
          continue;
        }
        if (t.dim === "chain" || t.dim === "moment" || t.dim === "place") {
          if ((t.key ?? "").trim() !== "") say(`${where}: dimension ${t.dim} has no attributes, so key must be empty`);
          if (t.dim === "moment" && !(MOMENTS as readonly string[]).includes(t.value)) {
            say(`${where}: unknown moment ${t.value} (the kernel raises: ${MOMENTS.join(" / ")})`);
          }
        } else if (!(dimKeys[t.dim] ?? []).includes(t.key ?? "")) {
          say(`${where}: dimension ${t.dim} has no attribute ${t.key ?? "(empty)"} (it has: ${(dimKeys[t.dim] ?? []).join(" / ")})`);
        }
        if (t.op === "in") {
          try {
            if (!Array.isArray(JSON.parse(t.value))) say(`${where}: the value for in must be a list, but it is ${t.value}`);
          } catch {
            say(`${where}: the value for in is not readable JSON: ${t.value}`);
          }
        }
        // 关键词带空格 = 把几个词写一起了。系统不替你猜要的是相邻还是有序。
        if (t.op !== "in" && /\s/.test(t.value) && t.dim !== "task") {
          say(`${where}: the value contains a space (${JSON.stringify(t.value)}) - split it into two terms in the same group rather than letting the system guess`);
        }
      }
    }
  };

  // ── 工具 ──────────────────────────────────────────────────────────────
  const tools = new Set<string>();
  for (const t of d.tools ?? []) {
    const at = `tool ${t.name || "(unnamed)"}`;
    if (!t.name || !t.name.trim()) {
      say(`a tool has no name`);
      continue;
    }
    if (tools.has(t.name)) say(`${at}: appears twice in this declaration`);
    tools.add(t.name);
    if (!t.identity || !handleThere(t.identity)) {
      say(`${at}: identity is ${t.identity ?? "(empty)"}, but ${noHandle(String(t.identity))}`);
    }
    if (!t.does) say(`${at}: does is missing - that is the description the model reads; empty means the model has no idea what it is for`);
    if (t.params === undefined || t.params === null) say(`${at}: params is missing - that is the argument schema the model reads`);
    if (t.output === undefined || t.output === null) say(`${at}: output is missing - that is the result schema the model reads`);
    checkWhen(at, t.when);
    // 不是系统工具、又一条条件都没有 = 谁都拿不到它。**合法，但一定不是本意。**
    if (!t.system && (t.when ?? []).length === 0) {
      say(`${at}: not a system tool and it has no trigger terms - it would never be attached to any agent`);
    }
  }

  // ── 压法 ──────────────────────────────────────────────────────────────
  const hows = new Set<string>();
  for (const h of d.hows ?? []) {
    const at = `press how ${h.name || "(unnamed)"}`;
    if (!h.name || !h.name.trim()) {
      say(`a way of pressing has no name`);
      continue;
    }
    if (hows.has(h.name)) say(`${at}: appears twice in this declaration`);
    hows.add(h.name);
    if (!h.identity || !handleThere(h.identity)) {
      say(`${at}: identity is ${h.identity ?? "(empty)"}, but ${noHandle(String(h.identity))}`);
    }
    // 两份 schema 都得给。**收什么、回什么说不清的话，压出来的东西没人验得了**，
    // 而压错了的上下文照样发得出去 —— 那是最难查的一种错。
    if (h.params === undefined || h.params === null) say(`${at}: params is missing - what the handle is given must be declared`);
    if (h.output === undefined || h.output === null) say(`${at}: output is missing - what the handle answers must be declared`);
  }

  // ── 规则 ──────────────────────────────────────────────────────────────
  const rules = new Set<string>();
  for (const r of d.rules ?? []) {
    const at = `rule ${r.identity || "(unnamed)"}`;
    if (!r.identity || !r.identity.trim()) {
      say(`a rule has no identity`);
      continue;
    }
    if (rules.has(r.identity)) say(`${at}: appears twice in this declaration`);
    rules.add(r.identity);
    if (!handleThere(r.identity)) {
      say(`${at}: a rule identity is the handle name, and ${noHandle(r.identity)}`);
    }
    if (r.writes === undefined || r.writes === null) say(`${at}: writes is missing - which tables it touches and how must be declared`);
    if (r.scope === undefined || r.scope === null) say(`${at}: scope is missing - which rows it may touch must be declared`);
    checkWhen(at, r.when);
    if ((r.when ?? []).length === 0) say(`${at}: no trigger terms at all - it would never run`);
  }

  // ── skill ─────────────────────────────────────────────────────────────
  const skills = new Set<string>();
  for (const s of d.skills ?? []) {
    const at = `skill ${s.identity || "(unnamed)"}`;
    if (!s.identity || !s.identity.trim()) {
      say(`a skill has no identity`);
      continue;
    }
    if (skills.has(s.identity)) say(`${at}: appears twice in this declaration`);
    skills.add(s.identity);
    // `body` 留空 = 动态生成，那就得真有个句柄现给；写死了的就不用。
    if (!s.body && !handleThere(s.identity)) {
      say(`${at}: body is empty (dynamically generated), but ${noHandle(s.identity)} - nobody can produce the content on demand`);
    }
    if (!s.role) say(`${at}: role is missing`);
    checkWhen(at, s.when);
    if ((s.when ?? []).length === 0) say(`${at}: no trigger terms at all - it would never be injected`);
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
export async function apply(db: Conn, reg: Registry, pool: Servers, d: Declare): Promise<Declared> {
  const bad = inspect(db, reg, d);
  if (bad.length) {
    const e = new Error(`this declaration has ${bad.length} problems; nothing was written`) as Error & {
      statusCode?: number;
      problems?: string[];
    };
    e.statusCode = 400;
    e.problems = bad;
    throw e;
  }

  const before = new Set(tableNames(db));

  // ── server 先连、先拉工具，**再开事务** ───────────────────────────────
  //
  // 连出去是要等的，而 SQLite 的事务里不该挂着等网络 —— 一个连不上的 server
  // 能把库锁到超时。而且「连不上」本来就该在动库之前拒：声明一个连不上的
  // server 是错，跟声明一个不存在的句柄一样。
  const grew: Record<string, string[]> = {};
  for (const s of d.servers ?? []) {
    run(
      db,
      `insert into mcp_server (name, spec, note) values (?, ?, ?)
       on conflict(name) do update set spec = excluded.spec, note = excluded.note`,
      [
        s.name,
        JSON.stringify({
          ...(s.command ? { command: s.command, args: s.args ?? [], env: s.env ?? {} } : {}),
          ...(s.url ? { url: s.url, headers: s.headers ?? {} } : {}),
        }),
        null,
      ],
    );
    grew[s.name] = await pull(db, pool, { ...s, name: s.name }, s.tools, { expectMs: MCP_EXPECT_MS });
    // 工具是 server 报的，`when` 是我们补的 —— 补在这儿，跟别的 owner 一个写法。
    for (const [tool, o] of Object.entries(s.tools ?? {})) {
      if (o.when !== undefined) putWhen(db, "tool", tool, o.when as WhenDecl);
    }
  }

  db.exec("begin");
  try {
    for (const p of d.places ?? []) {
      run(
        db,
        `insert into workplace (place, identity, runtime, forward, tools, usable) values (?, ?, ?, ?, ?, ?)
         on conflict(place) do update set identity = excluded.identity, runtime = excluded.runtime,
           forward = excluded.forward, tools = excluded.tools, usable = excluded.usable`,
        [
          p.place,
          p.identity ?? null,
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
          `insert into cycle (mode, cycle, api_mode, must_call, max_units, "from", next, infer) values (?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            m.mode,
            c.cycle,
            (c.apiMode ?? "").trim() || null,
            (c.mustCall ?? "").trim() || null,
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
        `insert into agent (name, config, apis, unit, knobs, state) values (?, ?, ?, ?, ?, ?)
         on conflict(name) do update set config = excluded.config, apis = excluded.apis,
           unit = excluded.unit, knobs = excluded.knobs, state = excluded.state`,
        [
          a.name,
          a.config ?? null,
          JSON.stringify(a.apis),
          a.unit,
          // 不给就是不给 —— 空对象和「没有这一栏」是同一件事，没必要让调用方在两种
          // 「没有」之间选。
          a.knobs && Object.keys(a.knobs).length ? JSON.stringify(a.knobs) : null,
          a.state ?? "idle",
        ],
      );
    }

    for (const h of d.handles ?? []) {
      run(
        db,
        `insert into handle (name, expect_ms, module) values (?, ?, ?)
         on conflict(name) do update set expect_ms = excluded.expect_ms, module = excluded.module`,
        [h.name, h.expectMs, h.module ?? null],
      );
    }

    for (const h of d.hows ?? []) {
      run(
        db,
        `insert into press_how (name, note, identity, params, output) values (?, ?, ?, ?, ?)
         on conflict(name) do update set note = excluded.note, identity = excluded.identity,
           params = excluded.params, output = excluded.output`,
        [h.name, h.note ?? null, h.identity, JSON.stringify(h.params), JSON.stringify(h.output)],
      );
    }

    for (const t of d.tools ?? []) {
      run(
        db,
        `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable, gives)
         values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         on conflict(name) do update set identity = excluded.identity, does = excluded.does,
           params = excluded.params, output = excluded.output, prompt = excluded.prompt,
           concurrent = excluded.concurrent, system = excluded.system,
           access = excluded.access, usable = excluded.usable, gives = excluded.gives`,
        [
          t.name, t.identity, t.does, JSON.stringify(t.params), JSON.stringify(t.output),
          t.prompt ?? null, t.concurrent ? 1 : 0, t.system ? 1 : 0, t.access ?? null,
          t.usable === false ? 0 : 1, t.gives ?? null,
        ],
      );
      putWhen(db, "tool", t.name, t.when);
    }

    for (const r of d.rules ?? []) {
      run(
        db,
        `insert into rule (identity, does, params, writes, access, scope) values (?, ?, ?, ?, ?, ?)
         on conflict(identity) do update set does = excluded.does, params = excluded.params,
           writes = excluded.writes, access = excluded.access, scope = excluded.scope`,
        [
          r.identity, r.does, JSON.stringify(r.params), JSON.stringify(r.writes),
          r.access === undefined ? null : JSON.stringify(r.access), JSON.stringify(r.scope),
        ],
      );
      putWhen(db, "rule", r.identity, r.when);
    }

    for (const s of d.skills ?? []) {
      run(
        db,
        `insert into skill (identity, does, params, body, role, usable) values (?, ?, ?, ?, ?, ?)
         on conflict(identity) do update set does = excluded.does, params = excluded.params,
           body = excluded.body, role = excluded.role, usable = excluded.usable`,
        [s.identity, s.does, JSON.stringify(s.params), s.body ?? null, s.role, s.usable === false ? 0 : 1],
      );
      putWhen(db, "skill", s.identity, s.when);
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
    servers: grew,
    handles: (d.handles ?? []).map((h) => h.name),
    places: (d.places ?? []).map((p) => p.place),
    modes: (d.modes ?? []).map((m) => m.mode),
    cycles: (d.modes ?? []).reduce((n, m) => n + m.cycles.length, 0),
    agents: (d.agents ?? []).map((a) => a.name),
    tools: (d.tools ?? []).map((t) => t.name),
    rules: (d.rules ?? []).map((r) => r.identity),
    skills: (d.skills ?? []).map((s) => s.identity),
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
  const places = (all(db, `select place, identity, runtime, forward, tools, usable from workplace order by place`) as {
    place: string; identity: string | null; runtime: string | null; forward: number; tools: string; usable: number;
  }[]).map((r) => ({
    place: r.place,
    identity: r.identity,
    runtime: r.runtime,
    forward: Boolean(r.forward),
    tools: safeJson(r.tools, []) as { tool: string; policy: string }[],
    usable: Boolean(r.usable),
  }));

  const modes: ModeDecl[] = [];
  for (const m of all(db, `select name, note from mode order by name`) as { name: string; note: string | null }[]) {
    const cycles = all(db, `select cycle, api_mode, must_call, max_units, "from", next, infer from cycle where mode = ? order by cycle`, [
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

  const agents = (all(db, `select name, config, apis, unit, knobs, state from agent order by name`) as {
    name: string; config: string | null; apis: string; unit: string; state: string;
  }[]).map((r) => ({
    name: r.name,
    config: r.config,
    apis: safeJson(r.apis, []) as [string, string][],
    unit: r.unit,
    state: r.state,
  }));

  // 句柄只导**外面注册进来的那些**（`http://`）。进程内的 `fn:` 是代码带来的，
  // 导出去再回灌一遍毫无意义 —— 而且回灌到一台没有那段代码的机器上就是一条
  // 谁都认领不了的句柄。
  const handles = (all(db, `select name, expect_ms from handle where name like 'http://%' or name like 'https://%' order by name`) as {
    name: string; expect_ms: number;
  }[]).map((r) => ({ name: r.name, expectMs: r.expect_ms }));

  const tools = (all(db, `select * from tool order by name`) as Record<string, unknown>[]).map((r) => ({
    name: String(r.name),
    identity: String(r.identity),
    does: String(r.does),
    params: safeJson(String(r.params), {}),
    output: safeJson(String(r.output), {}),
    prompt: (r.prompt as string | null) ?? null,
    concurrent: Boolean(r.concurrent),
    system: Boolean(r.system),
    access: (r.access as string | null) ?? null,
    usable: Boolean(r.usable),
    when: whenOf(db, "tool", String(r.name)),
  }));

  const rules = (all(db, `select * from rule order by identity`) as Record<string, unknown>[]).map((r) => ({
    identity: String(r.identity),
    does: String(r.does),
    params: safeJson(String(r.params), {}),
    writes: safeJson(String(r.writes), {}),
    scope: safeJson(String(r.scope), {}),
    access: r.access == null ? null : safeJson(String(r.access), null),
    when: whenOf(db, "rule", String(r.identity)),
  }));

  const skills = (all(db, `select * from skill order by identity`) as Record<string, unknown>[]).map((r) => ({
    identity: String(r.identity),
    does: String(r.does),
    params: safeJson(String(r.params), {}),
    body: (r.body as string | null) ?? null,
    role: String(r.role),
    usable: Boolean(r.usable),
    when: whenOf(db, "skill", String(r.identity)),
  }));

  return { handles, places, modes, agents, tools, rules, skills };
}

/**
 * 把一个 owner 的触发条件整组换掉。
 *
 * **整组换，不是逐条 upsert。** 少给一组就该是「删掉它」，而 upsert 会把它留在
 * 库里 —— 那一组照样会命中，于是「我明明把条件改窄了」而它还是到处触发，零报错。
 *
 * `when` 整个不给（`undefined`）= 不动它现有的条件；给了空数组 = 明确清空。
 * 这两件事不一样：前者是「这次没提」，后者是「我要它一条都没有」。
 */
function putWhen(db: Conn, kind: string, owner: string, when: WhenDecl | undefined): void {
  if (when === undefined) return;
  run(db, `delete from trigger where owner_kind = ? and owner = ?`, [kind, owner]);
  for (const [i, group] of when.entries()) {
    for (const t of group) {
      run(
        db,
        `insert into trigger (owner_kind, owner, "group", dim, "key", op, value) values (?, ?, ?, ?, ?, ?, ?)`,
        [kind, owner, i, t.dim, t.key ?? "", t.op, t.value],
      );
    }
  }
}

/** 库里那个 owner 的条件读回来，还原成 `when` 的形状（外层组，组间 or）。 */
function whenOf(db: Conn, kind: string, owner: string): WhenDecl {
  const rows = all(db, `select "group", dim, "key", op, value from trigger where owner_kind = ? and owner = ? order by "group"`, [
    kind,
    owner,
  ]) as { group: number; dim: string; key: string; op: string; value: string }[];
  const by = new Map<number, TermDecl[]>();
  for (const r of rows) {
    const g = Number(r.group);
    by.set(g, [...(by.get(g) ?? []), { dim: r.dim, key: r.key, op: r.op, value: r.value }]);
  }
  return [...by].sort((a, b) => a[0] - b[0]).map(([, terms]) => terms);
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
