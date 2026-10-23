/**
 * 把重建出来的那一发**原样打回去**，看能不能复现 `Failed to process successful response`。
 *
 * 跟内核那条路一样：同一个 provider、同一套工具、同一个 toolChoice、同样的采样参数。
 * 两处不同，都是**故意**的：
 *
 * - `maxRetries: 0` —— 要看的是第一次的真样子，不是重试之后的结论
 * - 把 `cause` 整条链打出来 —— 内核那边只打了外层那句，真正的原因一直没人看见
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
 * 交卷站钉死了工具 → **思考关掉**。
 *
 * 内核那边是 `effort = u.mustCall ? "none" : knobs.reasoningEffort`，而 `"none"` 是真值，
 * 所以它照样走 `withExtra` 把 `reasoning_effort: "none"` 塞进 body。第一次重放我漏了这一层，
 * 那一端当场 400：`Thinking mode does not support this tool_choice` —— 少一个字段就不是
 * 同一发了。
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
