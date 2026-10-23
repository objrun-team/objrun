// Adapter boundaries extracted from the original runner for receipt replay.
export function requestTimeoutMs(deadline:number|undefined,now:number):number {
  const remaining=deadline===undefined?600000:Math.floor(deadline-now);
  if(remaining<=0)throw Error('ProviderSolveDeadlineReached');
  return Math.min(600000,remaining);
}
export function canaryReady(arm:string,records:any[]):boolean {
  const record=records.find(r=>r.arm===arm);
  return !!record?.grade?.valid&&(arm==='baseline'||record.candidateHow==='submitted');
}
export function failureFor(response:any,status:number):string|undefined {
  return response.error?.message??(status===200?undefined:'ProviderHttp:'+status);
}
export function retainedTaskAttempts(previous:any):number {
  return previous?.taskAttempts??0;
}
