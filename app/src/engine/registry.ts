/**
 * 句柄注册表 —— 名字换出真东西。
 *
 * **注册一律走内核**，因为只有内核这个进程持有得住函数。库里存的永远只是名字。
 *
 * **只有一条轴：进程内，还是进程外。** 名字的前缀说的就是它：
 *
 * | 前缀 | 实现在哪 |
 * | --- | --- |
 * | `fn:` | **内核进程里** |
 * | `http://` `https://` | 另一个进程 |
 *
 * 两边共用 `expect_ms`：调用超过这个时间就判死，**内外一视同仁**。
 *
 * ## 「进程内」不等于「必须编进二进制」
 *
 * 传不过来的是函数**对象**，不是函数**在哪儿**。所以 `fn:` 的实现有两个来源：
 *
 * | `handle.module` | 实现从哪儿来 | 谁写那一行 | 住在哪 |
 * | --- | --- | --- | --- |
 * | 留空 | 随二进制发 | 代码调 `register` | 主线程，裸函数调用 |
 * | `路径#导出名` | 运行时装进来的插件 | **外面写一行就行** | 自己的 Worker（见 `plugin.ts`） |
 *
 * 两种都在这个进程里，都不过 OS 的进程边界。库里那一行的作用是一样的：
 * **让内核知道系统里有这个函数**。
 *
 * 插件那条住在 Worker 里，是因为**生命周期的单位是 realm**：只有换掉整个 realm
 * 才能真换版本、真卸载。代价是一次结构化克隆 —— 「能真卸载」和「零开销直接调」
 * 在 JS 里换不到一起，那一条选了前者，随二进制发的这一条选了后者。
 *
 * 库里有一个 `fn:` 而进程内没人认领、`module` 也没给 —— 那才是错，当场就该说
 * 出来，不能等到真去调它那一刻。
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
import { Plugins } from "./plugin.ts";

/** 一次调用。参数和返回都是能过 JSON 的东西 —— 程序外那条路只能传这些。 */
export type Handle = (arg: unknown) => Promise<unknown>;

export interface Entry {
  name: string;
  expectMs: number;
  call: Handle;
  /** 进程内的函数，还是外面的接口。 */
  where: "in" | "out";
  /**
   * 运行时装进来的插件，实现在这个模块里（`路径#导出名`）。
   *
   * 随二进制发的那些没有这一项 —— 它们不该被「卸载」，也没地方去卸。
   */
  plugin?: string;
}

const IN = /^fn:/;
const OUT = /^https?:\/\//;
const MCP = /^mcp:/;

/**
 * 外面能不能注册这个名字。
 *
 * `fn:` **能** —— 但得说清实现从哪儿来（`module`）。不说的话，库里就多了一条
 * 谁都认领不了的句柄，而错要等到真去调它那一刻才冒出来。
 */
export function registrable(name: string, module?: string | null): boolean {
  if (OUT.test(name) || MCP.test(name)) return true;
  return IN.test(name) && Boolean(module && module.trim());
}

export class Registry {
  #by = new Map<string, Entry>();

  /**
   * 运行时装进来的插件住的地方 —— 一个插件一个 Worker。
   *
   * 放在这儿是因为**注册表就是「系统里有哪些函数」那张表**，而插件的建和毁跟
   * 这张表是同一件事的两面：库里多一行就起一个，少一行就收一个。
   */
  readonly plugins = new Plugins();

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
    if (!IN.test(name)) throw new Error(`an in-process handle name must start with fn: - got ${name}`);
    if (!Number.isFinite(expectMs) || expectMs <= 0) throw new Error(`expect_ms for ${name} must be a positive number`);
    this.#by.set(name, { name, expectMs, call: fn, where: "in" });
    run(db, `insert into handle (name, expect_ms, module) values (?, ?, null)
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
  sync(db: Conn): { added: string[]; missing: string[]; dropped: string[] } {
    this.beforeSync?.();
    const rows = all(db, `select name, expect_ms, module from handle`) as {
      name: string;
      expect_ms: number;
      module: string | null;
    }[];
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
      } else if (IN.test(r.name) && r.module) {
        // 进程内，实现在磁盘上 —— 住在自己的 worker 里。第一次调它的时候才起，
        // 装表这一步不该因为一个插件写坏了就起不来。
        const spec = r.module;
        this.#by.set(r.name, {
          name: r.name,
          expectMs: r.expect_ms,
          where: "in",
          plugin: spec,
          call: (arg) => this.plugins.call(r.name, spec, arg),
        });
        added.push(r.name);
      } else {
        missing.push(r.name);
      }
    }

    // **库里没有了 = 真卸载。** 把那个 worker 收掉：代码、内存、它起的定时器
    // 一起走。只从注册表里删掉的话，那些东西会一直留在进程里，而且没人看得见。
    const inDb = new Set(rows.map((r) => r.name));
    const dropped: string[] = [];
    for (const [name, e] of this.#by) {
      if (e.plugin === undefined || inDb.has(name)) continue;
      this.plugins.drop(name);
      this.#by.delete(name);
      dropped.push(name);
    }

    if (missing.length) {
      throw new Error(`registered in the database but never registered in this process: ${missing.join(", ")}`);
    }
    return { added, missing, dropped };
  }

  get(name: string): Entry {
    const e = this.#by.get(name);
    if (!e) throw new Error(`no such handle: ${name}`);
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
    if (!res.ok) throw new Error(`${url} returned ${res.status}`);
    return await res.json();
  };
}
