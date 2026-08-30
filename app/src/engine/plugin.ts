/**
 * 进程内插件的生命周期 —— **加载、换版本、真卸载**。
 *
 * 一个插件一个 Worker。这样才凑得齐一条完整的生命周期：
 *
 * | | 主线程 import | 这儿（Worker） |
 * | --- | --- | --- |
 * | 加载 | ✔ | ✔ |
 * | 原地改了文件 | ✘ 拿回来还是老那份 | ✔ 换个 worker |
 * | 卸载 | ✘ 只能没人再调它 | ✔ 代码、内存、定时器一起收 |
 * | 写坏了 | 炸在内核里 | 只炸它自己 |
 *
 * JS 的模块表只进不出，所以生命周期的单位只能是 **realm**。这跟 Java 扔掉一个
 * `ClassLoader` 是同一件事 —— Java 也不能热卸载一个方法。
 *
 * 代价：一次调用要过一次结构化克隆。**「能真卸载」和「零开销直接调」在 JS 里
 * 换不到一起**，这一层选了前者 —— 它装的是运行时加进来的第三方代码，那正是最
 * 需要能收回、也最可能写坏的东西。随二进制发的那几个不走这儿。
 */

import { statSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

/**
 * worker 那一半在哪个文件里。
 *
 * ## 为什么是环境变量
 *
 * 这条路两种跑法解析规则不一样，而且**都不能靠猜**：
 *
 * | | `new Worker(路径)` 怎么解析 |
 * | --- | --- |
 * | `bun src/main.ts` | 相对**进程的 cwd**，从磁盘上找 |
 * | 编译成的单文件 | 一样是相对 cwd 从磁盘上找 —— 源文件不在那儿就没有 |
 *
 * 试过的两种写法都不成：`new URL("./x.ts", import.meta.url)` 打包后拼出来的是
 * `B:/~BUN/root/x.ts`（虚拟路径，不存在）；写成相对路径则跟着 cwd 走，换个目录
 * 启动就找不着。
 *
 * 所以位置得**由外面告诉它**，跟 `config.yaml` 和钥匙一个道理。默认值只对
 * 「在 `app/` 底下 `bun start`」这一种情况成立，别的情况下必须给。
 */
function hostPath(): string {
  const given = process.env.TGENGIN_PLUGIN_HOST;
  if (given && given.trim()) return given;
  // 直接跑源码时 `import.meta.url` 指得到真文件，从哪个目录启动都对。
  // 打包之后它是个虚拟路径，那儿没有文件 —— 这时候只能靠上面那个环境变量。
  try {
    const beside = fileURLToPath(new URL("./plugin-host.ts", import.meta.url));
    if (statSync(beside).isFile()) return beside;
  } catch {
    // 打包了，或者文件不在 —— 落到下面那个
  }
  return "./src/engine/plugin-host.ts";
}

const HOST = hostPath();

/**
 * 起一个 worker 等多久算它没起来。
 *
 * 没有这道墙的话，找不到那个文件就是一个永远不 resolve 的 promise —— 调用方
 * 挂着，日志上一个字都没有。
 */
const READY_MS = 10_000;

interface Waiting {
  ok(v: unknown): void;
  fail(e: Error): void;
}

/** 一个装着插件的 worker。**一个文件一个**，不是一个导出一个。 */
class Live {
  readonly stamp: number;
  #w: Worker;
  #ready: Promise<void>;
  #id = 0;
  #waiting = new Map<number, Waiting>();
  #dead: Error | null = null;

  constructor(name: string, spec: string, stamp: number) {
    this.stamp = stamp;
    this.#w = new Worker(HOST);

    this.#ready = new Promise<void>((ok, fail) => {
      // **起不来要当场说。** 没有这道墙的话，worker 起不来就是一个永远不 resolve
      // 的 promise：调用方挂在那儿，日志上一个字都没有。而这正是打包之后最容易
      // 出的事 —— worker 文件得**单独当一个入口点**编进去（见 package.json 的
      // build:win 那几行），漏了的话 `new Worker` 什么也找不到，而它不报错。
      const wall = setTimeout(
        () => fail(new Error(`${name}: the worker did not come up within ${READY_MS}ms (${HOST})`)),
        READY_MS,
      );
      const up = () => {
        clearTimeout(wall);
        ok();
      };
      const no = (e: Error) => {
        clearTimeout(wall);
        this.#die(e);
        fail(e);
      };

      this.#w.onmessage = (e: MessageEvent) => {
        const m = (e.data ?? {}) as { kind?: string; id?: number; ok?: boolean; value?: unknown; error?: string };
        if (m.kind === "ready") return up();
        if (m.kind === "failed") return no(new Error(`${name}: ${m.error}`));
        if (m.kind !== "done") return;
        const w = this.#waiting.get(Number(m.id));
        if (!w) return;
        this.#waiting.delete(Number(m.id));
        if (m.ok) w.ok(m.value);
        else w.fail(new Error(String(m.error)));
      };
      // worker 自己没了（吃爆内存、被 terminate、进程级的错）—— 在途的全得结掉，
      // 不结的话调用方挂到 expect_ms 才超时，而日志上看不出是它没了。
      this.#w.onerror = (e: ErrorEvent) => no(new Error(`${name}: ${e.message}`));
    });
    // 起不来这件事由上面那道墙报，别让它变成一个没人接的 rejection。
    this.#ready.catch(() => {});

    this.#w.postMessage({ kind: "load", module: spec });
  }

  #die(e: Error): void {
    this.#dead ??= e;
    for (const w of this.#waiting.values()) w.fail(e);
    this.#waiting.clear();
  }

  async call(exp: string, arg: unknown): Promise<unknown> {
    await this.#ready;
    if (this.#dead) throw this.#dead;
    const id = ++this.#id;
    return await new Promise((ok, fail) => {
      this.#waiting.set(id, { ok, fail });
      this.#w.postMessage({ kind: "call", id, export: exp, arg });
    });
  }

  close(): void {
    this.#dead ??= new Error("already closed");
    this.#w.terminate();
  }
}

export class Plugins {
  /** 文件 → 那个 realm。 */
  #live = new Map<string, Live>();
  /** 句柄 → 它落在哪个文件上。一个文件上挂着好几条句柄是常事。 */
  #on = new Map<string, string>();

  /** worker 那一半在哪儿 —— 报出来，配错了一眼看得见。 */
  readonly host = HOST;

  /**
   * 开机探一遍这条路通不通。
   *
   * **不拦启动**：没装插件的机器不该因为这个起不来。但也不能不吭声 —— 不探的话
   * 要等到某个任务真去调一个插件那一刻才发现，而那时候它已经在半路上了。
   */
  async probe(): Promise<string | null> {
    const w = new Worker(HOST);
    try {
      await new Promise<void>((ok, fail) => {
        const wall = setTimeout(() => fail(new Error(`did not come up within ${READY_MS}ms`)), READY_MS);
        w.onmessage = () => {
          clearTimeout(wall);
          ok();
        };
        w.onerror = (e: ErrorEvent) => {
          clearTimeout(wall);
          fail(new Error(e.message));
        };
        // 装一个不存在的模块：起得来就会回 `failed`，那也算「这条路通」——
        // 我们要探的是 worker 本身起不起得来，不是那个模块在不在。
        w.postMessage({ kind: "load", module: "file:///tgengin-probe-not-a-real-module" });
      });
      return null;
    } catch (e) {
      return `plugin path unusable (${HOST}): ${e instanceof Error ? e.message : String(e)} - point TGENGIN_PLUGIN_HOST at plugin-host.ts`;
    } finally {
      w.terminate();
    }
  }

  /**
   * 调一次。**每次先看一眼文件的 mtime** —— 变了就把旧的 worker 收掉、起新的。
   *
   * 「运行时能加进来」和「改一行就得重启」放在一起是自相矛盾的，所以这一眼必须看。
   * 一次 `stat` 而已，比一次结构化克隆便宜。
   *
   * realm 按**文件**分，不按句柄分：`a.ts#login` 和 `a.ts#book` 落在同一个 worker
   * 里，共享那个模块的状态 —— 前一个在文件顶上起的监听，后一个等得到。分开的话
   * 那个变量会悄悄有两份，而这种 bug 从外面一点都看不出来。
   */
  async call(name: string, spec: string, arg: unknown): Promise<unknown> {
    const hash = spec.lastIndexOf("#");
    const path = resolve(hash === -1 ? spec : spec.slice(0, hash));
    const exp = hash === -1 ? "default" : spec.slice(hash + 1);

    let stamp = 0;
    try {
      stamp = statSync(path).mtimeMs;
    } catch {
      throw new Error(`${name}: cannot find ${path}`);
    }

    this.#on.set(name, path);
    const had = this.#live.get(path);
    if (!had || had.stamp !== stamp) {
      // 换版本 = 收掉旧的那个 realm。旧版本起的定时器、占的内存跟着一起走 ——
      // 主线程那条路做不到这件事。
      had?.close();
      this.#live.set(path, new Live(name, pathToFileURL(path).href, stamp));
    }
    return await this.#live.get(path)!.call(exp, arg);
  }

  /**
   * 真卸载：那份代码、内存、它起的定时器一起收。
   *
   * 同一个文件上还挂着别的句柄的话，只把这条摘掉 —— **最后一条走了才收 realm**。
   */
  drop(name: string): boolean {
    const path = this.#on.get(name);
    if (path === undefined) return false;
    this.#on.delete(name);
    if ([...this.#on.values()].includes(path)) return false;
    this.#live.get(path)?.close();
    this.#live.delete(path);
    return true;
  }

  /** 现在装着哪几个文件。 */
  names(): string[] {
    return [...this.#live.keys()].sort();
  }

  closeAll(): void {
    for (const l of this.#live.values()) l.close();
    this.#live.clear();
    this.#on.clear();
  }
}
