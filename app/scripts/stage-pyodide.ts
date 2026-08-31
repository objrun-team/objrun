/**
 * 把 Pyodide 那堆文件摆到 `dist/pyodide/` —— **安装包里那一份。**
 *
 * ```
 * bun scripts/stage-pyodide.ts
 * ```
 *
 * 编出来的二进制里没有 wasm：`bun build --compile` 打的是 JS 模块，`.wasm`、
 * 标准库 zip、那几个轮子都是运行时从磁盘读的。所以发出去的东西是**两样**：
 * 一个 exe，加它旁边一个 `pyodide/` 目录（`whereIs()` 默认就在那儿找）。
 *
 * ## 为什么要先跑一遍
 *
 * 轮子是**用到才下载**的：没人 `import numpy` 过的话，`node_modules` 里就没有
 * 那个 `.whl`，摆出去的目录自然也没有 —— 而那要到用户第一次算东西、而且那台
 * 机器还得能上 CDN 的时候才发现。所以这儿先把要带的包加载一遍，把轮子落到本地，
 * 再整个拷过去。
 */

import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { join } from "node:path";
import { loadPyodide } from "pyodide";

/** 安装包里要带哪几个包。**带了就是离线可用，没带就是第一次用要联网。** */
const BRING = ["sympy", "numpy", "scipy"];

const from = join(import.meta.dir, "..", "node_modules", "pyodide");
const to = join(import.meta.dir, "..", "..", "dist", "pyodide");

if (!existsSync(from)) throw new Error(`pyodide is not installed at ${from} - run bun install first`);

console.log(`fetching the wheels for: ${BRING.join(", ")}`);
const py = await loadPyodide();
await py.loadPackage(BRING);

rmSync(to, { recursive: true, force: true });
mkdirSync(to, { recursive: true });

// 地图文件、示例网页、类型声明都是给开发看的，装机器上没人读 —— 那是十几兆。
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
