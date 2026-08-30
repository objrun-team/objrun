/**
 * 实时轨（duplex）的端到端。
 *
 * ```
 * bun examples/duplex-e2e.ts
 * ```
 *
 * ## 为什么不直接打 DashScope
 *
 * 要验的是**事件名对不对得上**，而真端点只会把对的那套发过来 —— 它验不了
 * 「名字漂了会怎样」。所以这儿起一个**说 beta 事件名的假服务器**，
 * 把老代码踩过的三个坑原样摆出来，看我们这边接不接得住：
 *
 * 1. `response.done` **不带 usage** —— 老代码在这儿崩掉整条接收协程，之后全静默
 * 2. 中间夹一条**解不开的垃圾**和一条**没见过的事件** —— 不许带倒连接
 * 3. 参会者转写走 beta schema —— 老代码整条跳过，于是永远拿不到「别人说了什么」
 *
 * 不烧额度、不看网络、跑得完。真端点那一趟另说，它验的是钥匙和地址，不是这个。
 */

import { Session } from "../app/src/llm/duplex.ts";

/** 假服务器收到的东西，跑完拿来对。 */
const got = {
  auth: "",
  model: "",
  session: null as Record<string, unknown> | null,
  items: [] as Record<string, unknown>[],
  turns: 0,
};

/** 一条 beta 事件。**故意用 beta 名** —— 这正是要验的那件事。 */
function beta(ws: { send(s: string): void }, o: Record<string, unknown>): void {
  ws.send(JSON.stringify(o));
}

const server = Bun.serve({
  port: 0,
  fetch(req, srv) {
    got.auth = req.headers.get("authorization") ?? "";
    got.model = new URL(req.url).searchParams.get("model") ?? "";
    if (srv.upgrade(req)) return undefined;
    return new Response("a websocket is required", { status: 400 });
  },
  websocket: {
    open(ws) {
      beta(ws, { type: "session.created", session: { id: "fake-1" } });
    },
    message(ws, raw) {
      const m = JSON.parse(String(raw)) as Record<string, unknown>;

      if (m.type === "session.update") {
        got.session = m.session as Record<string, unknown>;
        beta(ws, { type: "session.updated", session: m.session });
        return;
      }
      if (m.type === "conversation.item.create") {
        got.items.push(m.item as Record<string, unknown>);
        return;
      }
      if (m.type !== "response.create") return;

      got.turns++;
      if (got.turns === 1) return firstTurn(ws);
      return toolTurn(ws);
    },
  },
});

/** 第一个来回：正常讲话 + 三个坑。 */
function firstTurn(ws: { send(s: string): void }): void {
  // beta 名。映射不生效的话，这两条没人认领，text 就是空的。
  beta(ws, { type: "response.audio_transcript.delta", delta: "first a line, " });
  beta(ws, { type: "response.text.delta", delta: "then another." });

  // 【坑】音频块：收到就丢，只计数。
  beta(ws, { type: "response.audio.delta", delta: "AAAAAAAA" });

  // 【坑】一条根本不是 JSON 的。带倒连接的话，后面全收不到。
  ws.send("{ this is not json");

  // 【坑】没见过的事件名。那边随时会加新的，不许当成错。
  beta(ws, { type: "response.something.brand_new", whatever: 1 });

  // 【坑】参会者转写：beta schema，通用解析器解不了。老代码在这儿整条跳过。
  beta(ws, {
    type: "conversation.item.input_audio_transcription.completed",
    transcript: "  from the floor: where does this number come from?  ",
  });

  // 【坑】beta 的 response.done **不带 usage**。老代码读统计字段当场崩，
  // 接收协程死掉 —— 从这一刻起再没有一个字被处理。
  beta(ws, { type: "response.done", response: { id: "r1", status: "completed" } });
}

/** 第二个来回：请求一个工具。名字**只在 item 那条给**，done 那条不带。 */
function toolTurn(ws: { send(s: string): void }): void {
  beta(ws, {
    type: "conversation.item.created",
    item: { id: "item-9", type: "function_call", name: "read", call_id: "call-9" },
  });
  beta(ws, {
    type: "response.function_call_arguments.done",
    item_id: "item-9",
    arguments: JSON.stringify({ file_path: "/tmp/a.txt" }),
  });
  beta(ws, { type: "response.done", response: { id: "r2", status: "completed" } });
}

// ── 跑 ──────────────────────────────────────────────────────────────────────

let bad = 0;
function ok(what: string, cond: boolean, saw?: unknown): void {
  if (cond) {
    console.log(`  ✓ ${what}`);
    return;
  }
  bad++;
  console.log(`  x ${what}${saw === undefined ? "" : ` actually got: ${JSON.stringify(saw)}`}`);
}

const url = `ws://127.0.0.1:${server.port}`;
console.log(`fake realtime endpoint listening on ${url}\n`);

const s = new Session(url, "fake-key", "qwen-audio-3.0-realtime-flash");
await s.ready();

await s.update("You are the presenter.", [
  { type: "function", name: "read", description: "read a file", parameters: { type: "object", properties: {} } },
]);

console.log("Turn one: ordinary speech plus three traps");
const one = await s.turn([
  { type: "message", role: "user", content: [{ type: "input_text", text: "go ahead" }] },
]);

// 这一条是整块的要害：beta 名没映射的话，两条 delta 都没人认领，text 是空的。
ok("the beta event-name mapping works (the text arrived)", one.text === "first a line, then another.", one.text);
ok("audio is counted, not stored", one.audio === 1, one.audio);
ok("a garbage line and an unseen event did not take the connection down", s.dead === null);
ok("the number skipped is counted (1 garbage + 1 unseen)", one.skipped === 2, one.skipped);
ok("the participant transcript was caught, and trimmed", one.heard.length === 1 && one.heard[0] === "from the floor: where does this number come from?", one.heard);
ok("a response.done without usage still wraps up", one.errors.length === 0, one.errors);

console.log("\nTurn two: requesting a tool (the name comes only on the item event)");
const two = await s.turn([
  { type: "message", role: "user", content: [{ type: "input_text", text: "go read it" }] },
]);
ok("the tool name was filled in from the item event", two.calls.length === 1 && two.calls[0].name === "read", two.calls);
ok("call_id is the one the item event gave", two.calls[0]?.id === "call-9", two.calls[0]?.id);
ok("the arguments were parsed", JSON.stringify(two.calls[0]?.input) === '{"file_path":"/tmp/a.txt"}', two.calls[0]?.input);
ok("transcripts are cleared once taken, with no repeats", two.heard.length === 0, two.heard);

console.log("\nThe session layer");
ok("the key travels in a request header", got.auth === "Bearer fake-key", got.auth);
ok("the model rides on the URL", got.model === "qwen-audio-3.0-realtime-flash", got.model);
ok("instructions are sent once, when the session opens", got.session?.instructions === "You are the presenter.", got.session);
ok("text only", JSON.stringify(got.session?.modalities) === '["text"]', got.session?.modalities);
ok("both turns shared one session", got.turns === 2, got.turns);

s.close();
server.stop(true);

console.log(bad === 0 ? "\nall passed." : `\n${bad} failed.`);
process.exit(bad === 0 ? 0 : 1);
