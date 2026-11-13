/**
 * Stage the Pyodide files in `dist/pyodide/`: **the copy shipped with the installation**.
 *
 * ```
 * bun scripts/stage-pyodide.ts
 * ```
 *
 * The compiled executable does not contain the WASM runtime: `bun build --compile` packages
 * JavaScript modules, while `.wasm`, the standard-library ZIP, and package wheels are loaded
 * from disk at runtime. Distribution therefore consists of **two parts**: an executable and
 * an adjacent `pyodide/` directory, where `whereIs()` looks by default.
 *
 * ## Why load the packages first
 *
 * Wheels are **downloaded on demand**. If nobody has run `import numpy`, its `.whl` is absent
 * from `node_modules` and therefore from the staged directory. Users would discover this only
 * when they first calculate something, and their machine would need access to the CDN.
 * Load the bundled packages here to download their wheels before copying the complete directory.
 */

import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { join } from "node:path";
import { loadPyodide } from "pyodide";

/** Packages included in the installation. **Included packages work offline; omitted packages need network access on first use.** */
const BRING = ["sympy", "numpy", "scipy"];

const from = join(import.meta.dir, "..", "node_modules", "pyodide");
const to = join(import.meta.dir, "..", "..", "dist", "pyodide");

if (!existsSync(from)) throw new Error(`pyodide is not installed at ${from} - run bun install first`);

console.log(`fetching the wheels for: ${BRING.join(", ")}`);
const py = await loadPyodide();
await py.loadPackage(BRING);

rmSync(to, { recursive: true, force: true });
mkdirSync(to, { recursive: true });

// Source maps, example pages, and type declarations are for development, not installed users; they occupy more than ten megabytes.
const skip = (name: string) => /\.(map|html|d\.ts|md)$/i.test(name);
let bytes = 0;
for (const name of readdirSync(from)) {
  if (skip(name)) continue;
  const src = join(from, name);
  cpSync(src, join(to, name), { recursive: true });
  bytes += statSync(src).isFile() ? statSync(src).size : 0;
}

console.log(`staged ${to} (${(bytes / 1024 / 1024).toFixed(1)} MB)`);
console.log("ship this folder next to the binary - that is where it is looked for.");
