export async function sampleUpToFive(options:{
  prior:any[];
  generate:(index:number)=>Promise<any>;
  grade:(answer:string)=>Promise<any>;
  persist:(samples:any[])=>void;
}):Promise<any[]> {
  const samples=[...options.prior];
  if(samples.length>5)throw Error('More than five attempts in the fixed-five namespace');
  if(samples.some(x=>x.grade?.valid&&x.grade?.passed))return samples;
  for(let index=samples.length;index<5;index++){
    let sample:any;
    try{
      const response=await options.generate(index);
      sample={index,...response,grade:await options.grade(response.answer)};
    }catch(error){
      sample={index,error:String(error),grade:{valid:false,passed:false,errorType:'IndependentGenerationOrGradingError'}};
    }
    samples.push(sample);options.persist(samples);
    if(sample.grade?.valid&&sample.grade?.passed)break;
  }
  return samples;
}
