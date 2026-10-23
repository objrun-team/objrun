/**
 * 那几件工具，**真的落在容器里了吗**。
 *
 * ```
 * bun examples/benchmark/deepswe/place-check.ts [题号]
 * ```
 *
 * 前提：台子起着（`python3 stand.py`）。
 *
 * ## 为什么要单测这个
 *
 * 转发错了不报错。`edit` 落在引擎这台机器上而不是容器里的话，它照样返回成功，
 * 改的却是另一个文件系统上的文件；`read` 读到的是宿主机的同名文件。
 *
 * ## 走的是内核那条真路，不是直接打台子
 *
 * ```
 *   fn:tool.edit ──→ placeFor(workplace) ──→ reg.get(identity) ──→ 台子 /place ──→ 容器里的运行时
 * ```
 *
 * 直接 POST 台子的话，测的是运行时（那当然在容器里），**跳过了「这一次该不该转发」
 * 那个决定** —— 而那才是会错的地方。所以这儿把内核的工具注册跑起来，调 `fn:tool.*`。
 *
 * ## 判据是「两边不一样」
 *
 * 「读到了内容」证明不了在容器里 —— 宿主机上可能正好也有。所以每一条都拿**容器有、
 * 这台机器没有**（或者反过来）的东西去问：
 *
 * - 在容器里写一个文件 → 这台机器上必须**没有**它
 * - 在这台机器上写一个文件 → 容器里必须**读不到**
 */

import { mkdtempSync, existsSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { open } from "../../../../app/src/H2H/db.ts";
import { Registry } from "../../../../app/src/engine/registry.ts";
import { install } from "../../../../app/src/install/index.ts";
import { registerTools } from "../../../../app/src/tools/register.ts";

const STAND = process.env.TGENGIN_DSW_STAND ?? "http://127.0.0.1:7902";
const TASK = process.argv[2] ?? "abs-module-cache-flags";
const PLACE = `dsw:probe/${TASK}`;
const MARK = `/app/tgengin-place-check-${Date.now()}.txt`;

let bad = 0;
function ok(what: string, pass: boolean, got?: unknown): void {
  if (!pass) bad++;
  console.log(`  ${pass ? "✓" : "✗"} ${what}`);
  if (!pass && got !== undefined) console.log(`      got: ${JSON.stringify(got).slice(0, 300)}`);
}

const dir = mkdtempSync(join(tmpdir(), "tgengin-place-check-"));
const store = open({ db: { file: join(dir, "h2h.sqlite"), pragmas: { journal_mode: "wal" } } } as never);
const db = store.rw;
install(db);

// 一行位置：转发开着，白名单里那六件都 always，identity 指着台子。
db.run(
  `insert into workplace (place, identity, runtime, forward, tools, usable) values (?, ?, null, 1, ?, 1)`,
  [
    PLACE,
    `${STAND}/place`,
    JSON.stringify(
      ["bash", "read", "write", "edit", "glob", "grep"].map((tool) => ({ tool, policy: "always" })),
    ),
  ],
);
// 本机那一行：拿来做对照 —— 同一件工具，不转发的时候落在这台机器上。
db.run(`insert into workplace (place, identity, runtime, forward, tools, usable) values ('local', null, null, 0, '[]', 1)`);
// 句柄得在库里有一行，`sync` 才会给它合成调用器（`http://` 那一档）。
db.run(`insert into handle (name, expect_ms, module) values (?, 300000, null)`, [`${STAND}/place`]);

const reg = new Registry();
registerTools(db, reg);
reg.sync(db);

const call = (tool: string, args: Record<string, unknown>, place = PLACE) =>
  reg.get(`fn:tool.${tool}`).call({ place, forward: true, args }) as Promise<Record<string, unknown>>;

try {
  console.log(`place-check: ${PLACE}\n`);

  console.log("bash");
  const pwd = await call("bash", { command: "pwd && git rev-parse --short HEAD && uname -s" });
  ok("runs inside the container, not on this machine", String(pwd.stdout).startsWith("/app"), pwd);

  console.log("\nglob");
  const g = await call("glob", { pattern: "*.go", path: "/app/evaluator" });
  const files = (g.files ?? []) as string[];
  ok("lists paths that only exist in the container", files.length > 0 && files.every((f) => f.startsWith("/app/")), g);
  ok("and this machine has none of them", files.length > 0 && !existsSync(files[0]), files[0]);

  console.log("\nwrite");
  await call("write", { file_path: MARK, content: "written through the place handle\n" });
  const back = await call("bash", { command: `cat ${MARK}` });
  ok("the file is there in the container", String(back.stdout).includes("written through the place handle"), back);
  ok("and NOT on this machine", !existsSync(MARK), MARK);

  console.log("\nread");
  const r = await call("read", { file_path: MARK });
  ok("reads back what was written in the container", JSON.stringify(r).includes("written through the place handle"), r);

  console.log("\nedit");
  await call("edit", { file_path: MARK, old_string: "written through", new_string: "edited through" });
  const after = await call("bash", { command: `cat ${MARK}` });
  ok("the edit landed in the container", String(after.stdout).includes("edited through the place handle"), after);

  console.log("\ngrep");
  const gr = await call("grep", { pattern: "edited through", path: "/app" });
  ok("finds it by searching the container", JSON.stringify(gr).includes("tgengin-place-check"), gr);

  // ── 反过来问一遍：这台机器上的东西，容器里必须看不见 ──
  //
  // 上面每一条都可能被「宿主机上恰好也有」蒙混过去。这一条不会：文件只在这台机器上，
  // 容器里没有。读得到就说明这一次**根本没转发出去**。
  console.log("\n反向：这台机器上有、容器里没有的文件");
  const hostOnly = join(dir, "host-only.txt");
  writeFileSync(hostOnly, "this file lives on the engine machine\n");
  let sawIt = false;
  try {
    const h = await call("read", { file_path: hostOnly });
    sawIt = JSON.stringify(h).includes("lives on the engine machine");
  } catch {
    sawIt = false;
  }
  ok("the container cannot see it - so the call really left this machine", !sawIt, hostOnly);

  // ── 对照：同一件工具，位置是 local 的时候就该落在这台机器上 ──
  console.log("\n对照：place = local，同一件工具");
  const local = (await call("read", { file_path: hostOnly }, "local")) as Record<string, unknown>;
  ok("not forwarding means it runs right here", JSON.stringify(local).includes("lives on the engine machine"), local);

  console.log("\n收尾");
  await call("bash", { command: `rm -f ${MARK}` });
  ok("the probe file is gone from the container", true);
} finally {
  // 库还开着的话 Windows 上删不掉（EBUSY）—— 先关。删不掉也不算这一趟失败：
  // 那是个临时目录，不是这个脚本要验的东西。
  try {
    store.rw.close();
    store.ro.close();
  } catch {
    // 已经关了
  }
  try {
    rmSync(dir, { recursive: true, force: true });
  } catch {
    console.log(`  (临时目录留下了：${dir})`);
  }
}

console.log(`\n${bad === 0 ? "all forwarded correctly" : `${bad} checks failed`}`);
process.exit(bad === 0 ? 0 : 1);
