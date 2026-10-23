import {expect,test} from 'bun:test';
import {nativeInterfaceTimedOut} from './mbpp-proxy-transport.ts';

test('native transport timeout ends the Bench wait only after all provider receipts are durable',()=>{
  const why={problems:['ask#1: the kernel threw while advancing it - The operation timed out.']};
  expect(nativeInterfaceTimedOut(why,0)).toBe(true);
  expect(nativeInterfaceTimedOut(why,1)).toBe(false);
  expect(nativeInterfaceTimedOut({problems:['The required submit tool was not called exactly once']},0)).toBe(false);
  expect(nativeInterfaceTimedOut({problems:['Candidate verification failed']},0)).toBe(false);
  expect(nativeInterfaceTimedOut({problems:['Candidate operation timed out']},0)).toBe(false);
});
