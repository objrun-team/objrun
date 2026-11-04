export type ExceptionRecovery={taskIds:string[];solveSeconds:number;maxTaskAttempts:number};
const TARGETS=['ClassEval_48','ClassEval_65','ClassEval_67','ClassEval_74','ClassEval_85','ClassEval_90','ClassEval_97'];
export function assertExceptionRecovery(policy:ExceptionRecovery,authorization:any):void {
 const same=(ids:string[])=>Array.isArray(ids)&&ids.length===TARGETS.length&&new Set(ids).size===TARGETS.length&&TARGETS.every(x=>ids.includes(x));
 if(!same(policy?.taskIds)||policy.solveSeconds!==2400||policy.maxTaskAttempts!==3||!authorization?.approved||!same(authorization.taskIds)||authorization.solveSeconds!==2400||authorization.maxTaskAttempts!==3||authorization.additionalAttemptsPerTask!==1)throw Error('UnapprovedExceptionRecovery');
}
export function exceptionLimits(arm:string,taskId:string,policy?:ExceptionRecovery):{solveSeconds:number;maxTaskAttempts:number}|undefined {
 if(arm!=='objrun'||!policy?.taskIds.includes(taskId))return undefined;
 if(policy.solveSeconds!==2400||policy.maxTaskAttempts!==3||!TARGETS.includes(taskId))throw Error('InvalidExceptionRecoveryLimits');
 return {solveSeconds:policy.solveSeconds,maxTaskAttempts:policy.maxTaskAttempts};
}
