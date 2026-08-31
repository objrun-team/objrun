/**
 * 例子：**消息列表的形状,在入库那一刻就得站得住。**
 *
 * ```
 * bun test/shape.ts
 * ```
 *
 * 库里那张消息表要能当**一份跟内核无关的快照**用：拿着它，就该知道模型看见了
 * 什么。做不到的话，出了事只能靠猜 —— 而这件事真发生过：一次请求被网关拒了，
 * 想查发出去的到底长什么样，查不出来，因为库里存的是「发生了什么事」，发出去的
 * 是内核现拼的另一份东西。
 *
 * 两条规矩把这件事钉住：
 *
 * 1. **入库就查形状**（`checkBody`）。站不住的行根本进不来
 * 2. **缺的补上，不摘**（`answerMissing`）。一次没人跑的工具调用，补一条「没跑成」
 *    写回库里；以前是发之前把那一行摘掉
 *
 * ## 为什么会有「没人跑的调用」
 *
 * 模型请求工具，落一行 `call`；工具跑完落一行 `tool`，靠 `id` 配对。但**这一站有
 * 没有人真去跑，取决于机制怎么搭** —— 下一站走 `fn:unit.tools` 就有人跑，一条纯
 * 问答的轨就没人跑。而系统工具是无条件挂上去的，所以纯问答的多站机制里，模型
 * 迟早会请求一次没人跑的工具。
 *
 * 缺了结果，整份上下文就发不出去（模型那边一律要求「有 tool_call 就得有对应的
 * tool result」）。摘掉那一行确实能发出去，代价是模型看到的历史里那次调用**凭空
 * 消失**，而且库和发出去的不是一份东西。
 */

import { checkBody } from "../app/src/msg/deliver.ts";
import { done, machine, ok, outside, part, show, step, until } from "./_lib.ts";

const m = await machine();

/** 这一站只说「我要调工具」，而这个机制里没有人会去跑它。 */
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
  // `id` 是这一对的钥匙。没有它，工具结果永远配不回来，而那份上下文从此发不出去。
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
  // 这才是这个例子真正在验的东西：不用同时拿着某一版内核代码，光看这张表就能
  // 知道模型看见了什么。摘行的做法下，这一条不成立 —— 表里有那次调用，发出去的
  // 那份里没有。
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
  // 世界注入的 `inject` 是 user，内核注入的 `inject` 是 system —— 一个进消息流，
  // 一个进交代。按 kind 查的话这两条只能得到同一个答案，而它们本来就不该一样。
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
