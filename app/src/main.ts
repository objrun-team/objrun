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
import { build } from "./H2H/server.ts";
import { install } from "./install/index.ts";
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
const kernel = new Kernel(app.store, app.log, registry);
wake = () => kernel.wake();

// 基础工具：注册进内核（它才持有得住函数），同时把给模型看的那几样落进 tool 表。
// 注册进去的函数只负责**转发** —— 按 workplace 决定这一次在哪儿跑。
app.log.info(`工具：${registerTools(app.store.rw, registry, places).join("、")}`);

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
kernel.start();
app.log.info(`库 ${cfg.db.file}｜写 ${cfg.api.allowWrite ? "开" : "关"}｜令牌 ${cfg.api.token ? "要" : "不要"}`);
