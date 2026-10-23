from pathlib import Path
p=Path(__file__).parent
f=p/'preflight-adoption-v48.ts';s=f.read_text();s="import {execFileSync} from 'node:child_process';import {resolve} from 'node:path';\n"+s
a=s.index(' for(const port of [17889,17895])');b=s.index(' const disk=',a)
s=s[:a]+" const absence=JSON.parse(execFileSync('D:/ProgramData/anaconda3/python.exe',[resolve(import.meta.dir,'port-absence-v48.py')],{timeout:10000,encoding:'utf8',windowsHide:true}));demand(absence.previousExecutorAbsent&&absence.localTCPListenersAbsent&&JSON.stringify(absence.exclusiveBindPassed)==='[17889,17895]','actual_local_port_absence');\n"+s[b:]
s=s.replace("const restart=jsonPin(plan.restartProofPin);if(","const restart=jsonPin(plan.restartProofPin),previousGuard=jsonPin(plan.previousAdoptionGuardPin);demand(previousGuard.liveExecutorPid===1304&&previousGuard.directory===restart.previousDirectory&&JSON.stringify(previousGuard.signedPlanPin)===JSON.stringify(restart.previousSignedPlanPin),'exact_previous_global_adoption_guard');if(")
f.write_text(s)
f=p/'check-http-adoption-v48.ts';s=(p/'check-http-adoption-v46.ts').read_text().replace("'./broker-adoption-v46.ts'","'./broker-adoption-v48.ts'").replace('broker-adoption-v46-fixtures','broker-adoption-v48-fixtures').replace('novaeve-adoption-v46-synthetic','novaeve-adoption-v48-synthetic');f.write_text(s)
