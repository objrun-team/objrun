/**
 * `python_exec` —— 跑一段 Python，把它印出来的东西拿回来。
 *
 * ## 为什么这台机器需要它
 *
 * 一道推导题，模型手上没有算力的时候会**猜**：写一个看起来对的式子，然后没有
 * 任何办法知道它对不对。实测过更糟的：一道题拿十二个执行单元去查
 * `python --version`，一个字答案都没写 —— 伸手要算力却摸到空气，额度就这么没的。
 *
 * ## 它跑在哪儿
 *
 * 一个 Worker 里的 Pyodide（CPython 编到 wasm）。见 `./python-host.ts`。
 * 这儿这一半只管三件事：**起它、超时了掀掉它、把结果收回来。**
 *
 * 掀掉这件事是关键：`runPython` 是同步的，死循环在主线程里就是整个引擎停摆，
 * 而 `terminate()` 能把一个正在同步执行的 worker 真的杀掉。
 *
 * ## 装什么包不用谁去配
 *
 * 代码里 `import sympy`，宿主那边就把 sympy 装上（`loadPackagesFromImports`）。
 * sympy / numpy / scipy 都有预编译好的轮子。
 */

import { statSync } from "node:fs";
import { fileURLToPath } from "node:url";

/** 一段代码最多跑多久。到点连 worker 一起掀掉。 */
export const PYTHON_WALL_MS = 30_000;
/** 起解释器本身要两秒半，加上第一次装包，头一次调用得给够时间。 */
const BOOT_MS = 120_000;

/**
 * worker 那一半在哪个文件里。
 *
 * 跟 `../engine/plugin.ts` 里那个是同一个问题，也是同一个解法：**位置由外面
 * 告诉它**。跑源码时 `import.meta.url` 指得到真文件；编译成单文件之后它是个
 * 虚拟路径（`B:/~BUN/root/...`），那儿没有文件。
 */
function hostPath(): string {
  const given = process.env.TGENGIN_PYTHON_HOST;
  if (given && given.trim()) return given;
  try {
    const beside = fileURLToPath(new URL("./python-host.ts", import.meta.url));
    if (statSync(beside).isFile()) return beside;
  } catch {
    // 打包了，或者文件不在 —— 落到下面那个
  }
  // **打包之后这条路是相对主入口那个目录解析的**，不是相对进程 cwd，也不是
  // 源码里那条路径。主入口是 `src/main.ts`，所以这儿写的是从 `src/` 出发的
  // 相对路径。写错了得到的是
  //   `BuildMessage: ModuleNotFound resolving "..." (entry point)`,
  // 而这句话只出现在 worker 的 error 事件里 —— 不把它带出来的话，现场只有
  // 一句「起不来」。
  return "./tools/python-host.ts";
}

interface Done {
  kind?: string;
  id?: number;
  exitCode?: number;
  stdout?: string;
  stderr?: string;
  error?: string;
}

/**
 * 那个解释器。
 *
 * **起一次用很多次** —— 每次调用重起的话，光启动就两秒半，装包还要几秒。
 * 但只要有一次超时把它掀了，下一次自然会重起一个新的。
 */
class Interpreter {
  #w: Worker | null = null;
  #ready: Promise<void> | null = null;
  #next = 1;
  #waiting = new Map<number, (d: Done) => void>();

  #open(): Worker {
    if (this.#w) return this.#w;
    const w = new Worker(hostPath());
    // **不许它拦着进程退出。** 解释器是烧着待命的，引擎收工时没人再调它了，
    // 而一个 ref 着的 worker 会让整个进程一直挂在那儿等一件永远不会来的事。
    (w as unknown as { unref?: () => void }).unref?.();
    this.#w = w;
    this.#ready = new Promise<void>((yes, no) => {
      const t = setTimeout(() => no(new Error(`the python interpreter did not come up within ${BOOT_MS}ms`)), BOOT_MS);
      w.addEventListener("message", (e: MessageEvent) => {
        const m = (e.data ?? {}) as Done;
        if (m.kind === "ready") {
          clearTimeout(t);
          yes();
          return;
        }
        if (m.kind === "failed") {
          clearTimeout(t);
          no(new Error(String(m.error)));
          return;
        }
        if (m.kind === "done" && m.id !== undefined) {
          const f = this.#waiting.get(m.id);
          this.#waiting.delete(m.id);
          f?.(m);
        }
      });
      w.addEventListener("error", (e: ErrorEvent) => {
        clearTimeout(t);
        // **把它说了什么带上。** 光说「起不来」的话，接下来要查的是「wasm 文件在不在、
        // 路径对不对、这一版 bun 认不认得 worker」—— 而那句话里本来就写着答案。
        const said = String(e.message || (e.error as Error | undefined)?.message || '').trim();
        no(new Error('the python interpreter crashed while starting' + (said ? ': ' + said : '')));
      });
    });
    return w;
  }

  /** 掀掉。正在跑的那些调用得各自去处理超时 —— 这儿只负责让下一次拿到一个干净的。 */
  #drop(): void {
    this.#w?.terminate();
    this.#w = null;
    this.#ready = null;
    this.#waiting.clear();
  }

  async run(code: string, wallMs: number): Promise<Record<string, unknown>> {
    const w = this.#open();
    try {
      await this.#ready;
    } catch (e) {
      this.#drop();
      throw e;
    }

    const id = this.#next++;
    const answer = new Promise<Done>((yes) => this.#waiting.set(id, yes));
    w.postMessage({ kind: "run", id, code });

    let timer: ReturnType<typeof setTimeout> | null = null;
    const clock = new Promise<null>((yes) => {
      timer = setTimeout(() => yes(null), wallMs);
    });
    const got = await Promise.race([answer, clock]);
    if (timer) clearTimeout(timer);

    if (got === null) {
      // 到点还没回来 —— 多半是个死循环。**连解释器一起掀掉**：不掀的话它会一直
      // 转下去占着一个核，而这个 worker 也再没法接下一次调用。
      this.#drop();
      return {
        exitCode: 1,
        stdout: "",
        stderr: `the program ran longer than ${wallMs}ms and was stopped`,
        timedOut: true,
      };
    }
    return { exitCode: got.exitCode ?? 1, stdout: got.stdout ?? "", stderr: got.stderr ?? "" };
  }

  close(): void {
    this.#drop();
  }
}

const one = new Interpreter();

/** 引擎收工时把它收掉，不然进程退不干净。 */
export function closePython(): void {
  one.close();
}

export const python = {
  name: "python_exec",
  does:
    "Run a short Python program and get back what it printed. sympy, numpy and scipy are available - " +
    "importing one installs it. There is no network and no access to the files around you: " +
    "use this to compute and to check, not to look around.",
  params: {
    type: "object",
    properties: {
      code: { type: "string", description: "The program. Print what you want to see - nothing else comes back." },
    },
    required: ["code"],
    additionalProperties: false,
  },
  output: {
    type: "object",
    properties: {
      exitCode: { type: "integer" },
      stdout: { type: "string" },
      stderr: { type: "string" },
      timedOut: { type: "boolean" },
    },
  },
  prompt:
    "Prefer computing over guessing. If a quantity can be counted, enumerated, expanded or checked numerically, " +
    "write the program and read the answer off it. Nothing carries over between calls - each program starts from " +
    "an empty namespace, so repeat the definitions you need. Several calls in one turn cost the same as one: " +
    "every call you make is run before you are asked again, so batch the work rather than spending a turn per question.",
  concurrent: false,
  expectMs: PYTHON_WALL_MS + 30_000,
  // **交卷站不摆它。** 跑工具的只有动作站；交卷站是模型站、下一站也是模型站，
  // 在那儿请求算力没有人会去跑 —— 那次调用会一直挂着，最后被补一条「没跑成」。
  // 交卷交的是它说的话，本来也用不着算。
  when: [[{ dim: "cycle", key: "cycle", op: "ne", value: "submit" }]],
  async run(args: Record<string, unknown>): Promise<unknown> {
    const code = args.code;
    if (typeof code !== "string" || code.trim() === "") throw new Error("python_exec needs code to run");
    return one.run(code, PYTHON_WALL_MS);
  },
};
