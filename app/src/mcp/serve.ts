/**
 * **This engine is itself an MCP server.**
 *
 * Otherwise integration would be one-way: external servers could connect, but nobody else
 * could use the kernel's own `read` / `write` / `edit` / `glob` / `grep` / `bash` tools.
 * That would isolate them rather than merely make them built-in.
 *
 * Exposing them allows:
 *
 * - Any MCP client, including another engine or Claude Desktop, to use these tools.
 * - Two engines to connect to each other as servers.
 * - Internal calls to continue directly through `fn:` without an HTTP round trip.
 *   Exposure is for external clients, not a change to internal invocation.
 *
 * Use standard MCP JSON-RPC: `initialize` → `tools/list` → `tools/call`.
 *
 * ## Which tools are exposed
 *
 * **Only locally implemented tools**, identified by `fn:` identities. Do not re-export tools
 * imported from another MCP server: that creates proxy loops when A connects to B and B to A,
 * making `tools/list` unbounded. Clients needing B's tools should connect directly to B.
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

/** Convert locally implemented tools to MCP definitions. */
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
    // Treat an empty object as an omitted outputSchema. MCP makes it optional; providing `{}`
    // would cause some clients to validate against it and reject every result.
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
      does: "This engine as an MCP server: JSON-RPC speaking initialize / tools/list / tools/call",
      why:
        "Without this, none of the tools the kernel implements itself are usable from outside - that is not built-in, that is shut in. " +
        "Once exposed there is no inside and outside: other MCP clients can use them, and two engines can talk to each other. " +
        "Only what this machine implements itself (`fn:`) is exposed; tools pulled in from other servers are not forwarded - that would be proxying, and it loops.",
      params: [
        { name: "jsonrpc", in: "body", kind: "string", required: true, only: ["2.0"], note: "Always 2.0" },
        { name: "id", in: "body", kind: "int", note: "Given for requests, omitted for notifications" },
        {
          name: "method",
          in: "body",
          kind: "string",
          required: true,
          only: ["initialize", "tools/list", "tools/call", "notifications/initialized"],
          note: "The MCP method name",
        },
        { name: "params", in: "body", kind: "object", note: "Arguments for that method. `tools/call` needs `{name, arguments}`" },
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
      errs: [{ code: 200, when: "Protocol-level errors also return 200 - a JSON-RPC error rides in the `error` field, not in the HTTP status" }],
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
          // An unknown tool is a **protocol error**, unlike invalid arguments that the model can correct.
          if (!row || !Number(row.usable) || !row.identity.startsWith("fn:")) {
            return { jsonrpc: "2.0", id, error: { code: -32602, message: `no such tool: ${name}` } };
          }
          try {
            const value = await reg.get(row.identity).call({
              args: p.arguments ?? {},
              // External calls have no task context and run locally. Forwarding through `workplace` is this
              // machine's decision, not caller-controlled; otherwise callers could target arbitrary locations.
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
            // Tool failures are **tool execution errors** returned as results, so callers, usually models,
            // can see the problem and correct it. A protocol error would say only that the call failed.
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

        return { jsonrpc: "2.0", id, error: { code: -32601, message: `unknown method: ${method}` } };
      },
    },
  ];
}
