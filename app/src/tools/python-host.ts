/**
 * Host `python_exec` in a Worker running Pyodide, CPython compiled to WASM.
 *
 * **Why not use the main thread?** Pyodide's `runPython` is synchronous. A model's
 * `while True: pass` would freeze the engine and every task. A dedicated Worker can instead
 * be terminated externally at timeout, affecting only that interpreter.
 *
 * **Why not use containers?** Docker is installed inside WSL on this machine, but this runtime
 * ships with the application. A clean Windows installation may have neither WSL nor Docker.
 * WASM requires only files distributed beside the executable.
 *
 * ## Protocol
 *
 * ```
 * → { kind: "run", id, code }
 * ← { kind: "ready" } | { kind: "failed", error }
 * ← { kind: "done", id, exitCode, stdout, stderr }
 * ```
 *
 * Pyodide takes about two and a half seconds to start, so **start once and reuse it**. Initial
 * package imports such as numpy take a few additional seconds, also only once.
 *
 * ## Fresh globals for each invocation
 *
 * Reuse the interpreter, **not variables**: give every `runPython` fresh globals. Symbols leaking
 * between tasks would make results depend on execution order, a harder problem than startup latency.
 */

import { statSync } from "node:fs";
import { dirname, join } from "node:path";

declare const self: {
  onmessage: ((e: { data: unknown }) => void) | null;
  postMessage(v: unknown): void;
};

/** Maximum output returned to the model. More output only exhausts context. */
const CAP = 4000;

/** Use Pyodide's own types; copied definitions would silently drift after upgrades. */
type Py = Awaited<ReturnType<typeof import("pyodide").loadPyodide>>;

let py: Py | null = null;
let out: string[] = [];
let err: string[] = [];

/**
 * Locate the Pyodide assets.
 *
 * As with the plugin host, **do not guess this path**. Source execution can find node_modules,
 * but compilation makes `import.meta.url` a virtual path without files. Supply an external
 * location: distribute `pyodide/` beside the executable and allow the environment override.
 */
function whereIs(): string | undefined {
  const given = process.env.TGENGIN_PYODIDE;
  if (given && given.trim()) return given;
  // **Look beside the executable by default.** Shipping `pyodide/` adjacent to the exe should
  // work without an environment variable, which first-time users would easily omit.
  // The override above supports assets installed elsewhere.
  try {
    const beside = join(dirname(process.execPath), "pyodide");
    if (statSync(beside).isDirectory()) return beside;
  } catch {
    // No adjacent assets: assume source execution and let Pyodide locate node_modules.
  }
  return undefined;
}

async function boot(): Promise<Py> {
  if (py) return py;
  const { loadPyodide } = await import("pyodide");
  const where = whereIs();
  const it = await loadPyodide({
    ...(where ? { indexURL: where } : {}),
    // Package availability determines loading. The first numpy import downloads and caches a wheel
    // from the CDN; bundled wheels turn that operation into a local read without network access.
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
  // **Load packages imported by the code.** No per-task package list needs maintenance:
  // `import sympy` causes sympy to load, and subsequent loads are no-ops.
  let trouble = "";
  try {
    await it.loadPackagesFromImports(code);
  } catch (e) {
    // Package-loading failure does not necessarily prevent execution; the import may belong to the standard library.
    trouble = e instanceof Error ? e.message : String(e);
  }
  // Pyodide itself writes "Loading numpy / Loaded numpy" while loading packages. **Those lines
  // are not program output** and would mislead the model. Clear output after loading, not before.
  out = [];
  err = trouble ? [trouble] : [];
  try {
    // Fresh globals for every invocation prevent earlier variables from leaking into later executions.
    const names = it.globals.get("dict") as () => unknown;
    await it.runPythonAsync(code, { globals: names() as never });
    return { exitCode: 0, stdout: cut(out), stderr: cut(err) };
  } catch (e) {
    // Return Python exceptions **as tool results**, not protocol errors; the model needs the traceback to fix its code.
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

// Warm the interpreter at worker startup rather than making the first invocation wait two and a half seconds.
void boot().then(
  () => self.postMessage({ kind: "ready" }),
  (x: unknown) => self.postMessage({ kind: "failed", error: x instanceof Error ? x.message : String(x) }),
);
