import { open, run, all } from "../src/H2H/db.ts";
const store = open({ db: { file: "../data/h2h.sqlite", pragmas: { journal_mode: "wal" } } } as never);
const db = store.rw;
const t1 = all(db, `select sql from sqlite_master where name='agent_bot_ctx'`) as any[];
const t2 = all(db, `select sql from sqlite_master where name='agent_bot_msg'`) as any[];
run(db, t1[0].sql.replaceAll("agent_bot_ctx","agent_searcher_ctx"));
run(db, t2[0].sql.replaceAll("agent_bot_msg","agent_searcher_msg"));
console.log("tables:", (all(db,`select name from sqlite_master where name like 'agent_searcher%'`) as any[]).map(r=>r.name));
