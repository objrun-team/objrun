/** The existing signed historyAdmission function remains the only policy decision. */
import{readFileSync}from'node:fs';import{pin,demand}from'./manifest.ts';
import{historyAdmission}from'./nonblocking-history-policy.ts';
const[path,hash,taskKey]=process.argv.slice(2);demand(pin(path).sha256===hash,'child_history_manifest_pin');
const m=JSON.parse(readFileSync(path,'utf8'));demand(m.bench+':'+m.taskId===taskKey,'child_policy_exact_task');
const result=historyAdmission(m);demand(result,'child_root_signed_policy_required');
console.log(JSON.stringify({protocol:'bench-verified-child-history-policy-v1',taskKey,authorized:true,authorizationPin:result.authorizationPin,historyUnknownPreserved:true}));
