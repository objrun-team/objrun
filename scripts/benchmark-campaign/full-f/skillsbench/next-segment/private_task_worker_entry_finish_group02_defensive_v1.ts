import {readFileSync} from 'node:fs';
import {actualPin,jsonPin,verifyPin,demand} from '../../../../benchmark-repair/paid-resource-proof-v2.ts';
const path=process.argv[2];demand(path,'explicit_private_worker_plan_required');
const pin=actualPin(path),plan=jsonPin(pin);verifyPin(plan.manifestPin);for(const p of plan.sourcePins)verifyPin(p);
const manifest=JSON.parse(readFileSync(plan.manifestPin.path,'utf8'));
const route=plan.targetTaskId==='suricata-custom-exfil'
 ? await import('../runtime_private_task_suricata_finish_group02_defensive_v1.ts')
 : await import('../runtime_private_task_dynamic_v4.next.ts');
await route.runSkillsBenchPrivateTask(manifest,pin);
