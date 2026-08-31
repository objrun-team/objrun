/**
 * `python_exec` 住的地方 —— 一个 Worker，里面是 Pyodide（CPython 编到 wasm）。
 *
 * **为什么不在主线程里跑。** Pyodide 的 `runPython` 是同步的：模型写一句
 * `while True: pass`，整个引擎进程就停在那儿了 —— 内核醒不过来，所有任务一起挂。
 * 单开一个 Worker，超时了外面 `terminate()`，掀掉的只是它自己。
 *
 * **为什么不用容器。** 这台机器上 docker 装在 WSL 里，而这东西是要跟安装包一起
 * 分发的基础设施：换一台干净的 Windows 就没有 WSL，也没有 docker。wasm 没有这个
 * 问题 —— 它就是几个文件，跟二进制放一块儿。
 *
 * ## 协议
 *
 * ```
 * → { kind: "run", id, code }
 * ← { kind: "ready" } | { kind: "failed", error }
 * ← { kind: "done", id, exitCode, stdout, stderr }
 * ```
 *
 * 起 Pyodide 大约两秒半，所以**起一次用很多次**；换包（第一次 import numpy 之类）
 * 还要几秒，也是一次性的。
 *
 * ## 每次调用换一套全局名字
 *
 * 解释器复用，但**变量不复用**：每次 `runPython` 给一个新的 globals。一道题里
 * 定义的符号漏到下一道题去，比慢几秒难查得多 —— 那会变成「换个顺序跑结果就不一样」。
 */

import { statSync } from "node:fs";
import { dirname, join } from "node:path";

declare const self: {
  onmessage: ((e: { data: unknown }) => void) | null;
  postMessage(v: unknown): void;
};

/** 回给模型的输出上限。再多也没用，只会把上下文撑掉。 */
const CAP = 4000;

/** 用 pyodide 自己的类型 —— 手抄一份的话，它一升级我们这份就悄悄对不上了。 */
type Py = Awaited<ReturnType<typeof import("pyodide").loadPyodide>>;

let py: Py | null = null;
let out: string[] = [];
let err: string[] = [];

/**
 * Pyodide 那一堆文件在哪儿。
 *
 * 跟插件宿主一个道理：**这条路不能靠猜**。跑源码时 `node_modules` 里那份找得到；
 * 编译成单文件之后 `import.meta.url` 是个虚拟路径，那儿没有文件 —— 得由外面告诉
 * 它，也就是安装包把 `pyodide/` 放在二进制旁边，再用这条环境变量指过去。
 */
function whereIs(): string | undefined {
  const given = process.env.TGENGIN_PYODIDE;
  if (given && given.trim()) return given;
  // **默认就在二进制旁边找。** 安装包把 `pyodide/` 放在 exe 边上就完事了，
  // 不用谁去配一条环境变量 —— 要配才能用的东西，第一次装的人一定会漏。
  // 上面那条留着是给「放到别处」用的。
  try {
    const beside = join(dirname(process.execPath), "pyodide");
    if (statSync(beside).isDirectory()) return beside;
  } catch {
    // 旁边没有 —— 那就是在跑源码，让 pyodide 自己从 node_modules 里找
  }
  return undefined;
}

async function boot(): Promise<Py> {
  if (py) return py;
  const { loadPyodide } = await import("pyodide");
  const where = whereIs();
  const it = await loadPyodide({
    ...(where ? { indexURL: where } : {}),
    // 装到哪儿算哪儿：第一次用 numpy 会去 CDN 取轮子并缓存下来。安装包里带上
    // 那几个轮子的话，这一步就是本地读文件，一次网都不用上。
    stdout: (s: string) => out.push(s),
    stderr: (s: string) => err.push(s),
  });
  py = it;
  return it;
}

function cut(lines: string[]): string {
  const t = lines.join("\n").trim();
  return t.length > CAP ? `${t.slice(0, CAP)}\n... (${t.length - CAP} more characters)` : t;
}

async function runOnce(code: string): Promise<Record<string, unknown>> {
  const it = await boot();
  // **代码里 import 了什么就装什么。** 不用谁去维护一张「这道题要哪几个包」的表 ——
  // 模型写 `import sympy`，这一句就把 sympy 装上。装过的第二次是空操作。
  let trouble = "";
  try {
    await it.loadPackagesFromImports(code);
  } catch (e) {
    // 装不上不代表跑不了（可能它 import 的本来就是标准库里的东西）。
    trouble = e instanceof Error ? e.message : String(e);
  }
  // 装包这一步 pyodide 自己会往 stdout 上写「Loading numpy / Loaded numpy」。
  // **那不是这段程序印的**，混给模型看只会让它以为自己的代码印了这些东西 ——
  // 所以清在这儿，而不是清在装包之前。
  out = [];
  err = trouble ? [trouble] : [];
  try {
    // 每次一套新的全局名字 —— 上一次留下的变量不该被下一次看见。
    const names = it.globals.get("dict") as () => unknown;
    await it.runPythonAsync(code, { globals: names() as never });
    return { exitCode: 0, stdout: cut(out), stderr: cut(err) };
  } catch (e) {
    // Python 抛的错**当结果回**，不当协议错：模型看得见回溯才改得动代码。
    err.push(e instanceof Error ? e.message : String(e));
    return { exitCode: 1, stdout: cut(out), stderr: cut(err) };
  }
}

self.onmessage = (e) => {
  const m = (e.data ?? {}) as { kind?: string; id?: number; code?: string };
  if (m.kind !== "run") return;
  const id = m.id;
  void runOnce(String(m.code))
    .then((r) => self.postMessage({ kind: "done", id, ...r }))
    .catch((x: unknown) =>
      self.postMessage({
        kind: "done",
        id,
        exitCode: 1,
        stdout: "",
        stderr: x instanceof Error ? x.message : String(x),
      }),
    );
};

// 一起来就先把解释器烧上，别等第一次调用才花那两秒半。
void boot().then(
  () => self.postMessage({ kind: "ready" }),
  (x: unknown) => self.postMessage({ kind: "failed", error: x instanceof Error ? x.message : String(x) }),
);
