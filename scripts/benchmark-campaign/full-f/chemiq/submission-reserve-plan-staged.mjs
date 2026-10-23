// Pure inactive scheduling proposal. No source installation, model IO or answer inspection.
export function reserveOpen(task,nowMs,reserveSeconds=450){
  const created=Number(task?.created_at),seconds=Number(task?.solve_seconds);
  if(seconds!==900||!Number.isFinite(created)||!Number.isFinite(nowMs)||nowMs<created||reserveSeconds!==450)return false;
  const remaining=created+900000-nowMs;return remaining>0&&remaining<=450000;
}
export function endWorkingContinuation({task,nowMs,mustCall,finishReason,toolCalls}){
  return !mustCall&&finishReason==='length'&&Array.isArray(toolCalls)&&toolCalls.length===0&&reserveOpen(task,nowMs);
}
