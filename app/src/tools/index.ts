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

/**
 * **一次搜索最多往回带多少。** 一个池子，装满就当场中断，回一个「截断了」的结果。
 *
 * 不压缩、不摘要：带回来的每一条都是原样的，只是到点不再往下走。压缩是拿真东西
 * 换一个看起来完整的假象，而这两件工具的用处正是「看见真的那几行」。
 *
 * 按 token 定量（5000），换算成字节按 4 —— 量过一道题的整份上下文，4234989 字节
 * 对模型报的 1033906 token。
 *
 * `read` 不用这个池子截断，它**先算再决定**：一次要的范围超了就整个拒掉，一行都
 * 不给。给半份的话它读到的是一个看着完整的残缺文件，而那种错要等到改坏了才看得出来。
 */
export const TOOL_POOL_TOKENS = 5_000;
export const TOOL_POOL_BYTES = TOOL_POOL_TOKENS * 4;

/** grep 的一条命中里，正文最多留多少字符。一行几十万字符的话，一条就把池子吃光了。 */
export const READ_MAX_LINE_LENGTH = 2000;

/**
 * 一条命令的输出最多带回多少字节，**stdout 和 stderr 各算一份**。
 *
 * 没有上限的时候实测过一次：`grep` 扫进 `node_modules`，一次返回 3.9 MB，
 * 那一条落进上下文之后这道题再也发不出去 ——「requested 1443851 tokens」，
 * 而模型的上限是 1048576。之后每一站都是同一句，直到这一站被判死。
 *
 * 比搜索那个池子松：一条命令的输出（编译报错、测试结果）是它接着往下走的依据，
 * 而搜索是拿来定位的，定位不需要一次看两百条。
 */
export const SH_MAX_BYTES = 50 * 1024;

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
  /**
   * 它的返回是哪一类东西 → `msg_part.name`。**压上下文的时候按这个决定丢什么。**
   *
   * - `look` 状态：**再看一眼就有，而且会过期**。读到的是文件当时的样子，同一个文件
   *   后来被改过的话，留着那一份比丢了还糟 —— 模型照着一段已经不成立的内容往下推
   * - `event` 事件：**拿不回来了**。跑了四分钟的测试、一次判决，丢了就是丢了
   * - `receipt` 回执：「这件事办成了」的一行账，几十个字节
   * - `recall` 回放：**把这次对话自己的上下文读回来**（那棵树、另一个节点）。压的时候
   *   哪一级都丢：库里本来就有，留着等于在一个节点的摘要里夹着另一个节点的摘要
   *
   * 不填 = `event`。把拿不回来的当成能再拿一次，是唯一赔不起的那个方向。
   */
  gives: string;
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

    // **文件比池子还大的时候连读都不读。** 一个几百兆的文件读进内存再回一句「太大了」，
    // 那句话本身没错，代价却已经付掉了。这一层只看 `stat`。
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
    // 末尾的换行会切出一个空段，那不是一行。
    if (all.length > 1 && all[all.length - 1] === "") all.pop();

    const want = all.slice(offset - 1, offset - 1 + limit);
    // 要多少算多少 —— 行号和换行也在这份账里，因为它们也要出现在返回里。
    const bytes = want.reduce((n, t) => n + Buffer.byteLength(t, "utf8") + 12, 0);
    // **拒了就一行都不给**，不给半份。给半份的话它读到的是一个看着完整的残缺文件，
    // 而那种错要等到改坏了才看得出来。
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

/**
 * 走树最多看几个文件、最多走多久。
 *
 * **期限得有人去停，不能只记在账上。** `expectMs` 是内核放弃这一站的时刻，工具
 * 自己不会因此停下 —— 实测过一条 `grep -rln … /` 从根目录扫起，工具那边早就交回
 * 「超时」了，活还在容器里烧着，50 分钟一直占着一整个核。
 *
 * 池子满了会中断，可**一次命中都没有的时候池子一直是满的** —— 从 `/` 走起，那就
 * 一直走。这两道闸管的是那种。
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
    // 没有分隔符的式子按 basename 比 —— 这条是 dsh 的约定，抄过来的：
    // 不这么定的话 "*.ts" 只匹配顶层，而人写它的时候想的是整棵树。
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
    // **「最新的在前」是在收到的这些里面排**，不是整棵树里最新的那几个：装满就中断，
    // 后面还有什么根本没看过。
    found.sort((a, b) => b.mtimeMs - a.mtimeMs);
    return { files: found.map((f) => f.path), truncated: cut || full };
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

/**
 * 走一棵树。**回 true 表示没走完就停了** —— 上限到了，或者调用方说够了。
 *
 * `hit` 回 `"stop"` 就当场收工。之前那一版走不完不回话，于是 `grep` 命中够了
 * 之后接着把整棵树走完，走的那部分一条结果都不会多出来。
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
    return false; // 读不动的目录跳过，不让一个权限问题毁掉整次搜索
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
        /* 中途没了就算了 */
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
    // 池子按**真要带回去的那份**扣：一条命中的路径、行号、正文加起来多少字节。
    let left = TOOL_POOL_BYTES;

    const scan = async (file: string): Promise<void | "stop"> => {
      if (left <= 0) return "stop";
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
        const t = lines[i];
        const one = { path: file, line: i + 1, text: t.length > READ_MAX_LINE_LENGTH ? t.slice(0, READ_MAX_LINE_LENGTH) + "…" : t };
        // 加一是把它跟上一条之间那个逗号也算上 —— 池子量的是**真发出去的那串 JSON**，
        // 只按元素算的话，一百多条就差出一百多字节，刚好翻过线。
        const cost = Buffer.byteLength(JSON.stringify(one), "utf8") + 1;
        // **装不下就当场中断**，不塞半条进去。
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

/**
 * 输出超了就**掐掉中间**，两头留着，中间记一句掐了多少。
 *
 * 掐中间不掐尾巴：一条命令要紧的往往在最后几行（跑挂了的那条断言、`exit 1` 前
 * 那句话），只留开头的话，最要紧的那段正好是丢掉的那段。
 */
function cut(s: string): string {
  const bytes = Buffer.byteLength(s, "utf8");
  if (bytes <= SH_MAX_BYTES) return s;
  const half = Math.floor(SH_MAX_BYTES / 2);
  const buf = Buffer.from(s, "utf8");
  // 按字节切会把一个多字节字符劈成两半，`toString` 那儿变成一个替换符 —— 一个字
  // 的事，不值得为它多绕一层。
  const head = buf.subarray(0, half).toString("utf8");
  const tail = buf.subarray(bytes - half).toString("utf8");
  return `${head}\n... (${bytes - SH_MAX_BYTES} more bytes cut from the middle of this output)\n${tail}`;
}

/**
 * 把一条命令连同它起的活一起停掉。
 *
 * POSIX：进程组的号就是组长的 pid，`kill(-pid)` 送给整组。Windows 没有进程组这
 * 回事，用 `taskkill /T`（连着子孙一起）。
 */
function stop(p: { pid?: number; kill: (sig?: NodeJS.Signals) => boolean }): void {
  const pid = p.pid;
  if (pid === undefined) return;
  try {
    if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(pid), "/T", "/F"], { windowsHide: true });
    else process.kill(-pid, "SIGKILL");
  } catch {
    // 已经没了，或者组长不在了 —— 补一刀给它自己，杀不掉就算了
    try {
      p.kill("SIGKILL");
    } catch {
      /* 已经走了 */
    }
  }
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
    // POSIX 上 `detached` 让子进程自成一个进程组，超时那一下才杀得动**整组** ——
    // 不这么起的话 `p.kill()` 只送走那个 shell，它起的活（`grep -r /` 那种）被
    // init 收养接着跑。实测：六个容器各占一整个核，最久的一条烧了 50 分钟，而工具
    // 那边早就交回「超时」了。
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
