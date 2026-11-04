/**
 * 发出去之前那道闸：**调用和结果配不上，就摘掉那一小段，不回退。**
 *
 * ```
 * bun test/integration/mend.ts
 * ```
 *
 * 撞过的那次：拼上下文的收尾里，「补齐没人答的调用」排在了压缩**后面**。补齐靠
 * `kind='tool'` 认「这个调用答过了」，而压过的那份里，收口节点的调用和结果都已经是
 * 一段文字 —— 它一个都认不出来，该补的漏掉；补齐一动手又把整份换回原文，于是原文里
 * 那个悬空的调用一路发到那一端，SDK 本地就拒：`Tool result is missing for tool call …`。
 * 八站栽在这儿，全是交卷站。
 *
 * 顺序已经改回来了（补齐在前、压缩在后）。这儿钉的是**最后那道闸**：万一以后又有谁
 * 往这条路上加东西，闸得自己拦住，而且拦住的时候要说话。
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
// 一个调用都不剩、话也没说 —— 留下的是一条空消息，而有的家直接拒收空 content。
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
// 反过来那一句：`Messages with role 'tool' must be a response to a preceding message
// with 'tool_calls'` —— 一样是整份拒收。
const e = mendPairs([said(1, "do it"), result(2, "ghost")]);
ok("the stray result is gone", e.rows.length === 1, e.rows.map((r) => r.kind));
ok("and it said which one", e.dropped[0].includes("ghost"), e.dropped);

step("6. the kernel's own verdict is judged by the same rule");
// `graded` 那一对是内核事后记的（id 以 g- 开头），形状跟模型自己调的一样，
// 所以走同一条判据 —— 另开一条的话，两边迟早会不一样。
const graded: Pair = {
  unit: 4, seq: 4, role: "assistant", kind: "graded",
  body: JSON.stringify({ text: "", calls: [{ id: "g-1", name: "verify", input: {} }] }),
};
const f = mendPairs([graded, result(5, "g-1")]);
ok("a verdict with its answer is left alone", f.dropped.length === 0, f.dropped);
const g = mendPairs([graded]);
ok("a verdict with no answer is taken out", g.rows.length === 0 && g.dropped.length === 1, g);

step("7. an error says what actually went wrong, not just the wrapper");
// 撞过的那次：AI SDK 收到 200，把返回体映射成自己的结构那一步失败，包一句
// `Failed to process successful response` —— 真正的原因挂在 `cause` 上，而日志
// 只打了外面那句，于是十几条错误长得一模一样，查不下去。
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
