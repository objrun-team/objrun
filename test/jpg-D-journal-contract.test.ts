import { describe, expect, test } from 'bun:test';
import { assertJpgDServiceHome } from '../scripts/benchmark-repair/jpg-D-native-service-v1.ts';
import { assertJpgDResourceObservation, assertJpgFoundationColdOnly, jpgDResourceRequirements } from '../scripts/benchmark-repair/jpg-D-journal-contract.ts';
import { JPG_D_PARENT, type JpgDDescriptor } from '../scripts/benchmark-repair/jpg-d-storage-profile.ts';

const MiB=1024**2,GiB=1024**3,nonce='a'.repeat(32),root=JPG_D_PARENT+'/'+nonce;
// Explicit synthetic geometry. No D path is opened or created by these tests.
const d={ownerNonce:nonce,storePhysical:root,directories:{stand:root+'/stand'},CMinimumFreeBytes:GiB,DMinimumFreeBytes:3*GiB,FMinimumFreeBytes:GiB,
  FPointerMaximumAllocatedBytes:MiB,dockerMetadataReserveBytes:16*MiB,FStopBufferBytes:8*MiB,solverUpperMaximumBytes:256*MiB,storeMaximumAllocatedBytes:3*GiB} as JpgDDescriptor;

describe('independent prospective JPG D contract',()=>{
  test('one engineering task cannot enable a paid ten-task trial',()=>{
    expect(()=>assertJpgFoundationColdOnly('docker-mock')).not.toThrow();
    expect(()=>assertJpgFoundationColdOnly('run')).toThrow('jpg_foundation_cold_only_requires_at_least_ten_distinct_SKB_tasks');
    expect(()=>assertJpgFoundationColdOnly('real-provider')).toThrow('jpg_foundation_cold_only_requires_at_least_ten_distinct_SKB_tasks');
  });
  test('service accepts only its exact descriptor stand; unknown paths cannot launch',()=>{
    expect(assertJpgDServiceHome(d,root+'/stand').replaceAll('\\','/')).toBe(root+'/stand');
    expect(()=>assertJpgDServiceHome(d,root+'/stand/nested')).toThrow('jpg_D_service_exact_home');
    expect(()=>assertJpgDServiceHome(d,'F:/unowned/stand')).toThrow('jpg_D_service_exact_home');
    expect(()=>assertJpgDServiceHome({...d,ownerNonce:'b'.repeat(32)},root+'/stand')).toThrow('jpg_D_service_exact_home');
  });
  test('new resource formula preserves the actual 256MiB solver boundary once',()=>{
    const start=jpgDResourceRequirements(d,true,true,0),end=jpgDResourceRequirements(d,false,true,256*MiB),ram=jpgDResourceRequirements(d,false,false,0);
    expect(start.F).toBe(GiB+281*MiB);expect(start.D).toBe(6*GiB);expect(start.solverRemainingFReservationBytes).toBe(256*MiB);
    expect(end.F).toBe(GiB+25*MiB);expect(ram.F).toBe(end.F);expect(end.solverRemainingFReservationBytes).toBe(0);
    expect(()=>jpgDResourceRequirements(d,false,true,512*MiB)).toThrow('jpg_D_resource_state');
    expect(()=>jpgDResourceRequirements(d,false,true,-1)).toThrow('jpg_D_resource_state');
  });
  test('actual-observation admission denies missing capacity and noninteger facts',()=>{
    expect(()=>assertJpgDResourceObservation(d,{C:GiB,D:6*GiB,F:GiB+281*MiB-1},true,true,0)).toThrow('jpg_D_physical_resource_guard');
    expect(()=>assertJpgDResourceObservation(d,{C:GiB,D:3*GiB,F:2*GiB},true,true,0)).toThrow('jpg_D_physical_resource_guard');
    expect(()=>assertJpgDResourceObservation(d,{C:NaN,D:6*GiB,F:2*GiB},true,true,0)).toThrow('jpg_D_physical_resource_guard');
    expect(assertJpgDResourceObservation(d,{C:GiB,D:6*GiB,F:GiB+281*MiB},true,true,0).required.F).toBe(GiB+281*MiB);
  });
});
