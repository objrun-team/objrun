/**
 * 起这个程序。
 *
 * **这一层是组装**：读配置、把库和接口拉起来、管停机。
 * 底下每个部件都不认得配置文件长什么样，只拿到已经算好的东西。
 *
 * ```
 * bun src/main.ts
 * ```
 */

import pkg from "../package.json" with { type: "json" };
import { aboutRoutes } from "./api/about.ts";
import { benchRoutes } from "./api/bench.ts";
import { declareRoutes } from "./api/declare.ts";
import { mount, mountHelp } from "./api/spec.ts";
import { taskRoutes } from "./api/tasks.ts";
import { Kernel } from "./engine/loop.ts";
import { Registry } from "./engine/registry.ts";
import { readConfig } from "./H2H/config.ts";
import { all, run } from "./H2H/db.ts";
import { build } from "./H2H/server.ts";
import { install, tableNameOf } from "./install/index.ts";
import { registerVendors, seedModes } from "./llm/index.ts";
import { registerDuplex, Sessions } from "./llm/duplex.ts";
import { Servers } from "./mcp/client.ts";
import { attach } from "./mcp/register.ts";
import { mcpServeRoutes } from "./mcp/serve.ts";
import { evaluate } from "./objective/run.ts";
import { openSealed } from "./objective/store.ts";
import { deliverVerdict, seedKinds, seedRoles } from "./msg/deliver.ts";
import { handedIn, registerTree, SUBMIT } from "./tree/dfs.ts";
import { registerVerifyTool } from "./objective/tool.ts";
import { registerTreeView } from "./tree/view.ts";
import { check } from "./trigger/check.ts";
import { checkData } from "./trigger/data.ts";
import { Places, registerTools } from "./tools/register.ts";
import { registerSearchTool } from "./tools/search.ts";
import { closePython } from "./tools/python.ts";
import { registerToolUnit } from "./tools/unit.ts";

const VERSION = pkg.version;

/** 这个任务最后一站是谁在干。 */
function lastUnit(
  db: Parameters<typeof all>[0],
  task: string,
): { agent: string; instance: string; unit: number } | undefined {
  const t = all(db, `select mode from task where id = ?`, [task])[0] as { mode?: string } | undefined;
  if (!t?.mode) return undefined;
  const sub = tableNameOf("task_{}", String(t.mode));
  return all(db, `select agent, instance, unit from "${sub}" where task = ? order by unit desc limit 1`, [task])[0] as
    | { agent: string; instance: string; unit: number }
    | undefined;
}

/**
 * 等那一站落完。**收尾判决要给正在干活的调用让路。**
 *
 * 时限到了不代表那一站回来了 —— 它可能正跑着一段 python，或者正等着模型回话。
 * 判决和那一站的结果都是「取当前最大 seq 再加一」往同一格里追加，所以谁先落谁
 * 排前面。判决抢在前面的话，上一站那次调用和它的结果中间就夹了一对判决，而模型
 * 那边不许这个形状（`An assistant message with 'tool_calls' must be followed by
 * tool messages responding to each of them`），整条链路从此发不出去。
 *
 * **超时是这里面优先级最低的一件事** —— 那次调用是真在干活，判决只是收尾。
 *
 * 不硬等：那一站自己有 `expect_ms`，到点内核会把它判死关掉，这儿只是跟着那个钟
 * 走。反正这道题已经判完了，判决晚落一会儿不改变任何结果。
 */
async function settled(db: Parameters<typeof all>[0], task: string, unit: number | undefined): Promise<void> {
  if (unit === undefined) return;
  const t = all(db, `select mode from task where id = ?`, [task])[0] as { mode?: string } | undefined;
  if (!t?.mode) return;
  const sub = tableNameOf("task_{}", String(t.mode));
  const CAP_MS = 16 * 60 * 1000; // 比句柄那 15 分钟稍长，让它先被判死
  const t0 = Date.now();
  while (Date.now() - t0 < CAP_MS) {
    const row = all(db, `select done from "${sub}" where task = ? and unit = ?`, [task, unit])[0] as
      | { done?: number }
      | undefined;
    if (!row || Number(row.done) === 1) return;
    await Bun.sleep(500);
  }
}

/**
 * 收尾那一刻，**这道题交上来的是什么**。
 *
 * 交卷是流转表上的一站（`tree/dfs.ts` 的 `SUBMIT`，随机制一起装上）。**交的就是
 * 那一站说的那段话** —— 不是内核回头去消息表里猜哪句像答案。
 *
 * | 先看 | 为什么 |
 * | --- | --- |
 * | 交卷站上最后那段有内容的话 | 那一站的意思就是「我交这个」，不用猜 |
 * | 别处最后一条有内容的 `prompt` | 没走到交卷站的兜底（超时、额度耗干） |
 *
 * 只认 `prompt`。`call` 那一行的 text 是**调工具前的开场白**，不是答复 ——
 * 实测拿它去判过，判卷台看到的是「let me look at the environment to understand
 * this task better.」。空话也跳过：一发什么都没生成出来不是答复。
 *
 * 全都没有就回 `undefined` —— **那是「没交卷」**，跟「交了但判错」是两回事，
 * 收尾那边据它给出不同的 `why`。
 */
function lastSaid(db: Parameters<typeof all>[0], task: string): { body: string; how: string } | undefined {
  const u = lastUnit(db, task);
  if (!u) return undefined;
  const t = all(db, `select mode from task where id = ?`, [task])[0] as { mode?: string } | undefined;
  const sub = t?.mode ? tableNameOf("task_{}", String(t.mode)) : "";
  const msg = tableNameOf("agent_{}_msg", u.agent);

  const spoke = (units: number[]): string | undefined => {
    if (units.length === 0) return undefined;
    // `call` 行的 `body` 是 `{text, calls}` —— 它开口说的那半句在 `text` 里。
    // 只认 `prompt` 的话，一个「说了两句然后去调工具」的交卷站会被读成「什么都没交」。
    const rows = all(
      db,
      `select kind, body from "${msg}"
        where instance = ? and kind in ('prompt', 'call') and unit in (${units.map(() => "?").join(",")})
        order by unit desc, seq desc limit 20`,
      [u.instance, ...units],
    ) as { kind?: string; body?: string }[];
    for (const r of rows) {
      if (r.body === undefined) continue;
      let text = r.body;
      if (r.kind === "call") {
        try {
          const v = JSON.parse(r.body) as { text?: unknown; calls?: { input?: { answer?: unknown } }[] };
          // 说了话就取话；一个字没说就取它想拿去问 G 的那一份（`verify` 的 `answer`）——
          // 跟 `tree/dfs.ts` 在交卷站上的取法是同一条，两处不许各读各的。
          text = String(v.text ?? "");
          if (!text.trim()) {
            for (const c of [...(v.calls ?? [])].reverse()) {
              if (typeof c.input?.answer === "string" && c.input.answer.trim()) {
                text = c.input.answer;
                break;
              }
            }
          }
        } catch {
          continue;
        }
      }
      if (text.trim()) return text;
    }
    return undefined;
  };

  // **先看它交了什么，再看它说了什么 —— 而「交了什么」只有一个出处。**
  //
  // 交卷是调一次 `submit` 并把答案放进去（见 `tree/dfs.ts`）。收尾这一路要是自己
  // 另读一遍「它在交卷站说的那段话」，同一份东西就有了两个答案：交卷站按调用里的
  // 那份判，收尾按它随口说的那段判，两边判出不同的结果，而成绩以后者为准。
  //
  // 实测就这么丢过题：交卷站判 1、树正常收工（`status = reached`），收尾又判了
  // 一次判 0，成绩单上是没过。**真的做对了的题被判成没做对。**
  const answer = handedIn(db, u.agent, u.instance);
  if (answer !== null && answer.trim()) return { body: answer, how: "submitted" };

  // 没有交卷那一站的机制（不走树的那些）到这儿 —— 它们没有 `submit` 可调，
  // 「交了什么」就只能是它最后说的那段话。
  const anywhere = sub
    ? (all(db, `select unit from "${sub}" where task = ? order by unit desc`, [task]) as { unit: number }[]).map(
        (r) => Number(r.unit),
      )
    : [];
  const last = spoke(anywhere);
  return last ? { body: last, how: "last words" } : undefined;
}

const cfg = readConfig();

// 写口打完喊一声，内核醒过来。内核还没造出来，先留个空的，造好再换 ——
// 这一圈是组装层的事，H2H 不认得内核，内核也不认得 HTTP。
let wake = () => {};
const app = await build(cfg, { onWrite: () => wake() });

// 装表。幂等 —— 已经在且形状对的跳过；对不上当场炸，不自动改。
const built = install(app.store.rw);
app.log.info(
  `tables: created ${built.create.length}, already there ${built.ok.length}` +
    (built.extra.length ? `, ${built.extra.length} outside the declaration (untouched)` : ""),
);

// 句柄注册表 + 内核。
//
// **进程内的句柄在这一层注册** —— 只有这个进程持有得住函数。
// 进程外的（http:// 开头）不用碰这儿：往库里 handle 表写一行，
// 内核下一圈醒来自己给它合成调用器。
const registry = new Registry();
const places = new Places(app.store.ro);

// MCP server 池。声明一个 server 是**一条批量来源** —— 它自己报有哪些工具，
// 替你把那些行写出来。起着的子进程和连接是活状态，跟位置一样不进库；停机时全关。
const servers = new Servers();

// 库里登记的 MCP 工具，每圈把调用器装上。**新登记一个 server，下一圈就有了** ——
// 不用重启。这一步得排在内核起来之前，不然第一圈会说「句柄没人注册」。
registry.beforeSync = () => attach(app.store.rw, registry, servers);

// 验证函数 G 的封存区。**单独一个库，H2H 不开它** —— 主库全接口开放，
// G 存主库就等于没有墙。红线靠「够不着」，不靠「规定不许」。
const sealed = openSealed(cfg.db.sealed);

// 内核判一个任务的执行单元全干完了 → 这儿跑 G，把判决写回主库。
// **内核不认得 G**，它只喊一声「跑完了」。
const kernel = new Kernel(app.store, app.log, registry, {
  onDone(task, expired) {
    if (!sealed.has(task)) return; // 没有 G 的任务，跑完就是跑完
    void (async () => {
      const g = sealed.open(task);
      if (!g) return;
      const row = all(app.store.ro, `select id, description, place, workdir from task where id = ?`, [task])[0];
      const at = lastUnit(app.store.ro, String(task));
      const said = lastSaid(app.store.ro, String(task));

      // **没交卷就不用问 G 了。** 有 G 的任务，收尾得有一份「我交的是这个」——
      // `verify` 就是那个口。递空串进去的话，判卷台只会说「没找到答案」，
      // 日志上看像判据出了毛病，其实是它压根没交。这两件事得分得开。
      const v = said
        ? await evaluate(g, registry, { task: row, result: said })
        : { pass: 0 as const, why: "nothing submitted - it never reached the hand-in step, so there is nothing to grade", trace: [] };

      // **拿到判决就投回上下文** —— 跟树那一路一个规矩（`tree/dfs.ts`）：
      // 凡是问过 G 的，判决都以「一次带结果的工具调用」落在那一站上。
      // 只写 `task.result` 的话，那是给我们看的，模型永远不知道自己被判了什么。
      // **超时让路。** 收尾判决要落在那一站上，而那一站这会儿可能还在跑 ——
      // 时限到了不代表那次调用回来了。两边都是「取当前最大 seq 再加一」，所以
      // 谁先落谁排前面：判决抢在前面的话，上一站那次调用和它的结果就被隔开了，
      // 而模型那边不许这个形状（`An assistant message with 'tool_calls' must be
      // followed by tool messages responding to each of them`）。整条链路从此
      // 发不出去，库里留一句 stuck。
      //
      // **超时是这里面优先级最低的一件事** —— 那次调用是真在干活，判决只是收尾。
      // 所以等它落完再写。等不到也不硬等：那一站自己有 `expect_ms`，到点会被判死
      // 关掉，这儿的等待封顶就是那个时长。
      await settled(app.store.ro, String(task), at?.unit);

      if (at) {
        deliverVerdict(app.store.rw, {
          agent: at.agent,
          instance: at.instance,
          unit: at.unit,
          name: "verify",
          input: { task, at: "wrap-up" },
          value: { pass: v.pass, why: v.why },
        });
      }

      // 超时那一路也走到这儿（`#reap`）。**判决照给** —— 它要是在时限内就把对的
      // 交上来了，那就是做出来了，只是树没来得及收尾；时限只说明「没能自己收工」。
      // 判 0 的话把超时一起记进 `why`，不然成绩单上分不清是判错还是耗光。
      const why = v.pass === 1 ? v.why : [expired, v.why].filter(Boolean).join("; ");
      run(app.store.rw, `update task set state = ?, result = ? where id = ?`, [
        v.pass === 1 ? "done" : "failed",
        JSON.stringify({ pass: v.pass, why }),
        task,
      ]);
      app.log.info(
        `graded ${task}: ${v.pass} (${said ? said.how : "nothing submitted"}${why ? ", " + why : ""})`,
      );
    })();
  },
});
wake = () => kernel.wake();

// 树的控制流：派生 / 判死开兄弟 / 回退。它是个推断函数，不是内核的一部分 ——
// 换一种搜索策略就是换一个 infer 句柄，内核一个字不动。
app.log.info(`tree: ${registerTree(app.store.rw, registry, sealed).join(", ")}`);

// 树自省那两个工具。**不是 system 工具** —— 按 mode 分发：条件是「这一站的推断函数
// 走不走树」，所以一条道走到黑的单链机制一个都拿不到（它本来就直接继承上下文）。
app.log.info(`tree introspection: ${registerTreeView(app.store.rw, registry, "fn:infer.dfs").join(", ")}`);
// **有 G 就能问 G。** 判决本来每轮就投进上下文（名字也叫 verify），
// 补上这个工具那条轨迹才名副其实 —— 见 `objective/tool.ts`。
app.log.info(`grading tool: ${registerVerifyTool(app.store.rw, registry, sealed)}`);

// 认得的消息类型。**取值就是那条「谁放的 → kind」推断表的值域** —— 灌进来是
// 为了让 check 和人都能查得到，不是让谁去填。
app.log.info(`message kinds: ${seedKinds(app.store.rw).join(", ")}`);
app.log.info(`message roles: ${seedRoles(app.store.rw).join(", ")}`);

// 基础工具：注册进内核（它才持有得住函数），同时把给模型看的那几样落进 tool 表。
// 注册进去的函数只负责**转发** —— 按 workplace 决定这一次在哪儿跑。
app.log.info(`tools: ${registerTools(app.store.rw, registry, places).join(", ")}`);

// 检索单独一件：它不转发到 workplace（要的是网络和钥匙，不是那台机器上的文件系统），
// 而且**摆给谁看由 `trigger` 说了算** —— 只有 apis 里是「自己会搜」那几家的智能体
// 才拿得到。一家都不是，条件一条都不命中，谁也拿不到 —— 这正是 trigger 本来的语义。
app.log.info(`search tool: ${registerSearchTool(app.store.rw, registry)}`);

// 把上一站模型请求的工具真跑掉。**少了这一步工具那条链是断的** ——
// 请求落了库却永远不被执行，而且不报错。周期表上 api_mode 留空的那一站走它。
app.log.info(`tool-running unit: ${registerToolUnit(app.store.rw, registry)}`);

// 认得的调用形状。**取值就是 `api.modes` 那一列的值域** —— 跟消息类型一样，
// 灌进来是为了让 check 和人都查得到，不是让谁去填。
app.log.info(`api modes: ${seedModes(app.store.rw).join(", ")}`);

// 模型这一侧：每家一个适配器。**这个句柄同时是 api.handle 和 agent.unit** ——
// 一次调用就是一个执行单元。下面那几行 api 是数据，改它不用动代码。
app.log.info(
  `models: ${registerVendors(
    app.store.rw,
    registry,
    app.log,
    [
      ["deepseek", "deepseek-v4-flash", "chat,tools"],
      ["deepseek", "deepseek-v4-pro", "chat,tools"],
      ["deepseek", "deepseek-chat", "chat,tools"],
      ["deepseek", "deepseek-reasoner", "chat"],
      ["dashscope", "qwen-max", "chat,tools"],
    ],
    cfg.llm,
  ).join(", ")} | ${cfg.llm.maxTokens} output tokens (up to ${cfg.llm.continueTimes} continuations) | reasoning ${cfg.llm.reasoningEffort}`,
);

// 实时轨。**另一条句柄** —— 它不是一次调用，是一条会话，一个执行单元对应会话里的
// 一个来回。会话活在这个池子里（跟位置一样，是连接不是状态，不进库），停机时全关。
const sessions = new Sessions();
const duplexHandles = registerDuplex(app.store.rw, registry, sessions, [
  ["dashscope", "qwen-audio-3.0-realtime-flash"],
]);
app.log.info(`realtime lanes: ${duplexHandles.join(", ")}`);

// 内核这一侧的口。**每个口的说明、参数表、实现是同一份声明** —— 契约长在接口上，
// 不在旁边的文档里：文档会漂（说一套做一套，零报错），声明漂不了，漂了请求就会
// 被错误地拒，当场看得出来。参数表同时就是**校验**，也就是客户端的操作范围。
const kernelRoutes = [
  ...aboutRoutes(cfg.api.prefix, app.store, VERSION, duplexHandles),
  ...declareRoutes(app.store, registry, servers, () => wake()),
  ...taskRoutes(app.store, registry, sealed, () => wake()),
  ...benchRoutes(app.store, registry, sealed, () => wake()),
  // 这台引擎自己的 MCP server —— 不开的话，内核实现的那几个工具外面用不上。
  ...mcpServeRoutes(app.store, registry),
];
mount(app, cfg.api.prefix, kernelRoutes);

// help 得**列全**。路由分两处装（库那一层一处、这儿一处），漏掉一组的话，
// 客户端会以为那组不存在，然后回头去读表 —— 一读表两端就焊死了。
mountHelp(app, cfg.api.prefix, [...app.routes, ...kernelRoutes]);
app.log.info(`routes: ${app.routes.length + kernelRoutes.length}; GET ${cfg.api.prefix}/help for usage`);

// 停机：先不收新请求，等在途的走完；超时就硬停 —— 不设上限的话，
// 一个挂住的请求能把整个进程钉在那儿。
for (const sig of ["SIGINT", "SIGTERM"] as const) {
  process.on(sig, () => {
    const hard = setTimeout(() => process.exit(1), cfg.server.shutdownTimeout).unref();
    app
      .close()
      .then(() => {
        clearTimeout(hard);
        kernel.stop();
        closePython();
        places.closeAll();
        sessions.closeAll();
        servers.closeAll();
        registry.plugins.closeAll();
        sealed.close();
        app.store.close();
        process.exit(0);
      })
      .catch(() => process.exit(1));
  });
}

// 不只听本机、又不要令牌、还能写 —— 这三件凑齐就是同一个网里谁都能改库。
// 安卓那类客户端要连过来时最容易凑齐，所以在这儿喊一声。
const loopback = /^(127\.|::1$|localhost$)/.test(cfg.server.host);
if (!loopback && !cfg.api.token && cfg.api.allowWrite) {
  app.log.warn(`listening on ${cfg.server.host} with no api.token while api.allowWrite is on - anyone on this network can write to the database`);
}

await app.listen({ host: cfg.server.host, port: cfg.server.port });

// 开机自己验一遍触发条件。**不拦启动** —— 条件写错不该让整台机器起不来；
// 但也不能不吭声，静默不生效正是这张表最容易出的事。
const bad = check(app.store.ro);
if (bad.length) {
  app.log.warn(`${bad.length} trigger problems:`);
  for (const b of bad.slice(0, 10)) app.log.warn(`  ${b.owner_kind} ${b.owner} group ${b.group}: ${b.why}`);
}
const badData = checkData(app.store.ro, registry);
if (badData.length) {
  app.log.warn(`${badData.length} data inconsistencies:`);
  for (const b of badData.slice(0, 10)) app.log.warn(`  ${b.what}: ${b.why}`);
}

// 插件那条路开机探一遍。**不拦启动** —— 没装插件的机器不该因为它起不来；
// 但也不能不吭声，不然要等到某个任务真去调一个插件那一刻才发现。
const plugBad = await registry.plugins.probe();
if (plugBad) app.log.warn(plugBad);
else app.log.info(`plugin host: ${registry.plugins.host}`);

kernel.start();
app.log.info(`db ${cfg.db.file} | write ${cfg.api.allowWrite ? "on" : "off"} | token ${cfg.api.token ? "required" : "none"}`);
