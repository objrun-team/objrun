/** Standalone read-only host probe; never imported by a paid campaign. */
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { actualPin, hash, jsonPin } from './paid-resource-proof-v2.ts';
import { durableChemiqJson } from './chemiq-f-paid-admission-v3.ts';
import { CHEMIQ_F_ROOT as ROOT } from './chemiq-f-journal-contract-v3.ts';
const provenance=jsonPin(actualPin(join(ROOT,'docs/repair-2026-10-08/chemiq-nextwave-grader-provenance.json')));
const scriptPin=actualPin(join(ROOT,'scripts/repair-2026-10-08/chemiq-grader-provenance.py'));
process.env.PATH='D:/Program/resources/bin;'+process.env.PATH;
const docker='D:/Program/resources/bin/docker.exe';
const records:any[]=[];
for(const mode of ['bare-inspect','absolute-inspect','bare-runtime','absolute-runtime']) {
  const runtime=mode.endsWith('runtime'), executable=mode.startsWith('bare-')?'docker':docker;
  const args=runtime?['exec','-i',provenance.actual_grader_container.name,'python','-','--worker']:['inspect',provenance.actual_grader_container.name];
  const startedAtUtc=new Date().toISOString(), start=Date.now();
  try {
    const raw=execFileSync(executable,args,{encoding:'utf8',windowsHide:true,timeout:runtime?120000:30000,maxBuffer:8*1024**2,...(runtime?{input:readFileSync(scriptPin.path,'utf8')}:{})});
    const parsed=JSON.parse(raw), value=runtime?parsed:parsed[0];
    records.push({mode,executable,args,startedAtUtc,finishedAtUtc:new Date().toISOString(),elapsedMs:Date.now()-start,success:true,stdoutSha256:hash(raw),summary:runtime?{pythonVersion:value.python_version,publicModuleNames:Object.keys(value.public_modules),distributionCount:value.distributions.length}:{containerId:value.Id,imageId:value.Image,running:value.State.Running,startedAt:value.State.StartedAt}});
  } catch(error) {
    const e=error as any;
    records.push({mode,executable,args,startedAtUtc,finishedAtUtc:new Date().toISOString(),elapsedMs:Date.now()-start,success:false,error:{name:e.name,code:e.code??null,errno:e.errno??null,syscall:e.syscall??null,status:e.status??null,signal:e.signal??null,killed:e.killed??null,messageSha256:hash(String(e.message)),stdoutSha256:hash(e.stdout??''),stderrSha256:hash(e.stderr??'')}});
  }
}
const value={protocol:'chemiq-v3-native-shutdown-diagnostic-v1',observedAtUtc:new Date().toISOString(),sourcePin:actualPin(import.meta.path),provenancePin:actualPin(join(ROOT,'docs/repair-2026-10-08/chemiq-nextwave-grader-provenance.json')),scriptPin,pid:process.pid,bunVersion:Bun.version,pathSha256:hash(process.env.PATH??''),records,modelCalls:0,gradeCalls:0,paidLockTaken:false,containerMutated:false,originalRunModified:false};
const pin=durableChemiqJson(join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-implementation-v3/observations/native-shutdown-diagnostic-'+value.observedAtUtc.replace(/[:.]/g,'-')+'.json'),value);
console.log(JSON.stringify({pin,records,modelCalls:0,gradeCalls:0}));
