/**
 * Approach 1: in-process. The engine imports this file in its own Worker.
 *
 * Two exports and two handles refer to the same file:
 *
 * | Handle | `module` |
 * | --- | --- |
 * | `fn:tool.google_login_in` | `…/book-plugin.ts#login` |
 * | `fn:tool.meet_book_in` | `…/book-plugin.ts#book` |
 *
 * They share a module in the same Worker, so `book` can wait for the callback listener started by `login`.
 */

import { authStart, book as create } from "./google.ts";

export async function login(): Promise<unknown> {
  const got = await authStart();
  console.log(`[book-plugin] authorisation: ${got.note}`);
  return { ...got, from: "fn" };
}

export async function book(arg: unknown): Promise<unknown> {
  const a = ((arg ?? {}) as { args?: Record<string, unknown> }).args ?? {};
  console.log(`[book-plugin] booking ${JSON.stringify(a)}`);
  const got = await create(a as Parameters<typeof create>[0]);
  console.log(`[book-plugin] → ${got.meetUrl}`);
  return { ...got, from: "fn" };
}
