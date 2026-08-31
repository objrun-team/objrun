/**
 * 例子：**`python_exec`** —— 模型手上那点算力。
 *
 * ```
 * bun test/python.ts
 * ```
 *
 * 一道推导题，模型没有算力的时候会**猜**：写一个看起来对的式子，然后没有任何
 * 办法知道它对不对。这个工具就是让它能自己验一下。
 *
 * ## 为什么不是容器
 *
 * 它是**跟安装包一起分发的基础设施**。容器方案在这台机器上要 Docker-in-WSL，
 * 换一台干净的 Windows 就什么都没有 —— 那样这个工具只在开发机上存在。
 * Pyodide 是 CPython 编到 wasm，几个文件跟二进制放一块儿，到哪儿都一样。
 *
 * ## 这个例子盯的是四件事
 *
 * 1. 它**真的会算** —— sympy 积得出、numpy 解得出特征值
 * 2. 两次调用之间**变量不串** —— 不然换个顺序跑结果就变了，这种事最难查
 * 3. 报错**回给模型**，不是抛给内核 —— 模型看得见回溯才改得动代码
 * 4. **死循环掐得掉**，而且掐完还能接着用
 *
 * 第 4 条是这一层存在的理由：Pyodide 的 `runPython` 是同步的，跑在主线程里的话
 * 一句 `while True: pass` 就是整个引擎停摆。所以它住在一个 Worker 里。
 */

import { done, ok, part, show, step } from "./_lib.ts";
import { closePython, python, PYTHON_WALL_MS } from "../app/src/tools/python.ts";

interface Ran {
  exitCode: number;
  stdout: string;
  stderr: string;
  timedOut?: boolean;
}

const run = (code: string) => python.run({ code }) as Promise<Ran>;

try {
  part("python_exec: the arithmetic the model gets to lean on");

  step("1. it really computes - this is a symbolic integral, not a lookup");
  const t0 = Date.now();
  const sym = await run("import sympy\nx = sympy.symbols('x')\nprint(sympy.integrate(sympy.sin(x)**2, x))");
  show("what came back:", sym);
  ok("sympy is there and the answer is right", sym.stdout.includes("x/2 - sin(x)*cos(x)/2"), sym);
  show("first call, interpreter and packages included:", `${String(Date.now() - t0)}ms`);

  step("2. the interpreter is reused, so the second call is cheap");
  const t1 = Date.now();
  const again = await run("import sympy\nprint(sympy.factorint(600851475143))");
  const cost = Date.now() - t1;
  show("second call:", `${String(cost)}ms`);
  ok("it did not pay for a fresh interpreter", cost < 1000, cost);

  step("3. nothing carries over between calls");
  // **换个顺序跑结果就不一样**是最难查的一类毛病。一道题定义的符号漏到下一道题，
  // 表现是「单独跑对、连着跑错」，而那时候谁都不会先怀疑这儿。
  await run("leaked = 'I should not survive'");
  const fresh = await run("print('leaked' in dir())");
  show("is the old variable still visible:", fresh.stdout.trim());
  ok("each program starts from an empty namespace", fresh.stdout.trim() === "False", fresh);

  step("4. a program that throws comes back as a result, not as a broken tool call");
  const boom = await run("print(1 / 0)");
  show("what came back:", { exitCode: boom.exitCode, stderr: boom.stderr.slice(0, 120) });
  ok("it is a failed run, not a failed handle", boom.exitCode === 1, boom.exitCode);
  ok("and the traceback goes back to the model, which is who can fix it", boom.stderr.includes("ZeroDivisionError"), boom.stderr);

  step("5. an endless loop is cut off rather than taking the engine with it");
  const stuck = await run("while True:\n    pass");
  show("what came back:", stuck);
  ok("it stopped", stuck.timedOut === true, stuck);
  ok("at the wall, not whenever", stuck.stderr.includes(String(PYTHON_WALL_MS)), stuck.stderr);

  step("6. and it still works afterwards");
  // 掐掉的是整个解释器，所以这一条验的是**它会自己重新起一个**。不会的话，
  // 一个死循环就永久废掉这个工具 —— 后面每道题都拿不到算力。
  const after = await run("import numpy as np\nprint(np.linalg.eigvalsh(np.array([[2.,1.],[1.,2.]])))");
  show("what came back:", after.stdout.trim());
  ok("the interpreter came back by itself", after.exitCode === 0 && after.stdout.includes("1."), after);
} finally {
  closePython();
}

done();
