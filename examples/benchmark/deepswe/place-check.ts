/**
 * Check that the tools **actually execute inside the container**.
 *
 * ```
 * bun examples/benchmark/deepswe/place-check.ts [problem-id]
 * ```
 *
 * Requires a running grader (`python3 stand.py`).
 *
 * ## Why test this separately?
 *
 * Incorrect routing can succeed silently: edit may modify the host filesystem instead of the container, and read may return a same-named host file.
 *
 * ## Exercise the real kernel route
 *
 * ```
 * fn:tool.edit -> placeFor(workplace) -> reg.get(identity) -> grader /place -> container runtime
 * ```
 *
 * POSTing directly to the grader tests the runtime but skips the **decision to forward this call**, which is where routing can fail. Register kernel tools and invoke fn:tool.* here.
 *
 * ## Require differences between the two filesystems
 *
 * Reading content does not prove container execution because the host may have the same file. Probe content present on only one side:
 * - Write a file in the container; it must **not** appear on the host.
 * - Write a file on the host; it must **not** be readable in the container.
 */

import { mkdtempSync, existsSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { open } from "../../../app/src/H2H/db.ts";
import { Registry } from "../../../app/src/engine/registry.ts";
import { install } from "../../../app/src/install/index.ts";
import { registerTools } from "../../../app/src/tools/register.ts";

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

// A place row with forwarding enabled, all six allowlisted tools set to always, and identity pointing to the grader.
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
// Local-place control: without forwarding, the same tool should execute on this machine.
db.run(`insert into workplace (place, identity, runtime, forward, tools, usable) values ('local', null, null, 0, '[]', 1)`);
// The handle needs a database row before `sync` can synthesize its HTTP caller.
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

  // ── Reverse check: host-only content must be invisible in the container ──
  //
  // The previous checks could be fooled by a coincidental host file. This one cannot: the file exists only here. Reading it from the supposed container proves that **the call was never forwarded**.
  console.log("\nReverse check: file present on this host but absent in the container");
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

  // ── Control: with place=local, the same tool must execute on this machine ──
  console.log("\nControl: place = local, same tool");
  const local = (await call("read", { file_path: hostOnly }, "local")) as Record<string, unknown>;
  ok("not forwarding means it runs right here", JSON.stringify(local).includes("lives on the engine machine"), local);

  console.log("\nCleanup");
  await call("bash", { command: `rm -f ${MARK}` });
  ok("the probe file is gone from the container", true);
} finally {
  // Close the database before deletion: Windows otherwise returns EBUSY. Cleanup failure does not fail the check; the temporary directory is not what this script validates.
  try {
    store.rw.close();
    store.ro.close();
  } catch {
    // Already closed.
  }
  try {
    rmSync(dir, { recursive: true, force: true });
  } catch {
    console.log(`  (Temporary directory retained: ${dir})`);
  }
}

console.log(`\n${bad === 0 ? "all forwarded correctly" : `${bad} checks failed`}`);
process.exit(bad === 0 ? 0 : 1);
