import fs from 'node:fs';
const p=import.meta.dirname+'/publish-budget-entry-ready.mjs';let s=fs.readFileSync(p,'utf8');s="import {Database} from 'bun:sqlite';\n"+s;
const start=s.indexOf('// Historical timestamps'),end=s.indexOf('\nassert.equal(boundaries',start);
s=s.slice(0,start)+`const result=read(path.join(prior.output,'task-39/result.json'));verifyPin(result.tracePin);
const db=new Database(dbPath,{readonly:true});const taskRow=db.query('select id,created_at,solve_seconds from task').get();const units=db.query('select unit,at from agent_bot_msg where kind=? order by at').all('prompt');db.close();assert.equal(taskRow.solve_seconds,900);
const created=Number(taskRow.created_at),boundaries=units.map(b=>({unit:b.unit,messageAtMs:b.at,remainingSeconds:(created+900000-b.at)/1000,shadowEligible:shouldBudgetHandOff(taskRow,b.at)}));`+s.slice(end);
s=s.replace("sourceRun:prior.runId,boundaries","sourceRun:prior.runId,tracePin:result.tracePin,taskDatabasePin:actualPin(dbPath),taskWalPin:actualPin(dbPath+'-wal'),boundaries");
fs.writeFileSync(p,s);
