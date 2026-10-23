/** Coordinator-selected draft worker. It never registers readiness itself. */
import {readFileSync} from 'node:fs';
import {actualPin,verifyPin,jsonPin,demand} from '../../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {runSkillsBenchPrivateTask} from '../runtime_private_task_adapter2_20261013_v1.ts';
process.env.PYTHONIOENCODING='utf-8';
const path=process.argv[2];demand(path,'explicit_private_worker_plan_required');
const pin=actualPin(path),plan=jsonPin(pin);verifyPin(plan.manifestPin);
demand(plan.coordinatorReviewed===true&&plan.dispatchEnabled===true,'coordinator_reviewed_dispatch_required');
for(const source of plan.sourcePins)verifyPin(source);
const manifest=JSON.parse(readFileSync(plan.manifestPin.path,'utf8'));
await runSkillsBenchPrivateTask(manifest,pin);
