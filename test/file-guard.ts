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
import { Places, registerTools } from "../app/src/tools/register.ts";
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
registerTools(db, reg, new Places(store.ro));
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
  part("新建文件");

  step("① write 一个不存在的文件 —— **不该**被交回「先去读」");
  const 新建 = join(dir, "brand-new.txt");
  const r1 = await asUnit("t#1", 1, 新建, "hello");
  show("回的是：", r1);
  ok("直接写了，没交回操作单元", r1.unit === undefined, r1);
  ok("文件真落地了", readFileSync(新建, "utf8") === "hello");
  ok("而且报了这是新建的", r1.created === true);

  part("盖掉已有文件");

  step("② 文件已经在那儿，之前没读过 —— 该交回「先去读」");
  const 已有 = join(dir, "already.txt");
  writeFileSync(已有, "老内容", "utf8");
  const r2 = await asUnit("t#2", 1, 已有, "新内容");
  show("回的是：", r2);
  ok("交回了一个 read 操作单元", (r2.unit as { tool?: string })?.tool === "read", r2);
  ok("**没动那个文件**", readFileSync(已有, "utf8") === "老内容");

  step("③ 读过之后再来 —— 该放行");
  // 闸交回去的 read 落在**下一站**（unit 2），闸自己是在 unit 3 上再被问到的。
  // 只看本站的话这一条会红 —— 那正是以前的写法。
  sawRead("t#2", 2, 已有);
  const r3 = await asUnit("t#2", 3, 已有, "新内容");
  show("回的是：", r3);
  ok("放行了", r3.unit === undefined, r3);
  ok("内容换了", readFileSync(已有, "utf8") === "新内容");

  step("④ 读的是**别的**文件，不算读过这一个");
  const 另一个 = join(dir, "other.txt");
  writeFileSync(另一个, "别动我", "utf8");
  const r4 = await asUnit("t#2", 4, 另一个, "偷偷盖掉");
  show("回的是：", r4);
  ok("还是交回「先去读」", (r4.unit as { tool?: string })?.tool === "read", r4);
  ok("那个文件没被动", readFileSync(另一个, "utf8") === "别动我");
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
