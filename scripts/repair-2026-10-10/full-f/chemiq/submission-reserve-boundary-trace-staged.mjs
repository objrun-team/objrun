import fs from 'node:fs';import path from 'node:path';import {reserveOpen} from './submission-reserve-plan-staged.mjs';
export function reserveBoundary(task,kind,handedIn,spoke,unit,cycle){
 const nowMs=Date.now(),eligible=kind==='prompt'&&reserveOpen(task,nowMs),applied=!handedIn&&!spoke&&eligible,config=process.env.TGENGIN_CONFIG;
 if(!config)throw Error('Native config required for reserve telemetry');
 fs.appendFileSync(path.join(path.dirname(config),'submission-reserve-boundaries.jsonl'),JSON.stringify({nowMs,atUtc:new Date(nowMs).toISOString(),taskId:task?.id,createdAtMs:Number(task?.created_at),solveSeconds:Number(task?.solve_seconds),remainingSeconds:(Number(task?.created_at)+900000-nowMs)/1000,unit,cycle,kind,handedIn,spoke,eligible,applied})+'\n');return applied;
}
