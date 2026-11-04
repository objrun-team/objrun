/**
 * 一次工具调用能往回带多少，以及**到点了是不是真停下了**。
 *
 * ```
 * bun test/integration/output-cap.ts
 * ```
 *
 * ## 为什么单独写一个
 *
 * `read` 一直有上限，`bash` 没有。实测撞到的样子：模型在一个 TypeScript 仓库里
 * `grep` 了一遍，扫进了 `node_modules`，那一次返回 **3909459 字节**。那条落进上下文
 * 之后这道题再也发不出去 ——
 *
 * ```
 * This model's maximum context length is 1048576 tokens.
 * However, you requested 1443851 tokens (1427467 in the messages, 16384 in the completion).
 * ```
 *
 * 一趟 112 道里，前 25 道就有 7 道一次调用超过 100 KB，两道超过 3.5 MB。
 *
 * ## 期限得有人去停
 *
 * 后来又撞到另一半：`sh` 超时那一下调的是 `p.kill()`，杀的是那个 shell，**不是进程组**。
 * `sh -c 'grep -r … /'` 起的 `grep` 是 shell 的子进程，shell 一死它被 init 收养接着跑。
 * 实测六个容器各占一整个核，最久的一条烧了 50 分钟 —— 而工具那边早就交回「超时」了。
 *
 * 所以这儿验的不是「回没回话」，是**那条命令是不是真的不干活了**。
 */

import { mkdtempSync, readFileSync, rmSync, writeFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { SH_MAX_BYTES, TOOL_POOL_BYTES, TOOL_POOL_TOKENS, glob, grep, read, sh } from "../../app/src/tools/index.ts";
import { done, ok, part, show, step } from "../_lib.ts";

part("What one call is allowed to bring back, and whether it really stops");

step("1. a small output comes back untouched");
const small = await sh(`node -e "console.log('hello')"`, undefined, 30_000);
ok("byte for byte", small.stdout === "hello\n", small);

step("2. a huge one is cut down");
// 两百万行，两兆多。
const big = await sh(`node -e "for(let i=0;i<200000;i++)console.log('line '+i)"`, undefined, 120_000);
const bytes = Buffer.byteLength(big.stdout, "utf8");
show("what came back:", `${String(bytes)} bytes`);
ok(`under the cap (${String(SH_MAX_BYTES)} plus the line that says what went)`, bytes < SH_MAX_BYTES + 200, bytes);
ok("it ran fine - the cut is about the answer, not the command", big.code === 0 && !big.timedOut, big.code);

step("3. both ends are there, and it says how much went");
ok("the beginning", big.stdout.startsWith("line 0\n"), big.stdout.slice(0, 40));
ok("the end", big.stdout.trimEnd().endsWith("line 199999"), big.stdout.slice(-40));
const mark = big.stdout.split("\n").find((l) => l.startsWith("... ("));
show("the line in the middle:", mark);
ok("and a line in the middle says what is missing", Boolean(mark && /\d+ more bytes/.test(mark)), mark);

step("4. stderr is capped the same way");
const err = await sh(`node -e "for(let i=0;i<200000;i++)console.error('e '+i)"`, undefined, 120_000);
const eb = Buffer.byteLength(err.stderr, "utf8");
show("what came back on stderr:", `${String(eb)} bytes`);
ok("under the same cap", eb < SH_MAX_BYTES + 200, eb);
ok("and its two ends are there too", err.stderr.startsWith("e 0\n") && err.stderr.trimEnd().endsWith("e 199999"), err.stderr.slice(-30));

// ── 到点了是真停，不是只回话 ────────────────────────────────────────────────
const dir = mkdtempSync(join(tmpdir(), "tgengin-cap-"));
const beat = join(dir, "beat.txt").replace(/\\/g, "/");

step("5. a command that outlives its timeout is actually gone");
// 一条**起了个孩子**的命令：孩子每 100ms 往文件里写一笔。超时杀的要是只有 shell，
// 孩子会接着写 —— 那正是实测里烧掉六个核的形状。
const child = `node -e "setInterval(()=>require('fs').appendFileSync('${beat}','.'),100)"`;
const t0 = Date.now();
const timed = await sh(child, undefined, 1_500);
show("came back after:", `${String(Date.now() - t0)}ms`);
ok("the call itself came back on time", timed.timedOut && Date.now() - t0 < 6_000, timed);

const at = statSync(beat).size;
await Bun.sleep(1_500);
const later = statSync(beat).size;
show("beats written by the time it returned / 1.5s later:", `${String(at)} / ${String(later)}`);
ok("the work stopped too - nothing was written after it returned", later === at, { at, later });

// ── 搜索那两件：一个池子，装满就中断 ────────────────────────────────────────
step("6. grep fills a pool and cuts off");
// 一百个文件，每个两百行全是命中 —— 两万条，池子远装不下。
for (let f = 0; f < 100; f++) {
  writeFileSync(join(dir, `f${String(f)}.txt`), Array.from({ length: 200 }, (_, i) => `hit ${String(f)}-${String(i)} xyzzy`).join("\n"));
}
const g = (await grep.run({ pattern: "xyzzy", path: dir })) as { matches: { text: string }[]; truncated: boolean };
const gBytes = Buffer.byteLength(JSON.stringify(g.matches), "utf8");
show("matches / bytes:", `${String(g.matches.length)} / ${String(gBytes)}`);
ok(`under the pool (${String(TOOL_POOL_BYTES)} bytes ≈ ${String(TOOL_POOL_TOKENS)} tokens)`, gBytes <= TOOL_POOL_BYTES, gBytes);
ok("and it says it was cut", g.truncated, g.truncated);
ok("what it did return is whole - nothing was shortened", g.matches.every((m) => m.text.endsWith("xyzzy")), g.matches[0]);

step("7. glob fills the same pool");
const gl = (await glob.run({ pattern: "*.txt", path: dir })) as { files: string[]; truncated: boolean };
const glBytes = Buffer.byteLength(JSON.stringify(gl.files), "utf8");
show("paths / bytes:", `${String(gl.files.length)} / ${String(glBytes)}`);
ok("under the pool", glBytes <= TOOL_POOL_BYTES, glBytes);
ok("every path it returned is a real one", gl.files.every((f) => statSync(f).isFile()), gl.files[0]);

// ── read：不截断，先算，太大就整个拒 ────────────────────────────────────────
step("8. read returns a small file whole");
const smallFile = join(dir, "small.txt");
writeFileSync(smallFile, "one\ntwo\nthree\n");
const r1 = (await read.run({ file_path: smallFile })) as { lines: { number: number; text: string }[]; totalLines: number };
show("lines:", r1.lines);
ok("all three, numbered from 1", r1.lines.length === 3 && r1.lines[0].number === 1 && r1.lines[2].text === "three", r1);

step("9. a file over the pool is refused, not shortened");
const bigFile = join(dir, "big.txt");
writeFileSync(bigFile, Array.from({ length: 20_000 }, (_, i) => `line ${String(i)} ${"x".repeat(40)}`).join("\n"));
show("that file is:", `${String(statSync(bigFile).size)} bytes`);
const r2 = (await read.run({ file_path: bigFile })) as { error?: string; lines?: unknown[]; bytes?: number };
show("what came back:", r2.error);
ok("refused", Boolean(r2.error), r2);
ok("and not a single line came with it", r2.lines === undefined, r2.lines?.length);
ok("the refusal carries the size", typeof r2.bytes === "number" && r2.bytes > TOOL_POOL_BYTES, r2.bytes);

step("10. and a range inside that file comes back whole");
const r3 = (await read.run({ file_path: bigFile, offset: 100, limit: 50 })) as {
  lines?: { number: number; text: string }[];
  totalLines?: number;
  error?: string;
};
ok("no refusal for a range that fits", r3.error === undefined, r3.error);
ok("fifty lines, starting at 100", r3.lines?.length === 50 && r3.lines[0].number === 100, r3.lines?.[0]);
ok("nothing was cut off the line", r3.lines?.[0].text.endsWith("x") === true, r3.lines?.[0].text.slice(-8));
ok("and it says how many lines the file has", r3.totalLines === 20_000, r3.totalLines);

rmSync(dir, { recursive: true, force: true });
done();
