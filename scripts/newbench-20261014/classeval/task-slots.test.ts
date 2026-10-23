import {test,expect} from 'bun:test';
import {TaskSlots} from './task-slots.ts';
test('two arm queues share eight slots and all eight are available to one arm',async()=>{
 const slots=new TaskSlots(8);let active=0,peak=0,completed=0;
 await Promise.all(Array.from({length:24},(_,i)=>slots.run(async()=>{
  active++;peak=Math.max(peak,active);await Bun.sleep(5+(i%3));active--;completed++;
 })));
 expect(peak).toBe(8);expect(active).toBe(0);expect(completed).toBe(24);
});
test('a failed task releases its slot without blocking later tasks',async()=>{
 const slots=new TaskSlots(1);let next=false;
 const result=await Promise.allSettled([slots.run(async()=>{throw Error('provider fault');}),slots.run(async()=>{next=true;return 1;})]);
 expect(result[0].status).toBe('rejected');expect(result[1].status).toBe('fulfilled');expect(next).toBe(true);
});
