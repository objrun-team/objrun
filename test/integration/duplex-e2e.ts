/**
 * End-to-end test of the real-time duplex lane.
 *
 * ```
 * bun test/integration/duplex-e2e.ts
 * ```
 *
 * ## Why not call DashScope directly?
 *
 * This tests **event-name compatibility**. A real endpoint sends only its valid
 * event names and cannot establish what happens when names drift. A **mock server
 * using beta event names** reproduces three failures seen in the old implementation:
 *
 * 1. `response.done` **omits usage**; the old receive coroutine crashed and went silent.
 * 2. **Undecodable garbage** and an **unknown event** occur between valid messages;
 *    neither may break the connection.
 * 3. Participant transcripts use the beta schema; the old implementation skipped
 *    them entirely, so it never learned what other participants said.
 *
 * This consumes no quota, does not depend on the network, and terminates. A real-endpoint
 * check separately validates credentials and addresses, rather than these behaviors.
 */

import { Session } from "../../app/src/llm/duplex.ts";

/** Record the mock server's incoming payloads for checks after the run. */
const got = {
  auth: "",
  model: "",
  session: null as Record<string, unknown> | null,
  items: [] as Record<string, unknown>[],
  turns: 0,
};

/** A beta event. **Use the beta name deliberately**; compatibility is the subject of this test. */
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

/** First exchange: normal speech plus the three failure cases. */
function firstTurn(ws: { send(s: string): void }): void {
  // Beta names: without mapping, neither delta is handled and text remains empty.
  beta(ws, { type: "response.audio_transcript.delta", delta: "first a line, " });
  beta(ws, { type: "response.text.delta", delta: "then another." });

  // Failure case: count audio chunks, then discard them.
  beta(ws, { type: "response.audio.delta", delta: "AAAAAAAA" });

  // Failure case: a payload that is not JSON. Breaking the connection would lose every later event.
  ws.send("{ this is not json");

  // Failure case: an unknown event name. The provider may add events at any time; this must not be an error.
  beta(ws, { type: "response.something.brand_new", whatever: 1 });

  // Failure case: participant transcription in the beta schema, which the generic parser cannot decode. The old code skipped it.
  beta(ws, {
    type: "conversation.item.input_audio_transcription.completed",
    transcript: "  from the floor: where does this number come from?  ",
  });

  // Failure case: beta response.done **omits usage**. Reading missing statistics crashed
  // the receive coroutine, so no subsequent text was processed.
  beta(ws, { type: "response.done", response: { id: "r1", status: "completed" } });
}

/** Second exchange: request a tool. Its name appears **only in the item event**, not in done. */
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

// -- Run ---------------------------------------------------------------------

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

// The key invariant: without mapping the beta names, neither delta is handled and text is empty.
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
