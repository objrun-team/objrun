import {writeFileSync,mkdirSync} from 'node:fs';import {dirname} from 'node:path';
export function reserveRecoveryTaskLock(path:string,record:any){mkdirSync(dirname(path),{recursive:true});writeFileSync(path,JSON.stringify({...record,protocol:'pipeline-root-permanent-recovery-task-lock',neverDelete:true})+'\n',{flag:'wx',mode:0o600});}
