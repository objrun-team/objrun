/**
 * Example: **message-list structure must already be valid when stored**.
 *
 * ```
 * bun test/integration/shape.ts
 * ```
 *
 * The message table must serve as **a kernel-independent snapshot**: it should reveal
 * what the model saw without requiring a particular kernel version. Otherwise a failure
 * can only be guessed at. This happened when a gateway rejected a request: the exact
 * outbound shape was unrecoverable because the database recorded events while the
 * kernel assembled a different representation for sending.
 *
 * Two rules establish the invariant:
 *
 * 1. **Validate structure on insertion** (`checkBody`); invalid rows never enter the database.
 * 2. **Repair omissions instead of removing rows** (`answerMissing`). Store a synthetic
 *    "not executed" result for an unexecuted tool call. Previously, the call was removed before sending.
 *
 * ## Why can a tool call remain unexecuted?
 *
 * A model request creates a `call` row; tool completion creates a `tool` row, paired
 * by `id`. But **whether a station actually executes it depends on the mechanism**.
 * A successor using `fn:unit.tools` executes tools; a pure question-answer lane does not.
 * System tools are exposed unconditionally, so a multi-station question-answer mechanism
 * will eventually request a tool that nobody executes.
 *
 * Without a result, providers reject the entire context: every tool_call requires a
 * corresponding tool result. Removing the call makes sending possible but causes it
 * to **disappear from the history** seen by the model, and the stored and sent contexts differ.
 */

import { checkBody } from "../../app/src/msg/deliver.ts";
import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();

/** This station only requests a tool; the mechanism contains no executor for it. */
const out = await outside({
  "/unit": () => ({
    role: "assistant",
    kind: "call",
    body: JSON.stringify({ text: "", calls: [{ id: "never-run-1", name: "read", input: { file: "x" } }] }),
  }),
  "/infer": () => null,
});

try {
  part("Part one: a shape that cannot stand is refused at the door");

  step("1. a tool call with no id");
  // `id` is the pairing key. Without it, a tool result can never be matched and the context becomes unsendable.
  let said = "";
  try {
    checkBody("call", JSON.stringify({ text: "", calls: [{ name: "read", input: {} }] }));
  } catch (e) {
    said = e instanceof Error ? e.message : String(e);
  }
  show("it answered:", said);
  ok("it is refused, rather than sitting in the table until a request fails", said.includes("id"), said);

  step("2. a tool result that does not say which call it answers");
  said = "";
  try {
    checkBody("tool", JSON.stringify({ name: "read", value: 1 }));
  } catch (e) {
    said = e instanceof Error ? e.message : String(e);
  }
  show("it answered:", said);
  ok("also refused", said.length > 0, said);

  step("3. a body that is not JSON at all");
  said = "";
  try {
    checkBody("call", "not json");
  } catch (e) {
    said = e instanceof Error ? e.message : String(e);
  }
  ok("refused, and it says which kind was wrong", said.includes("call"), said);

  step("4. an ordinary message is none of its business");
  checkBody("prompt", "just something the model said");
  ok("a plain message passes through untouched", true);

  // ═══════════════════════════════════════════════════════════════════════
  part("Part two: a call nobody ran is answered, not hidden");

  step("5. two stations, and nobody who runs tools");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [
      { name: out.url("/unit"), expectMs: 20_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
    ],
    modes: [
      {
        mode: "talk",
        cycles: [
          { cycle: "ask", maxUnits: 2, from: [], next: ["again"], infer: out.url("/infer") },
          { cycle: "again", maxUnits: 2, from: ["ask"], next: [], infer: out.url("/infer") },
        ],
      },
    ],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  ok("the declaration went in", true);

  step("6. run it, then look at what the table holds");
  await m.api("POST", "/tasks", {
    id: "t-dangle", mode: "talk", agent: "bot", place: "local", source: "user",
    description: "ask for a tool nobody will run", solveSeconds: 60,
  });
  await until("t-dangle to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-dangle");
    return d.state === "done" || d.state === "failed" ? d : null;
  }, 40_000);

  const rows = (
    await m.api<{ rows: { unit: number; seq: number; kind: string; body: string }[] }>("POST", "/query", {
      sql: "select unit, seq, kind, body from agent_bot_msg where instance = 't-dangle#1' and kind in ('call','tool') order by unit, seq",
    })
  ).rows;
  show("the call/result rows in the table:", rows.map((r) => `${r.kind}#${r.unit}.${r.seq}`));

  const call = rows.find((r) => r.kind === "call");
  const answer = rows.find((r) => r.kind === "tool");
  ok("the call it made is still there - nothing was hidden", call !== undefined, rows);
  ok("and it has an answer in the table", answer !== undefined, rows);
  ok(
    "the answer says plainly that it never ran",
    String(answer?.body ?? "").includes('"ran":false'),
    answer?.body,
  );
  ok(
    "and the answer is matched to that call by id",
    String(answer?.body ?? "").includes("never-run-1"),
    answer?.body,
  );

  step("7. so the table alone is a faithful snapshot");
  // The actual invariant: this table alone must reveal what the model saw, without requiring a particular
  // kernel implementation. Removing rows before sending violates it: the table contains the call,
  // but the outbound request does not.
  const answered = new Set(
    rows.filter((r) => r.kind === "tool").map((r) => (JSON.parse(r.body) as { id?: string }).id),
  );
  const asked = rows
    .filter((r) => r.kind === "call")
    .flatMap((r) => (JSON.parse(r.body) as { calls?: { id?: string }[] }).calls ?? [])
    .map((c) => c.id);
  show("asked:", asked);
  show("answered:", [...answered]);
  ok("every call in the table has its result in the table", asked.every((id) => answered.has(id)), { asked, answered });
  // ═══════════════════════════════════════════════════════════════════════
  part("Part three: where a line goes is written down, not compiled in");

  step("8. the table says where each role goes");
  const roles = (
    await m.api<{ rows: { name: string; sent_as: string }[] }>("POST", "/query", {
      sql: "select name, sent_as from msg_role order by name",
    })
  ).rows;
  show("what the table says:", roles.map((r) => `${r.name} -> ${r.sent_as}`));
  ok(
    "the three the model knows go into the conversation",
    ["user", "assistant", "tool"].every((n) => roles.find((r) => r.name === n)?.sent_as === "messages"),
    roles,
  );
  ok(
    "and the two that are told rather than said go into instructions",
    ["system", "skill"].every((n) => roles.find((r) => r.name === n)?.sent_as === "instructions"),
    roles,
  );

  step("9. it is keyed by role, because one kind can wear two");
  // World-originated `inject` has role user; kernel-originated `inject` has role system. One enters the message stream,
  // the other instructions. Classifying by kind alone would conflate these intentionally different cases.
  const kinds = (
    await m.api<{ rows: { name: string }[] }>("POST", "/query", { sql: "select name from msg_kind" })
  ).rows.map((r) => r.name);
  show("the kinds registered:", kinds);
  ok("inject is a single kind", kinds.filter((k) => k === "inject").length === 1, kinds);
  ok(
    "yet user and system part ways - so the answer cannot hang off the kind",
    roles.find((r) => r.name === "user")?.sent_as !== roles.find((r) => r.name === "system")?.sent_as,
    roles,
  );
} finally {
  out.stop();
  m.stop();
}

done();
