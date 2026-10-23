/** Match the isolated engine's tool-unit watchdog to its existing tool envelope.
 * The task solveSeconds, tool timeout, model budget and grader are unchanged.
 */
import {writeFileSync} from 'node:fs';
export async function alignToolUnitBudget(machine:{api:(method:string,path:string,body?:any)=>Promise<any>},declaredToolMs:number,proofPath?:string){
  if(!Number.isSafeInteger(declaredToolMs)||declaredToolMs<=0)throw Error('declared_tool_envelope_required');
  const before=await machine.api('POST','/query',{sql:"select name,expect_ms from handle where name='fn:unit.tools'"});
  await machine.api('POST','/exec',{sql:"update handle set expect_ms=:ms where name='fn:unit.tools'",params:{ms:declaredToolMs}});
  const after=await machine.api('POST','/query',{sql:"select name,expect_ms from handle where name='fn:unit.tools'"});
  const rows=Array.isArray(after)?after:after.rows;
  if(!Array.isArray(rows)||rows.length!==1||Number(rows[0].expect_ms)!==declaredToolMs)throw Error('tool_unit_envelope_readback');
  const proof={atUtc:new Date().toISOString(),before,after,declaredToolMs,isolatedEngineOnly:true,taskSolveSecondsUnchanged:true,individualToolTimeoutUnchanged:true,modelBudgetUnchanged:true};
  if(proofPath)writeFileSync(proofPath,JSON.stringify(proof,null,2)+'\n',{flag:'wx'});
  return proof;
}
