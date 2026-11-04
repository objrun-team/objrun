import {Semaphore} from './scheduling.ts';
const slots=new Semaphore(32);let active=0,peak=0;
await Promise.all(Array.from({length:128},async()=>{const release=await slots.acquire(Date.now()+10000);active++;peak=Math.max(peak,active);await Bun.sleep(5);active--;release();}));
if(peak!==32||slots.peak!==32||active||slots.active||slots.queue.length)throw Error('ConcurrencyControlFailed');
const one=new Semaphore(1),release=await one.acquire(Date.now()+1000);let timed=false;
try{await one.acquire(Date.now()+10);}catch{timed=true;}finally{release();}
if(!timed||one.queue.length||one.active)throw Error('DeadlineQueueControlFailed');
console.log(JSON.stringify({passed:true,globalCap:32,peak,deadlineQueueCancellation:true,fixtureOnly:true,modelCalls:0}));
