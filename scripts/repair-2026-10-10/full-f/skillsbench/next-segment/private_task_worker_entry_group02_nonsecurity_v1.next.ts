import {readFileSync} from 'node:fs';
import {actualPin,verifyPin,jsonPin,demand} from '../../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {runSkillsBenchPrivateTask} from '../runtime_private_task_group02_nonsecurity_v1.next.ts';
process.env.PYTHONIOENCODING='utf-8';
const planPath=process.argv[2];demand(planPath,'explicit_private_worker_plan_required');
const pin=actualPin(planPath),plan=jsonPin(pin);verifyPin(plan.manifestPin);
for(const sourcePin of plan.sourcePins)verifyPin(sourcePin);
const manifest=JSON.parse(readFileSync(plan.manifestPin.path,'utf8'));
await runSkillsBenchPrivateTask(manifest,pin);
