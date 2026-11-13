/**
 * Bound the output of one tool call and verify **that work actually stops at its deadline**.
 *
 * ```
 * bun test/integration/output-cap.ts
 * ```
 *
 * ## Why a separate test?
 *
 * `read` always had an output limit; `bash` did not. In a real TypeScript repository,
 * a model's `grep` entered `node_modules` and returned **3909459 bytes**. Once that
 * result entered the context, the task could never send another request:
 *
 * ```
 * This model's maximum context length is 1048576 tokens.
 * However, you requested 1443851 tokens (1427467 in the messages, 16384 in the completion).
 * ```
 *
 * In a 112-task run, 7 of the first 25 tasks had a call exceeding 100 KB, and two exceeded 3.5 MB.
 *
 * ## A deadline must actively stop execution
 *
 * Another failure affected timeout handling: `sh` called `p.kill()`, killing the shell,
 * **not the process group**. A `grep` child spawned by `sh -c 'grep -r … /'` was adopted
 * by init and kept running after the shell died. Six containers each consumed a full
 * core, one for 50 minutes, even though the tool had already reported a timeout.
 *
 * This test therefore checks **whether the command has actually stopped working**,
 * not merely whether the caller received a response.
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
// Two million lines, totaling more than two megabytes.
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

// -- Timeout must stop execution, not merely return a response ----------------
const dir = mkdtempSync(join(tmpdir(), "tgengin-cap-"));
const beat = join(dir, "beat.txt").replace(/\\/g, "/");

step("5. a command that outlives its timeout is actually gone");
// A command **with a child process**: the child writes to a file every 100 ms. Killing only the shell
// lets the child continue writing, reproducing the failure that consumed six cores.
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

// -- Both search tools share a bounded pool and stop when it is full ----------
step("6. grep fills a pool and cuts off");
// One hundred files with two hundred matching lines each: twenty thousand matches, far beyond the pool capacity.
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

// -- read: calculate size first and reject oversized output rather than truncate
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
