// User-authorized cumulative retries, separate from the frozen original score.
export function passedCount(state:any):number{return Object.values(state.cases).filter((c:any)=>c.passed).length;}
export function remainingIds(state:any):string[]{return state.fixedIds.filter((id:string)=>!state.cases[id].passed);}
export function targetReached(state:any):boolean{return passedCount(state)>=state.targetPassed;}
export function canSchedule(state:any,inFlight:number):boolean{return passedCount(state)+inFlight<state.targetPassed;}
export function acceptAttempt(state:any,result:any,path:string,round:number){
 const row=state.cases[result.officialId];if(!row)throw Error('UnexpectedTaskResult:'+result.officialId);
 row.lastAttempt={round,resultPath:path,valid:result.grade?.valid===true,passed:result.grade?.passed===true,completedAtUtc:result.completedAtUtc};
 if(!row.passed&&result.grade?.valid===true&&result.grade?.passed===true&&result.candidateHow==='submitted'&&!result.modelProtocolFailure){row.passed=true;row.resultPath=path;row.passedAtRound=round;}
 state.passed=passedCount(state);state.accuracy=state.passed/state.fixedIds.length;state.remainingIds=remainingIds(state);
 return state;
}
