/**
 * 写法一：进程内。引擎在自己的 Worker 里 import 这个文件。
 *
 * 两个导出，两条句柄，指的是同一个文件：
 *
 * | 句柄 | `module` |
 * | --- | --- |
 * | `fn:tool.google_login_in` | `…/book-plugin.ts#login` |
 * | `fn:tool.meet_book_in` | `…/book-plugin.ts#book` |
 *
 * 同一个 Worker 里的同一个模块 —— 所以 `login` 起的那个回调监听，`book` 等得到。
 */

import { authStart, book as create } from "./google.ts";

export async function login(): Promise<unknown> {
  const got = await authStart();
  console.log(`[book-plugin] 授权：${got.note}`);
  return { ...got, 来自: "进程内插件" };
}

export async function book(arg: unknown): Promise<unknown> {
  const a = ((arg ?? {}) as { args?: Record<string, unknown> }).args ?? {};
  console.log(`[book-plugin] 开会 ${JSON.stringify(a)}`);
  const got = await create(a as Parameters<typeof create>[0]);
  console.log(`[book-plugin] → ${got.meetUrl}`);
  return { ...got, 来自: "进程内插件" };
}
