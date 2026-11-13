/**
 * Host a plugin in a Worker.
 *
 * **This is one half of the roughly hundred-line implementation.** It has no knowledge of
 * specific plugins: import a requested module, call the requested export, and return its result.
 *
 * ## Why use a separate realm
 *
 * In JavaScript, **the lifecycle unit is a realm**, not a function or module. The module registry
 * only grows. For a module imported on the main thread, an upgrade can only point the registry
 * to a new version while retaining the old one. Removal can prevent future calls, but its code,
 * memory, and timers remain.
 *
 * A separate realm provides actual cleanup: `terminate()` removes the code, its 8MB of memory,
 * and its timers together. This is analogous to discarding a Java `ClassLoader`; Java cannot
 * hot-unload an individual method either.
 *
 * Calls incur structured-clone overhead rather than directly calling a function. JavaScript
 * cannot provide both **actual unloading** and **zero-overhead direct calls**; this chooses unloading.
 *
 * ## Protocol
 *
 * ```
 * → { kind: "load", module: "file path" }
 * ← { kind: "ready" } | { kind: "failed", error }
 * → { kind: "call", id, export: "export name", arg }
 * ← { kind: "done", id, ok: true,  value }
 * ← { kind: "done", id, ok: false, error }
 * ```
 *
 * **Load a file, then select its export when calling.** A file commonly exports several tools
 * that should share module state. One realm per export would silently duplicate module-level variables.
 */

declare const self: {
  onmessage: ((e: { data: unknown }) => void) | null;
  postMessage(v: unknown): void;
};

type Fn = (arg: unknown) => Promise<unknown> | unknown;

let mod: Record<string, unknown> | null = null;
let from = "";

async function load(path: string): Promise<void> {
  // This worker is **single-use**: it loads one file. Upgrades terminate it and create another.
  // There is no import-cache management here because a new worker has a new module registry.
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
        // Return plugin exceptions **only to the caller**, without terminating the worker: one failed
        // call does not mean the plugin is broken. A fatal failure such as an infinite loop or memory
        // exhaustion remains isolated to this worker.
        self.postMessage({ kind: "done", id, ok: false, error: err instanceof Error ? err.message : String(err) });
      }
    })();
  }
};
