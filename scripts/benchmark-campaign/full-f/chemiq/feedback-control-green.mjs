import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { randomBytes } from "node:crypto";
import { machine } from "./feedback-control-machine-green.mjs";
const root = resolve(import.meta.dir, "../../../.."), directory = join(root, "docs/repair-2026-10-10/full-f-rerun/chemiq/submission-controls", Date.now().toString());
mkdirSync(directory, { recursive: true });
const rows = [], token = randomBytes(24).toString("hex");
let misses = 0;
const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
  const path = new URL(request.url).pathname;
  if (path === "/ran" || path === "/passed")
    return Response.json({ value: true });
  if (path === "/place")
    return Response.json({ alive: true });
  const body = await request.json();
  const required = body.tools?.length === 1 && body.tools[0].function?.name === "submit";
  const hasFeedback = body.messages?.some((m) => String(m.content).includes("The previous response was rejected"));
  const missing = required && (misses++, !hasFeedback);
  rows.push({ required, missing, hasFeedback, model: body.model, maxTokens: body.max_tokens, reasoning: body.reasoning, provider: body.provider });
  return Response.json({ id: "synthetic-" + rows.length, model: body.model, choices: [{
    index: 0,
    finish_reason: missing ? "stop" : "tool_calls",
    message: { role: "assistant", content: missing ? "I am finished." : null, ...missing ? {} : { tool_calls: [{ id: "call-" + rows.length, type: "function", function: { name: "submit", arguments: '{"answer":"local-control"}' } }] } }
  }], usage: { prompt_tokens: 1, completion_tokens: 1 } });
} });
let engine;
const proof = { protocol: "chemiq-required-submit-native-control-v1", modelCalls: 0, dockerActions: 0, syntheticLocalOnly: true, complete: false };
try {
  process.env.TGENGIN_GRADER_TOKEN = token;
  process.env.TGENGIN_GRADER_ORIGINS = "http://127.0.0.1:" + server.port;
  mkdirSync(join(directory, "engine"), { recursive: true });
  engine = await machine({}, { directory: join(directory, "engine"), keep: true });
  const origin = "http://127.0.0.1:" + server.port;
  await engine.api("POST", "/exec", { sql: "update api set base_url=:base where key_env='OPENROUTER_API_KEY' and model='deepseek/deepseek-v4.1-flash'", params: { base: origin + "/v1" } });
  await engine.api("POST", "/declare", {
    handles: ["ran", "passed", "place"].map((name) => ({ name: origin + "/" + name, expectMs: 1e4 })),
    places: [{ place: "tb-local", identity: origin + "/place", forward: false, tools: [] }],
    modes: [{ mode: "tb_submit_control", cycles: [{ cycle: "ask", apiMode: "chat", maxUnits: 4, from: [], next: ["act"], infer: "fn:infer.dfs" }, { cycle: "act", maxUnits: 4, from: ["ask"], next: ["ask"], infer: "fn:infer.dfs" }] }],
    agents: [{ name: "bot", apis: [["OPENROUTER_API_KEY", "deepseek/deepseek-v4.1-flash"]], unit: "fn:unit.tools" }]
  });
  await engine.api("POST", "/tasks", {
    id: "tb12-local-submission-control",
    place: "tb-local",
    mode: "tb_submit_control",
    agent: "bot",
    source: "user",
    readable: false,
    description: "Submit local-control using submit.",
    solveSeconds: 60,
    maxBranches: 1,
    maxDeadSiblings: 1,
    objective: { nodes: [{ name: "ran", domain: "bool", moment: "done", handle: origin + "/ran" }, { name: "passed", domain: "bool", moment: "done", handle: origin + "/passed" }], edges: [{ src: "ran", out: 0, dst: "passed" }], sink: "passed", checks: 1, reuse: "never" }
  });
  const deadline = Date.now() + 60000;
  let state;
  do {
    state = await engine.api("GET", "/tasks/tb12-local-submission-control");
    if (state.result && JSON.parse(state.result).valid === true)
      break;
    await Bun.sleep(100);
  } while (Date.now() < deadline);
  const units = await engine.api("POST", "/query", { sql: "select done from agent_bot_ctx" });
  proof.state = state;
  proof.units = units;
  proof.requests = rows;
  if (state.state !== "done" || JSON.parse(state.result ?? "{}").valid !== true || misses < 2)
    throw Error("submission_native_retry_or_finalization_failed");
  proof.complete = true;
} catch (error) {
  proof.fault = String(error);
  process.exitCode = 2;
} finally {
  if (engine)
    proof.engineClose = await engine.stop();
  await server.stop(true);
  writeFileSync(join(directory, "control.json"), JSON.stringify(proof, null, 2) + `
`);
  writeFileSync("F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\docs\\repair-2026-10-10\\full-f-rerun\\chemiq\\submit-feedback-staging\\1791669084947\\green\\control-latest.json", JSON.stringify({ path: join(directory, "control.json"), complete: proof.complete, fault: proof.fault ?? null, modelCalls: 0 }) + `
`);
}
console.log(JSON.stringify({ complete: proof.complete, fault: proof.fault ?? null, directory, modelCalls: 0 }));
