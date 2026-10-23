import {test,expect} from 'bun:test';
import {mkdtempSync,writeFileSync,readFileSync,renameSync,readdirSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {atomicStateJson} from './atomic-state.ts';
test('Windows sharing violations retry without destroying the existing snapshot',()=>{
 const dir=mkdtempSync(join(tmpdir(),'bench-atomic-')),p=join(dir,'state.json');
 try {writeFileSync(p,'{"old":true}');let calls=0;
 atomicStateJson(p,{new:true},(a,b)=>{expect(JSON.parse(readFileSync(p,'utf8'))).toEqual({old:true});if(++calls<=3)throw Object.assign(new Error('sharing'),{code:'EPERM'});renameSync(a,b);},()=>{});
 expect(calls).toBe(4);expect(JSON.parse(readFileSync(p,'utf8'))).toEqual({new:true});expect(readdirSync(dir)).toEqual(['state.json']);
 }finally{rmSync(dir,{recursive:true});}
});
test('permanent failure preserves old JSON and removes only its own temporary file',()=>{
 const dir=mkdtempSync(join(tmpdir(),'bench-atomic-')),p=join(dir,'state.json');
 try {writeFileSync(p,'{"old":true}');expect(()=>atomicStateJson(p,{new:true},()=>{throw Object.assign(new Error('sharing'),{code:'EPERM'});},()=>{})).toThrow('sharing');
 expect(JSON.parse(readFileSync(p,'utf8'))).toEqual({old:true});expect(readdirSync(dir)).toEqual(['state.json']);
 }finally{rmSync(dir,{recursive:true});}
});
