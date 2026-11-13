/**
 * **Keep existing databases usable** when a declaration adds a column.
 *
 * ```
 * bun test/integration/migrate.ts
 * ```
 *
 * The installer originally rejected every schema mismatch without changing anything.
 * That is appropriate for **changes to existing columns**: changing types or constraints
 * requires rebuilding the table, which means guessing the intended migration and risking data.
 *
 * A missing column is different: adding it need not alter existing rows. Rejecting
 * this case invalidated every old database whenever a column was added, including
 * databases containing a full day's work.
 *
 * This test verifies three cases:
 *
 * 1. Missing column -> **add it without changing any existing row**.
 * 2. Install again -> do nothing.
 * 3. Changed existing column -> **reject as before, leaving everything untouched**.
 */

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { all, open, run } from "../../app/src/H2H/db.ts";
import { install, plan } from "../../app/src/install/index.ts";
import { done, ok, part, show, step } from "../_lib.ts";

const dir = mkdtempSync(join(tmpdir(), "tgengin-migrate-"));
const store = open({ db: { file: join(dir, "h2h.sqlite"), pragmas: { journal_mode: "wal" } } } as never);
const db = store.rw;

const apiCols = () => (all(db, `pragma table_info("api")`) as { name: string }[]).map((c) => c.name);

part("A declaration that grew a column, and a database that did not");

step("1. a database from before that column existed");
install(db);
// Reproduce a database from the previous version by omitting the new column and inserting a row.
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
// Replace api with a table whose `retry_on` is integer, representing a changed existing column.
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
// Windows may retain a database handle briefly after close. Cleanup failure in a temporary directory
// is not the behavior under test and must not fail this run.
try {
  rmSync(dir, { recursive: true, force: true });
} catch {
  /* Leave the temporary directory if cleanup is unavailable. */
}
done();
