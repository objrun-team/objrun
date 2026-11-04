import {test,expect} from 'bun:test';
import {mkdtempSync,existsSync,readFileSync,writeFileSync,unlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {cfg,OUT,model,accounting,walk,read} from './common.ts';

test('whitespace retry preserves fees and raw bytes; retries never exceed three',{timeout:15000},async()=>{
 const real=globalThis.fetch,cap=cfg.perQuestionDollarCap,batch=cfg.pilotBudgetUsd,balanceFile=join(OUT,'balance-latest.json');
 const previous=existsSync(balanceFile)?readFileSync(balanceFile):null;
 cfg.perQuestionDollarCap=null;cfg.pilotBudgetUsd=null;
 let calls=0,mode='recover';const raw='\n         \n';
 globalThis.fetch=(async(url:any)=>{
  const u=String(url);
  if(u.endsWith('/credits'))return Response.json({data:{total_credits:100,total_usage:0}});
  if(u.endsWith('/key'))return Response.json({data:{limit_remaining:100}});
  if(!u.endsWith('/chat/completions'))throw Error('FixtureUnexpectedURL');
  calls++;
  if(mode==='partial')return new Response('{"choices":[',{status:200});
  if(mode==='empty'||calls===1)return new Response(raw,{status:200});
  return Response.json({id:'synthetic-delivery',model:cfg.model,provider:'DigitalOcean',choices:[{message:{content:'delivered'},finish_reason:'stop'}],usage:{cost:0}});
 }) as any;
 try{
  const root=mkdtempSync(join(tmpdir(),'scibench-transport-control-'));
  const d=join(root,'recovered');const r=await model(d,{messages:[{role:'user',content:'Q'}]},d,Date.now()+30000);
  expect(r.answer).toBe('delivered');expect(calls).toBe(2);
  expect(readFileSync(join(d,'attempt-0/response.raw.txt'),'utf8')).toBe(raw);
  expect(accounting(d).unknownCostCount).toBe(1);expect(accounting(d).unknownCostUpperBoundUsd).toBeGreaterThan(0);
  mode='partial';calls=0;
  const partial=join(root,'partial');await expect(model(partial,{messages:[]},partial,Date.now()+30000)).rejects.toThrow('NonJSONProviderResponse');expect(calls).toBe(1);
  mode='empty';calls=0;
  const empty=join(root,'empty');await expect(model(empty,{messages:[]},empty,Date.now()+30000)).rejects.toThrow('IncompleteProviderResponse');
  expect(calls).toBe(3);expect(accounting(empty).unknownCostCount).toBe(3);
  expect(walk(empty).filter(p=>p.endsWith('/receipt.json')).every(p=>read(p).unknownCost)).toBe(true);
 }finally{
  globalThis.fetch=real;cfg.perQuestionDollarCap=cap;cfg.pilotBudgetUsd=batch;
  if(previous)writeFileSync(balanceFile,previous);else if(existsSync(balanceFile))unlinkSync(balanceFile);
 }
});
