/**
 * 插件住的地方 —— 一个 Worker。
 *
 * **这个文件是那一百行里的一半。** 它不认得任何一个具体的插件：收到「装这个」
 * 就 import，收到「调一次」就调，把结果回过去。
 *
 * ## 为什么要单开一个 realm
 *
 * JS 里**生命周期的单位不是函数，也不是模块，是 realm**。模块表只进不出：主线程
 * 里 import 进来的东西，换版本只能让注册表指向新的（旧的还在），删掉只能让没人再
 * 调它（代码、内存、它起的定时器全留着）。
 *
 * 换个 realm 就都有了：`terminate()` 一下，那份代码、那 8MB、那个定时器一起没。
 * 这跟 Java 扔掉一个 `ClassLoader` 是同一件事 —— Java 也不能热卸载一个方法。
 *
 * 代价是调用要过一次结构化克隆，不是裸函数调用。**「能真卸载」和「零开销直接调」
 * 在 JS 里换不到一起**，这是选了前者。
 *
 * ## 协议
 *
 * ```
 * → { kind: "load", module: "文件路径" }
 * ← { kind: "ready" } | { kind: "failed", error }
 * → { kind: "call", id, export: "导出名", arg }
 * ← { kind: "done", id, ok: true,  value }
 * ← { kind: "done", id, ok: false, error }
 * ```
 *
 * **装的是文件，调的时候才挑导出。** 一个文件导出好几个工具是常事，它们本来就
 * 该在同一份模块状态里 —— 一个导出一个 realm 的话，文件顶上那个变量会悄悄有两份。
 */

declare const self: {
  onmessage: ((e: { data: unknown }) => void) | null;
  postMessage(v: unknown): void;
};

type Fn = (arg: unknown) => Promise<unknown> | unknown;

let mod: Record<string, unknown> | null = null;
let from = "";

async function load(path: string): Promise<void> {
  // 这个 worker 是**一次性**的：它只装一个文件，换版本靠外面把它 terminate 掉重起。
  // 所以这儿不用管 import 缓存 —— 新的 worker 就是新的模块表。
  mod = (await import(path)) as Record<string, unknown>;
  from = path;
}

function pick(name: string): Fn {
  if (!mod) throw new Error("this worker has no plugin loaded yet");
  const got = mod[name];
  if (typeof got !== "function") {
    const has = Object.keys(mod).join(", ") || "(none)";
    throw new Error(`${name} in ${from} is not a function (this file exports ${has})`);
  }
  return got as Fn;
}

self.onmessage = (e) => {
  const m = (e.data ?? {}) as { kind?: string; module?: string; id?: number; export?: string; arg?: unknown };

  if (m.kind === "load") {
    void load(String(m.module))
      .then(() => self.postMessage({ kind: "ready" }))
      .catch((err: unknown) =>
        self.postMessage({ kind: "failed", error: err instanceof Error ? err.message : String(err) }),
      );
    return;
  }

  if (m.kind === "call") {
    const id = m.id;
    void (async () => {
      try {
        self.postMessage({ kind: "done", id, ok: true, value: await pick(String(m.export))(m.arg) });
      } catch (err) {
        // 插件抛的错**只回给调用方**，不掀掉这个 worker —— 一次调用失败不是这个
        // 插件坏了。真把 worker 弄挂了（死循环、吃爆内存）也只影响它自己。
        self.postMessage({ kind: "done", id, ok: false, error: err instanceof Error ? err.message : String(err) });
      }
    })();
  }
};
