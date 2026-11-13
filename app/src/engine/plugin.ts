/**
 * In-process plugin lifecycle: **load, upgrade, and actually unload**.
 *
 * Use one Worker per plugin to provide the complete lifecycle:
 *
 * | Operation | Main-thread import | Worker implementation |
 * | --- | --- | --- |
 * | Load | ✔ | ✔ |
 * | Edit the file in place | ✘ Returns the old module | ✔ Replace the worker |
 * | Unload | ✘ Only prevent future calls | ✔ Reclaim code, memory, and timers |
 * | Broken plugin | Fails in the kernel | Fails in its own worker |
 *
 * JavaScript's module registry only grows, so the lifecycle unit must be a **realm**.
 * This is analogous to discarding a Java `ClassLoader`; Java cannot hot-unload one method either.
 *
 * Each call costs a structured clone. JavaScript cannot provide both **actual unloading** and
 * **zero-overhead direct calls**. This layer chooses unloading because it loads third-party code
 * at runtime, which most needs cleanup and is most likely to fail. Bundled functions bypass it.
 */

import { statSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

/**
 * Locate the worker-side file.
 *
 * ## Why an environment variable
 *
 * Path resolution depends on how the program is launched, and **must not be guessed**:
 *
 * | Launch mode | Resolution of `new Worker(path)` |
 * | --- | --- |
 * | `bun src/main.ts` | On disk, relative to the **process cwd** |
 * | Compiled single executable | Also on disk relative to cwd; absent source files cannot be found |
 *
 * Two attempted approaches failed: `new URL("./x.ts", import.meta.url)` becomes
 * `B:/~BUN/root/x.ts` after compilation, a nonexistent virtual path. A plain relative path
 * follows cwd and breaks when launched from another directory.
 *
 * The location must therefore be **supplied externally**, like `config.yaml` and credentials.
 * The default applies only to `bun start` from `app/`; other launch modes must provide a value.
 */
function hostPath(): string {
  const given = process.env.TGENGIN_PLUGIN_HOST;
  if (given && given.trim()) return given;
  // When running source, `import.meta.url` points to a real file regardless of startup directory.
  // After bundling it is a virtual path with no file; use the environment-variable override above.
  try {
    const beside = fileURLToPath(new URL("./plugin-host.ts", import.meta.url));
    if (statSync(beside).isFile()) return beside;
  } catch {
    // Bundled or missing file: use the fallback below.
  }
  // **After compilation this path is relative to the main entry point's directory**, not cwd
  // or the original source path. The main entry is `src/main.ts`, so use a path relative to `src/`.
  // A wrong path produces `BuildMessage: ModuleNotFound resolving "..." (entry point)` only
  // in the worker's error event. Surface that detail instead of merely reporting startup failure.
  return "./engine/plugin-host.ts";
}

const HOST = hostPath();

/**
 * Maximum time to wait for worker startup.
 *
 * Without this timeout, a missing file can leave a promise unresolved forever, hanging the
 * caller without any log output.
 */
const READY_MS = 10_000;

interface Waiting {
  ok(v: unknown): void;
  fail(e: Error): void;
}

/** A worker containing a plugin: **one per file**, not one per export. */
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
      // **Report startup failures immediately.** Otherwise a failed worker leaves a promise unresolved,
      // hanging the caller without logs. This is especially likely after compilation: worker files
      // must be compiled as **separate entry points** (see build:win in package.json). If omitted,
      // `new Worker` finds nothing and may not report an error.
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
      // The worker has disappeared due to memory exhaustion, termination, or a process-level error.
      // Settle all in-flight calls. Otherwise callers wait until expect_ms without learning the cause.
      this.#w.onerror = (e: ErrorEvent) => no(new Error(`${name}: ${e.message}`));
    });
    // The startup guard above reports this failure; do not leave an unhandled rejection.
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
  /** File → its realm. */
  #live = new Map<string, Live>();
  /** Handle → its implementing file. Several handles commonly share a file. */
  #on = new Map<string, string>();

  /** Report the worker file location so a bad configuration is immediately visible. */
  readonly host = HOST;

  /**
   * Probe this path at startup.
   *
   * **Do not block application startup**: a machine using no plugins should still run. But report
   * failures now, rather than discovering them halfway through a task's first plugin invocation.
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
        // Load a nonexistent module. A `failed` response still proves the path works: this probe tests
        // whether the worker starts, not whether that module exists.
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
   * Invoke a plugin. **Check the file's mtime before every call**; replace the worker if it changed.
   *
   * Runtime installation would be inconsistent with requiring a process restart after every edit.
   * A `stat` call is cheaper than the structured clone already required.
   *
   * Realms are assigned by **file**, not handle: `a.ts#login` and `a.ts#book` share one worker and
   * module state. A listener created at module scope by one export is visible to the other.
   * Separate workers would silently duplicate that state, making the bug invisible externally.
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
      // An upgrade discards the old realm together with its timers and memory, which main-thread
      // module imports cannot do.
      had?.close();
      this.#live.set(path, new Live(name, pathToFileURL(path).href, stamp));
    }
    return await this.#live.get(path)!.call(exp, arg);
  }

  /**
   * Actually unload the code, memory, and timers.
   *
   * If other handles still reference the file, remove only this handle. **Discard the realm only
   * when the final handle is removed.**
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

  /** Files currently loaded. */
  names(): string[] {
    return [...this.#live.keys()].sort();
  }

  closeAll(): void {
    for (const l of this.#live.values()) l.close();
    this.#live.clear();
    this.#on.clear();
  }
}
