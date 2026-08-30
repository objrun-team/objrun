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
import { seedKinds } from "./msg/deliver.ts";
import { registerTree } from "./tree/dfs.ts";
import { check } from "./trigger/check.ts";
import { checkData } from "./trigger/data.ts";
import { Places, registerTools } from "./tools/register.ts";
import { registerToolUnit } from "./tools/unit.ts";

const VERSION = pkg.version;

/**
 * 这个任务最后说的那句。
 *
 * G 在收尾那一刻要判「做成了没有」，而答案在消息表里 —— `task.result` 存的是判决
 * 本身，不是答复。取的是**最后一条模型自己说的**（`prompt` 或 `call`），跟树那一路
 * 递给 G 的 `result` 是同一样东西。
 *
 * 取不到就回 `undefined`：没答等于没做对，G 那边自己会归 0。
 */
function lastSaid(db: Parameters<typeof all>[0], task: string): { body: string } | undefined {
  const t = all(db, `select mode from task where id = ?`, [task])[0] as { mode?: string } | undefined;
  if (!t?.mode) return undefined;
  const sub = tableNameOf("task_{}", String(t.mode));
  const u = all(db, `select agent, instance from "${sub}" where task = ? order by unit desc limit 1`, [task])[0] as
    | { agent: string; instance: string }
    | undefined;
  if (!u) return undefined;
  const msg = tableNameOf("agent_{}_msg", u.agent);
  const r = all(
    db,
    `select body from "${msg}" where instance = ? and kind in ('prompt', 'call') order by unit desc, seq desc limit 1`,
    [u.instance],
  )[0] as { body?: string } | undefined;
  return r?.body === undefined ? undefined : { body: r.body };
}

const cfg = readConfig();

// 写口打完喊一声，内核醒过来。内核还没造出来，先留个空的，造好再换 ——
// 这一圈是组装层的事，H2H 不认得内核，内核也不认得 HTTP。
let wake = () => {};
const app = await build(cfg, { onWrite: () => wake() });

// 装表。幂等 —— 已经在且形状对的跳过；对不上当场炸，不自动改。
const built = install(app.store.rw);
app.log.info(
  `表：建了 ${built.create.length} 张，已有 ${built.ok.length} 张` +
    (built.extra.length ? `，声明外的 ${built.extra.length} 张（没动）` : ""),
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
  onDone(task) {
    if (!sealed.has(task)) return; // 没有 G 的任务，跑完就是跑完
    void (async () => {
      const g = sealed.open(task);
      if (!g) return;
      const row = all(app.store.ro, `select id, description, place, workdir from task where id = ?`, [task])[0];
      // **把最后那句答复一起递过去。** G 判的是「这道题做成了没有」，而答案在
      // 消息表里，不在 `task` 那一行上（`task.result` 是判决本身，不是答复）。
      // 不递的话 G 那一步拿到的是空字符串，凡是要看答案的 G 一律判 0 ——
      // 而且它会把树那一路刚判对的结果覆盖掉，看着像判据出错。
      //
      // 形状跟树那一路对齐（`tree/dfs.ts` 递的是 `{task, chain, result}`），
      // 这样一个 G 脚本两处都能用，不用问自己「这次是谁在叫我」。
      const v = await evaluate(g, registry, { task: row, result: lastSaid(app.store.ro, String(task)) });
      run(app.store.rw, `update task set state = ?, result = ? where id = ?`, [
        v.pass === 1 ? "done" : "failed",
        JSON.stringify({ pass: v.pass, why: v.why }),
        task,
      ]);
      app.log.info(`G 判了 ${task}：${v.pass}${v.why ? "（" + v.why + "）" : ""}`);
    })();
  },
});
wake = () => kernel.wake();

// 树的控制流：派生 / 判死开兄弟 / 回退。它是个推断函数，不是内核的一部分 ——
// 换一种搜索策略就是换一个 infer 句柄，内核一个字不动。
app.log.info(`树：${registerTree(app.store.rw, registry, sealed).join("、")}`);

// 认得的消息类型。**取值就是那条「谁放的 → kind」推断表的值域** —— 灌进来是
// 为了让 check 和人都能查得到，不是让谁去填。
app.log.info(`消息类型：${seedKinds(app.store.rw).join("、")}`);

// 基础工具：注册进内核（它才持有得住函数），同时把给模型看的那几样落进 tool 表。
// 注册进去的函数只负责**转发** —— 按 workplace 决定这一次在哪儿跑。
app.log.info(`工具：${registerTools(app.store.rw, registry, places).join("、")}`);

// 把上一站模型请求的工具真跑掉。**少了这一步工具那条链是断的** ——
// 请求落了库却永远不被执行，而且不报错。周期表上 api_mode 留空的那一站走它。
app.log.info(`执行工具：${registerToolUnit(app.store.rw, registry)}`);

// 认得的调用形状。**取值就是 `api.modes` 那一列的值域** —— 跟消息类型一样，
// 灌进来是为了让 check 和人都查得到，不是让谁去填。
app.log.info(`调用形状：${seedModes(app.store.rw).join("、")}`);

// 模型这一侧：每家一个适配器。**这个句柄同时是 api.handle 和 agent.unit** ——
// 一次调用就是一个执行单元。下面那几行 api 是数据，改它不用动代码。
app.log.info(
  `模型：${registerVendors(app.store.rw, registry, [
    ["deepseek", "deepseek-chat", "chat,tools"],
    ["deepseek", "deepseek-reasoner", "chat"],
    ["dashscope", "qwen-max", "chat,tools"],
  ]).join("、")}`,
);

// 实时轨。**另一条句柄** —— 它不是一次调用，是一条会话，一个执行单元对应会话里的
// 一个来回。会话活在这个池子里（跟位置一样，是连接不是状态，不进库），停机时全关。
const sessions = new Sessions();
const duplexHandles = registerDuplex(app.store.rw, registry, sessions, [
  ["dashscope", "qwen-audio-3.0-realtime-flash"],
]);
app.log.info(`实时轨：${duplexHandles.join("、")}`);

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
app.log.info(`接口：${app.routes.length + kernelRoutes.length} 个，打 ${cfg.api.prefix}/help 看用法`);

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
  app.log.warn(`听在 ${cfg.server.host}，没有 api.token，而 api.allowWrite 是开的 —— 同一个网里谁都能改这个库`);
}

await app.listen({ host: cfg.server.host, port: cfg.server.port });

// 开机自己验一遍触发条件。**不拦启动** —— 条件写错不该让整台机器起不来；
// 但也不能不吭声，静默不生效正是这张表最容易出的事。
const bad = check(app.store.ro);
if (bad.length) {
  app.log.warn(`触发条件有 ${bad.length} 处不对：`);
  for (const b of bad.slice(0, 10)) app.log.warn(`  ${b.owner_kind} ${b.owner} 第 ${b.group} 组：${b.why}`);
}
const badData = checkData(app.store.ro, registry);
if (badData.length) {
  app.log.warn(`库里有 ${badData.length} 处对不上：`);
  for (const b of badData.slice(0, 10)) app.log.warn(`  ${b.what}：${b.why}`);
}

// 插件那条路开机探一遍。**不拦启动** —— 没装插件的机器不该因为它起不来；
// 但也不能不吭声，不然要等到某个任务真去调一个插件那一刻才发现。
const plugBad = await registry.plugins.probe();
if (plugBad) app.log.warn(plugBad);
else app.log.info(`插件：${registry.plugins.host}`);

kernel.start();
app.log.info(`库 ${cfg.db.file}｜写 ${cfg.api.allowWrite ? "开" : "关"}｜令牌 ${cfg.api.token ? "要" : "不要"}`);
