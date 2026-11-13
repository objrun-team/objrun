/**
 * Example: **`python_exec`**, the model's local computation tool.
 *
 * ```
 * bun test/integration/python.ts
 * ```
 *
 * Without computation, a model solving a derivation problem may **guess** a plausible
 * expression without a way to check it. This tool lets the model verify its own work.
 *
 * ## Why not a container?
 *
 * This is **infrastructure distributed with the application**. A container solution
 * requires Docker-in-WSL on this machine and is absent on a clean Windows installation,
 * making the tool development-machine-only. Pyodide compiles CPython to wasm; shipping
 * its few files alongside the executable gives the same environment everywhere.
 *
 * ## Four properties under test
 *
 * 1. It **really computes**: sympy integrates and numpy computes eigenvalues.
 * 2. **Variables do not leak between calls**, avoiding hard-to-diagnose order-dependent results.
 * 3. Errors **return to the model**, not to the kernel, so the traceback can guide a correction.
 * 4. **Infinite loops can be terminated**, and the tool remains usable afterward.
 *
 * The fourth property is why this layer exists. Pyodide's `runPython` is synchronous;
 * running it on the main thread would let `while True: pass` halt the entire engine.
 * It therefore runs in a Worker.
 */

import { done, ok, part, show, step } from "../_lib.ts";
import { closePython, python, PYTHON_WALL_MS } from "../../app/src/tools/python.ts";

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
  // **Order-dependent results** are especially hard to diagnose. A symbol leaking from one task into the next
  // appears as "passes alone, fails in sequence", and this layer is unlikely to be the first suspect.
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
  // Termination kills the entire interpreter, so verify **that a replacement starts automatically**.
  // Otherwise one infinite loop would disable computation for every subsequent task.
  const after = await run("import numpy as np\nprint(np.linalg.eigvalsh(np.array([[2.,1.],[1.,2.]])))");
  show("what came back:", after.stdout.trim());
  ok("the interpreter came back by itself", after.exitCode === 0 && after.stdout.includes("1."), after);
} finally {
  closePython();
}

done();
