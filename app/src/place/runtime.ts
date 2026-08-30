/**
 * 运行时 —— **被送到那个位置上去跑的那个东西**。
 *
 * 它是一个 **MCP server**，说 stdio 上的 JSON-RPC：`initialize` → `tools/list`
 * → `tools/call`。装的就是 `../tools/` 那一批，跟本机同一份实现 —— 所以 `local`
 * 和转发出去的结果一样，不会出现「本机能跑、转过去行为不一样」。
 *
 * ## 为什么是 MCP 而不是自己定
 *
 * 「把二进制送到那台机器上、起起来、在 stdin/stdout 上一行一条 JSON 地对话」
 * 这件事，就是 MCP stdio。自己再定一套的话，同一件事有两份实现，而其中一份
 * 别人用不了 —— 而且真的出过：这个文件原先说的是 `{id,tool,args}`，
 * 引擎那边有一个手写的客户端专门陪它。
 *
 * 说 MCP 之后，这个二进制**任何 MCP 客户端都能用**，不只这台引擎。
 *
 * ## stdout 上只许有协议行
 *
 * 工具自己的输出是被捕获的（子进程的 stdout 不继承）。混进来一行，对面解析就
 * 错位，而那不报错，只是从某一刻起答非所问。日志一律写 stderr。
 */

import { TOOLS } from "../tools/index.ts";

const by = new Map(TOOLS.map((t) => [t.name, t]));

/** 一个工具翻成 MCP 的形状。字段名是 MCP 的。 */
const DEFS = TOOLS.map((t) => ({
  name: t.name,
  description: t.does,
  inputSchema: t.params,
  outputSchema: t.output,
}));

const PROTOCOL = "2026-07-28";

async function handle(m: { id?: number; method?: string; params?: unknown }): Promise<unknown | null> {
  const id = m.id;
  const reply = (result: unknown) => ({ jsonrpc: "2.0", id, result });

  if (m.method === "initialize") {
    return reply({
      protocolVersion: String((m.params as { protocolVersion?: string })?.protocolVersion ?? PROTOCOL),
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "tgengin-runtime", version: "1.0.0" },
    });
  }
  if (m.method?.startsWith("notifications/")) return null;
  if (m.method === "tools/list") return reply({ tools: DEFS });

  if (m.method === "tools/call") {
    const p = (m.params ?? {}) as { name?: string; arguments?: Record<string, unknown> };
    const t = by.get(String(p.name));
    // 没这个工具是**协议错**：调用方改参数也没用。
    if (!t) return { jsonrpc: "2.0", id, error: { code: -32602, message: `this runtime has no tool named ${String(p.name)}` } };
    try {
      const value = await t.run(p.arguments ?? {});
      return reply({
        content: [{ type: "text", text: JSON.stringify(value) }],
        ...(value !== null && typeof value === "object" ? { structuredContent: value } : {}),
      });
    } catch (e) {
      // 工具跑出来的错是**工具执行错**：当结果回，调用方（多半是个模型）看得见、
      // 能自己改。回协议错的话它只知道「失败了」。
      return reply({
        content: [{ type: "text", text: e instanceof Error ? e.message : String(e) }],
        isError: true,
      });
    }
  }

  return { jsonrpc: "2.0", id, error: { code: -32601, message: `unknown method: ${String(m.method)}` } };
}

let buf = "";
/** 还在跑的调用。**stdin 关了也得等它们走完** —— 不等的话答案就没了。 */
let inflight = 0;
let ended = false;

function bye(): void {
  if (ended && inflight === 0) process.exit(0);
}

process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk: string) => {
  buf += chunk;
  let nl = buf.indexOf("\n");
  while (nl !== -1) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (line) {
      inflight++;
      void (async () => {
        try {
          const out = await handle(JSON.parse(line) as { id?: number; method?: string });
          if (out !== null) process.stdout.write(JSON.stringify(out) + "\n");
        } catch (e) {
          process.stderr.write(`cannot parse this line: ${e instanceof Error ? e.message : String(e)}\n`);
        } finally {
          inflight--;
          bye();
        }
      })();
    }
    nl = buf.indexOf("\n");
  }
});
// 管道关了就收摊，但**先把在途的答完**。管道喂进来的最后一条多半是最慢的那条
// （比如一条 bash），直接 exit 的话它的答案永远出不来，而调用方只看到「没回」。
process.stdin.on("end", () => {
  ended = true;
  bye();
});
