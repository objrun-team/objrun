/**
 * 一张给人看的页。**引擎自己 serve** —— 浏览器打开 `/ui` 就能看，不打包、不装东西。
 *
 * ## 它只是又一个客户端
 *
 * 看的全是 `api/` 底下那些口，一行表都不读。状态取值、消息类型也不写死，
 * 开机从 `/about` 拿 —— 那边加一种，这边自动就有。这跟 `api/about.ts` 开头
 * 说的是同一件事：客户端把这些当数据用，不当常量抄。
 *
 * ## 为什么嵌进来，不放文件旁边
 *
 * 编译成单文件之后 `import.meta.dir` 是个虚拟路径，那儿没有文件（`tools/python.ts`
 * 里说过）。按文本 import 进来，打包时就随代码一起进了二进制，跑源码和跑 exe
 * 拿到的是同一张页。
 *
 * ## 令牌
 *
 * 页本身不校验令牌（`H2H/server.ts` 的 `public`）—— 它里面没有数据，只有代码。
 * 页里发出去的每一次数据请求照样要带 `Authorization`，令牌在页上填。
 */

import type { FastifyInstance } from "fastify";

import raw from "./index.html" with { type: "text" };

// bun-types 把 `*.html` 声明成 `Bun.serve` 用的 HTMLBundle。这儿按文本引进来
// （`with { type: "text" }`），运行时拿到的是字符串，类型上得亲手说一遍。
const PAGE = raw as unknown as string;

/** 页挂在哪儿。不进 config：它跟 `/help` 一样是这台机器的固定门牌，不是可调的量。 */
export const UI_PATH = "/ui";

/**
 * 把页装上。前缀在这一刻烧进页里 —— 页不该自己猜接口在哪儿。
 * 回的是它挂的路径，好让开机日志把整个地址打出来。
 */
export function mountUi(app: FastifyInstance, prefix: string): string {
  const page = PAGE.replaceAll("__PREFIX__", prefix);
  app.get(UI_PATH, async (_req, reply) => reply.type("text/html; charset=utf-8").send(page));
  return UI_PATH;
}
