/** Shared runId protocol unchanged; an exclusive directory prevents collisions. */
import {mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {fullFRunId} from '../shared/shared-admission.ts';
export async function reserveIsolatedRunDirectory(root:string,runsRoot:string){
 while(true){
  const runId=fullFRunId(root,'terminal-bench'),output=join(runsRoot,runId);
  try{mkdirSync(output);return {runId,output};}
  catch(error:any){if(error.code!=='EEXIST')throw error;await Bun.sleep(2);}
 }
}
