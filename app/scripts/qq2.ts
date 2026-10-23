import { open, all } from "../src/H2H/db.ts";
const store = open({ db: { file: "../data/h2h.sqlite", pragmas: { journal_mode: "wal" } } } as never);
const db = store.ro;
for (const t of ["agent","api","handle","tool","task","cycle"]) {
  const r = all(db, `select sql from sqlite_master where name=?`, [t]) as any[];
  console.log("== "+t+" ==\n"+(r[0]?.sql ?? "none"));
}
console.log("AGENT ROWS:", JSON.stringify(all(db,`select * from agent`)));
console.log("API ROWS:", JSON.stringify(all(db,`select * from api`)).slice(0,2000));
