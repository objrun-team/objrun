import { open, all } from "../src/H2H/db.ts";
const store = open({ db: { file: "../data/h2h.sqlite", pragmas: { journal_mode: "wal" } } } as never);
const db = store.ro;
for (const t of ["agent_bot_ctx","agent_bot_msg","task_solve","press"]) {
  const r = all(db, `select sql from sqlite_master where name=?`, [t]) as any[];
  console.log("== "+t+" ==\n"+(r[0]?.sql ?? "none"));
}
