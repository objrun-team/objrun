import {test,expect} from 'bun:test';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {readNativeCheckpoint,recoverSubmittedAtDeadline} from './native-checkpoint.ts';
const out=join(import.meta.dir,'../../../docs/newbench-20261014/classeval');
const taskId='classeval-20261014/objrun/ClassEval_0';
const engine=(attempt:number)=>join(out,'tasks/objrun/ClassEval_0/attempt-'+attempt+'/engine');
test('real 1200s deadline receipt preserves the already submitted native candidate',()=>{
 const cp=readNativeCheckpoint(engine(4),taskId);
 const error=JSON.parse(readFileSync(join(out,'tasks/objrun/ClassEval_0/attempt-4/error.json'),'utf8')).error;
 expect(cp.candidate?.how).toBe('submitted');
 const recovered=recoverSubmittedAtDeadline(engine(4),taskId,error,Number(cp.state.created_at)+1200001);
 expect(recovered.answer).toBe(cp.candidate!.body);
 expect(recovered.candidateHow).toBe('submitted');
 expect(recovered.solveSeconds).toBe(1200);
 expect(recovered.modelProtocolFailure).toBe(false);
 expect(recovered.nativeInterruptedBy).toContain('ProviderSolveDeadlineReached');
});
test('the original 600s verify-only attempt cannot become a final submission',()=>{
 const cp=readNativeCheckpoint(engine(3),taskId);
 expect(cp.candidate).toBeUndefined();
 expect(()=>recoverSubmittedAtDeadline(engine(3),taskId,Error('ProviderSolveDeadlineReached'),Number(cp.state.created_at)+600001)).toThrow('ProviderSolveDeadlineReached');
});
test('source or grader faults are not hidden by a previous submit',()=>{
 expect(()=>recoverSubmittedAtDeadline(engine(4),taskId,Error('SourceChanged'))).toThrow('SourceChanged');
 expect(()=>recoverSubmittedAtDeadline(engine(4),taskId,Error('NativeGraderEnvironmentError'))).toThrow('NativeGraderEnvironmentError');
});
test('a deadline error cannot stop a task before its native deadline',()=>{
 const cp=readNativeCheckpoint(engine(4),taskId);
 expect(()=>recoverSubmittedAtDeadline(engine(4),taskId,Error('ProviderSolveDeadlineReached'),Number(cp.state.created_at)+1199999)).toThrow('ProviderSolveDeadlineReached');
});
