/** One controller owns every upstream request, including all native engine branches. */
export class Semaphore {
 active=0;peak=0;queue:{resolve:(v:()=>void)=>void,reject:(e:Error)=>void,timer:any}[]=[];
 constructor(readonly limit:number,readonly changed:()=>void=()=>{}){if(!Number.isInteger(limit)||limit<1||limit>32)throw Error('InvalidConcurrencyCap');}
 async acquire(deadline:number):Promise<()=>void>{
  if(Date.now()>=deadline)throw Error('SolveTimeBudget');
  if(this.active<this.limit)return this.enter();
  return new Promise((resolve,reject)=>{const item:any={resolve,reject};item.timer=setTimeout(()=>{this.queue.splice(this.queue.indexOf(item),1);reject(Error('SolveTimeBudget'));this.changed();},deadline-Date.now());this.queue.push(item);this.changed();});
 }
 private enter(){this.active++;this.peak=Math.max(this.peak,this.active);this.changed();let released=false;return()=>{if(released)throw Error('DoubleSemaphoreRelease');released=true;this.active--;const next=this.queue.shift();if(next){clearTimeout(next.timer);next.resolve(this.enter());}this.changed();};}
}
