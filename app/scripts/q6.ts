import { open, all } from "../src/H2H/db.ts";
const store = open({ db: { file: "../data/h2h.sqlite", pragmas: { journal_mode: "wal" } } } as never);
const db = store.ro;
try{ const r = all(db, `select * from task where id='survey-39'`) as any[]; console.log("TASK:", JSON.stringify(r,null,1).slice(0,4000)); }catch(e){console.log("err",String(e));}
try{ const r = all(db, `select id, mode, domain, source, objective from task`) as any[]; console.log("IDS:", JSON.stringify(r).slice(0,3000)); }catch(e){}
