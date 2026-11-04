import {test,expect} from 'bun:test';
import {assertExceptionRecovery,exceptionLimits} from './exception-policy.ts';
const p={taskIds:['ClassEval_48','ClassEval_65','ClassEval_67','ClassEval_74','ClassEval_85','ClassEval_90','ClassEval_97'],solveSeconds:2400,maxTaskAttempts:3};
const a={...p,approved:true,additionalAttemptsPerTask:1};
test('only the seven authorized ObjRun exceptions receive 2400s and one third attempt',()=>{
 assertExceptionRecovery(p,a);
 for(const tid of p.taskIds)expect(exceptionLimits('objrun',tid,p)).toEqual({solveSeconds:2400,maxTaskAttempts:3});
 expect(exceptionLimits('baseline','ClassEval_48',p)).toBeUndefined();
 expect(exceptionLimits('objrun','ClassEval_98',p)).toBeUndefined();
 expect(exceptionLimits('objrun','ClassEval_0',p)).toBeUndefined();
});
test('no unauthorized tasks, unbounded retries, or unapproved time changes',()=>{
 expect(()=>assertExceptionRecovery({...p,taskIds:[...p.taskIds,'ClassEval_98']},a)).toThrow();
 expect(()=>assertExceptionRecovery({...p,maxTaskAttempts:4},a)).toThrow();
 expect(()=>assertExceptionRecovery(p,{...a,approved:false})).toThrow();
 expect(()=>assertExceptionRecovery({...p,solveSeconds:3600},a)).toThrow();
});
