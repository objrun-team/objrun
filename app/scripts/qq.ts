import { open, all } from "../src/H2H/db.ts";
const store = open({ db: { file: "../data/h2h.sqlite", pragmas: { journal_mode: "wal" } } } as never);
const db = store.ro;
const rows = all(db, `select name from sqlite_master where type='table'`) as any[];
console.log("TABLES:", rows.map(r=>r.name).join(", "));
try { const a = all(db, `select * from agent`) as any[]; console.log("AGENTS:", JSON.stringify(a,null,1)); } catch(e){ console.log("agent err", e); }
