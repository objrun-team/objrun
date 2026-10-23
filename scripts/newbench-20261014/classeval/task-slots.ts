/** One shared ceiling for task generation and grading across both experiment arms. */
export class TaskSlots {
  private used=0;
  private waiting:Array<()=>void>=[];
  constructor(readonly limit:number){if(!Number.isInteger(limit)||limit<1)throw Error('InvalidTaskConcurrency');}
  async run<T>(job:()=>Promise<T>):Promise<T>{
    if(this.used>=this.limit)await new Promise<void>(resolve=>this.waiting.push(resolve));
    else this.used++;
    try{return await job();}finally{
      const next=this.waiting.shift();
      if(next)next();else this.used--;
    }
  }
}
