/**
 * **这台引擎自己就是一个 MCP server。**
 *
 * 不然就成了单向的：外面的 server 能接进来，而内核自己实现的那几个工具
 * （`read` / `write` / `edit` / `glob` / `grep` / `bash`）外面一个都用不上。
 * 那不是「内置」，那是关起来了。
 *
 * 开出去之后内外就没有分别了：
 *
 * - 别的 MCP 客户端（另一台引擎、Claude Desktop、随便什么）都能用这几个工具
 * - 两台引擎可以互相接：A 把 B 当 server，B 也能把 A 当 server
 * - 内部照旧走 `fn:` 直接调，不绕一圈 HTTP —— 开出去是为了外面能用，
 *   不是为了自己用
 *
 * 说的是标准 MCP：`initialize` → `tools/list` → `tools/call`，JSON-RPC。
 *
 * ## 开出去的是哪些
 *
 * **只有这台机器自己实现的**（`identity` 是 `fn:` 的那些）。从别的 MCP server
 * 拉进来的不转发出去 —— 那是代理，而代理会绕圈：A 接了 B，B 又接了 A，
 * `tools/list` 就没有底了。要用 B 的工具，直接接 B。
 */

import type { Registry } from "../engine/registry.ts";
import type { Store } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import type { Route } from "../api/spec.ts";

const PROTOCOL = "2026-07-28";

interface Row {
  name: string;
  identity: string;
  does: string;
  params: string;
  output: string;
  usable: number;
}

/** 这台机器自己实现的工具，翻成 MCP 的形状。 */
function tools(store: Store) {
  const rows = all(
    store.ro,
    `select name, identity, does, params, output, usable from tool
      where identity like 'fn:%' and usable = 1 order by name`,
  ) as unknown as Row[];
  return rows.map((r) => ({
    name: r.name,
    description: r.does,
    inputSchema: json(r.params, { type: "object" }),
    outputSchema: json(r.output, undefined),
  }));
}

function json(s: string, fallback: unknown): unknown {
  try {
    const v = JSON.parse(s) as unknown;
    // 空对象当成「没给」—— MCP 那边 outputSchema 是可选的，给个 `{}` 反而
    // 会让客户端拿它去校验，然后什么都通不过。
    return v && typeof v === "object" && Object.keys(v).length === 0 ? fallback : v;
  } catch {
    return fallback;
  }
}

export function mcpServeRoutes(store: Store, reg: Registry): Route[] {
  return [
    {
      method: "POST",
      path: "/mcp",
      group: "MCP",
      does: "这台引擎自己的 MCP server：JSON-RPC，说 initialize / tools/list / tools/call",
      why:
        "**不开出去的话，内核自己实现的那几个工具外面一个都用不上** —— 那不是内置，是关起来了。" +
        "开出去之后内外没有分别：别的 MCP 客户端能用它们，两台引擎也能互相接。" +
        "只开这台机器自己实现的（`fn:`），从别的 server 拉进来的不转发 —— 那是代理，会绕圈。",
      params: [
        { name: "jsonrpc", in: "body", kind: "string", required: true, only: ["2.0"], note: "固定 2.0" },
        { name: "id", in: "body", kind: "int", note: "请求给，通知不给" },
        {
          name: "method",
          in: "body",
          kind: "string",
          required: true,
          only: ["initialize", "tools/list", "tools/call", "notifications/initialized"],
          note: "MCP 的方法名",
        },
        { name: "params", in: "body", kind: "object", note: "那个方法的参数。`tools/call` 要 `{name, arguments}`" },
      ],
      returns: {
        jsonrpc: "2.0",
        id: 1,
        result: {
          tools: [
            {
              name: "read",
              description: "Read a UTF-8 text file and return line-numbered content.",
              inputSchema: { type: "object", properties: { file_path: { type: "string" } } },
            },
          ],
        },
      },
      errs: [{ code: 200, when: "**协议里的错也回 200** —— JSON-RPC 的错在 `error` 那一项里，不是 HTTP 状态码" }],
      handler: async (a, _req, reply) => {
        const id = a.id as number | undefined;
        const method = String(a.method);
        const p = (a.params ?? {}) as Record<string, unknown>;

        if (method === "notifications/initialized") return reply.code(202).send();

        if (method === "initialize") {
          return {
            jsonrpc: "2.0",
            id,
            result: {
              protocolVersion: String(p.protocolVersion ?? PROTOCOL),
              capabilities: { tools: { listChanged: false } },
              serverInfo: { name: "tgengin", version: "1.0.0" },
            },
          };
        }

        if (method === "tools/list") return { jsonrpc: "2.0", id, result: { tools: tools(store) } };

        if (method === "tools/call") {
          const name = String(p.name ?? "");
          const row = all(store.ro, `select identity, usable from tool where name = ?`, [name])[0] as
            | { identity: string; usable: number }
            | undefined;
          // **没这个工具是协议错**（模型改不了），跟「参数不合理」不是一回事。
          if (!row || !Number(row.usable) || !row.identity.startsWith("fn:")) {
            return { jsonrpc: "2.0", id, error: { code: -32602, message: `没有这个工具：${name}` } };
          }
          try {
            const value = await reg.get(row.identity).call({
              args: p.arguments ?? {},
              // 外面调进来没有任务上下文，就在本机跑。要转发到别处是这台机器
              // 自己的事（`workplace`），不由调用方指定 —— 不然谁都能指到别处去。
              place: "local",
            });
            return {
              jsonrpc: "2.0",
              id,
              result: {
                content: [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value) }],
                ...(value !== null && typeof value === "object" ? { structuredContent: value } : {}),
              },
            };
          } catch (e) {
            // 工具跑出来的错是**工具执行错**：当结果回，让调用方（多半是个模型）
            // 看得见、能自己改。回协议错的话它只知道「失败了」。
            return {
              jsonrpc: "2.0",
              id,
              result: {
                content: [{ type: "text", text: e instanceof Error ? e.message : String(e) }],
                isError: true,
              },
            };
          }
        }

        return { jsonrpc: "2.0", id, error: { code: -32601, message: `不认得这个方法：${method}` } };
      },
    },
  ];
}
