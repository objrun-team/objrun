/**
 * Execution locations and forwarding.
 *
 * **A tool call forwards to the runtime at its assigned place.** Establishing a connection
 * ships and starts that runtime; subsequent calls use MCP.
 *
 * `local` is the special case: directly call the same tools in-process without shipping them.
 * Both paths therefore use identical implementations and behavior.
 *
 * ## A location is a command prefix
 *
 * "Remote" has no additional meaning here. `wsl -d X --`, `ssh box-7`, and `docker exec -i c`
 * are simply **prefixes around the runtime command**. Launch the resulting subprocess and
 * speak MCP through stdin/stdout, just like a local MCP server.
 *
 * This layer has no separate protocol: `ship` transfers the binary, `launch` builds the command,
 * and `McpClient` handles communication. The old custom JSON-line client duplicated this work
 * and could not be reused by other clients; it has been removed.
 *
 * ## Location syntax
 *
 * ```
 * local
 * wsl                        default distribution
 * wsl:Ubuntu-24.04           selected distribution
 * ssh://box-7
 * wsl/docker:build-01        container inside WSL
 * ssh://box-7/docker:build-01
 * ```
 *
 * ## Reaching a place is a handle, not a compiled-in policy
 *
 * `hops` / `launch` / `ship` support a **closed set** of transports: `wsl`, `ssh`, and `docker`,
 * with fixed command construction. Machine-specific needs exceed that set: Docker installed
 * through snap may appear only in a login shell's PATH; shipped paths may be inaccessible;
 * nested destinations may need hop-by-hop transfer. These are **machine properties**, not
 * properties of execution locations in general.
 *
 * Forwarding is therefore a handle, like tools, G nodes, and inference functions. `registerPlace`
 * registers it, and `workplace.identity` selects the implementation. This file supplies **one**
 * implementation, `fn:place.hops`, rather than the only possible implementation.
 *
 * ## Connection liveness is not database state
 *
 * `workplace.usable` records configuration, not a health check. Remote connectivity and container
 * existence are live facts to probe on demand. Persisting them would leave stale claims after a crash.
 */

import { spawn } from "node:child_process";

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { McpClient } from "../mcp/client.ts";
import { TOOLS } from "../tools/index.ts";

/** A location capable of receiving tool calls. */
export interface Place {
  place: string;
  /** Forward one tool call. */
  call(tool: string, args: Record<string, unknown>): Promise<unknown>;
  /** Probe current connectivity. **Do not persist the result.** */
  alive(): Promise<boolean>;
  close(): void;
}

// ── local: direct in-process invocation, without shipping a runtime ──

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

// ── Location string → command that starts the runtime ──

export interface Hop {
  kind: "wsl" | "ssh" | "docker";
  arg: string;
}

/** Parse a location into transport hops. **Reject unknown syntax immediately** rather than guessing and connecting elsewhere. */
export function hops(place: string): Hop[] {
  if (place === "local") return [];
  // Normalize `ssh://host` to `ssh:host` before splitting, so `//` does not create empty segments.
  return place.replace("://", ":").split("/").map((seg) => {
    if (seg === "wsl") return { kind: "wsl", arg: "" } as Hop;
    if (seg.startsWith("wsl:")) return { kind: "wsl", arg: seg.slice(4) } as Hop;
    if (seg.startsWith("ssh:")) return { kind: "ssh", arg: seg.slice(4) } as Hop;
    if (seg.startsWith("docker:")) return { kind: "docker", arg: seg.slice(7) } as Hop;
    throw new Error(`unrecognised segment in the place string: ${seg} (whole string: ${place})`);
  });
}

/**
 * Build nested commands, with each outer layer transporting its inner command.
 *
 * The result is exactly the `command` + `args` of an MCP stdio server, equivalent to manually
 * declaring `"command": "ssh", "args": ["box-7", "/tmp/…"]`.
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

/** Transfer the local runtime file to the destination and return its remote path. */
export function ship(place: string, localFile: string, remotePath: string): { cmd: string; argv: string[] } {
  const layers = hops(place);
  const outer = layers[0];
  if (!outer) throw new Error("local needs no runtime shipped");
  if (outer.kind === "wsl") {
    // WSL mounts Windows drives under /mnt, so transfer is a simple cp.
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
 * Open an execution location.
 *
 * `local` immediately returns an in-process implementation. Other locations receive the runtime
 * and launch it as an MCP stdio server. `runtimeFile` is the local binary path registered in
 * `workplace.runtime`.
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
    // Handshake and list tools. **A started but unresponsive runtime** is as unusable as one that never started; detect it now.
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

/** Derive a stable short name from a location string for remote filenames. */
function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return h;
}

// ── Locations are handles too ──

/**
 * Reuse connections to opened places; shipping the runtime for every invocation would be impractical.
 *
 * **This pool belongs only to the built-in implementation**, not to the abstract concept of a place.
 * Other implementations, such as an HTTP sidecar or plugin, manage their own connections.
 */
export class Places {
  #open = new Map<string, Promise<Place>>();
  #db: Conn;

  constructor(db: Conn) {
    this.#db = db;
  }

  /** The runtime to transfer is registered in `workplace.runtime`, not hard-coded. */
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
      // Remove failed connection attempts from the pool so later calls can retry; retaining them would permanently disable the location.
      p.catch(() => this.#open.delete(place));
    }
    return p;
  }

  closeAll(): void {
    for (const p of this.#open.values()) void p.then((x) => x.close()).catch(() => {});
    this.#open.clear();
  }
}

/** Built-in forwarding handle name. Set `workplace.identity` to this to retain the original behavior. */
export const HOPS_HANDLE = "fn:place.hops";

/** Timeout for forwarding **one tool call, not an entire solve**. */
export const PLACE_EXPECT_MS = 120_000;

/**
 * Forwarding request: **the input contract of a location handle**.
 *
 * Two `op` values share one handle: `call` forwards a tool invocation, and `ping` probes liveness.
 * Separate handles would require custom forwarders to implement two contracts for one concern:
 * **a destination must be reachable for forwarding to work**.
 */
export interface PlaceCall {
  /** Target location. The handle defines how its address string is interpreted. */
  place: string;
  op: "call" | "ping";
  /** For `op: "call"`, the tool to forward. */
  tool?: string;
  /** For `op: "call"`, the tool arguments. */
  args?: Record<string, unknown>;
}

/** Result of `op: "ping"`. A call returns the tool's own result without interpretation by this layer. */
export interface Pong {
  alive: boolean;
  why?: string;
}

/**
 * Register the built-in forwarding implementation as a handle.
 *
 * **Transport logic was previously compiled into the kernel**: `hops` recognized only
 * `wsl` / `ssh` / `docker`, and `launch` / `ship` built their argv. Machine-specific properties,
 * such as snap-installed Docker existing only in a login shell's PATH, could be accommodated
 * only by editing those three functions.
 *
 * Now forwarding is a handle like tools, G nodes, and inference. `workplace.identity` selects
 * its implementation. The built-in name preserves behavior unchanged; an `http://…` endpoint
 * or a `fn:` with `module` supplies machine-specific behavior without kernel changes.
 */
export function registerPlace(db: Conn, reg: Registry, places: Places): string {
  reg.register(db, HOPS_HANDLE, PLACE_EXPECT_MS, async (arg) => {
    const a = (arg ?? {}) as PlaceCall;
    const place = String(a.place ?? "");
    if (!place) throw new Error("a place call must say which place");

    if (a.op === "ping") {
      // **Probe the pooled connection already in use**, rather than opening another one. The question
      // is whether the current connection works. A new connection would answer a different question
      // and unnecessarily ship the runtime again.
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
