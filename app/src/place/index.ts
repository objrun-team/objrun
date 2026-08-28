/**
 * 在哪儿干 —— 转发层。
 *
 * **调用工具本质上是转发给那个位置上的运行时。** 建立连接的时候把运行时送过去、
 * 起起来；之后每次调用发一行 JSON 过去，收一行回来。
 *
 * `local` 是特例：不用送，同进程直接调同一批工具。所以两条路的行为一样 ——
 * 装的是同一份实现。
 *
 * ## 位置串怎么读
 *
 * `workplace.place` 是**带层级的地址串**，一层一层套：
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

import { spawn, type ChildProcess } from "node:child_process";
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
      if (!t) throw new Error(`本机没有 ${tool} 这个工具`);
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
    throw new Error(`位置串不认得这一段：${seg}（整串是 ${place}）`);
  });
}

/** 一层层套出来的命令：外层负责把内层送进去。 */
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
  if (!outer) throw new Error("local 不用送运行时");
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

// ── 远端：送过去 + JSON 行转发 ───────────────────────────────────────────────

interface Waiting {
  ok(v: unknown): void;
  fail(e: Error): void;
}

class Remote implements Place {
  place: string;
  #p: ChildProcess;
  #buf = "";
  #id = 0;
  #waiting = new Map<number, Waiting>();
  #dead: Error | null = null;

  constructor(place: string, p: ChildProcess) {
    this.place = place;
    this.#p = p;
    p.stdout?.setEncoding("utf8");
    p.stdout?.on("data", (c: string) => this.#feed(c));
    p.on("exit", (code) => this.#die(new Error(`${place} 上的运行时退了（${code}）`)));
    p.on("error", (e) => this.#die(e));
  }

  #feed(chunk: string): void {
    this.#buf += chunk;
    let nl = this.#buf.indexOf("\n");
    while (nl !== -1) {
      const line = this.#buf.slice(0, nl);
      this.#buf = this.#buf.slice(nl + 1);
      if (line.trim() !== "") this.#take(line);
      nl = this.#buf.indexOf("\n");
    }
  }

  #take(line: string): void {
    let res: { id?: number; ok?: boolean; value?: unknown; error?: string };
    try {
      res = JSON.parse(line) as typeof res;
    } catch {
      // 协议行错位了。**当场炸整条连接** —— 从这一刻起所有回答都对不上号，
      // 继续下去只会答非所问，而那不报错。
      this.#die(new Error(`${this.place} 上的运行时吐了一行不是 JSON 的东西：${line.slice(0, 200)}`));
      return;
    }
    const w = this.#waiting.get(Number(res.id));
    if (!w) return;
    this.#waiting.delete(Number(res.id));
    if (res.ok) w.ok(res.value);
    else w.fail(new Error(res.error ?? "那边没说为什么"));
  }

  #die(e: Error): void {
    this.#dead = e;
    for (const w of this.#waiting.values()) w.fail(e);
    this.#waiting.clear();
  }

  call(tool: string, args: Record<string, unknown>): Promise<unknown> {
    if (this.#dead) return Promise.reject(this.#dead);
    const id = ++this.#id;
    return new Promise((ok, fail) => {
      this.#waiting.set(id, { ok, fail: (e) => fail(e) });
      this.#p.stdin?.write(JSON.stringify({ id, tool, args }) + "\n");
    });
  }

  async alive(): Promise<boolean> {
    if (this.#dead) return false;
    try {
      await this.call("ping", {});
      return true;
    } catch {
      return false;
    }
  }

  close(): void {
    this.#p.stdin?.end();
    this.#p.kill();
  }
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
 * `local` 直接回一个进程内的；别的先把运行时送过去，再把它起起来接管道。
 * `runtimeFile` 是本机那份运行时二进制的路径 —— 它登记在 `workplace.runtime`。
 */
export async function openPlace(place: string, runtimeFile?: string): Promise<Place> {
  if (place === "local") return openLocal();
  if (!runtimeFile) throw new Error(`${place} 要转发，但 workplace.runtime 没登记要送什么过去`);

  const remotePath = `/tmp/tgengin-runtime-${Math.abs(hash(place))}`;
  const s = ship(place, runtimeFile, remotePath);
  const sent = await run(s.cmd, s.argv);
  if (sent.code !== 0) throw new Error(`往 ${place} 送运行时失败：${sent.err.trim() || "退出码 " + sent.code}`);

  const l = launch(place, remotePath);
  const p = spawn(l.cmd, l.argv, { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  const r = new Remote(place, p);
  if (!(await r.alive())) throw new Error(`${place} 上的运行时起来了但不应答`);
  return r;
}

/** 位置串换一个稳定的短名，给远端文件名用。 */
function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return h;
}
