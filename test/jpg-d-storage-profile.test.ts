/** F-only Python/TS ABI. No native service, D writes, Docker or model. */
import {expect,test} from 'bun:test';
import {mkdtempSync,writeFileSync,readFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
import {actualPin} from '../scripts/repair-2026-10-08/paid-resource-proof-v2.ts';
import {loadJpgDDescriptor,jpgDStagePath,jpgDNativeEnvironment,jpgDPointerPayload} from '../scripts/repair-2026-10-08/jpg-d-storage-profile.ts';

const root=resolve(import.meta.dir,'..'),native=join(root,'scripts/repair-2026-10-08/jpg_d_storage_profile.py');
const profilePath=process.env.JPG_D_PROFILE_F_CONTROL_JSON!;
if(!profilePath||!resolve(profilePath).startsWith(join(root,'docs/repair-2026-10-08/jpg-D-storage-and-private-ram-controls-v1')))throw new Error('Only owned F-generated control descriptor allowed');
const p=actualPin(profilePath),src=actualPin(native);
test('actual native descriptor crosses TS ABI and all nested policy objects freeze',()=>{
 const d=loadJpgDDescriptor(p,src);expect(d.solverUpperMaximumBytes).toBe(256*1024**2);expect(d.privateSharedRamMaximumBytes).toBe(512*1024**2);
 expect(Object.isFrozen(d)).toBe(true);expect(Object.isFrozen(d.nativeEnvironment)).toBe(true);
 expect(jpgDStagePath(d,'provider','call/response.gz')).toBe(d.directories.raw+'/call/response.gz');
 const existing={TEMP:'C:/wrong'};expect(jpgDNativeEnvironment(d,existing).TEMP).toBe(d.directories.tmp);expect(existing.TEMP).toBe('C:/wrong');
 for(const name of ['../x','/x','NUL.txt','x:ads','x\\y','x.'])expect(()=>jpgDStagePath(d,'provider',name)).toThrow();
 expect(()=>jpgDStagePath(d,'constructor','x')).toThrow();
 const pointer=jpgDPointerPayload(d,'prepared-only',[src]);expect(pointer.paidReady).toBe(false);expect(Buffer.byteLength(JSON.stringify(pointer))).toBeLessThan(16384);
});
test('changed pointer/caps/ready flags rejected even with a fresh matching fixture file Pin',()=>{
 const original=JSON.parse(readFileSync(profilePath,'utf8'));
 const folder=resolve(profilePath,'..');
 for(const [key,value] of [['FPointerDirectory','C:/foreign'],['solverUpperMaximumBytes',512*1024**2],['paidReady',true],['modelCalls',1]]){
  const file=join(folder,'tampered-'+key+'.json');writeFileSync(file,JSON.stringify({...original,[key]:value}));
  expect(()=>loadJpgDDescriptor(actualPin(file),src)).toThrow();
 }
});
