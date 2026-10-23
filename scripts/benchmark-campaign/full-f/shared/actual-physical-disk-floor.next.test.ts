
import {test,expect} from 'bun:test';
import {GiB,evaluateDockerDisk} from './actual-physical-disk-floor.next.ts';
const nowMs=100000,o={nowMs,expectedDrive:'E:',plannedGrowthBytes:1000*GiB,minimumFreeBytes:8*GiB},obs=(n:number)=>({drive:'E:',driveType:3,freeBytes:n,observedAtMs:nowMs});
test('five GiB actual boundary overrides old prediction and eight GiB reservation',()=>{expect(evaluateDockerDisk(obs(5*GiB),o).admissible).toBe(true);expect(evaluateDockerDisk(obs(5*GiB-1),o).admissible).toBe(false);expect(evaluateDockerDisk(obs(6*GiB),o).minimumRequiredBytes).toBe(5*GiB);});
test('disk freshness identity and missing evidence stay required',()=>{for(const v of [null,{...obs(8*GiB),drive:'F:'},{...obs(8*GiB),driveType:4},{...obs(8*GiB),observedAtMs:nowMs-30001}])expect(evaluateDockerDisk(v,o).admissible).toBe(false);});
