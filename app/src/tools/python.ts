/**
 * `python_exec`: execute Python and return its printed output.
 *
 * ## Why this engine needs it
 *
 * Without computational tools, a model solving a derivation problem may **guess** a plausible
 * formula with no way to check it. An observed task spent twelve execution units checking
 * `python --version` without producing an answer: it kept seeking unavailable computation
 * until its budget was exhausted.
 *
 * ## Execution location
 *
 * Pyodide runs in a Worker; see `./python-host.ts`. This half handles only **startup, termination
 * on timeout, and receiving results**.
 *
 * Termination is essential: synchronous `runPython` would freeze the engine on the main thread,
 * whereas `terminate()` can stop a worker even during synchronous execution.
 *
 * ## No manual package configuration
 *
 * `import sympy` causes the host to load sympy through `loadPackagesFromImports`.
 * Precompiled wheels are available for sympy, numpy, and scipy.
 */

import { statSync } from "node:fs";
import { fileURLToPath } from "node:url";

/** Maximum execution time for one code snippet; terminate its worker at the deadline. */
export const PYTHON_WALL_MS = 30_000;
/** Interpreter startup takes two and a half seconds, and initial package loading adds time. Allow enough for the first call. */
const BOOT_MS = 120_000;

/**
 * Locate the worker-side file.
 *
 * As in `../engine/plugin.ts`, **the location can be supplied externally**. During source
 * execution, `import.meta.url` references a real file; in a compiled executable it is a virtual
 * path such as `B:/~BUN/root/...` with no corresponding file.
 */
function hostPath(): string {
  const given = process.env.TGENGIN_PYTHON_HOST;
  if (given && given.trim()) return given;
  try {
    const beside = fileURLToPath(new URL("./python-host.ts", import.meta.url));
    if (statSync(beside).isFile()) return beside;
  } catch {
    // Bundled or missing file: use the fallback below.
  }
  // **Compiled worker paths resolve relative to the main entry point's directory**, not cwd
  // or the original source path. With `src/main.ts` as entry, use a path relative to `src/`.
  // An incorrect path produces `BuildMessage: ModuleNotFound resolving "..." (entry point)`
  // only in the worker error event. Surface that diagnostic rather than just "cannot start".
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
 * The interpreter instance.
 *
 * **Start once and reuse it** to avoid two and a half seconds of startup plus package loading
 * on every invocation. After a timeout terminates it, the next invocation starts a fresh worker.
 */
class Interpreter {
  #w: Worker | null = null;
  #ready: Promise<void> | null = null;
  #next = 1;
  #waiting = new Map<number, (d: Done) => void>();

  #open(): Worker {
    if (this.#w) return this.#w;
    const w = new Worker(hostPath());
    // **Do not prevent process exit.** The warmed interpreter waits for future calls, but once the
    // engine finishes none will arrive. A referenced worker would keep the whole process alive forever.
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
        // **Include the worker's actual diagnostic.** A generic startup failure would force users to
        // investigate WASM assets, paths, and Bun worker support even though the error already explains it.
        const said = String(e.message || (e.error as Error | undefined)?.message || '').trim();
        no(new Error('the python interpreter crashed while starting' + (said ? ': ' + said : '')));
      });
    });
    return w;
  }

  /** Terminate the interpreter. In-flight calls handle their own timeouts; this ensures the next call gets a clean worker. */
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
      // The deadline passed, likely due to an infinite loop. **Terminate the interpreter too**;
      // otherwise it consumes a core indefinitely and cannot accept another call.
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

/** Dispose of the interpreter when the engine finishes so the process can exit cleanly. */
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
    "Nothing carries over between calls - each program starts from an empty namespace. Every call made in one " +
    "turn is run before the next turn.",
  concurrent: false,
  gives: "event",
  expectMs: PYTHON_WALL_MS + 30_000,
  // **Do not offer this at submission.** Only action stations run tools; submission and its
  // successor are model stations. Computation requested there would remain pending until repair
  // adds a failure result. Submitting the model's answer requires no computation.
  when: [[{ dim: "cycle", key: "cycle", op: "ne", value: "submit" }]],
  async run(args: Record<string, unknown>): Promise<unknown> {
    const code = args.code;
    if (typeof code !== "string" || code.trim() === "") throw new Error("python_exec needs code to run");
    return one.run(code, PYTHON_WALL_MS);
  },
};
