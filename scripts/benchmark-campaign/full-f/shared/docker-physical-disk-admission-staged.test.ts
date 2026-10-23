import {test,expect} from 'bun:test';
import {GiB,evaluateDockerDisk} from './docker-physical-disk-admission-staged.ts';
const nowMs=100000,options={nowMs,expectedDrive:'E:'},observe=(freeBytes=20*GiB)=>({drive:'E:',driveType:3,freeBytes,observedAtMs:nowMs});
test('workspace F space cannot satisfy Docker physical E reserve',()=>expect(evaluateDockerDisk({...observe(),drive:'F:'},options).admissible).toBe(false));
test('current E full fails while an actual sufficient reserve passes',()=>{expect(evaluateDockerDisk(observe(30*1024**2),options).admissible).toBe(false);expect(evaluateDockerDisk(observe(),options).admissible).toBe(true);});
test('planned layer growth is reserved before admission',()=>{expect(evaluateDockerDisk(observe(10*GiB),{...options,plannedGrowthBytes:3*GiB}).admissible).toBe(false);expect(evaluateDockerDisk(observe(11*GiB),{...options,plannedGrowthBytes:3*GiB}).admissible).toBe(true);});
test('stale and future observations do not grant admission',()=>{expect(evaluateDockerDisk({...observe(),observedAtMs:nowMs-30001},options).admissible).toBe(false);expect(evaluateDockerDisk({...observe(),observedAtMs:nowMs+1},options).admissible).toBe(false);});
test('missing, invalid and network disk evidence fails closed',()=>{for(const obs of [null,{...observe(),driveType:4},{...observe(),freeBytes:NaN},{...observe(),freeBytes:-1}])expect(evaluateDockerDisk(obs,options).admissible).toBe(false);});
test('policy cannot silently lower emergency reserve or use negative growth',()=>{expect(()=>evaluateDockerDisk(observe(),{...options,minimumFreeBytes:4*GiB})).toThrow('invalid_disk_policy');expect(()=>evaluateDockerDisk(observe(),{...options,plannedGrowthBytes:-1})).toThrow('invalid_disk_policy');});
