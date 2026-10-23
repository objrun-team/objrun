import {readFileSync} from 'node:fs';
import {actualPin,verifyPin,jsonPin,demand} from '../../../../benchmark-repair/paid-resource-proof-v2.ts';
import {runSkillsBenchPrivateTask} from '../runtime_private_task_finish_group02_fuzzing_v1.next.ts';
process.env.PYTHONIOENCODING='utf-8';
const planPath=process.argv[2];demand(planPath,'explicit_private_worker_plan_required');
const pin=actualPin(planPath),plan=jsonPin(pin);verifyPin(plan.manifestPin);
for(const sourcePin of plan.sourcePins)verifyPin(sourcePin);
const manifest=JSON.parse(readFileSync(plan.manifestPin.path,'utf8'));
await runSkillsBenchPrivateTask(manifest,pin);
