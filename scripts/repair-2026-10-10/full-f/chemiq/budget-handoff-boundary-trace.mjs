import fs from 'node:fs';
import path from 'node:path';
import {shouldBudgetHandOff} from './task39-budget-handoff-staged.mjs';
// Observability only: no prompt, answer, reasoning or tool arguments are recorded.
export function budgetBoundary(task, kind, handedIn, spoke, unit, cycle) {
  const nowMs=Date.now(), createdAtMs=Number(task?.created_at);
  const eligible=kind==='prompt' && shouldBudgetHandOff(task,nowMs);
  const applied=!handedIn && !spoke && eligible;
  const config=process.env.TGENGIN_CONFIG;
  if(!config)throw Error('Budget boundary trace requires native engine config');
  fs.appendFileSync(path.join(path.dirname(config),'budget-handoff-boundaries.jsonl'),JSON.stringify({atUtc:new Date(nowMs).toISOString(),taskId:task?.id,createdAtMs,solveSeconds:Number(task?.solve_seconds),nowMs,remainingSeconds:(createdAtMs+Number(task?.solve_seconds)*1000-nowMs)/1000,unit,cycle,kind,handedIn,spoke,eligible,applied,decision:handedIn||spoke?'original-submit':applied?'budget-submit':'original-continue'})+'\n');
  return applied;
}

