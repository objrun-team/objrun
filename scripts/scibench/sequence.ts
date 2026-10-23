export function messages(prompt:string,arm:string,history:any[]){
 const out:any[]=[{role:'user',content:prompt}];
 if(arm==='binary')for(const item of history){out.push({role:'assistant',content:item.answer},{role:'user',content:item.grade.passed?'passed':'failed'});}
 return out;
}
export async function sequence(arm:string,prompt:string,generate:(messages:any[],index:number)=>Promise<any>,grade:(answer:string)=>Promise<any>,persist:(samples:any[])=>void){
 const samples:any[]=[];
 for(let i=0;i<(arm==='baseline'?1:5);i++){
  const input=messages(prompt,arm,samples),r=await generate(input,i);
  const item={index:i,answer:r.answer,receipt:r.receipt,grade:await grade(r.answer)};
  if(!item.grade.valid)throw Error('InvalidGraderResult');
  samples.push(item);persist(samples);
  if(item.grade.passed)break;
 }
 return {samples,selected:samples.at(-1)};
}
