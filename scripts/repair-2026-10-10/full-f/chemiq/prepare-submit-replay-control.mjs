import fs from 'node:fs';const here=import.meta.dirname;let s=fs.readFileSync(here+'/task39-budget-entry-sdk-control.mjs','utf8');
s="import {gunzipSync} from 'node:zlib';\n"+s;
s=s.replace("const token=randomUUID()", "const replayRun=JSON.parse(fs.readFileSync(path.join(base,'active-run.json'),'utf8'));const replayResponsePath=path.join(replayRun.output,'journal/provider-12-response.json.gz');const replayResponse=JSON.parse(gunzipSync(fs.readFileSync(replayResponsePath)).toString());assert.equal(replayResponse.choices[0].finish_reason,'length');assert(!replayResponse.choices[0].message.tool_calls?.length);\nconst token=randomUUID()");
s=s.replace("'-budget-entry-'","'-submit-replay-'").replaceAll('task39-budget-entry-sdk-','task39-submit-replay-sdk-');
s=s.replace("if(seq>0)assert(carried.includes(prefix+(seq-1)+';')", "if(seq>0)assert(carried.includes(only&&mode==='red'?(replayResponse.choices[0].message.reasoning??replayResponse.choices[0].message.reasoning_content):prefix+(seq-1)+';')");
s=s.replace(" const message=length?", " if(only&&mode==='red'){if(seq===3)await engine.api('POST','/exec',{sql:'update task set created_at=:created where id=:id',params:{created:Date.now()-900001,id:task.taskId}});return Response.json(replayResponse);}\n const message=length?");
s=s.replace("if(mode==='red'&&ordinary>=9)break;", "");
s=s.replace("}else{assert(ordinary>=9);assert.equal(required,0);}", "}else{assert.equal(state.state,'failed');assert.equal(JSON.parse(state.result).outcome,'no_candidate');assert.equal(ordinary,8);assert.equal(required,4);}");
s=s.replace("const proof={protocol:", "const proof={replayResponsePin:actualPin(replayResponsePath),replaySubmissionLengthOnly:mode==='red',syntheticDeadlineExpireAfterFourthLength:mode==='red',protocol:");
// Replay both variants use the previously reviewed budget build; no provider endpoint.
s=s.replace("const machine=mode==='green'?candidateMachine:baselineMachine;", "const machine=candidateMachine;");
fs.writeFileSync(here+'/task39-submit-replay-sdk-control.mjs',s);
