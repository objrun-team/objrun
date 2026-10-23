import {randomBytes} from 'node:crypto';
import {mkdirSync,openSync,writeFileSync,fsyncSync,closeSync,renameSync,unlinkSync} from 'node:fs';
import {dirname} from 'node:path';
/** Readers on Windows can briefly deny replacement. Keep the old file intact. */
export function atomicStateJson(path:string,value:unknown,replace=renameSync,wait=(ms:number)=>Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,ms)) {
  mkdirSync(dirname(path),{recursive:true});
  const temporary=path+'.'+randomBytes(12).toString('hex')+'.tmp';
  const fd=openSync(temporary,'wx',0o600);
  try {writeFileSync(fd,JSON.stringify(value,null,2)+'\n');fsyncSync(fd);} finally {closeSync(fd);}
  try {
    for(let attempt=0;;attempt++) {
      try {replace(temporary,path);return;} catch(error) {
        if(!['EPERM','EACCES','EBUSY'].includes((error as any)?.code)||attempt>=40)throw error;
        wait(Math.min(10+attempt*2,50));
      }
    }
  } finally {try {unlinkSync(temporary);} catch(error) {if((error as any)?.code!=='ENOENT')throw error;}}
}
