/**
 * 压上下文的那几种压法本身，以及**表里填的名字是不是都有人实现**。
 *
 * ```
 * bun test/press.ts
 * ```
 *
 * 端到端那一份在 `test/answer-once.ts` 第 10 步（节点收口 → 三级落库 → 树上读回来）。
 * 这儿只管两件小事，但都是撞过的：
 *
 * 1. **按行留的按行留。** `cut` 数字节，停得下半行，而半行读起来跟整行一样理直气壮。
 *    `top` / `tail` 数行。
 * 2. **`msg_part` 里填的每个名字，`press_how` 里都得有一个实现。** 填了个没实现的
 *    （比如现在还空着的 `ask`），表现是跑到那一级才炸 —— 而那时候正在压的是一道
 *    真题的上下文。
 */

import { HOWS, PARTS } from "../app/src/msg/deliver.ts";
import { CUT_BYTES, LEVELS, TOP_LINES, TAIL_LINES, cut, sample, top, tail } from "../app/src/msg/press.ts";
import { done, ok, part, show, step } from "./_lib.ts";

part("The ways of pressing themselves, and whether the table names one nobody implements");

const lines = (n: number) => Array.from({ length: n }, (_, i) => `line ${String(i)}`).join("\n");

step("1. top keeps the first lines and says how many it dropped");
const t = top(lines(500));
show("what came back:", t.split("\n").slice(0, 2).concat(["..."], t.split("\n").slice(-1)));
ok("as many lines as it says", t.split("\n").length === TOP_LINES + 1, t.split("\n").length);
ok("the first line is the first line", t.startsWith("line 0\n"), t.slice(0, 20));
ok("and it says what is missing", t.endsWith(`... (${String(500 - TOP_LINES)} more lines)`), t.slice(-40));

step("2. tail keeps the last lines - that is where the point usually is");
const l = tail(lines(500));
ok("as many lines as it says", l.split("\n").length === TAIL_LINES + 1, l.split("\n").length);
ok("the last line is the last line", l.endsWith("line 499"), l.slice(-20));
// 说明放在**开头** —— 放末尾的话它会读成那份输出最后说的一句话。
ok("and what is missing is said before it, not after", l.startsWith(`... (${String(500 - TAIL_LINES)} earlier lines)`), l.slice(0, 40));

step("3. neither of them cuts a line in half");
ok("top ends on a line boundary", top(lines(500)).split("\n").every((x) => x === "..." || /^(line \d+|\.\.\. \(\d+ more lines\))$/.test(x)), t.split("\n").slice(-2));
ok("tail does too", l.split("\n").every((x) => /^(line \d+|\.\.\. \(\d+ earlier lines\))$/.test(x)), l.split("\n").slice(0, 2));
// 对着一样的输入，按字节那个是会停在半行上的 —— 这就是为什么有按行的这两个。
const byBytes = cut("x".repeat(10) + "\n" + lines(5000));
const frag = byBytes.split("\n").at(-2) ?? "";
ok("cut, which measures bytes, stops wherever the bytes run out - mid-line", frag !== "" && !/^line \d+$/.test(frag), frag);

step("4. something short enough is left alone");
ok("top", top("a\nb\nc") === "a\nb\nc", top("a\nb\nc"));
ok("tail", tail("a\nb\nc") === "a\nb\nc", tail("a\nb\nc"));
ok("cut", cut("hello") === "hello", cut("hello"));
ok("sample", sample("a\nb\nc") === "a\nb\nc", sample("a\nb\nc"));
// 只多出一行的时候也别留：省下一行，却要花一行去说省了一行。
ok("and one line over the limit is not worth a line saying so", top(lines(TOP_LINES + 1)) === lines(TOP_LINES + 1), top(lines(TOP_LINES + 1)).split("\n").length);

step("5. everything msg_part names, press_how implements");
const done_ = new Set(HOWS.filter(([, , identity]) => identity && identity !== "ask").map(([n]) => n));
show("implemented:", [...done_]);
show("declared but not implemented:", HOWS.filter(([, , i]) => !i || i === "ask").map(([n]) => n));
const missing = PARTS.flatMap(([name, , l1, l2, l3]) =>
  [l1, l2, l3].filter((h) => !done_.has(h)).map((h) => `${name} -> ${h}`),
);
ok("no part is set to a way of pressing that nothing does", missing.length === 0, missing);
ok("cut is measured in bytes, and that is the number the table was written against", CUT_BYTES === 2_000, CUT_BYTES);

step("6. what the tools hand back about this conversation itself is gone at every level");
const recall = PARTS.find(([n]) => n === "recall");
show("recall:", recall?.slice(2));
// `task_tree` / `node_load` 回的是库里已经有的东西。留着的话，一个节点的摘要里会
// 夹着另一个节点的摘要 —— 而模型要看，再调一次就是了。
ok("recall is a part", recall !== undefined, PARTS.map(([n]) => n));
ok("and it is dropped at l1, l2 and l3 alike", recall?.slice(2).every((h) => h === "drop") === true, recall?.slice(2));

step("7. there is a fourth level, and nothing is in it yet");
show("levels:", [...LEVELS]);
ok("four columns", LEVELS.length === 4 && LEVELS[3] === "l4", [...LEVELS]);
// **空着是它的状态，不是漏了。** 那一级留给要花一次调用的那种压法（把一段丢给模型
// 换一句话），而那种是从外面声明进来的 —— 声明发生在一个正在跑的库上，列得先在。
ok("no part says anything about it", PARTS.every((t) => t.length === 5), PARTS.filter((t) => t.length !== 5).map(([n]) => n));
// 空着的一级不算数：设好了的最后一级仍是 l3，降级降到那儿为止（见 loop 的 #fit）。
ok("so the last level that is set up is still l3", LEVELS.slice(0, 3).every((l, i) => l === ["l1", "l2", "l3"][i]), [...LEVELS]);

done();
