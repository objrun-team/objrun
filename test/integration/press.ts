/**
 * Test context-compression methods and **whether every method named in the table is implemented**.
 *
 * ```
 * bun test/integration/press.ts
 * ```
 *
 * The end-to-end test is step 10 of `test/integration/answer-once.ts`
 * (node closure -> three stored levels -> retrieval from the tree). This file
 * checks two smaller behaviors, both of which have failed before:
 *
 * 1. **Line-based retention must respect lines.** `cut` counts bytes and may stop
 *    mid-line, while the fragment can look like a complete assertion. `top` and
 *    `tail` count lines.
 * 2. **Every method named in `msg_part` must have an implementation in `press_how`.**
 *    An unimplemented entry, such as the currently empty `ask`, fails only when
 *    execution reaches that level and is already compressing a real task's context.
 */

import { HOWS, PARTS } from "../../app/src/msg/deliver.ts";
import { CUT_BYTES, LEVELS, TOP_LINES, TAIL_LINES, cut, sample, top, tail } from "../../app/src/msg/press.ts";
import { done, ok, part, show, step } from "../_lib.ts";

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
// Put the explanation **first**; at the end, it would look like the original output's concluding statement.
ok("and what is missing is said before it, not after", l.startsWith(`... (${String(500 - TAIL_LINES)} earlier lines)`), l.slice(0, 40));

step("3. neither of them cuts a line in half");
ok("top ends on a line boundary", top(lines(500)).split("\n").every((x) => x === "..." || /^(line \d+|\.\.\. \(\d+ more lines\))$/.test(x)), t.split("\n").slice(-2));
ok("tail does too", l.split("\n").every((x) => /^(line \d+|\.\.\. \(\d+ earlier lines\))$/.test(x)), l.split("\n").slice(0, 2));
// On the same input, byte-based truncation can stop mid-line. This is why both line-based methods exist.
const byBytes = cut("x".repeat(10) + "\n" + lines(5000));
const frag = byBytes.split("\n").at(-2) ?? "";
ok("cut, which measures bytes, stops wherever the bytes run out - mid-line", frag !== "" && !/^line \d+$/.test(frag), frag);

step("4. something short enough is left alone");
ok("top", top("a\nb\nc") === "a\nb\nc", top("a\nb\nc"));
ok("tail", tail("a\nb\nc") === "a\nb\nc", tail("a\nb\nc"));
ok("cut", cut("hello") === "hello", cut("hello"));
ok("sample", sample("a\nb\nc") === "a\nb\nc", sample("a\nb\nc"));
// Do not annotate the removal of just one line: the annotation itself consumes the line that was saved.
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
// `task_tree` and `node_load` return material already stored in the database. Retaining it would embed
// one node's summary inside another. The model can call the tool again if it needs to read it.
ok("recall is a part", recall !== undefined, PARTS.map(([n]) => n));
ok("and it is dropped at l1, l2 and l3 alike", recall?.slice(2).every((h) => h === "drop") === true, recall?.slice(2));

step("7. there is a fourth level, and nothing is in it yet");
show("levels:", [...LEVELS]);
ok("four columns", LEVELS.length === 4 && LEVELS[3] === "l4", [...LEVELS]);
// **Empty is its intended state, not an omission.** This level is reserved for a compressor that spends a model call
// to turn a passage into a sentence. Such compressors are declared externally into a running database, so the columns must exist first.
ok("no part says anything about it", PARTS.every((t) => t.length === 5), PARTS.filter((t) => t.length !== 5).map(([n]) => n));
// An empty level does not count: l3 remains the last configured level and the limit of fallback (see loop's #fit).
ok("so the last level that is set up is still l3", LEVELS.slice(0, 3).every((l, i) => l === ["l1", "l2", "l3"][i]), [...LEVELS]);

done();
