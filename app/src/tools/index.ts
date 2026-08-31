/**
 * 基础工具。
 *
 * **这些工具跑在它们所在的那个位置上**，所以这里直接用 `node:fs` / 子进程 ——
 * 转发发生在调用的边界（见 `../place/`），不在工具体里面。`local` 是同进程调
 * 这一批；别的位置是把运行时送过去，那个运行时里装的也是这一批，一份实现两边通用。
 *
 * 描述、参数、返回值 schema 抄自 DeepSeek Harness（MIT, Copyright (c) 2026 DeepSeek，
 * github.com/deepseek-ai/deepseek-harness）：那几个上限和「唯一匹配」之类的约定是
 * 踩出来的，不是随手定的。壳子是我们自己的 —— 它那套是插件 + 容器，我们这套是表行。
 *
 * **grep / glob 没有用 ripgrep**：它是一个外部二进制，进不了单文件包，
 * 一引就把交叉编译废掉。宁可纯 TS 慢一点。
 */

import { spawn, spawnSync } from "node:child_process";
import { constants } from "node:fs";
import { access, mkdir, readdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, join, relative, resolve, sep } from "node:path";

import { python } from "./python.ts";

/** 一次 read 默认/最多返回多少行。 */
export const READ_LIMIT = 2000;
/** 单行超过这么多字符就截断 —— 一行几十万字符会把上下文顶爆。 */
export const READ_MAX_LINE_LENGTH = 2000;
/** 一次 read 最多返回多少字节，行数没到也停。 */
export const READ_MAX_BYTES = 50 * 1024;
/** glob 最多返回多少条。 */
export const GLOB_MAX_RESULTS = 100;
/** grep 最多返回多少条。 */
export const GREP_MAX_MATCHES = 200;

/** 一个工具：给模型看的那几样 + 真正干活的那个函数。 */
export interface Tool {
  name: string;
  /** 给模型看的描述。 */
  does: string;
  /** 给模型看的参数 schema。 */
  params: Record<string, unknown>;
  /** 给模型看的返回值 schema。 */
  output: Record<string, unknown>;
  /** 往系统提示里加的用法约定 —— 跟 `does` 不是一回事：这条说怎么用才不出错。 */
  prompt: string;
  /** 能不能跟别的工具同时跑。 */
  concurrent: boolean;
  /** 预期多久，超过判死。 */
  expectMs: number;
  /**
   * 什么时候摆给模型。**不填 = 谁都有、不看条件**（读写那一组就是这样）。
   *
   * 填了就落成 `trigger` 里的行，这一件工具也就从「系统工具」那一档退出来，
   * 归条件管。一组里每条都得中，组之间是或 —— 跟外面声明的工具同一套规矩，
   * 内核不为随二进制发的这几件另开一条路。
   */
  when?: { dim: string; key: string; op: string; value: string }[][];
  run(args: Record<string, unknown>): Promise<unknown>;
}

/**
 * 参数 schema。**存进 `tool.params` 的必须是真的 JSON Schema** ——
 * 供应商那边照着它校验，形状不对直接 400，而那是在真调模型的时候才发现。
 */
function schema(properties: Record<string, unknown>, required: string[]): Record<string, unknown> {
  return { type: "object", properties, required, additionalProperties: false };
}

function str(args: Record<string, unknown>, key: string, required = true): string {
  const v = args[key];
  if (v === undefined || v === null) {
    if (required) throw new Error(`${key} is required`);
    return "";
  }
  if (typeof v !== "string") throw new Error(`${key} must be a string`);
  return v;
}

function num(args: Record<string, unknown>, key: string, dflt: number): number {
  const v = args[key];
  if (v === undefined || v === null) return dflt;
  const n = Number(v);
  if (!Number.isFinite(n)) throw new Error(`${key} must be a number`);
  return n;
}

// ── read ────────────────────────────────────────────────────────────────────

export const read: Tool = {
  name: "read",
  does: "Read a UTF-8 text file and return line-numbered content.",
  params: schema(
    {
      file_path: { type: "string", description: "Path to read." },
      offset: { type: "number", description: "1-based first line to return. Defaults to 1." },
      limit: { type: "number", description: `Maximum number of lines to return. Defaults to ${READ_LIMIT}.` },
    },
    ["file_path"],
  ),
  output: {
    type: "object",
    properties: {
      path: { type: "string" },
      offset: { type: "integer" },
      lines: { type: "array", items: { type: "object", properties: { number: { type: "integer" }, text: { type: "string" } } } },
      totalLines: { type: "integer" },
      truncated: { type: "boolean" },
    },
  },
  prompt:
    "Use read before edit or write on an existing file. Content comes back line-numbered; " +
    `a single line longer than ${READ_MAX_LINE_LENGTH} characters is truncated, and one call returns at most ` +
    `${READ_LIMIT} lines or ${READ_MAX_BYTES} bytes — use offset to continue.`,
  concurrent: true,
  expectMs: 30_000,
  async run(args) {
    const path = str(args, "file_path");
    const offset = Math.max(1, Math.trunc(num(args, "offset", 1)));
    const limit = Math.min(Math.max(1, Math.trunc(num(args, "limit", READ_LIMIT))), READ_LIMIT);

    const text = await readFile(path, "utf8");
    const all = text.split(/\r?\n/);
    // 末尾的换行会切出一个空段，那不是一行。
    if (all.length > 1 && all[all.length - 1] === "") all.pop();

    const lines: { number: number; text: string }[] = [];
    let bytes = 0;
    let truncated = false;
    for (let i = offset - 1; i < all.length && lines.length < limit; i++) {
      let t = all[i];
      if (t.length > READ_MAX_LINE_LENGTH) {
        t = t.slice(0, READ_MAX_LINE_LENGTH) + `... (${all[i].length - READ_MAX_LINE_LENGTH} more characters on this line)`;
        truncated = true;
      }
      bytes += Buffer.byteLength(t, "utf8") + 1;
      if (bytes > READ_MAX_BYTES && lines.length > 0) {
        truncated = true;
        break;
      }
      lines.push({ number: i + 1, text: t });
    }
    if (offset - 1 + lines.length < all.length) truncated = true;
    return { path, offset, lines, totalLines: all.length, truncated };
  },
};

// ── write ───────────────────────────────────────────────────────────────────

export const write: Tool = {
  name: "write",
  does: "Create or fully replace a UTF-8 text file.",
  params: schema(
    {
      file_path: { type: "string", description: "Path to write." },
      content: { type: "string", description: "Full UTF-8 text content to write." },
    },
    ["file_path", "content"],
  ),
  output: { type: "object", properties: { path: { type: "string" }, bytes: { type: "integer" }, created: { type: "boolean" } } },
  prompt:
    "Use write to create a file or completely replace its contents. Existing files are overwritten — " +
    "read it first, and prefer edit for targeted changes.",
  concurrent: false,
  expectMs: 30_000,
  async run(args) {
    const path = str(args, "file_path");
    const content = str(args, "content");
    const created = !(await exists(path));
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, content, "utf8");
    return { path, bytes: Buffer.byteLength(content, "utf8"), created };
  },
};

// ── edit ────────────────────────────────────────────────────────────────────

export const edit: Tool = {
  name: "edit",
  does: "Edit an existing UTF-8 text file by replacing literal text.",
  params: schema(
    {
      file_path: { type: "string", description: "Path to edit." },
      old_string: { type: "string", description: "Literal text to replace. Must match exactly." },
      new_string: {
        type: "string",
        description: "Literal replacement text. Use an empty string to delete the match.",
      },
      replace_all: {
        type: "boolean",
        description: "Replace all matches. Defaults to false; when false, old_string must appear exactly once.",
      },
    },
    ["file_path", "old_string", "new_string"],
  ),
  output: { type: "object", properties: { path: { type: "string" }, replaced: { type: "integer" } } },
  prompt:
    "Use edit for targeted changes to existing UTF-8 text files. It replaces literal old_string with new_string; " +
    "by default old_string must appear exactly once. If it appears multiple times, give a more specific old_string " +
    "or set replace_all. Read the file first unless you just created or edited it.",
  concurrent: false,
  expectMs: 30_000,
  async run(args) {
    const path = str(args, "file_path");
    const oldStr = str(args, "old_string");
    const newStr = str(args, "new_string", false);
    const replaceAll = Boolean(args.replace_all ?? false);

    // 这三条 schema 表达不了，但每一条不挡住都会变成一次静默的空改。
    if (path.trim().length === 0) throw new Error("file_path cannot be empty");
    if (oldStr.length === 0) throw new Error("old_string cannot be empty");
    if (oldStr === newStr) throw new Error("old_string and new_string are identical - this edit would change nothing");

    const text = await readFile(path, "utf8");
    const hits = count(text, oldStr);
    if (hits === 0) throw new Error(`old_string not found in ${path}`);
    if (hits > 1 && !replaceAll) {
      throw new Error(`old_string occurs ${hits} times in ${path}. Give a more specific old_string, or set replace_all to true`);
    }
    const next = replaceAll ? text.split(oldStr).join(newStr) : text.replace(oldStr, newStr);
    await writeFile(path, next, "utf8");
    return { path, replaced: replaceAll ? hits : 1 };
  },
};

function count(hay: string, needle: string): number {
  let n = 0;
  let i = hay.indexOf(needle);
  while (i !== -1) {
    n++;
    i = hay.indexOf(needle, i + needle.length);
  }
  return n;
}

// ── glob ────────────────────────────────────────────────────────────────────

const SKIP = new Set([".git", "node_modules", ".hg", ".svn"]);

export const glob: Tool = {
  name: "glob",
  does:
    "Find files whose paths match a glob pattern. Returns matching file paths — never directories — " +
    `including hidden files (VCS metadata directories are excluded). Up to ${GLOB_MAX_RESULTS} paths come back ` +
    "in modification-time order, newest first.",
  params: schema(
    {
      pattern: {
        type: "string",
        description:
        'Glob pattern to match file paths against (e.g. "**/*.ts", "src/**/*.test.js"). ' +
        'A pattern with no "/" matches the basename at any depth, so "*" and "*.ts" both search the whole tree; ' +
          "include a separator to anchor the depth.",
      },
      path: { type: "string", description: "Directory to search under. Defaults to the current directory." },
    },
    ["pattern"],
  ),
  output: {
    type: "object",
    properties: { files: { type: "array", items: { type: "string" } }, truncated: { type: "boolean" } },
  },
  prompt:
    'Use glob — not shell find — to discover files by path pattern. A pattern with no "/" matches basenames at ' +
    'any depth, so "*" matches every file in the tree rather than its top level. Results are files only, never directories.',
  concurrent: true,
  expectMs: 60_000,
  async run(args) {
    const pattern = str(args, "pattern");
    const root = resolve(str(args, "path", false) || ".");
    // 没有分隔符的式子按 basename 比 —— 这条是 dsh 的约定，抄过来的：
    // 不这么定的话 "*.ts" 只匹配顶层，而人写它的时候想的是整棵树。
    const onBase = !pattern.includes("/");
    const re = globToRegExp(pattern);

    const found: { path: string; mtimeMs: number }[] = [];
    await walk(root, async (file, st) => {
      const rel = relative(root, file).split(sep).join("/");
      if (re.test(onBase ? rel.slice(rel.lastIndexOf("/") + 1) : rel)) {
        found.push({ path: file, mtimeMs: st.mtimeMs });
      }
    });
    found.sort((a, b) => b.mtimeMs - a.mtimeMs);
    return { files: found.slice(0, GLOB_MAX_RESULTS).map((f) => f.path), truncated: found.length > GLOB_MAX_RESULTS };
  },
};

/** glob 式子转正则。`**` 跨目录，`*` 不跨，`?` 一个字符，`{a,b}` 二选一。 */
export function globToRegExp(pattern: string): RegExp {
  let out = "";
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i];
    if (c === "*") {
      if (pattern[i + 1] === "*") {
        // `**/` 要能匹配零层目录，否则 "**/*.ts" 匹配不到顶层的文件。
        if (pattern[i + 2] === "/") {
          out += "(?:.*/)?";
          i += 2;
        } else {
          out += ".*";
          i += 1;
        }
      } else out += "[^/]*";
    } else if (c === "?") out += "[^/]";
    else if (c === "{") out += "(?:";
    else if (c === "}") out += ")";
    else if (c === "," ) out += "|";
    else out += c.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp(`^${out}$`);
}

async function walk(dir: string, hit: (file: string, st: { mtimeMs: number }) => Promise<void>): Promise<void> {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return; // 读不动的目录跳过，不让一个权限问题毁掉整次搜索
  }
  for (const e of entries) {
    const p = join(dir, e.name);
    if (e.isDirectory()) {
      if (SKIP.has(e.name)) continue;
      await walk(p, hit);
    } else if (e.isFile()) {
      try {
        await hit(p, await stat(p));
      } catch {
        /* 中途没了就算了 */
      }
    }
  }
}

// ── grep ────────────────────────────────────────────────────────────────────

export const grep: Tool = {
  name: "grep",
  does:
    "Search file contents with a regular expression. Returns matching lines with line numbers, grouped by file. " +
    `Returns the first ${GREP_MAX_MATCHES} matches; a capped result says so. Use read on a matched file for context.`,
  params: schema(
    {
      pattern: { type: "string", description: "Regular expression to search for." },
      path: { type: "string", description: "File or directory to search. Defaults to the current directory." },
      include: { type: "string", description: 'One glob filter for which files to search (e.g. "*.ts"). Not a list.' },
    },
    ["pattern"],
  ),
  output: {
    type: "object",
    properties: {
      matches: {
        type: "array",
        items: { type: "object", properties: { path: { type: "string" }, line: { type: "integer" }, text: { type: "string" } } },
      },
      truncated: { type: "boolean" },
    },
  },
  prompt: "Use grep — not shell grep — to search file contents. Use read on a matched file when you need surrounding context.",
  concurrent: true,
  expectMs: 60_000,
  async run(args) {
    const re = new RegExp(str(args, "pattern"));
    const target = resolve(str(args, "path", false) || ".");
    const include = str(args, "include", false);
    const inc = include ? globToRegExp(include) : null;

    const matches: { path: string; line: number; text: string }[] = [];
    let truncated = false;

    const scan = async (file: string) => {
      if (matches.length >= GREP_MAX_MATCHES) return;
      if (inc && !inc.test(file.slice(file.lastIndexOf(sep) + 1))) return;
      let text: string;
      try {
        text = await readFile(file, "utf8");
      } catch {
        return; // 二进制或读不动的跳过
      }
      const lines = text.split(/\r?\n/);
      for (let i = 0; i < lines.length; i++) {
        if (!re.test(lines[i])) continue;
        if (matches.length >= GREP_MAX_MATCHES) {
          truncated = true;
          return;
        }
        const t = lines[i];
        matches.push({ path: file, line: i + 1, text: t.length > READ_MAX_LINE_LENGTH ? t.slice(0, READ_MAX_LINE_LENGTH) + "…" : t });
      }
    };

    const st = await stat(target);
    if (st.isFile()) await scan(target);
    else await walk(target, async (f) => await scan(f));
    return { matches, truncated };
  },
};

// ── bash ────────────────────────────────────────────────────────────────────

export const bash: Tool = {
  name: "bash",
  does:
    "Run a shell command and return its stdout, stderr and exit code. " +
    "Uses /bin/sh on POSIX and PowerShell on Windows.",
  params: schema(
    {
      command: { type: "string", description: "The shell command to run." },
      cwd: { type: "string", description: "Working directory. Defaults to the current directory." },
      timeout_ms: { type: "number", description: "Kill the command after this long. Defaults to 120000." },
    },
    ["command"],
  ),
  output: {
    type: "object",
    properties: {
      code: { type: "integer" },
      stdout: { type: "string" },
      stderr: { type: "string" },
      timedOut: { type: "boolean" },
    },
  },
  prompt:
    "Use bash for commands that have no dedicated tool. Prefer read / write / edit / glob / grep over cat, tee, " +
    "sed, find and grep — they give structured results and the shell ones do not. " +
    "On Windows this runs in PowerShell: when only Windows PowerShell 5.1 is installed, `&&` and `||` are parse " +
    "errors — use `;` or `if ($?) { ... }` instead.",
  concurrent: false,
  expectMs: 130_000,
  async run(args) {
    const command = str(args, "command");
    const cwd = str(args, "cwd", false) || undefined;
    const timeoutMs = num(args, "timeout_ms", 120_000);
    return await sh(command, cwd, timeoutMs);
  },
};

/**
 * Windows 上用哪个 PowerShell。
 *
 * 有 `pwsh`（7+）就用它 —— Windows PowerShell 5.1 里 `&&` 和 `||` 是语法错误，
 * 而模型十有八九会写。探一次记下来，别每条命令都探。
 */
let PWSH: string | null = null;
function pwsh(): string {
  if (PWSH === null) {
    const r = spawnSync("pwsh.exe", ["-NoProfile", "-Command", "$PSVersionTable.PSVersion.Major"], { windowsHide: true });
    PWSH = r.status === 0 ? "pwsh.exe" : "powershell.exe";
  }
  return PWSH;
}

/** 跑一条命令。**一定要有上限** —— 没有的话一个不返回的命令能把整个位置钉死。 */
export function sh(
  command: string,
  cwd: string | undefined,
  timeoutMs: number,
): Promise<{ code: number; stdout: string; stderr: string; timedOut: boolean }> {
  return new Promise((done) => {
    // Windows 上不能直接把命令串丢给 cmd：命令行是按控制台代码页解的（中文机器是
    // GBK），命令里的中文**在进去的路上就烂了**，出来的输出也烂 —— 而且两头都不报错。
    // 走 PowerShell 的 -EncodedCommand：参数是 UTF-16 的 base64，进去这一路不经过
    // 代码页；再在里面把输出编码钉成 UTF-8，出来这一路也就对了。
    const win = process.platform === "win32";
    const spawned = win
      ? spawn(
          pwsh(),
          [
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            Buffer.from(
              `[Console]::OutputEncoding=[Text.Encoding]::UTF8; ${command}`,
              "utf16le",
            ).toString("base64"),
          ],
          { cwd, windowsHide: true },
        )
      : spawn(command, { shell: true, cwd, windowsHide: true });
    const p = spawned;
    let out = "";
    let err = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      p.kill();
    }, timeoutMs);
    p.stdout.on("data", (d: Buffer) => (out += d.toString()));
    p.stderr.on("data", (d: Buffer) => (err += d.toString()));
    p.on("close", (code) => {
      clearTimeout(timer);
      done({ code: code ?? -1, stdout: out, stderr: err, timedOut });
    });
    p.on("error", (e) => {
      clearTimeout(timer);
      done({ code: -1, stdout: out, stderr: String(e), timedOut });
    });
  });
}

async function exists(path: string): Promise<boolean> {
  try {
    await access(path, constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

/** 全部基础工具。**内核不认得这个名单** —— 它只查 `tool` 表。 */
/**
 * **交卷站一个工具都不摆，除了交卷本身。**
 *
 * 跑工具的只有动作站；交卷站是模型站、它的下一站也是模型站 —— 在那儿请求任何
 * 工具都没有人会去跑，那次调用会一直挂着，最后被补一条「没跑成」。而交卷本来
 * 也不需要工具：交的是那次 `submit` 调用里的答案。
 *
 * 写成条件挂在每一件上，而不是让内核去认「哪一站是交卷站」——**表说了算**，
 * 想让某件工具在那儿也摆着，改这一行数据就行。
 */
const NOT_AT_HAND_IN = [[{ dim: "cycle", key: "cycle", op: "ne", value: "submit" }]];

export const TOOLS: Tool[] = [read, write, edit, glob, grep, bash, python].map((t) => ({
  ...t,
  when: t.when ?? NOT_AT_HAND_IN,
}));
