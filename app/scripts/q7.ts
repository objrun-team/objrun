import { Database } from "bun:sqlite";
const p = process.argv[2] ?? "../data/sealed.sqlite";
try{ const db = new Database(p, { readonly: true }); const r = db.query("select name, sql from sqlite_master where type='table'").all(); console.log(JSON.stringify(r,null,1).slice(0,4000)); }catch(e){ console.log("ERR", String(e)); }
