/**
 * The final outbound gate: **remove a mismatched call/result fragment without reverting the context**.
 *
 * ```
 * bun test/integration/mend.ts
 * ```
 *
 * In the observed failure, missing-call repair ran **after** compression. Repair
 * recognized answers by `kind='tool'`, but closed-node calls and results had already
 * become plain text, so it missed unanswered calls. Starting repair also replaced
 * the compressed context with originals, sending a dangling call to the SDK, which
 * rejected it locally: `Tool result is missing for tool call …`.
 * Eight stations failed this way, all submission stations.
 *
 * The order is now repair first, compression second. This test guards **the final
 * validation step**: future additions to the path must not bypass it, and rejecting
 * a malformed fragment must produce a diagnostic.
 */

import { mendPairs, type Pair } from "../../app/src/msg/deliver.ts";
import { msg } from "../../app/src/engine/loop.ts";
import { done, ok, part, show, step } from "../_lib.ts";

const call = (unit: number, ids: string[], text = ""): Pair => ({
  unit, seq: 2, role: "assistant", kind: "call",
  body: JSON.stringify({ text, calls: ids.map((id) => ({ id, name: "bash", input: { command: "ls" } })) }),
});
const result = (unit: number, id: string): Pair => ({
  unit, seq: 3, role: "tool", kind: "tool",
  body: JSON.stringify({ id, name: "bash", value: { code: 0, stdout: "ok" } }),
});
const said = (unit: number, body: string): Pair => ({ unit, seq: 1, role: "user", kind: "user", body });

part("The last gate before it goes out: a call keeps its result, or it goes");

step("1. a list that holds together is left alone");
const fine = [said(1, "do it"), call(2, ["a"]), result(3, "a")];
const a = mendPairs(fine);
ok("nothing dropped", a.dropped.length === 0, a.dropped);
ok("and nothing moved", a.rows.length === 3, a.rows.length);

step("2. a call whose result never came is taken out");
const orphanCall = [said(1, "do it"), call(2, ["a", "b"]), result(3, "a")];
const b = mendPairs(orphanCall);
show("what it dropped:", b.dropped);
ok("it says which call", b.dropped.length === 1 && b.dropped[0].includes("b"), b.dropped);
const kept = JSON.parse(String(b.rows[1].body)) as { calls: { id: string }[] };
ok("the row stays, minus that one call", kept.calls.length === 1 && kept.calls[0].id === "a", kept);
ok("the result that did come is still there", b.rows.length === 3, b.rows.map((r) => r.kind));

step("3. a row that is left with nothing goes entirely");
// No calls or text remain, leaving an empty message; some providers reject empty content.
const c = mendPairs([said(1, "do it"), call(2, ["x"])]);
show("what came back:", c.rows.map((r) => `${r.kind}`));
ok("the empty assistant row is gone", c.rows.length === 1 && c.rows[0].kind === "user", c.rows);
ok("and it said why", c.dropped.length === 1 && c.dropped[0].includes("x"), c.dropped);

step("4. but a row that also said something keeps the words");
const d = mendPairs([call(2, ["x"], "I will look at the file")]);
const left = JSON.parse(String(d.rows[0].body)) as { text: string; calls: unknown[] };
ok("the row survives", d.rows.length === 1, d.rows.length);
ok("with its text and no calls", left.text.includes("look at the file") && left.calls.length === 0, left);

step("5. a result nobody asked for is taken out too");
// The reverse mismatch: `Messages with role 'tool' must be a response to a preceding message
// with 'tool_calls'` also causes rejection of the entire request.
const e = mendPairs([said(1, "do it"), result(2, "ghost")]);
ok("the stray result is gone", e.rows.length === 1, e.rows.map((r) => r.kind));
ok("and it said which one", e.dropped[0].includes("ghost"), e.dropped);

step("6. the kernel's own verdict is judged by the same rule");
// A `graded` pair is recorded by the kernel after the fact (id starts with g-) but has the same shape as a model call,
// so it uses the same validation rule. Separate rules would eventually diverge.
const graded: Pair = {
  unit: 4, seq: 4, role: "assistant", kind: "graded",
  body: JSON.stringify({ text: "", calls: [{ id: "g-1", name: "verify", input: {} }] }),
};
const f = mendPairs([graded, result(5, "g-1")]);
ok("a verdict with its answer is left alone", f.dropped.length === 0, f.dropped);
const g = mendPairs([graded]);
ok("a verdict with no answer is taken out", g.rows.length === 0 && g.dropped.length === 1, g);

step("7. an error says what actually went wrong, not just the wrapper");
// Observed failure: the AI SDK received HTTP 200 but failed while mapping the response into its own structures.
// It wrapped the error as `Failed to process successful response`, with the actual cause stored in `cause`.
// Logging only the wrapper made more than ten failures indistinguishable and impossible to diagnose.
const inner = new Error("Unexpected end of JSON input");
const outer = Object.assign(new Error("Failed to process successful response"), {
  cause: inner,
  statusCode: 200,
});
const line = msg(outer);
show("what the log would carry:", line);
ok("the wrapper is there", line.includes("Failed to process successful response"), line);
ok("and so is the real reason", line.includes("Unexpected end of JSON input"), line);
ok("with what that end said", line.includes("status 200"), line);

done();
