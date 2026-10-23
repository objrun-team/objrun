/**
 * 「改之前先读一遍」那道闸。
 *
 * ```
 * bun test/file-guard.ts
 * ```
 *
 * ## 为什么单独写一个
 *
 * 这道闸有过一个**能烧掉整道题**的毛病，而当时全套测试一条都没红：
 *
 * - `write` 一个**不存在**的文件 → 闸交回「先去读」→ `read` 回 ENOENT →
 *   再 `write` 还是交回「先去读」。**新建文件这条路根本走不通。**
 * - 而且 `hasRead` 本身就没认出读过：它找 `v.tool`，可结果行的形状是
 *   `{id, name, value}`；它又只看当前这一站，可闸交回去的那个 read 落在**下一站**。
 *   两处合起来 → 任何 `write` / `edit` 都被无限交回。
 *
 * 实测代价：cmt-0 那道题 12 个单元全花在这个循环上，一个字答案都没写。
 *
 * 所以这个测试不走 HTTP，直接调那条句柄 —— 闸就在句柄里，从外面发任务反而看不清。
 */

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { open } from "../app/src/H2H/db.ts";
import { Registry } from "../app/src/engine/registry.ts";
import { install, tableNameOf } from "../app/src/install/index.ts";
import { registerTools } from "../app/src/tools/register.ts";
import { done, ok, part, show, step } from "./_lib.ts";

const dir = mkdtempSync(join(tmpdir(), "tgengin-guard-"));
// 走内核自己那条开库的路（`open` 包了一层，`Conn` 不是裸的 bun:sqlite）。
const store = open({ db: { file: join(dir, "h2h.sqlite"), pragmas: { journal_mode: "wal" } } } as never);
const db = store.rw;
install(db);

// 智能体那张消息表：闸靠它判「读过没有」。
const MSG = tableNameOf("agent_{}_msg", "bot");
db.exec(
  `create table if not exists "${MSG}" (instance text, unit integer, seq integer, role text, kind text, body text, at integer)`,
);
db.run(`insert into workplace (place, forward, usable, tools) values (?, 0, 1, ?)`, ["local", ""]);

const reg = new Registry();
// 这道闸测的是本机那条路（`place: local`，不转发），所以不用挂位置句柄。
registerTools(db, reg);
const write = reg.get("fn:tool.write");

/** 装一行「read 回来了」的结果 —— 形状照抄 `tools/unit.ts` 真写进去的那一份。 */
function sawRead(instance: string, unit: number, path: string): void {
  db.run(
    `insert into "${MSG}" (instance, unit, seq, role, kind, body, at) values (?, ?, 1, 'tool', 'tool', ?, 0)`,
    [instance, unit, JSON.stringify({ id: "x", name: "read", value: { path, offset: 1, lines: [], totalLines: 0 } })],
  );
}

const asUnit = (instance: string, unit: number, file_path: string, content: string) =>
  write.call({ args: { file_path, content }, place: "local", agent: "bot", instance, unit }) as Promise<
    Record<string, unknown>
  >;

try {
  part("Creating a new file");

  step("1. write a file that does not exist - it must NOT be handed back a read-first unit");
  const fresh = join(dir, "brand-new.txt");
  const r1 = await asUnit("t#1", 1, fresh, "hello");
  show("it answered:", r1);
  ok("it wrote straight away, handing back no unit", r1.unit === undefined, r1);
  ok("the file really landed", readFileSync(fresh, "utf8") === "hello");
  ok("and it reported this as a creation", r1.created === true);

  part("Overwriting an existing file");

  step("2. the file is already there and was never read - it must hand back a read-first unit");
  const existing = join(dir, "already.txt");
  writeFileSync(existing, "old content", "utf8");
  const r2 = await asUnit("t#2", 1, existing, "new content");
  show("it answered:", r2);
  ok("it handed back a read unit", (r2.unit as { tool?: string })?.tool === "read", r2);
  ok("and it did not touch the file", readFileSync(existing, "utf8") === "old content");

  step("3. come back after reading - it must let the write through");
  // 闸交回去的 read 落在**下一站**（unit 2），闸自己是在 unit 3 上再被问到的。
  // 只看本站的话这一条会红 —— 那正是以前的写法。
  sawRead("t#2", 2, existing);
  const r3 = await asUnit("t#2", 3, existing, "new content");
  show("it answered:", r3);
  ok("it let the write through", r3.unit === undefined, r3);
  ok("the content changed", readFileSync(existing, "utf8") === "new content");

  step("4. having read a DIFFERENT file does not count as having read this one");
  const other = join(dir, "other.txt");
  writeFileSync(other, "do not touch me", "utf8");
  const r4 = await asUnit("t#2", 4, other, "quietly overwritten");
  show("it answered:", r4);
  ok("it still hands back a read unit", (r4.unit as { tool?: string })?.tool === "read", r4);
  ok("that file was left alone", readFileSync(other, "utf8") === "do not touch me");
} finally {
  store.close();
  // Windows 上 close 之后 WAL 那两个文件有时还锁着一小会儿，删不掉就算了 ——
  // 那是系统临时目录，留着不影响谁；为这个把测试判红没有意义。
  try {
    rmSync(dir, { recursive: true, force: true });
  } catch {
    /* 临时目录，留着就留着 */
  }
}

done();
