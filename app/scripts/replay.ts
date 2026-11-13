/**
 * Replay the reconstructed request **unchanged** to reproduce `Failed to process successful response`.
 *
 * Use the same provider, tools, toolChoice, and sampling parameters as the kernel.
 * Two differences are **intentional**:
 *
 * - `maxRetries: 0`: inspect the actual first response, not the outcome after retries.
 * - Print the entire `cause` chain. The kernel logged only the outer message, hiding the underlying cause.
 */
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { generateText, dynamicTool, jsonSchema, type ModelMessage } from "ai";
import { Database } from "bun:sqlite";

const S = "C:/Users/Administrator/AppData/Local/Temp/claude/E--sgu-bzhc-EACN-EX/4d80947c-9048-4447-b332-39e823f83cb3/scratchpad";
const j = JSON.parse(await Bun.file(`${S}/req286.clean.json`).text()) as {
  instructions?: string;
  messages: ModelMessage[];
};

const db = new Database("E:/sgu-bzhc/EACN_EX/TgEngin/data/h2h.sqlite", { readonly: true });
const t = db.query(`select name, does, params from tool where name = 'submit'`).get() as {
  name: string; does: string; params: string;
};
const api = db.query(`select base_url, model from api where model = 'deepseek-v4-flash'`).get() as {
  base_url: string; model: string;
};

const key = (await Bun.file("E:/sgu-bzhc/EACN_EX/TgEngin/.env").text())
  .split("\n").find((l) => l.startsWith("DEEPSEEK_API_KEY"))!.split("=")[1].trim().replace(/^"|"$/g, "");

/**
 * The submission station requires a specific tool, so **disable thinking**.
 *
 * The kernel uses `effort = u.mustCall ? "none" : knobs.reasoningEffort`. Since `"none"` is truthy,
 * it still calls `withExtra` to add `reasoning_effort: "none"` to the body. The first replay omitted
 * this step and immediately received a 400: `Thinking mode does not support this tool_choice`.
 * Omitting even one field means this is no longer the same request.
 */
const withExtra = (extra: Record<string, unknown>) => {
  const wrapped = async (input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
    if (init?.body && typeof init.body === "string") {
      init = { ...init, body: JSON.stringify({ ...(JSON.parse(init.body) as object), ...extra }) };
    }
    return await fetch(input, init);
  };
  return Object.assign(wrapped, { preconnect: fetch.preconnect.bind(fetch) });
};

const provider = createOpenAICompatible({
  name: "deepseek",
  baseURL: api.base_url,
  apiKey: key,
  fetch: withExtra({ reasoning_effort: "none" }),
});
const tools = {
  submit: dynamicTool({ description: t.does, inputSchema: jsonSchema(JSON.parse(t.params) as never) }),
};

const bytes = Buffer.byteLength(JSON.stringify(j.messages), "utf8");
console.log(`sending ${String(j.messages.length)} messages, ${String(Math.round(bytes / 1024))} KB ≈ ${String(Math.round(bytes / 4096))}k tok`);

const t0 = Date.now();
try {
  const out = await generateText({
    model: provider(api.model),
    messages: j.messages,
    ...(j.instructions ? { instructions: j.instructions } : {}),
    tools,
    toolChoice: { type: "tool" as const, toolName: "submit" },
    maxOutputTokens: 16384,
    temperature: 0,
    seed: 42,
    maxRetries: 0,
  });
  console.log(`OK in ${String(Math.round((Date.now() - t0) / 1000))}s`);
  console.log("finish:", out.finishReason, " usage:", JSON.stringify(out.usage));
  console.log("text:", (out.text ?? "").slice(0, 200));
  console.log("calls:", JSON.stringify(out.toolCalls?.map((c) => c.toolName)));
} catch (e) {
  console.log(`THREW after ${String(Math.round((Date.now() - t0) / 1000))}s`);
  let cur: unknown = e;
  for (let i = 0; cur && i < 6; i++) {
    const x = cur as { name?: string; message?: string; statusCode?: number; responseBody?: string; cause?: unknown; issues?: unknown };
    console.log(`  [${String(i)}] ${String(x.name)}: ${String(x.message).slice(0, 300)}`);
    if (x.statusCode) console.log(`      status ${String(x.statusCode)}`);
    if (x.responseBody) console.log(`      body: ${String(x.responseBody).slice(0, 600)}`);
    if (x.issues) console.log(`      issues: ${JSON.stringify(x.issues).slice(0, 600)}`);
    cur = x.cause;
  }
}
