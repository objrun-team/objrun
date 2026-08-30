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
 * ## 连上没连上，不进库
 *
 * `workplace.usable` 是**登记**，不是探活。远端断没断、容器还在不在，是活状态 ——
 * 每次现探，不写回库。写回去的话，崩了重启读到的那一列就是过期的谎话。
 */

import { spawn } from "node:child_process";

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

function openLocal(): Place {
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
