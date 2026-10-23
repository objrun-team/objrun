import fs from 'node:fs';
import path from 'node:path';
import {Database} from 'bun:sqlite';
import {actualPin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
const root=path.resolve(import.meta.dir,'../../../..');
const base=path.join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const active=read(path.join(base,'active-run.json')),status=read(path.join(base,'status.json'));
const snapshot=path.join(active.output,'docker-recovery-snapshots',String(Date.now()));fs.mkdirSync(snapshot,{recursive:true});
const tasks=[];
for(const index of status.activeTasks??[]){
 const dir=path.join(active.output,'task-'+index),process=read(path.join(dir,'process.json'));
 const database=path.join(dir,'engine/data/h2h.sqlite'),dest=path.join(snapshot,'task-'+index);fs.mkdirSync(dest,{recursive:true});
 const pins=[];for(const suffix of ['','-wal','-shm'])if(fs.existsSync(database+suffix)){const copy=path.join(dest,'h2h.sqlite'+suffix);fs.copyFileSync(database+suffix,copy);pins.push(actualPin(copy));}
 const db=new Database(database,{readonly:true});let state;try{state={task:db.query('select * from task').all(),repair:db.query('select * from task_repair').all()};}finally{db.close();}
 const stateFile=path.join(dest,'native-state.json');fs.writeFileSync(stateFile,JSON.stringify(state,null,2));
 const gradeDir=path.join(dir,'physical-grading'),names=fs.readdirSync(gradeDir);
 const receipts=names.filter(n=>n.endsWith('-receipt.json')).map(n=>read(path.join(gradeDir,n)));
 const unmatched=names.filter(n=>n.endsWith('-request.json.gz')&&!names.includes(n.replace('-request.json.gz','-receipt.json')));
 tasks.push({index,process,database,rawSnapshots:pins,statePin:actualPin(stateFile),activeGradeRequests:unmatched,lastGrade:receipts.sort((a,b)=>a.index-b.index).at(-1),scoreCertified:false});
}
const provenance=read(path.join(base,'grader-provenance.json'));
const result={atUtc:new Date().toISOString(),runId:active.runId,runnerPid:active.pid,pendingModelRequests:status.pendingRequests,valid:status.completed,passed:status.passed,tasks,grader:{container:'objrun-chemiq-full-f-20261010',containerId:provenance.containerId,imageId:provenance.imageId,command:provenance.command,mounts:provenance.mounts,provenancePin:actualPin(path.join(base,'grader-provenance.json')),health:'http://127.0.0.1:17918/health',restartExistingContainer:'docker start objrun-chemiq-full-f-20261010',opsinBridgePid:24628},action:'Root owns shared Docker recovery; no Docker/WSL restart here. Preserve native tasks and pending grading until natural terminal/closure; snapshots are evidence, not new scores.'};
fs.writeFileSync(path.join(base,'docker-recovery-evidence.json'),JSON.stringify(result,null,2));
console.log(JSON.stringify({runId:active.runId,pending:status.pendingRequests,valid:status.completed,tasks:tasks.map(t=>({index:t.index,pid:t.process.pid,activeGradeRequests:t.activeGradeRequests,lastGradeFault:t.lastGrade?.fault,dbSnapshots:t.rawSnapshots.length})),imageId:provenance.imageId}));
