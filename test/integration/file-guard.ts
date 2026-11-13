/**
 * The read-before-edit gate.
 *
 * ```
 * bun test/integration/file-guard.ts
 * ```
 *
 * ## Why a separate test?
 *
 * This gate once had a bug that **consumed an entire task**, while the full test suite stayed green:
 *
 * - `write` to a **nonexistent** file returned "read first"; `read` returned ENOENT;
 *   another `write` still returned "read first". **Creating a file was impossible.**
 * - `hasRead` also failed to recognize reads: it looked for `v.tool`, but result rows
 *   have shape `{id, name, value}`. It inspected only the current station, although
 *   the requested read completed at **the next station**. Together, these mistakes
 *   rejected every `write` and `edit` indefinitely.
 *
 * In the observed cmt-0 task, all 12 units were spent in this loop without producing an answer.
 *
 * This test calls the handle directly rather than through HTTP. The gate is inside
 * the handle; submitting an external task would obscure the behavior being tested.
 */

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { open } from "../../app/src/H2H/db.ts";
import { Registry } from "../../app/src/engine/registry.ts";
import { install, tableNameOf } from "../../app/src/install/index.ts";
import { registerTools } from "../../app/src/tools/register.ts";
import { done, ok, part, show, step } from "../_lib.ts";

const dir = mkdtempSync(join(tmpdir(), "tgengin-guard-"));
// Use the kernel's own database-opening path: `open` wraps SQLite, and `Conn` is not raw bun:sqlite.
const store = open({ db: { file: join(dir, "h2h.sqlite"), pragmas: { journal_mode: "wal" } } } as never);
const db = store.rw;
install(db);

// The agent's message table lets the gate determine whether a read occurred.
const MSG = tableNameOf("agent_{}_msg", "bot");
db.exec(
  `create table if not exists "${MSG}" (instance text, unit integer, seq integer, role text, kind text, body text, at integer)`,
);
db.run(`insert into workplace (place, forward, usable, tools) values (?, 0, 1, ?)`, ["local", ""]);

const reg = new Registry();
// This tests the local path (`place: local`, no forwarding), so no place handle is needed.
registerTools(db, reg);
const write = reg.get("fn:tool.write");

/** Insert a completed-read result in the exact shape actually written by `tools/unit.ts`. */
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
  // The read requested by the gate completes at **the next station** (unit 2); the gate is checked again at unit 3.
  // Looking only at the current station would fail this test, reproducing the old implementation.
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
  // On Windows, the WAL files may remain locked briefly after close. Ignore cleanup failure:
  // this is a system temporary directory, so leaving it does no harm and should not fail the test.
  try {
    rmSync(dir, { recursive: true, force: true });
  } catch {
    /* Leave the temporary directory if cleanup is unavailable. */
  }
}

done();
