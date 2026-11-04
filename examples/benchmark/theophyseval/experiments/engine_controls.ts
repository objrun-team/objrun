import {join} from 'node:path';
import {ROOT,read,save} from './common.ts';
import {native} from './native.ts';
import {bridge} from './tools.ts';
import {parseObjective,validate} from './engine/app/src/objective/spec.ts';
const g=parseObjective({nodes:[{name:'output_valid',domain:'bool',moment:'done',handle:'http://127.0.0.1/output_valid'},{name:'correct',domain:'bool',moment:'done',handle:'http://127.0.0.1/correct'}],edges:[{src:'output_valid',out:0,dst:'correct'}],sink:'correct',checks:5,reuse:'never'});
if(validate(g).length)throw Error('InvalidG:'+validate(g).join(';'));
// The real engine requires a nonempty key even for the local synthetic server.
// This fixture never calls the provider and never needs the user's credential.
process.env.OPENROUTER_API_KEY='fixture-local-only';
const fixture=read(join(ROOT,'control/engine-fixture-session.json'));
try{
 const record=await native({id:fixture.task},{id:fixture.task,prompt:'Synthetic no-model integration control. The required answer artifact is already present. Freeze it using snapshot, then submit its identifier.'},fixture.session,join(ROOT,'control/native-engine-'+Date.now()),join(ROOT,'control/no-model-calls'),true);
 const grade=await bridge('grade',{session:fixture.session,candidate:record.candidate,unit:fixture.task});
 if(record.candidateHow!=='submitted'||!grade.valid||!grade.passed||record.feedbackNodeCalls<2)throw Error('NativeIntegrationControlFailed:'+JSON.stringify(record));
 save(join(ROOT,'control/engine-controls.json'),{passed:true,validG:true,realEngine:true,fixtureOnly:true,modelCalls:0,record,grade});
 console.log(JSON.stringify({passed:true,realEngine:true,modelCalls:0,requests:record.nativeModelRequests}));
}finally{await bridge('dispose',{session:fixture.session});}
