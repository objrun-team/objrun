import { expect, test } from "bun:test";
import { machine, until } from "./_lib.ts";

test("a provider credit rejection terminates as an infrastructure fault without retrying", async () => {
  let requests = 0;
  const vendor = Bun.serve({ port: 0, fetch(request) {
    if (new URL(request.url).pathname === "/infer") return Response.json(null);
    requests++;
    return Response.json({ error: { message: "test credit limit", type: "insufficient_quota", code: "insufficient_quota" } }, { status: 402 });
  } });
  const endpoint = `http://127.0.0.1:${vendor.port}`;
  const m = await machine({ retryTimes: 2, continueTimes: 0, maxTokens: 32 });
  try {
    await m.api("POST", "/declare", { handles: [{ name: `${endpoint}/infer`, expectMs: 1000 }], places: [{ place: "local" }], modes: [{ mode: "fault", cycles: [{ cycle: "ask", apiMode: "chat", maxUnits: 1, from: [], next: [], infer: `${endpoint}/infer` }] }], agents: [{ name: "bot", apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]], unit: "fn:unit.tools" }] });
    await m.api("POST", "/exec", { sql: "update api set base_url=:endpoint where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'", params: { endpoint } });
    await m.api("POST", "/tasks", { id: "credits-fault", mode: "fault", agent: "bot", place: "local", source: "user", description: "say one number", solveSeconds: 30 });
    const result = await until("provider fault is finalized", async () => {
      const task = await m.api<{ state: string; result: string | null }>("GET", "/tasks/credits-fault");
      return task.state === "failed" ? task : null;
    }, 3000);
    expect(JSON.parse(result.result ?? "{}")).toMatchObject({ valid: false, outcome: "provider_error", httpStatus: 402 });
    expect(requests).toBe(1);
  } finally { m.stop(); void vendor.stop(true); }
}, 10000);

test("a provider permission rejection terminates without retrying", async () => {
  let requests = 0;
  const vendor = Bun.serve({ port: 0, fetch(request) {
    if (new URL(request.url).pathname === "/infer") return Response.json(null);
    requests++;
    return Response.json({ error: { message: "test permission rejection" } }, { status: 403 });
  } });
  const endpoint = `http://127.0.0.1:${vendor.port}`;
  const m = await machine({ retryTimes: 2, continueTimes: 0, maxTokens: 32 });
  try {
    await m.api("POST", "/declare", { handles: [{ name: `${endpoint}/infer`, expectMs: 1000 }], places: [{ place: "local" }], modes: [{ mode: "fault", cycles: [{ cycle: "ask", apiMode: "chat", maxUnits: 1, from: [], next: [], infer: `${endpoint}/infer` }] }], agents: [{ name: "bot", apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]], unit: "fn:unit.tools" }] });
    await m.api("POST", "/exec", { sql: "update api set base_url=:endpoint where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'", params: { endpoint } });
    await m.api("POST", "/tasks", { id: "permission-fault", mode: "fault", agent: "bot", place: "local", source: "user", description: "say one number", solveSeconds: 30 });
    const result = await until("permission fault is finalized", async () => {
      const task = await m.api<{ state: string; result: string | null }>("GET", "/tasks/permission-fault");
      return task.state === "failed" ? task : null;
    }, 3000);
    expect(JSON.parse(result.result ?? "{}")).toMatchObject({ valid: false, outcome: "provider_error", httpStatus: 403 });
    expect(requests).toBe(1);
  } finally { m.stop(); void vendor.stop(true); }
}, 10000);

for (const status of [402, 403]) test(`a search subagent ${status} refusal invalidates the task before another model request`, async () => {
  let modelRequests = 0;
  let searches = 0;
  const vendor = Bun.serve({ port: 0, async fetch(request) {
    const path = new URL(request.url).pathname;
    if (path === "/infer") {
      const arg = await request.json() as { cycle: { cycle: string }; result: { kind: string } };
      return Response.json(arg.cycle.cycle === "act" ? "ask" : arg.result.kind === "call" ? "act" : null);
    }
    if (path === "/responses") {
      searches++;
      return Response.json({ error: { message: "test search account refusal" } }, { status });
    }
    modelRequests++;
    const message = modelRequests === 1
      ? { role: "assistant", content: null, tool_calls: [{ id: "search-1", type: "function", function: { name: "web_search", arguments: JSON.stringify({ question: "find the required number" }) } }] }
      : { role: "assistant", content: "unmatched fallback answer" };
    return Response.json({ id: "fake", object: "chat.completion", created: 0, model: "deepseek-v4-flash", choices: [{ index: 0, message, finish_reason: modelRequests === 1 ? "tool_calls" : "stop" }], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 } });
  } });
  const endpoint = `http://127.0.0.1:${vendor.port}`;
  const m = await machine({ retryTimes: 0, continueTimes: 0, maxTokens: 32 });
  try {
    await m.api("POST", "/declare", { handles: [{ name: `${endpoint}/infer`, expectMs: 1000 }], places: [{ place: "local" }], modes: [{ mode: "search-fault", cycles: [{ cycle: "ask", apiMode: "tools", maxUnits: 3, from: [], next: ["act"], infer: `${endpoint}/infer` }, { cycle: "act", maxUnits: 3, from: ["ask"], next: ["ask"], infer: `${endpoint}/infer` }] }], agents: [{ name: "bot", apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]], unit: "fn:unit.tools" }, { name: "searcher", apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]], unit: "fn:unit.tools" }] });
    await m.api("POST", "/exec", { sql: "update api set base_url=:endpoint where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'", params: { endpoint } });
    await m.api("POST", "/tasks", { id: "search-fault", mode: "search-fault", agent: "bot", place: "local", source: "user", description: "search for one number", solveSeconds: 30 });
    const result = await until("search refusal terminates the task", async () => {
      const task = await m.api<{ state: string; result: string | null }>("GET", "/tasks/search-fault");
      return ["done", "failed"].includes(task.state) ? task : null;
    }, 3000);
    expect(result.state).toBe("failed");
    expect(JSON.parse(result.result ?? "{}")).toMatchObject({ valid: false, outcome: "provider_error", httpStatus: status });
    expect(searches).toBe(1);
    expect(modelRequests).toBe(1);
  } finally { m.stop(); void vendor.stop(true); }
}, 10000);

for (const status of [402, 403]) test(`an account ${status} fault during continuation does not become a completed partial answer`, async () => {
  let requests = 0;
  const vendor = Bun.serve({ port: 0, fetch(request) {
    if (new URL(request.url).pathname === "/infer") return Response.json(null);
    requests++;
    if (requests > 1) return Response.json({ error: { message: "test account refusal while continuing" } }, { status });
    return Response.json({ id: "fake", object: "chat.completion", created: 0, model: "deepseek-v4-flash", choices: [{ index: 0, message: { role: "assistant", content: "partial answer" }, finish_reason: "length" }], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 } });
  } });
  const endpoint = `http://127.0.0.1:${vendor.port}`;
  const m = await machine({ retryTimes: 0, continueTimes: 1, maxTokens: 32 });
  try {
    await m.api("POST", "/declare", { handles: [{ name: `${endpoint}/infer`, expectMs: 1000 }], places: [{ place: "local" }], modes: [{ mode: "fault", cycles: [{ cycle: "ask", apiMode: "chat", maxUnits: 1, from: [], next: [], infer: `${endpoint}/infer` }] }], agents: [{ name: "bot", apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]], unit: "fn:unit.tools" }] });
    await m.api("POST", "/exec", { sql: "update api set base_url=:endpoint where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'", params: { endpoint } });
    await m.api("POST", "/tasks", { id: "continuation-fault", mode: "fault", agent: "bot", place: "local", source: "user", description: "say one number", solveSeconds: 30 });
    const result = await until("the continuation fault terminates the task", async () => {
      const task = await m.api<{ state: string; result: string | null }>("GET", "/tasks/continuation-fault");
      return ["done", "failed"].includes(task.state) ? task : null;
    }, 3000);
    expect(result.state).toBe("failed");
    expect(JSON.parse(result.result ?? "{}")).toMatchObject({ valid: false, outcome: "provider_error", httpStatus: status });
    expect(requests).toBe(2);
  } finally { m.stop(); void vendor.stop(true); }
}, 10000);
