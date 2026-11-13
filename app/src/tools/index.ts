/**
 * Basic tools.
 *
 * **Tools execute at their assigned location**, so implementations use `node:fs` and subprocesses
 * directly. Forwarding occurs at the invocation boundary (`../place/`), not inside tool bodies.
 * `local` calls these implementations in-process; other places receive a runtime containing
 * the same implementations.
 *
 * Descriptions, parameter schemas, and output schemas come from DeepSeek Harness (MIT,
 * Copyright (c) 2026 DeepSeek, github.com/deepseek-ai/deepseek-harness). Its limits and contracts,
 * such as requiring a unique match, reflect practical experience. Our integration differs:
 * that project uses plugins and containers; this one uses table rows.
 *
 * **grep / glob do not use ripgrep** because an external binary cannot be included in the
 * single-file package and would prevent cross-compilation. Accept slower pure TypeScript instead.
 */

import { spawn, spawnSync } from "node:child_process";
import { constants } from "node:fs";
import { access, mkdir, readdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, join, relative, resolve, sep } from "node:path";

import { python } from "./python.ts";

/**
 * **Maximum data returned by one search.** Stop immediately when the shared allowance is
 * exhausted and return an explicit truncation indication.
 *
 * Do not compress or summarize matches: every returned result is unchanged, and traversal
 * simply stops at the limit. These tools exist to show the actual lines, not a shortened account
 * that falsely appears complete.
 *
 * The limit is 5000 tokens, estimated at 4 bytes each. A measured task context contained
 * 4234989 bytes for the model-reported 1033906 tokens.
 *
 * `read` does not truncate against this allowance. It **calculates the requested size first**
 * and rejects the whole range if oversized. Returning a partial file that appears complete
 * could lead to incorrect edits before the truncation is discovered.
 */
export const TOOL_POOL_TOKENS = 5_000;
export const TOOL_POOL_BYTES = TOOL_POOL_TOKENS * 4;

/** Maximum text characters per grep match. A single line hundreds of thousands of characters long must not consume the entire allowance. */
export const READ_MAX_LINE_LENGTH = 2000;

/**
 * Maximum returned bytes from one command, **separately for stdout and stderr**.
 *
 * Without a limit, one grep through `node_modules` returned 3.9 MB. After that result entered
 * context, every subsequent model request failed with "requested 1443851 tokens", above the
 * 1048576 limit, until the execution unit was marked dead.
 *
 * This allowance is larger than search output: compiler diagnostics and test results guide
 * subsequent work, whereas search primarily locates relevant files and need not return hundreds
 * of matches at once.
 */
export const SH_MAX_BYTES = 50 * 1024;

/** A tool: model-facing metadata plus its implementation function. */
export interface Tool {
  name: string;
  /** Model-facing description. */
  does: string;
  /** Model-facing parameter schema. */
  params: Record<string, unknown>;
  /** Model-facing result schema. */
  output: Record<string, unknown>;
  /** Usage instructions added to the system prompt. Unlike `does`, this explains how to use the tool correctly. */
  prompt: string;
  /** Whether the tool may execute concurrently with others. */
  concurrent: boolean;
  /**
   * Result category, referencing `msg_part.name`. **Context compression uses it to decide what to discard.**
   *
   * - `look`: state that **can be retrieved again and may become stale**. A file read records an
   *   earlier file version; retaining it after edits can mislead the model more than removing it.
   * - `event`: **irrecoverable observations**, such as a four-minute test run or a verdict.
   * - `receipt`: a small accounting record confirming an operation completed, typically tens of bytes.
   * - `recall`: **retrieved context from this same conversation**, such as its tree or another node.
   *   Discard it at every compression level because the database already stores it; retaining it
   *   would nest one node's summary inside another.
   *
   * Default to `event`. Misclassifying irrecoverable information as retrievable is the costly error.
   */
  gives: string;
  /** Expected duration; exceeding it marks the invocation dead. */
  expectMs: number;
  /**
   * When the tool is offered to the model. **Omitted means universally available without conditions**,
   * as with the basic file tools.
   *
   * Supplied conditions become `trigger` rows and remove the tool from the unconditional system-tool
   * category. Require all conditions within a group and any matching group, just as with externally
   * declared tools. Bundled tools do not get a separate kernel path.
   */
  when?: { dim: string; key: string; op: string; value: string }[][];
  run(args: Record<string, unknown>): Promise<unknown>;
}

/**
 * Parameter schema. **`tool.params` must contain actual JSON Schema**. Providers validate it and
 * return 400 for invalid structure; otherwise that problem appears only during a real model call.
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
  does:
    "Read a UTF-8 text file and return its lines, numbered, whole - nothing is shortened. " +
    `A range bigger than about ${TOOL_POOL_TOKENS} tokens is refused instead, and the refusal says how many lines the file has, so offset and limit can name a smaller range.`,
  params: schema(
    {
      file_path: { type: "string", description: "Path to read." },
      offset: { type: "number", description: "1-based first line to return. Defaults to 1." },
      limit: { type: "number", description: "How many lines to return. Defaults to all of them from offset on." },
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
      bytes: { type: "integer", description: "How big the range asked for is" },
      error: { type: "string", description: "Present when the range was too big to return; nothing was read" },
    },
  },
  prompt:
    `Lines come back whole and numbered. This is the one tool that returns everything it was asked for: a range over ${TOOL_POOL_BYTES} bytes ` +
    "is refused rather than shortened, and the refusal carries the file's line count.",
  concurrent: true,
  gives: "look",
  expectMs: 30_000,
  async run(args) {
    const path = str(args, "file_path");
    const offset = Math.max(1, Math.trunc(num(args, "offset", 1)));
    const limit = Math.max(1, Math.trunc(num(args, "limit", Number.MAX_SAFE_INTEGER)));

    // **Do not even read files larger than the allowance.** Reading hundreds of megabytes before
    // reporting "too large" has already incurred the cost. Check `stat` first.
    const size = (await stat(path)).size;
    if (size > TOOL_POOL_BYTES && !("limit" in args)) {
      return {
        path,
        bytes: size,
        error: `this file is ${size} bytes, over the ${TOOL_POOL_BYTES} one call may return; ask for a range with offset and limit`,
      };
    }

    const text = await readFile(path, "utf8");
    const all = text.split(/\r?\n/);
    // A trailing newline creates an empty split segment, not an additional line.
    if (all.length > 1 && all[all.length - 1] === "") all.pop();

    const want = all.slice(offset - 1, offset - 1 + limit);
    // Count the exact requested output, including line numbers and newlines because they are returned too.
    const bytes = want.reduce((n, t) => n + Buffer.byteLength(t, "utf8") + 12, 0);
    // **Return no lines on rejection**, never a partial file that appears complete. Such truncation
    // may be discovered only after an incorrect edit.
    if (bytes > TOOL_POOL_BYTES) {
      return {
        path,
        totalLines: all.length,
        bytes,
        error:
          `lines ${offset}-${offset + want.length - 1} are ${bytes} bytes, over the ${TOOL_POOL_BYTES} one call may return; ` +
          `this file has ${all.length} lines - ask for fewer with offset and limit`,
      };
    }
    return {
      path,
      offset,
      lines: want.map((t, i) => ({ number: offset + i, text: t })),
      totalLines: all.length,
      bytes,
    };
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
  prompt: "An existing file is overwritten in full.",
  concurrent: false,
  gives: "receipt",
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
  prompt: "",
  concurrent: false,
  gives: "receipt",
  expectMs: 30_000,
  async run(args) {
    const path = str(args, "file_path");
    const oldStr = str(args, "old_string");
    const newStr = str(args, "new_string", false);
    const replaceAll = Boolean(args.replace_all ?? false);

    // These three constraints cannot be expressed by the schema; failing to enforce any of them permits a silent no-op edit.
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

/**
 * Maximum files visited and elapsed time during traversal.
 *
 * **Someone must actually stop work at the deadline.** `expectMs` tells the kernel when to
 * abandon a unit but does not stop its tool. An observed `grep -rln … /` kept a full container
 * CPU busy for 50 minutes even though the tool had already reported timeout.
 *
 * Output limits stop traversal after enough matches, but **with no matches the full allowance
 * remains unused**, so a search starting at `/` could continue indefinitely. These two limits
 * bound that case.
 */
const WALK_MAX_FILES = 20_000;
const WALK_MS = 20_000;

export const glob: Tool = {
  name: "glob",
  does:
    "Find files whose paths match a glob pattern. Returns matching file paths — never directories — " +
    "including hidden files (VCS metadata directories are excluded), newest first among the ones it gathered. " +
    `It stops as soon as what it has gathered reaches about ${TOOL_POOL_TOKENS} tokens, and says so in truncated.`,
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
  prompt: "",
  concurrent: true,
  gives: "look",
  expectMs: 60_000,
  async run(args) {
    const pattern = str(args, "pattern");
    const root = resolve(str(args, "path", false) || ".");
    // Match separator-free patterns against basename, following dsh's convention. Otherwise
    // "*.ts" would match only top-level files despite the caller expecting the entire tree.
    const onBase = !pattern.includes("/");
    const re = globToRegExp(pattern);

    const found: { path: string; mtimeMs: number }[] = [];
    let left = TOOL_POOL_BYTES;
    let full = false;
    const cut = await walk(root, async (file, st) => {
      const rel = relative(root, file).split(sep).join("/");
      if (!re.test(onBase ? rel.slice(rel.lastIndexOf("/") + 1) : rel)) return;
      const cost = Buffer.byteLength(file, "utf8") + 3;
      if (cost > left) {
        full = true;
        return "stop";
      }
      left -= cost;
      found.push({ path: file, mtimeMs: st.mtimeMs });
    });
    // "Newest first" sorts **only collected results**, not the newest files in the entire tree.
    // Traversal stops when full, leaving later files unexamined.
    found.sort((a, b) => b.mtimeMs - a.mtimeMs);
    return { files: found.map((f) => f.path), truncated: cut || full };
  },
};

/** Convert glob syntax to regex: `**` crosses directories, `*` does not, `?` matches one character, and `{a,b}` selects either alternative. */
export function globToRegExp(pattern: string): RegExp {
  let out = "";
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i];
    if (c === "*") {
      if (pattern[i + 1] === "*") {
        // `**/` must also match zero directories so "**/*.ts" includes top-level files.
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

/**
 * Traverse a directory tree. **Return true if traversal stopped before completion**, because
 * of a limit or the caller's request.
 *
 * Stop immediately when `hit` returns `"stop"`. The old implementation continued walking the
 * whole tree after grep had enough results, doing work that could produce no further output.
 */
async function walk(
  dir: string,
  hit: (file: string, st: { mtimeMs: number }) => Promise<void | "stop">,
  budget: { files: number; until: number } = { files: WALK_MAX_FILES, until: Date.now() + WALK_MS },
): Promise<boolean> {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return false; // Skip unreadable directories rather than failing the entire search on one permission error.
  }
  for (const e of entries) {
    if (budget.files <= 0 || Date.now() > budget.until) return true;
    const p = join(dir, e.name);
    if (e.isDirectory()) {
      if (SKIP.has(e.name)) continue;
      if (await walk(p, hit, budget)) return true;
    } else if (e.isFile()) {
      budget.files--;
      try {
        if ((await hit(p, await stat(p))) === "stop") return true;
      } catch {
        /* Ignore files that disappear during traversal. */
      }
    }
  }
  return false;
}

// ── grep ────────────────────────────────────────────────────────────────────

export const grep: Tool = {
  name: "grep",
  does:
    "Search file contents with a regular expression. Returns matching lines with line numbers. " +
    `It stops as soon as what it has gathered reaches about ${TOOL_POOL_TOKENS} tokens, and says so in truncated; the matches it does return are whole. ` +
    "Use read on a matched file for context.",
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
  prompt: "",
  concurrent: true,
  gives: "look",
  expectMs: 60_000,
  async run(args) {
    const re = new RegExp(str(args, "pattern"));
    const target = resolve(str(args, "path", false) || ".");
    const include = str(args, "include", false);
    const inc = include ? globToRegExp(include) : null;

    const matches: { path: string; line: number; text: string }[] = [];
    let truncated = false;
    // Charge the allowance for **the actual returned payload**: path, line number, and matched text.
    let left = TOOL_POOL_BYTES;

    const scan = async (file: string): Promise<void | "stop"> => {
      if (left <= 0) return "stop";
      if (inc && !inc.test(file.slice(file.lastIndexOf(sep) + 1))) return;
      let text: string;
      try {
        text = await readFile(file, "utf8");
      } catch {
        return; // Skip binary or unreadable files.
      }
      const lines = text.split(/\r?\n/);
      for (let i = 0; i < lines.length; i++) {
        if (!re.test(lines[i])) continue;
        const t = lines[i];
        const one = { path: file, line: i + 1, text: t.length > READ_MAX_LINE_LENGTH ? t.slice(0, READ_MAX_LINE_LENGTH) + "…" : t };
        // Add one byte for the comma separating this element from the previous one. The allowance
        // covers **the actual serialized JSON**, and omitting hundreds of commas can cross the limit.
        const cost = Buffer.byteLength(JSON.stringify(one), "utf8") + 1;
        // **Stop immediately when a result cannot fit**; do not insert a partial result.
        if (cost > left) {
          truncated = true;
          return "stop";
        }
        left -= cost;
        matches.push(one);
      }
    };

    const st = await stat(target);
    if (st.isFile()) await scan(target);
    else if (await walk(target, async (f) => await scan(f))) truncated = true;
    return { matches, truncated };
  },
};

// ── bash ────────────────────────────────────────────────────────────────────

export const bash: Tool = {
  name: "bash",
  does: "Run a shell command and return its stdout, stderr and exit code.",
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
    `stdout and stderr each come back whole up to ${SH_MAX_BYTES} bytes. Past that the middle is cut out and a line in its place says how many bytes went.`,
  concurrent: false,
  gives: "event",
  expectMs: 130_000,
  async run(args) {
    const command = str(args, "command");
    const cwd = str(args, "cwd", false) || undefined;
    const timeoutMs = num(args, "timeout_ms", 120_000);
    return await sh(command, cwd, timeoutMs);
  },
};

/**
 * Select a PowerShell executable on Windows.
 *
 * Prefer `pwsh` (7+): Windows PowerShell 5.1 treats `&&` and `||` as syntax errors, while models
 * commonly use them. Probe once and cache the result instead of probing for every command.
 */
let PWSH: string | null = null;
function pwsh(): string {
  if (PWSH === null) {
    const r = spawnSync("pwsh.exe", ["-NoProfile", "-Command", "$PSVersionTable.PSVersion.Major"], { windowsHide: true });
    PWSH = r.status === 0 ? "pwsh.exe" : "powershell.exe";
  }
  return PWSH;
}

/**
 * When output exceeds its limit, **remove the middle**, retaining both ends and reporting how
 * much was omitted.
 *
 * Command output often contains the decisive diagnostic at the end: a failed assertion or the
 * message before `exit 1`. Keeping only the beginning would discard that important information.
 */
function cut(s: string): string {
  const bytes = Buffer.byteLength(s, "utf8");
  if (bytes <= SH_MAX_BYTES) return s;
  const half = Math.floor(SH_MAX_BYTES / 2);
  const buf = Buffer.from(s, "utf8");
  // A byte boundary may split one multibyte character, which `toString` replaces with a replacement
  // character. That single-character loss does not justify another processing layer.
  const head = buf.subarray(0, half).toString("utf8");
  const tail = buf.subarray(bytes - half).toString("utf8");
  return `${head}\n... (${bytes - SH_MAX_BYTES} more bytes cut from the middle of this output)\n${tail}`;
}

/**
 * Stop a command together with all work it spawned.
 *
 * POSIX process-group ids equal the leader's pid; `kill(-pid)` signals the whole group.
 * Windows uses `taskkill /T` to include descendants instead.
 */
function stop(p: { pid?: number; kill: (sig?: NodeJS.Signals) => boolean }): void {
  const pid = p.pid;
  if (pid === undefined) return;
  try {
    if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(pid), "/T", "/F"], { windowsHide: true });
    else process.kill(-pid, "SIGKILL");
  } catch {
    // The process or group leader may already be gone. Try terminating the process itself and ignore failure.
    try {
      p.kill("SIGKILL");
    } catch {
      /* Already exited. */
    }
  }
}

/** Execute a command. **Always impose a timeout**, or a non-returning command can block the entire execution location. */
export function sh(
  command: string,
  cwd: string | undefined,
  timeoutMs: number,
): Promise<{ code: number; stdout: string; stderr: string; timedOut: boolean }> {
  return new Promise((done) => {
    // On Windows, passing command text directly to cmd uses the console code page, commonly GBK
    // on Chinese systems. Chinese input and output can become corrupted without errors.
    // PowerShell -EncodedCommand accepts UTF-16 base64, bypassing the input code page; explicitly
    // set UTF-8 output encoding to preserve the return path too.
    const win = process.platform === "win32";
    // On POSIX, `detached` creates a process group so timeout can terminate **all descendants**.
    // Otherwise `p.kill()` kills only the shell; children such as `grep -r /` are adopted by init
    // and continue. In one observation, six containers each consumed a full core for up to
    // 50 minutes after the tools had already reported timeouts.
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
      : spawn(command, { shell: true, cwd, windowsHide: true, detached: true });
    const p = spawned;
    let out = "";
    let err = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      stop(p);
    }, timeoutMs);
    p.stdout.on("data", (d: Buffer) => (out += d.toString()));
    p.stderr.on("data", (d: Buffer) => (err += d.toString()));
    p.on("close", (code) => {
      clearTimeout(timer);
      done({ code: code ?? -1, stdout: cut(out), stderr: cut(err), timedOut });
    });
    p.on("error", (e) => {
      clearTimeout(timer);
      done({ code: -1, stdout: cut(out), stderr: String(e), timedOut });
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

/** All basic tools. **The kernel does not know this list**; it reads the `tool` table. */
/**
 * **Offer no tools at the submission station except submission itself.**
 *
 * Only action stations execute tools. Submission is a model station followed by another model
 * station, so other requested calls would remain unexecuted until completion repair adds failure
 * results. Submission itself only needs the answer in the `submit` call.
 *
 * Attach this as a condition to each tool rather than teaching the kernel which station is
 * submission. **The data determines availability**; changing a tool's row can make it available there.
 */
const NOT_AT_HAND_IN = [[{ dim: "cycle", key: "cycle", op: "ne", value: "submit" }]];

export const TOOLS: Tool[] = [read, write, edit, glob, grep, bash, python].map((t) => ({
  ...t,
  when: t.when ?? NOT_AT_HAND_IN,
}));
