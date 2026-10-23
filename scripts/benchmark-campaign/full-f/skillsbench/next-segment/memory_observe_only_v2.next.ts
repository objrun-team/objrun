/** Staged observation API: every probe failure is data, never admission. */
export function observeMemory(probe:()=>{exitCode:number;stdout:{toString():string}}){
  try{
    const result=probe(),kb=Number(result.stdout.toString().trim());
    const bytes=result.exitCode===0&&Number.isFinite(kb)&&kb>0?kb*1024:null;
    return {bytes,probeExitCode:result.exitCode,observationError:bytes===null?'nonzero_or_invalid_measurement':null,observationOnly:true,blocksExecution:false};
  }catch(error){
    return {bytes:null,probeExitCode:null,observationError:String(error),observationOnly:true,blocksExecution:false};
  }
}
