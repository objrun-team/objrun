import { open, all } from "../src/H2H/db.ts";
const store = open({ db: { file: "../data/h2h.sqlite", pragmas: { journal_mode: "wal" } } } as never);
const db = store.ro;
try{ const r = all(db, `select * from objective`) as any[]; console.log("OBJECTIVE ROWS:", JSON.stringify(r,null,1).slice(0,6000)); }catch(e){ console.log("ERR", String(e)); }
