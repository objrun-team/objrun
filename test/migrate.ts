/**
 * 声明多了一列的时候，**老库接着用**。
 *
 * ```
 * bun test/migrate.ts
 * ```
 *
 * 装表器原本是「形状对不上就炸，一个字不改」。那条对**改了已有的列**是对的：改类型、
 * 改约束都得重建整张表，重建就是在猜想要哪种改法，猜错的代价是数据。
 *
 * 但「少了一列」不是那种：补一列不动任何已有的行。原先一并炸掉的后果是，加一列就等于
 * 老库全部作废 —— 而库里躺着的是跑了一整天的东西。
 *
 * 所以这儿钉三件：
 *
 * 1. 少一列 → **补上，老数据一行不动**
 * 2. 再装一遍 → 什么都不做
 * 3. 改了已有的列 → **照旧炸，而且什么都没改**
 */

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { all, open, run } from "../app/src/H2H/db.ts";
import { install, plan } from "../app/src/install/index.ts";
import { done, ok, part, show, step } from "./_lib.ts";

const dir = mkdtempSync(join(tmpdir(), "tgengin-migrate-"));
const store = open({ db: { file: join(dir, "h2h.sqlite"), pragmas: { journal_mode: "wal" } } } as never);
const db = store.rw;

const apiCols = () => (all(db, `pragma table_info("api")`) as { name: string }[]).map((c) => c.name);

part("A declaration that grew a column, and a database that did not");

step("1. a database from before that column existed");
install(db);
// 上一版建的那份库就是这个样子：把新列拆掉，再放一行进去。
db.exec(`alter table api drop column compress_at`);
run(db, `insert into api (key_env, model, handle, modes, base_url, retry_on) values (?, ?, ?, ?, ?, ?)`, [
  "OLD_KEY",
  "old-model",
  "fn:api.old",
  "chat",
  "https://example.invalid",
  "[]",
]);
show("the columns it has:", apiCols().join(", "));
const before = plan(db);
show("declaration vs database:", { added: before.added, drift: before.drift });
ok("it knows which column is missing", before.added.includes("api.compress_at"), before.added);
ok("and that is not drift", before.drift.length === 0, before.drift);

step("2. installing adds it and leaves the rows alone");
const got = install(db);
show("added:", got.added);
ok("the column is there now", got.added.includes("api.compress_at") && apiCols().includes("compress_at"), apiCols());
const rows = all(db, `select key_env, base_url, compress_at from api where key_env = 'OLD_KEY'`) as {
  key_env: string;
  base_url: string;
  compress_at: number | null;
}[];
show("the row that was already there:", rows[0]);
ok("still there, with what it had", rows.length === 1 && rows[0].base_url === "https://example.invalid", rows);
ok("and the new column is empty on it", rows[0].compress_at === null, rows[0].compress_at);

step("3. a second install changes nothing");
const again = install(db);
ok("nothing added, nothing created", again.added.length === 0 && again.create.length === 0, again);

step("4. a column whose type changed still stops everything");
// 把 api 换成一张 `retry_on` 是 integer 的表 —— 这就是「已有的列变了」。
db.exec(`alter table api rename to api_old`);
db.exec(
  `create table "api" ("key_env" text not null, "model" text not null, "handle" text not null,
     "modes" text not null, "base_url" text not null, "retry_on" integer not null, "compress_at" integer,
     primary key ("key_env", "model"))`,
);
run(db, `insert into api select key_env, model, handle, modes, base_url, 0, compress_at from api_old`);
db.exec(`drop table api_old`);
const p2 = plan(db);
show("what it sees:", p2.drift.map((d) => `${d.table}: ${d.why.join("; ")}`));
ok("it calls that drift", p2.drift.some((d) => d.table === "api"), p2.drift);

let stopped = "";
try {
  install(db);
} catch (e) {
  stopped = e instanceof Error ? e.message : String(e);
}
show("what it says:", stopped.split("\n").slice(0, 2).join(" / "));
ok("install refuses", stopped.includes("do not match the declaration"), stopped);
ok("and says which column", stopped.includes("retry_on"), stopped);
ok(
  "the row is untouched",
  (all(db, `select count(*) as n from api where key_env = 'OLD_KEY'`)[0] as { n: number }).n === 1,
  all(db, `select key_env, retry_on from api`),
);

store.rw.close();
store.ro.close();
// Windows 上库刚关，文件句柄未必马上放开 —— 删不掉不算这一趟失败：那是个临时目录，
// 不是这个测试要验的东西。
try {
  rmSync(dir, { recursive: true, force: true });
} catch {
  /* 留在临时目录里就留着 */
}
done();
