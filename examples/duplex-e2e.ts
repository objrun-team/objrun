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

const server = Bun.serve<undefined, Record<string, never>>({
  port: 0,
  fetch(req, srv) {
    got.auth = req.headers.get("authorization") ?? "";
    got.model = new URL(req.url).searchParams.get("model") ?? "";
    if (srv.upgrade(req)) return undefined;
    return new Response("要 websocket", { status: 400 });
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
  beta(ws, { type: "response.audio_transcript.delta", delta: "先说一句，" });
  beta(ws, { type: "response.text.delta", delta: "再说一句。" });

  // 【坑】音频块：收到就丢，只计数。
  beta(ws, { type: "response.audio.delta", delta: "AAAAAAAA" });

  // 【坑】一条根本不是 JSON 的。带倒连接的话，后面全收不到。
  ws.send("{ 这不是 json");

  // 【坑】没见过的事件名。那边随时会加新的，不许当成错。
  beta(ws, { type: "response.something.brand_new", whatever: 1 });

  // 【坑】参会者转写：beta schema，通用解析器解不了。老代码在这儿整条跳过。
  beta(ws, {
    type: "conversation.item.input_audio_transcription.completed",
    transcript: "  台下问：这个数是哪来的？  ",
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
  console.log(`  ✗ ${what}${saw === undefined ? "" : `　实际拿到：${JSON.stringify(saw)}`}`);
}

const url = `ws://127.0.0.1:${server.port}`;
console.log(`假实时端点起在 ${url}\n`);

const s = new Session(url, "fake-key", "qwen-audio-3.0-realtime-flash");
await s.ready();

await s.update("你是汇报人。", [
  { type: "function", name: "read", description: "读一个文件", parameters: { type: "object", properties: {} } },
]);

console.log("第一个来回：正常讲话 + 三个坑");
const one = await s.turn([
  { type: "message", role: "user", content: [{ type: "input_text", text: "开始吧" }] },
]);

// 这一条是整块的要害：beta 名没映射的话，两条 delta 都没人认领，text 是空的。
ok("beta 事件名映射生效（文本收到了）", one.text === "先说一句，再说一句。", one.text);
ok("音频只计数不落库", one.audio === 1, one.audio);
ok("垃圾行和没见过的事件没带倒连接", s.dead === null);
ok("跳过的条数数出来了（垃圾 1 + 没见过 1）", one.skipped === 2, one.skipped);
ok("参会者转写接住了，而且去了空白", one.heard.length === 1 && one.heard[0] === "台下问：这个数是哪来的？", one.heard);
ok("不带 usage 的 response.done 照样收尾", one.errors.length === 0, one.errors);

console.log("\n第二个来回：请求工具（名字只在 item 那条给）");
const two = await s.turn([
  { type: "message", role: "user", content: [{ type: "input_text", text: "去读一下" }] },
]);
ok("工具名从 item 那条补上了", two.calls.length === 1 && two.calls[0].name === "read", two.calls);
ok("call_id 用的是 item 给的那个", two.calls[0]?.id === "call-9", two.calls[0]?.id);
ok("参数解出来了", JSON.stringify(two.calls[0]?.input) === '{"file_path":"/tmp/a.txt"}', two.calls[0]?.input);
ok("转写取走就清空，没重复", two.heard.length === 0, two.heard);

console.log("\n会话这一层");
ok("钥匙走的是请求头", got.auth === "Bearer fake-key", got.auth);
ok("model 挂在地址上", got.model === "qwen-audio-3.0-realtime-flash", got.model);
ok("instructions 只在开会话时发一次", got.session?.instructions === "你是汇报人。", got.session);
ok("只要文本", JSON.stringify(got.session?.modalities) === '["text"]', got.session?.modalities);
ok("两个来回共用同一条会话", got.turns === 2, got.turns);

s.close();
server.stop(true);

console.log(bad === 0 ? "\n全过。" : `\n${bad} 条没过。`);
process.exit(bad === 0 ? 0 : 1);
