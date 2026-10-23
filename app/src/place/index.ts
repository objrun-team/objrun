/**
 * 在哪儿干 —— 转发层。
 *
 * **调用工具本质上是转发给那个位置上的运行时。** 建立连接的时候把运行时送过去、
 * 起起来；之后每次调用走 MCP。
 *
 * `local` 是特例：不用送，同进程直接调同一批工具。所以两条路的行为一样 ——
 * 装的是同一份实现。
 *
 * ## 位置就是一段命令前缀
 *
 * 「远程」在这儿没有第二种含义：`wsl -d X --` / `ssh box-7` / `docker exec -i c`
 * 都只是**套在运行时那条命令外面的前缀**。套完之后起个子进程、在 stdin/stdout
 * 上说 MCP —— 跟起一个本机的 MCP server 是同一件事。
 *
 * 所以这一层没有自己的协议：`ship` 把二进制送过去，`launch` 拼出命令，
 * 剩下的交给 `McpClient`。原先这儿有一个手写的 JSON 行客户端陪着运行时那套私有
 * 协议 —— 同一件事两份实现，而且那一份别人用不了。删了。
 *
 * ## 位置串怎么读
 *
 * ```
 * local
 * wsl                        默认发行版
 * wsl:Ubuntu-24.04           指定发行版
 * ssh://box-7
 * wsl/docker:build-01        WSL 里的容器
 * ssh://box-7/docker:build-01
 * ```
 *
 * ## 「怎么到那个位置」是一条句柄，不是编译进来的
 *
 * 这个文件里的 `hops` / `launch` / `ship` 认得的是一个**封闭集合**：`wsl` /
 * `ssh` / `docker`，命令怎么拼也写死在里头。那套在「一台机器一个样」面前不够用
 * —— snap 装的 docker 只在登录 shell 的 PATH 上、送进去的路径它够不着、嵌套位置
 * 得一跳一跳接力送，这些全是**那台机器的性质**，不是位置这个概念的性质。
 *
 * 所以它跟工具、跟 G 的节点、跟推断函数一样，落成一条句柄（`registerPlace`）：
 * `workplace.identity` 指到哪儿，转发就由谁来办。这个文件提供的是**其中一条**
 * （`fn:place.hops`），不是唯一一条。

 * ## 连上没连上，不进库
 *
 * `workplace.usable` 是**登记**，不是探活。远端断没断、容器还在不在，是活状态 ——
 * 每次现探，不写回库。写回去的话，崩了重启读到的那一列就是过期的谎话。
 */

import { spawn } from "node:child_process";

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { McpClient } from "../mcp/client.ts";
import { TOOLS } from "../tools/index.ts";

/** 一个能接工具调用的位置。 */
export interface Place {
  place: string;
  /** 转发一次工具调用。 */
  call(tool: string, args: Record<string, unknown>): Promise<unknown>;
  /** 现探一下还通不通。**不写回库。** */
  alive(): Promise<boolean>;
  close(): void;
}

// ── local：不用送，同进程调 ──────────────────────────────────────────────────

const local = new Map(TOOLS.map((t) => [t.name, t]));

export function openLocal(): Place {
  return {
    place: "local",
    async call(tool, args) {
      const t = local.get(tool);
      if (!t) throw new Error(`this machine has no tool named ${tool}`);
      return await t.run(args);
    },
    async alive() {
      return true;
    },
    close() {},
  };
}

// ── 位置串 → 一条能把运行时跑起来的命令 ─────────────────────────────────────

export interface Hop {
  kind: "wsl" | "ssh" | "docker";
  arg: string;
}

/** 把位置串拆成一层层的跳板。**认不得的写法当场炸** —— 猜的话会连到别的地方去。 */
export function hops(place: string): Hop[] {
  if (place === "local") return [];
  // `ssh://host` 里的 `//` 会被切出空段，先把它抹平成 `ssh:host`。
  return place.replace("://", ":").split("/").map((seg) => {
    if (seg === "wsl") return { kind: "wsl", arg: "" } as Hop;
    if (seg.startsWith("wsl:")) return { kind: "wsl", arg: seg.slice(4) } as Hop;
    if (seg.startsWith("ssh:")) return { kind: "ssh", arg: seg.slice(4) } as Hop;
    if (seg.startsWith("docker:")) return { kind: "docker", arg: seg.slice(7) } as Hop;
    throw new Error(`unrecognised segment in the place string: ${seg} (whole string: ${place})`);
  });
}

/**
 * 一层层套出来的命令：外层负责把内层送进去。
 *
 * 出来的东西就是一个 MCP stdio server 的 `command` + `args` —— 你手写一条
 * `"command": "ssh", "args": ["box-7", "/tmp/…"]` 的声明，是同一件事。
 */
export function launch(place: string, remotePath: string): { cmd: string; argv: string[] } {
  const layers = hops(place);
  let argv: string[] = [remotePath];
  for (const h of [...layers].reverse()) {
    if (h.kind === "docker") argv = ["docker", "exec", "-i", h.arg, ...argv];
    else if (h.kind === "ssh") argv = ["ssh", h.arg, ...argv];
    else argv = h.arg ? ["wsl.exe", "-d", h.arg, "--", ...argv] : ["wsl.exe", "--", ...argv];
  }
  return { cmd: argv[0], argv: argv.slice(1) };
}

/** 把本机的运行时文件送到那个位置上去，返回它在那边的路径。 */
export function ship(place: string, localFile: string, remotePath: string): { cmd: string; argv: string[] } {
  const layers = hops(place);
  const outer = layers[0];
  if (!outer) throw new Error("local needs no runtime shipped");
  if (outer.kind === "wsl") {
    // WSL 把 Windows 盘挂在 /mnt 下，所以「送」就是一次 cp。
    const mnt = "/mnt/" + localFile[0].toLowerCase() + localFile.slice(2).replace(/\\/g, "/");
    const inner = `cp '${mnt}' '${remotePath}' && chmod +x '${remotePath}'`;
    return outer.arg
      ? { cmd: "wsl.exe", argv: ["-d", outer.arg, "--", "sh", "-c", inner] }
      : { cmd: "wsl.exe", argv: ["--", "sh", "-c", inner] };
  }
  if (outer.kind === "ssh") return { cmd: "scp", argv: [localFile, `${outer.arg}:${remotePath}`] };
  return { cmd: "docker", argv: ["cp", localFile, `${outer.arg}:${remotePath}`] };
}

function run(cmd: string, argv: string[]): Promise<{ code: number; err: string }> {
  return new Promise((done) => {
    const p = spawn(cmd, argv, { windowsHide: true });
    let err = "";
    p.stderr?.on("data", (d: Buffer) => (err += d.toString()));
    p.on("close", (code) => done({ code: code ?? -1, err }));
    p.on("error", (e) => done({ code: -1, err: String(e) }));
  });
}

/**
 * 打开一个位置。
 *
 * `local` 直接回一个进程内的；别的先把运行时送过去，再当成一个 MCP stdio server
 * 起起来。`runtimeFile` 是本机那份运行时二进制的路径 —— 它登记在
 * `workplace.runtime`。
 */
export async function openPlace(place: string, runtimeFile?: string): Promise<Place> {
  if (place === "local") return openLocal();
  if (!runtimeFile) throw new Error(`${place} forwards, but workplace.runtime does not say what to ship`);

  const remotePath = `/tmp/tgengin-runtime-${Math.abs(hash(place))}`;
  const s = ship(place, runtimeFile, remotePath);
  const sent = await run(s.cmd, s.argv);
  if (sent.code !== 0) throw new Error(`failed to ship the runtime to ${place}: ${sent.err.trim() || "exit code " + sent.code}`);

  const l = launch(place, remotePath);
  const client = new McpClient(place, { command: l.cmd, args: l.argv });
  try {
    // 握手 + 问它有哪些工具。**起来了但不应答**跟没起来一样糟，得当场发现。
    await client.tools();
  } catch (e) {
    client.close();
    throw new Error(`the runtime on ${place} started but does not answer: ${e instanceof Error ? e.message : String(e)}`);
  }

  return {
    place,
    async call(tool, args) {
      return await client.call(tool, args);
    },
    async alive() {
      try {
        await client.tools();
        return true;
      } catch {
        return false;
      }
    },
    close() {
      client.close();
    },
  };
}

/** 位置串换一个稳定的短名，给远端文件名用。 */
function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return h;
}

// ── 位置也是一个句柄 ────────────────────────────────────────────────────────

/**
 * 开过的位置留着复用 —— 每次调用都重送一遍运行时的话，什么都别干了。
 *
 * **这个池子是内置那条实现的私产**，不是位置这个概念的性质。别的实现（一条
 * `http://` 边车、一个插件）自己管自己的连接，跟这儿无关。
 */
export class Places {
  #open = new Map<string, Promise<Place>>();
  #db: Conn;

  constructor(db: Conn) {
    this.#db = db;
  }

  /** 送什么过去，登记在 `workplace.runtime` 里 —— 不在代码里写死。 */
  #runtimeOf(place: string): string | undefined {
    const row = all(this.#db, `select runtime from workplace where place = ?`, [place])[0] as
      | { runtime: string | null }
      | undefined;
    return row?.runtime ?? undefined;
  }

  get(place: string): Promise<Place> {
    let p = this.#open.get(place);
    if (!p) {
      p = openPlace(place, this.#runtimeOf(place));
      this.#open.set(place, p);
      // 连不上就把这次的坑清掉，下次还能重试 —— 留着的话这个位置就永久废了
      p.catch(() => this.#open.delete(place));
    }
    return p;
  }

  closeAll(): void {
    for (const p of this.#open.values()) void p.then((x) => x.close()).catch(() => {});
    this.#open.clear();
  }
}

/** 内置那条转发实现的句柄名。`workplace.identity` 写这个 = 要老行为。 */
export const HOPS_HANDLE = "fn:place.hops";

/** 转发一次调用要多久算死。**一次工具调用，不是一次求解。** */
export const PLACE_EXPECT_MS = 120_000;

/**
 * 一次转发请求 —— **位置句柄收到的就是这个形状**。
 *
 * `op` 两个动作，都归同一个句柄：`call` 转发一次工具调用，`ping` 探一次活。
 * 分成两个句柄的话，写自定义转发的人得实现两个契约，而这两件本来就是同一件事的
 * 两面：**够得着才转得过去**。
 */
export interface PlaceCall {
  /** 哪个位置。地址串怎么读，是这个句柄自己的事。 */
  place: string;
  op: "call" | "ping";
  /** `op: "call"` 时：转发哪件工具。 */
  tool?: string;
  /** `op: "call"` 时：那件工具的参数。 */
  args?: Record<string, unknown>;
}

/** `op: "ping"` 的回值。`call` 回的是那件工具自己的返回，这一层不解释。 */
export interface Pong {
  alive: boolean;
  why?: string;
}

/**
 * 把内置那条转发实现注册成句柄。
 *
 * **「怎么到那个位置」以前是编译进内核的**：`hops` 只认 `wsl` / `ssh` / `docker`
 * 三种，`launch` 和 `ship` 照那三种拼 argv。于是「这台机器上的 docker 装在 snap 里、
 * 只在登录 shell 的 PATH 上」这种**机器的性质**没地方安放，唯一的落点是改这三个函数。
 *
 * 现在它跟工具、跟 G 的节点、跟推断函数一样是一条句柄：`workplace.identity` 指到
 * 哪儿，转发就由谁来办。写这个名字 = 要老行为，一个字没变；写 `http://…` 或者一条
 * 带 `module` 的 `fn:` = 那台机器自己说了算，内核不用动。
 */
export function registerPlace(db: Conn, reg: Registry, places: Places): string {
  reg.register(db, HOPS_HANDLE, PLACE_EXPECT_MS, async (arg) => {
    const a = (arg ?? {}) as PlaceCall;
    const place = String(a.place ?? "");
    if (!place) throw new Error("a place call must say which place");

    if (a.op === "ping") {
      // **探活走池子里那条连接**，不另开一条：要问的就是「现在在用的这条还通不通」。
      // 另开一条问的是「还能不能再开一条」，那是另一个问题，而且要重送一遍运行时。
      try {
        return { alive: await (await places.get(place)).alive() } satisfies Pong;
      } catch (e) {
        return { alive: false, why: e instanceof Error ? e.message : String(e) } satisfies Pong;
      }
    }

    const tool = String(a.tool ?? "");
    if (!tool) throw new Error("a forwarded call must say which tool");
    return await (await places.get(place)).call(tool, a.args ?? {});
  });
  return HOPS_HANDLE;
}
