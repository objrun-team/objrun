import { open, all, run } from "../src/H2H/db.ts";
const store = open({ db: { file: "../data/h2h.sqlite", pragmas: { journal_mode: "wal" } } } as never);
const db = store.rw ?? store.ro;
console.log("keys", Object.keys(store));
try {
  run(db, `insert into agent (name, config, apis, unit, knobs, state) values (?, ?, ?, ?, ?, ?)
    on conflict(name) do update set apis=excluded.apis, unit=excluded.unit, state=excluded.state`,
    ["searcher", null, JSON.stringify([["DEEPSEEK_API_KEY","deepseek-v4-flash"]]), "fn:unit.tools", null, "idle"]);
  console.log("inserted");
} catch(e){ console.log("ERR", String(e)); }
console.log("agents now", JSON.stringify(all(db,`select * from agent`)));
