/**
 * 句柄注册表 —— 名字换出真东西。
 *
 * **注册一律走内核**，因为只有内核这个进程持有得住函数。库里存的永远只是名字。
 *
 * **只有一条轴：进程内，还是进程外。** 名字的前缀说的就是它：
 *
 * | 前缀 | 实现在哪 | 谁来注册 |
 * | --- | --- | --- |
 * | `fn:` | 内核进程里，随二进制发 | 只能由代码调 `register` |
 * | `http://` `https://` | 另一个进程 | **往库里写一行就算注册完了** |
 *
 * `fn:` 那条外面**不许**注册 —— 库里写了个 `fn:` 而进程内没人注册过，那是错，
 * 当场就该说出来，不能等到真去调它那一刻。
 *
 * 两边共用 `expect_ms`：调用超过这个时间就判死，**内外一视同仁**。
 *
 * ## MCP 不是第三类
 *
 * MCP 是这两边**说话的方式**，不是另一种句柄。协议本身两边都支持，决定进程边界的
 * 是传输：
 *
 * ```
 *   fn:      进程内  ←→  MCP 内存传输
 *   http://  进程外  ←→  MCP stdio 子进程 / HTTP
 * ```
 *
 * 所以一个 MCP server 报回来的工具，落成的是**上面那两类里的行**，不是新的一类。
 * 声明一个 server 只是一条**批量来源**：它自己报一堆工具，替你把行写出来 ——
 * 它不取代、也不排斥一条一条地写。
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";

/** 一次调用。参数和返回都是能过 JSON 的东西 —— 程序外那条路只能传这些。 */
export type Handle = (arg: unknown) => Promise<unknown>;

export interface Entry {
  name: string;
  expectMs: number;
  call: Handle;
  /** 进程内的函数，还是外面的接口。 */
  where: "in" | "out";
}

const IN = /^fn:/;
const OUT = /^https?:\/\//;
const MCP = /^mcp:/;

/** 外面能不能注册这个名字。`fn:` 不行 —— 那是随二进制发的，写个名字换不出函数。 */
export function registrable(name: string): boolean {
  return OUT.test(name) || MCP.test(name);
}

export class Registry {
  #by = new Map<string, Entry>();

  /**
   * 对表之前先喊一声。
   *
   * MCP 那条路要用：库里可能刚登记了一个 server，它的工具句柄还没人认领。
   * 这一声给它一个机会把调用器补上，**补完再对**，不然 `sync` 会说「没人注册过」
   * 而那不是实情 —— 只是还没轮到它装。
   */
  beforeSync: (() => void) | null = null;

  /**
   * 注册一个**进程内**的句柄：把函数收下，同时往 `handle` 表登记。
   *
   * 库里那一行是给别人看的（谁在引用这个句柄、它多久算死）；函数只活在这个进程里。
   */
  register(db: Conn, name: string, expectMs: number, fn: Handle): void {
    if (!IN.test(name)) throw new Error(`进程内的句柄名要以 fn: 开头：${name}`);
    if (!Number.isFinite(expectMs) || expectMs <= 0) throw new Error(`${name} 的 expect_ms 得是个正数`);
    this.#by.set(name, { name, expectMs, call: fn, where: "in" });
    run(db, `insert into handle (name, expect_ms) values (?, ?)
             on conflict(name) do update set expect_ms = excluded.expect_ms`, [name, expectMs]);
  }

  /**
   * 收下一个**已经在库里登记过**的句柄的调用器。
   *
   * 跟 `register` 的分别：`register` 是「我这儿有个函数，替我登记一行」；
   * `adopt` 是「库里那一行的调用器我给你合成好了」。MCP 那条路走这个 ——
   * 工具是 server 报的，行早就写进去了，这儿只是把调用器补上。
   */
  adopt(name: string, expectMs: number, fn: Handle): void {
    this.#by.set(name, { name, expectMs, call: fn, where: "out" });
  }

  /**
   * 照着库里的 `handle` 表对一遍。**这是那两层核对里的第二层。**
   *
   * - 外面的接口：注册表里没有就现合成一个调用器 —— 外部注册就是这么生效的。
   * - 进程内的句柄：库里有、进程里没人注册过 → **当场炸**。不炸的话，
   *   要等到某个任务真走到那一步才发现，而那时候已经在半路上了。
   */
  sync(db: Conn): { added: string[]; missing: string[] } {
    this.beforeSync?.();
    const rows = all(db, `select name, expect_ms from handle`) as { name: string; expect_ms: number }[];
    const added: string[] = [];
    const missing: string[] = [];
    for (const r of rows) {
      if (this.#by.has(r.name)) {
        this.#by.get(r.name)!.expectMs = r.expect_ms; // 库里改了时限，跟着改
        continue;
      }
      if (OUT.test(r.name)) {
        this.#by.set(r.name, { name: r.name, expectMs: r.expect_ms, where: "out", call: remote(r.name) });
        added.push(r.name);
      } else {
        missing.push(r.name);
      }
    }
    if (missing.length) {
      throw new Error(`库里登记了这些句柄，进程内没人注册过：${missing.join("、")}`);
    }
    return { added, missing };
  }

  get(name: string): Entry {
    const e = this.#by.get(name);
    if (!e) throw new Error(`没有这个句柄：${name}`);
    return e;
  }

  has(name: string): boolean {
    return this.#by.has(name);
  }

  names(): string[] {
    return [...this.#by.keys()].sort();
  }
}

/** 给外面的接口合成一个调用器。名字本身就是地址。 */
function remote(url: string): Handle {
  return async (arg: unknown) => {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(arg ?? {}),
    });
    if (!res.ok) throw new Error(`${url} 回了 ${res.status}`);
    return await res.json();
  };
}
