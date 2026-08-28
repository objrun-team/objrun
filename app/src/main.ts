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

import { Kernel } from "./engine/loop.ts";
import { Registry } from "./engine/registry.ts";
import { readConfig } from "./H2H/config.ts";
import { all, run } from "./H2H/db.ts";
import { build } from "./H2H/server.ts";
import { install } from "./install/index.ts";
import { registerVendors } from "./llm/index.ts";
import { evaluate } from "./objective/run.ts";
import { openSealed } from "./objective/store.ts";
import { publish, type Publish } from "./tasks/publish.ts";
import { seedKinds } from "./msg/deliver.ts";
import { registerTree } from "./tree/dfs.ts";
import { check, explain } from "./trigger/check.ts";
import { checkData } from "./trigger/data.ts";
import { Places, registerTools } from "./tools/register.ts";

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
      const v = await evaluate(g, registry, { task: row });
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

// 模型这一侧：每家一个适配器。**这个句柄同时是 api.handle 和 agent.unit** ——
// 一次调用就是一个执行单元。下面那几行 api 是数据，改它不用动代码。
app.log.info(
  `模型：${registerVendors(app.store.rw, registry, [
    ["deepseek", "deepseek-chat", "chat,tools"],
    ["deepseek", "deepseek-reasoner", "chat"],
    ["dashscope", "qwen-max", "chat,tools"],
  ]).join("、")}`,
);

// 触发条件：不跑系统就把全部条件过一遍。**写错的典型后果是静默不生效** ——
// 那条规则永远不触发而系统照常跑，所以这一步不是调试功能，是能不能用的前提。
app.get(`${cfg.api.prefix}/trigger/check`, async () => ({ problems: check(app.store.ro) }));

// 整库过一遍：条件写得对不对 + 数据互相对不对得上。
// 「谁都不接而且不报错」是这一类问题的通名 —— 任务躺在库里状态永远是 open，
// 没人知道为什么。这个口就是拿来问的。
app.get(`${cfg.api.prefix}/check`, async () => ({
  trigger: check(app.store.ro),
  data: checkData(app.store.ro, registry),
}));

// 没命中的时候逐条说清哪一条没过，**带上实际取到的值** —— 只说「没匹配」的话，
// 人得自己猜是词写错了还是那段文本里根本没有。
app.post(`${cfg.api.prefix}/trigger/explain`, async (req, reply) => {
  const b = (req.body ?? {}) as {
    kind?: string; owner?: string; agent?: string; task?: string;
    mode?: string; cycle?: string; chain?: string;
  };
  try {
    const row = (t: string, sql: string, p: unknown[]) => {
      const r = all(app.store.ro, sql, p)[0];
      if (!r) throw new Error(`${t} 里没有这一行`);
      return r;
    };
    return explain(app.store.ro, String(b.kind), String(b.owner), {
      agent: b.agent ? row("agent", `select * from agent where name = ?`, [b.agent]) : {},
      task: b.task ? row("task", `select * from task where id = ?`, [b.task]) : {},
      cycle: b.mode ? row("cycle", `select * from cycle where mode = ? and cycle = ?`, [b.mode, b.cycle]) : {},
      chain: b.chain ?? "",
    });
  } catch (e) {
    return reply.code(400).send({ error: e instanceof Error ? e.message : String(e) });
  }
});

// 重装：灌完声明（新模式、新智能体）之后让子表长出来。幂等，随时能打。
app.post(`${cfg.api.prefix}/install`, async () => {
  const r = install(app.store.rw);
  return { create: r.create, ok: r.ok.length, extra: r.extra };
});

// 发任务：**外面往系统里放活，只走这一个口。**
// 不用进代码 import 库才能发布任务 —— 对系统的操作停留在 HTTP 这一层。
app.post(`${cfg.api.prefix}/tasks`, async (req, reply) => {
  try {
    const r = publish(app.store.rw, req.body as Publish, sealed);
    wake();
    return reply.code(201).send(r);
  } catch (e) {
    // 发布这一路的拒收都是「这道题根本别发布」，是请求的问题不是系统的问题。
    return reply.code(400).send({ error: e instanceof Error ? e.message : String(e) });
  }
});

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

kernel.start();
app.log.info(`库 ${cfg.db.file}｜写 ${cfg.api.allowWrite ? "开" : "关"}｜令牌 ${cfg.api.token ? "要" : "不要"}`);
